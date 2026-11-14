"""Exercise the recorder process boundary without opening any physical camera."""
import io
import json
from pathlib import Path
import signal
import tempfile
import time
import unittest
from PIL import Image
from racevideo import storage
from racevideo.__main__ import parser
from racevideo.recorder import record


def synthetic_capture(args,ring,stop,done,reports):
    output=io.BytesIO();Image.new('RGB',(64,48),'white').save(output,'JPEG');jpeg=output.getvalue()
    start=time.monotonic_ns();wall=time.time_ns()
    reports.put(dict(width=64,height=48,negotiated_fps=60))
    # Metrics-only messages must not be mistaken for dimension reports.
    reports.put(dict(capture_fps=60,capture_window_seconds=3,capture_metrics_ns=wall))
    for i in range(180):
        offset=round(i*1e9/60)
        if stop.is_set():break
        ring.append(storage.Frame(wall+offset,start+offset,i,'1/60',jpeg))
        time.sleep(.003)
    done.set()


class CaptureDiagnosticsTests(unittest.TestCase):
    def test_split_reports_and_saved_clip_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.sqlite3'
            args=parser().parse_args(['record','--db',str(path),'--device','/dev/racevideo-nonexistent-test','--width','64','--height','48','--fps','60','--trigger','timer','--interval','1','--seconds','.5','--buffer-mb','2'])
            previous={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
            try:self.assertEqual(record(args,capture_target=synthetic_capture),0)
            finally:
                for s,handler in previous.items():signal.signal(s,handler)
            c=storage.connect(path,readonly=True)
            try:
                state=storage.read_runtime(c);self.assertEqual(state['negotiated_fps'],60);self.assertEqual(state['capture_fps'],60)
                rows=c.execute('SELECT metadata FROM clip_details').fetchall();self.assertGreaterEqual(len(rows),1)
                for row in rows:
                    data=json.loads(row[0]);self.assertEqual(data['camera_mode']['requested']['fps'],60)
                    self.assertEqual(data['camera_mode']['negotiated_fps'],60)
                    self.assertAlmostEqual(data['recording_metrics']['stored_fps'],60,places=3)
                    self.assertLess(data['recording_metrics']['max_frame_gap_ms'],17)
            finally:c.close()


if __name__=='__main__':unittest.main()
