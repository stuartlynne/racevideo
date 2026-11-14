"""Real recorder/SQLite integration with deterministic encoded camera packets.

No physical camera needed. Only the camera source is replaced; actual JPEG
analysis, receipt clocks, event assembly, writer thread and SQLite are exercised.
"""
from fractions import Fraction
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from racevideo import storage
from racevideo.__main__ import parser
from racevideo.recorder import record
from racevideo.pipeline import capture_worker


class Camera:
    streams = SimpleNamespace(video=[SimpleNamespace(codec_context=SimpleNamespace(
        name="mjpeg", width=640, height=360))])

    def demux(self, stream):
        start = time.monotonic()
        for tick in range(50):
            time.sleep(max(0, start + tick / 10 - time.monotonic()))
            image = Image.new("L", (640, 360), 70)
            if 10 <= tick <= 14:
                ImageDraw.Draw(image).rectangle((285, 100, 340, 210), fill=180 if tick % 2 else 240)
            out = io.BytesIO()
            image.save(out, "JPEG", quality=90)
            jpeg = b"damaged camera packet" if "--corrupt" in sys.argv and tick==20 else out.getvalue()

            class Packet:
                size, pts, time_base = len(jpeg), tick * 100, Fraction(1, 1000)

                def __bytes__(self):
                    return jpeg

            yield Packet()

    def close(self):
        pass


def fake_capture(*args):
    with patch('av.open', return_value=Camera()):
        capture_worker(*args)


def main():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "motion.sqlite3"
        args = parser().parse_args(["record", "--db", str(path), "--run-seconds", "4.6"])
        signals = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            assert record(args, capture_target=fake_capture) == 0
        finally:
            for sig, handler in signals.items():
                signal.signal(sig, handler)
        connection = storage.connect(path, readonly=True)
        clips = storage.list_clips(connection)
        assert len(clips) == 1, len(clips)
        clip = clips[0]
        assert clip["reason"] == "motion"
        metadata = json.loads(connection.execute("SELECT metadata FROM clip_details").fetchone()[0])
        frames = storage.frame_index(connection, clip["id"])
        pre = (metadata["first_motion_monotonic_ns"] - frames[0]["monotonic_ns"]) / 1e9
        post = (frames[-1]["monotonic_ns"] - metadata["last_motion_monotonic_ns"]) / 1e9
        assert 0.49 <= pre <= 0.65, pre
        assert 2 <= post < 2.2, post
        assert metadata["end_reason"] == "quiet", metadata
        if '--corrupt' in sys.argv:
            assert metadata['capture_bad_packets_in_segment']==1,metadata
            assert storage.read_runtime(connection)['capture_bad_packets']==1
            assert all(storage.read_frame(connection,clip['id'],f['ordinal']).startswith(b'\xff\xd8') for f in frames)
        # A brief passing's thumbnail must show motion, not its longer empty tail.
        with Image.open(io.BytesIO(clip["thumbnail"])) as thumbnail:
            assert thumbnail.convert("L").getpixel((thumbnail.width // 2, thumbnail.height // 2)) > 100
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        print(f"Recorder motion passed: one clip, {len(frames)} frames, {pre:.3f}s pre-roll, "
              f"{post:.3f}s post-roll, metadata and database valid")
        connection.close()


if __name__ == "__main__":
    main()
