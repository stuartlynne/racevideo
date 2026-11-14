import unittest
from racevideo.wheel_timing import direction,box_at,passing_candidate


class WheelTimingTests(unittest.TestCase):
    def test_direction_and_region_extrapolation_do_not_invent_wheel_samples(self):
        entry=dict(points=[dict(ordinal=10,box=[300,100,500,400]),dict(ordinal=20,box=[100,100,300,400])])
        self.assertEqual(direction(entry,640),-1)
        self.assertEqual(box_at(entry,15),[200,100,400,400])
        self.assertEqual(box_at(entry,5),[400,100,600,400])
        self.assertEqual(direction(dict(points=[]),640),0)
    def test_future_candidate_has_explicit_units_frame_bracket_and_unreviewed_status(self):
        report=dict(line_x=.5,crossing=dict(estimated_received_ns=10_500_000_000,before_received_ns=10_490_000_000,
            after_received_ns=10_520_000_000,before_ordinal=14,first_observed_after_ordinal=15,bracket_monotonic_ns=30_000_000,status='interpolated'))
        result=passing_candidate(report,'24',dict(id=3,start_ns=1_000_000_000),offset=.5)
        self.assertEqual(result['race_elapsed_ns'],9_000_000_000)
        self.assertEqual(result['first_touch_or_past_ordinal'],15)
        self.assertFalse(result['operator_reviewed']);self.assertTrue(result['provisional'])
        self.assertIsNone(passing_candidate({}))
    def test_wheel_pair_detection_requires_two_plausible_wheels(self):
        try:import cv2,numpy as np
        except ImportError:self.skipTest('Optional OpenCV runtime is absent')
        from racevideo.wheel_timing import detect
        cv2.setNumThreads(1)
        image=np.full((480,640,3),160,dtype=np.uint8)
        for x in (220,440):cv2.circle(image,(x,350),65,(5,5,5),10)
        box=[145,160,520,425]
        left=detect(image,box,-1);right=detect(image,box,1)
        self.assertIsNotNone(left);self.assertIsNotNone(right)
        self.assertLess(abs(left['leading_x']-150),12);self.assertLess(abs(right['leading_x']-510),12)
        self.assertIsNone(detect(np.full_like(image,160),box,-1))
        self.assertIsNone(detect(image,box,0))

    def test_abandoned_cached_job_is_recovered_and_live_job_is_reused(self):
        import importlib.util,io,os,tempfile
        if importlib.util.find_spec('cv2') is None:self.skipTest('Optional OpenCV runtime absent')
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from racevideo import storage,wheel_timing
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'store.sqlite3';c=storage.connect(path);storage.initialize(c)
            image=io.BytesIO();Image.new('RGB',(64,32)).save(image,'JPEG')
            clip=storage.save_clip(c,[storage.Frame(100,100,0,'1/30',image.getvalue())],100,'test',64,32,'test')
            entry=dict(key='bike:1',first_ordinal=0,last_ordinal=0,ordinal=0,box=[0,0,64,32],points=[])
            with patch('racevideo.service.neural_runtime',return_value=None),patch('racevideo.service.launch_worker') as launch:
                first=wheel_timing.start(path,clip,entry)
                self.assertEqual(wheel_timing.start(path,clip,entry),first)
                self.assertEqual(launch.call_count,1)
                with c:c.execute('UPDATE wheel_analyses SET pid=?,updated_ns=0 WHERE id=?',(os.getpid(),first))
                second=wheel_timing.start(path,clip,entry)
                self.assertNotEqual(first,second)
                self.assertEqual(wheel_timing.read(c,first)['state'],'error')
                self.assertEqual(launch.call_count,2)
            c.close()

    def test_geometry_matching_uses_this_encounter_and_preserves_ambiguity(self):
        from racevideo.wheel_timing import associate_geometry
        def track(key,first,x,y=100):
            return dict(key=key,ordinal=first+5,first_ordinal=first,last_ordinal=first+10,box=[x-50,y,x+100,y+100],
                points=[dict(ordinal=first,box=[x,y,x+150,y+100]),dict(ordinal=first+10,box=[x-100,y,x+50,y+100])])
        one=track('one',5,300);later=track('later',35,300)
        anchor=dict(key='manual:1',ordinal=10,box=None)
        self.assertEqual(associate_geometry(anchor,[one,later],640)['key'],'one')
        self.assertIsNone(associate_geometry(anchor,[later],640))
        other=track('other',5,500)
        self.assertIsNone(associate_geometry(anchor,[one,other],640))
        anchor['box']=[250,100,400,200]
        self.assertEqual(associate_geometry(anchor,[one,other],640)['key'],'one')

    def test_single_frame_review_gets_geometry_without_rewriting_review_identity(self):
        import test_review_position as fixtures
        from racevideo import storage,wheel_timing
        f=fixtures.ReviewPositionTests();f.setUp()
        try:
            clip=f.clip();index=storage.frame_index(f.c,clip)
            anchor=dict(key='manual:235',visual_key='review:235',ordinal=10,first_ordinal=10,last_ordinal=10,box=None)
            before=[tuple(r) for r in f.c.execute('SELECT * FROM frames')]
            resolved,info=wheel_timing.resolve_geometry(f.c,clip,anchor,index,640)
            self.assertTrue(resolved.get('points'))
            self.assertNotEqual(wheel_timing.direction(resolved,640),0)
            self.assertEqual(resolved['key'],'manual:235');self.assertEqual(resolved['visual_key'],'review:235')
            self.assertEqual(resolved['ordinal'],10);self.assertEqual(anchor['first_ordinal'],10)
            self.assertEqual(info['source'],'source-frame motion scan')
            self.assertEqual(before,[tuple(r) for r in f.c.execute('SELECT * FROM frames')])
            self.assertEqual(f.c.execute('SELECT count(*) FROM bike_analyses').fetchone()[0],0)
        finally:f.tearDown()

    def test_progress_labels_identify_active_clip_stage_and_frames(self):
        from racevideo.wheel_timing import progress_label
        self.assertEqual(progress_label(dict(clip_id=818,state='running',report=dict(progress=dict(stage='Measuring wheels',processed=12,total=25)))),'clip #818 · Measuring wheels · 12/25 frames')
        self.assertIn('clip #818',progress_label(dict(clip_id=818,state='running',report={})))
        self.assertIn('retrying',progress_label(None))
