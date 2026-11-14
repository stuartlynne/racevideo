from collections import deque
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from racevideo import storage
from racevideo.motion import DEFAULT_ROI, MotionDetector, MotionEvents, validate_roi


def picture(box=None, background=70):
    image = Image.new("L", (640, 360), background)
    if box:
        ImageDraw.Draw(image).rectangle(box, fill=220)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def frame(t):
    ns = round(t * 1e9)
    return storage.Frame(ns + 100_000_000_000, ns, ns, "1/1000000000", b"jpeg")


class DetectorTests(unittest.TestCase):
    def test_static_noise_and_motion_outside_roi_do_not_trigger(self):
        detector = MotionDetector()
        self.assertEqual(detector.analyze(picture()), (False, 0))
        self.assertFalse(detector.analyze(picture(background=73))[0])
        self.assertFalse(detector.analyze(picture((10, 80, 90, 180)))[0])
        detected, score = detector.analyze(picture((285, 100, 340, 210)))
        self.assertTrue(detected)
        self.assertGreater(score, 0.025)

    def test_changed_roi_resets_reference_without_triggering(self):
        detector = MotionDetector()
        detector.analyze(picture((10, 80, 90, 180)))
        detector.reset((0, 0, 0.3, 0.8))
        self.assertEqual(detector.analyze(picture((10, 80, 90, 180))), (False, 0))
        self.assertFalse(detector.analyze(picture((10, 80, 90, 180)))[0])

    def test_invalid_roi_is_rejected(self):
        for roi in ((0, 0, 0, 1), (-0.1, 0, 1, 1), (0, 0, 1, 2), (0, 0, 0.01, 1),
                    (float("nan"), 0, 1, 1)):
            with self.assertRaises(ValueError):
                validate_roi(roi)
        self.assertEqual(validate_roi(DEFAULT_ROI), DEFAULT_ROI)


class EventTests(unittest.TestCase):
    def test_quiet_limit_separates_riders_before_old_postroll_ends(self):
        events=MotionEvents(quiet_close=1);history=[];completed=[]
        for tick in range(45):
            f=frame(tick/10);history.append(f)
            completed.extend(events.update(f,tick in (10,25),history))
        self.assertEqual(len(completed),2)
        self.assertEqual(completed[0].frames[-1].monotonic_ns,frame(2).monotonic_ns)
        self.assertEqual(completed[1].frames[0].monotonic_ns,frame(2).monotonic_ns)
        self.assertNotEqual(completed[0].metadata['event_id'],completed[1].metadata['event_id'])
        self.assertEqual(completed[0].metadata['post_roll_seconds'],2)
        self.assertEqual(completed[0].metadata['effective_quiet_close_seconds'],1)

    def test_half_second_pre_roll_two_second_tail_and_gap_merging(self):
        events, history, completed = MotionEvents(), deque(), []
        for tick in range(47):
            f = frame(tick / 10)
            history.append(f)
            completed.extend(events.update(f, tick in (10, 12, 25), history))
            if tick == 11:
                self.assertTrue(events.moving(f.monotonic_ns))
            if tick == 15:
                self.assertFalse(events.moving(f.monotonic_ns))
                self.assertTrue(events.active)  # Yellow, but retaining the tail.
        self.assertEqual(len(completed), 1)
        clip = completed[0]
        self.assertEqual(clip.frames[0].monotonic_ns, frame(0.5).monotonic_ns)
        self.assertEqual(clip.frames[-1].monotonic_ns, frame(4.5).monotonic_ns)
        self.assertEqual(len(clip.frames), 41)
        self.assertEqual(clip.trigger_ns, frame(1).received_ns)
        self.assertFalse(events.active)

    def test_new_motion_after_tail_is_a_separate_clip(self):
        events, history, completed = MotionEvents(), [], []
        for tick in range(63):
            f = frame(tick / 10)
            history.append(f)
            completed.extend(events.update(f, tick in (10, 40), history))
        self.assertEqual(len(completed), 2)
        self.assertNotEqual(completed[0].metadata["event_id"], completed[1].metadata["event_id"])
        self.assertEqual(completed[0].frames[-1].monotonic_ns, frame(3).monotonic_ns)
        self.assertEqual(completed[1].frames[0].monotonic_ns, frame(3.5).monotonic_ns)

    def test_long_motion_splits_without_losing_or_duplicating_frames(self):
        events = MotionEvents(pre=0, max_bytes=20)
        completed = []
        for tick in range(15):
            f = frame(tick / 10)
            completed.extend(events.update(f, True, [f]))
        clip = events.flush()
        if clip:
            completed.append(clip)
        self.assertEqual(len(completed), 3)
        self.assertEqual([f.monotonic_ns for c in completed for f in c.frames],
                         [frame(t / 10).monotonic_ns for t in range(15)])
        self.assertEqual(len({c.metadata["event_id"] for c in completed}), 1)
        self.assertEqual([c.metadata["chunk"] for c in completed], [0, 1, 2])

    def test_unsampled_frames_are_retained_and_stop_flushes_partial_event(self):
        events, history = MotionEvents(), []
        for tick in range(20):
            f = frame(tick / 10)
            history.append(f)
            events.update(f, True if tick == 10 else None, history)
        clip = events.flush("stop")
        self.assertEqual(len(clip.frames), 15)
        self.assertEqual(clip.metadata["end_reason"], "stop")
        self.assertFalse(events.active)


class MigrationTests(unittest.TestCase):
    def test_settings_and_event_metadata_preserve_old_recordings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clips.sqlite3"
            connection = storage.connect(path)
            storage.initialize(connection)
            f = storage.Frame(0, 0, 0, "1/1", picture())
            old_id = storage.save_clip(connection, [f], 0, "timer", 640, 360, "old")
            connection.executescript("DROP TABLE settings; DROP TABLE clip_details; PRAGMA user_version=1;")
            storage.initialize(connection)
            self.assertEqual(storage.read_frame(connection, old_id, 0), f.jpeg)
            storage.write_setting(path, "motion_roi", list(DEFAULT_ROI))
            self.assertEqual(storage.read_setting(connection, "motion_roi"), list(DEFAULT_ROI))
            new_id = storage.save_clip(connection, [f], 0, "motion", 640, 360, "new", {"roi": list(DEFAULT_ROI)})
            saved = json.loads(connection.execute("SELECT metadata FROM clip_details WHERE clip_id=?",
                                                  (new_id,)).fetchone()[0])
            self.assertEqual(saved["roi"], list(DEFAULT_ROI))
            connection.close()


if __name__ == "__main__":
    unittest.main()
