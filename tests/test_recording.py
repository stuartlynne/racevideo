import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from racevideo import storage
from racevideo.recorder import RecentFrames


def jpeg(color="red"):
    out = io.BytesIO()
    Image.new("RGB", (320, 180), color).save(out, "JPEG")
    return out.getvalue()


class RecordingTests(unittest.TestCase):
    def test_buffer_uses_elapsed_time_not_nominal_frame_count(self):
        recent = RecentFrames(2, 1_000_000)
        for ns in (0, 20_000_000, 400_000_000, 2_100_000_000):
            recent.append(storage.Frame(ns, ns, ns, "1/1000000000", b"jpeg"))
        self.assertEqual([f.monotonic_ns for f in recent.snapshot()],
                         [400_000_000, 2_100_000_000])

    def test_byte_cap_bounds_memory_even_inside_time_window(self):
        recent = RecentFrames(2, 8)
        for ns in range(4):
            recent.append(storage.Frame(ns, ns, ns, "1/1", b"jpeg"))
        self.assertEqual(recent.bytes, 8)
        self.assertEqual(len(recent.snapshot()), 2)
        self.assertEqual(recent.evicted_for_size, 2)

    def test_clip_is_atomic_original_jpegs_and_timing_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "recording.sqlite3"
            writer = storage.connect(path)
            storage.initialize(writer)
            reader = storage.connect(path, readonly=True)
            frames = [storage.Frame(1_000 + ns, ns, i * 40, "1/1000", jpeg(color))
                      for i, (ns, color) in enumerate(((0, "red"), (40_000_000, "blue")))]
            clip_id = storage.save_clip(writer, frames, 123, "timer", 320, 180, "test")
            self.assertEqual(storage.list_clips(reader)[0]["frame_count"], 2)
            self.assertEqual(storage.read_frame(reader, clip_id, 1), frames[1].jpeg)
            # Failed frame insertion must not expose a partial clip to readers.
            bad = storage.Frame(None, 0, 0, "1/1", jpeg())
            with self.assertRaises(Exception):
                storage.save_clip(writer, [bad], 123, "timer", 320, 180, "test")
            self.assertEqual(len(storage.list_clips(reader)), 1)
            storage.publish(writer, {"state": "recording"}, frames[0].jpeg)
            self.assertEqual(storage.read_runtime(reader)["preview"], frames[0].jpeg)
            reader.close()
            writer.close()
            reopened = storage.connect(path, readonly=True)
            index = storage.frame_index(reopened, clip_id)
            self.assertEqual(index[1]["source_pts"], 40)
            self.assertEqual(index[1]["monotonic_ns"], 40_000_000)
            self.assertEqual(reopened.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
