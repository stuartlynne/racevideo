import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from racevideo.storage import Frame
from racevideo.pipeline import FrameRing, PreviewSource, preview_path, PreparedImage, PacketGuard
from racevideo.performance import Performance


class PipelineTests(unittest.TestCase):
    def test_variable_byte_ring_wraps_and_reports_lost_history(self):
        ring = FrameRing(13, slots=4)
        inputs = []
        for i, size in enumerate((4, 5, 3, 6, 2, 4)):
            f = Frame(100+i, 200+i, None if i%2 else i*30, '1/90000', bytes([i])*size)
            inputs.append(f)
            self.assertTrue(ring.append(f))
        cursor, batch, missed, info = ring.read(0, limit=10)
        self.assertEqual(batch, inputs[-3:])
        self.assertEqual(missed, 3)
        self.assertEqual(cursor, 6)
        self.assertEqual(info['ring_bytes'], 12)
        self.assertLessEqual(info['ring_bytes'], ring.capacity)
        self.assertFalse(ring.append(Frame(0,0,None,None,b'x'*14)))
        self.assertEqual(ring.read(cursor)[3]['oversized_frames'], 1)

    def test_ring_metadata_also_bounded_and_cursors_independent(self):
        ring = FrameRing(1024, slots=2)
        for i in range(4):ring.append(Frame(i,i,i,None,b'x'))
        cursor, batch, missed, info = ring.read(0, limit=1)
        self.assertEqual((cursor,missed,len(batch)),(3,2,1))
        self.assertEqual(ring.read(cursor)[1][0].received_ns,3)
        self.assertEqual(ring.read(0)[2],2)
        self.assertEqual(info['ring_frames'],2)

    def test_preview_mailbox_replaces_without_growing_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'recording.sqlite3'
            writer=PreviewSource(path,create=True);reader=PreviewSource(path)
            try:
                for i in range(3):writer.write(Frame(i+1,i+10,i,'1/30',bytes([i])*100))
                received,monotonic,jpeg=reader.read(0)
                self.assertEqual((received,monotonic,jpeg),(3,12,b'\x02'*100))
                self.assertIsNone(reader.read(received))
                self.assertEqual(preview_path(path).stat().st_mode & 0o777,0o600)
                size=preview_path(path).stat().st_size
                writer.write(Frame(4,13,None,None,b'a'))
                self.assertEqual(preview_path(path).stat().st_size,size)
            finally:reader.close();writer.close()

    def test_prepared_image_is_latest_only_and_busy_worker_never_blocks_gui(self):
        slot=PreparedImage()
        for i in range(1,4):
            self.assertTrue(slot.write(dict(produced=i, size=(2,1), rgb=bytes([i])*6)))
        self.assertEqual(slot.read()['rgb'],b'\x03'*6)
        self.assertIsNone(slot.read())
        slot.lock.acquire()
        try:
            self.assertIsNone(slot.read())
            self.assertFalse(slot.write(dict(produced=4,size=(2,1),rgb=b'x'*6)))
        finally:slot.lock.release()

    def test_isolated_corrupt_packet_is_skipped_and_session_recovers(self):
        guard=PacketGuard(0)
        self.assertTrue(guard.accept(b'\xff\xd8jpeg\xff\xd9',.01))
        self.assertFalse(guard.accept(b'broken',.02))
        self.assertFalse(guard.accept(b'\xff\xd8truncated',.03))
        self.assertTrue(guard.accept(b'\xff\xd8jpeg\xff\xd9',.04))
        self.assertEqual((guard.bad_packets,guard.consecutive),(2,0))
        ring=FrameRing(100)
        ring.bad_packets.value=2
        frame=Frame(1,2,None,None,b'\xff\xd8jpeg\xff\xd9',2)
        ring.append(frame)
        self.assertEqual(ring.read(0)[1],[frame])
        self.assertEqual(ring.read(0)[3]['capture_bad_packets'],2)

    def test_persistent_corruption_and_flagged_jpegs_fail_instead_of_hiding_failure(self):
        guard=PacketGuard(0,max_consecutive=3)
        self.assertFalse(guard.accept(b'\xff\xd8jpeg\xff\xd9',.1,corrupt=True))
        self.assertFalse(guard.accept(b'bad',.2))
        with self.assertRaisesRegex(RuntimeError,'stream unusable'):guard.accept(b'bad',.3)
        timed=PacketGuard(0)
        with self.assertRaisesRegex(RuntimeError,'stream unusable'):timed.accept(b'bad',2.1)

    def test_metrics_have_bounded_window_and_percentiles(self):
        p=Performance(samples=3)
        for x in range(10):p.observe('work_ms',x)
        self.assertEqual(p.snapshot()['work_ms'],dict(last=9.0,p50=8.0,p95=9.0,max=9.0,samples=3))


if __name__=='__main__':unittest.main()
