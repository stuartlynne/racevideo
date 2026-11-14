import json
import unittest
import test_passings as fixtures
from racevideo import storage,wheel_timing,passings,bike_index


class TimingLinkTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PassingsTests();self.f.setUp();self.c=self.f.c
        self.clip=self.f.clip(60,'24');self.entry=bike_index.navigation(self.c,self.clip)['stops'][0]
        self.cell=next(c for c in passings.compare_event(self.c,self.f.event)['cells'] if c['bib']=='24' and c.get('seconds')==60)
        with self.c:self.analysis=self.c.execute("INSERT INTO wheel_analyses(clip_id,subject_key,created_ns,updated_ns,state,parameters) VALUES(?,'test',0,0,'queued',?)",(self.clip,json.dumps(dict(entry=self.entry)))).lastrowid
        self.context=dict(event_id=self.f.event,cell_key=self.cell['cell_key'],bib='24',offset=.1,confirmed=False)
    def tearDown(self):self.f.tearDown()
    def complete(self,estimate=True):
        start=self.f.start
        report=dict(line_x=.5,status='crossing_estimate',timing_basis='host receipt clock; uncalibrated',crossing=dict(
            status='interpolated' if estimate else 'missing_frames',before_ordinal=0,first_observed_after_ordinal=1 if estimate else 3,
            before_received_ns=start+60_000_000_000,after_received_ns=start+60_100_000_000,
            bracket_monotonic_ns=100_000_000,estimated_received_ns=start+60_050_000_123 if estimate else None))
        with self.c:self.c.execute("UPDATE wheel_analyses SET state='complete',report=? WHERE id=?",(json.dumps(report),self.analysis))
    def link(self,context=None):
        with self.c:return wheel_timing.link_passing(self.c,self.analysis,context or self.context)
    def test_pending_association_survives_worker_finish_and_keeps_nanosecond_precision(self):
        ident=self.link();self.assertEqual(ident,self.link())
        row=wheel_timing.linked_results(self.c,self.f.event)[0]
        self.assertEqual(row['analysis_state'],'queued');self.assertIsNone(row['race_elapsed_ns'])
        self.complete();row=wheel_timing.linked_results(self.c,self.f.event)[0]
        self.assertEqual(row['race_elapsed_ns'],59_950_000_123)
        self.assertEqual(row['cm_estimate_ns'],self.f.start+59_950_000_123)
        self.assertEqual(row['before_ordinal'],0);self.assertEqual(row['first_after_ordinal'],1)
        self.assertEqual(row['bracket_ns'],100_000_000);self.assertEqual(row['passing_id'],int(self.cell['cell_key'][3:]))
        self.assertEqual(row['operator_timing_reviewed'],0)
    def test_missing_frame_bracket_never_fabricates_a_race_time(self):
        self.link();self.complete(False);row=wheel_timing.linked_results(self.c,self.f.event)[0]
        self.assertIsNone(row['race_elapsed_ns']);self.assertEqual(row['before_race_ns'],59_900_000_000)
        self.assertEqual(row['after_race_ns'],60_000_000_000);self.assertEqual(row['crossing_method'],'missing_frames')
    def test_wrong_passing_bib_is_rejected_without_link(self):
        with self.assertRaises(ValueError):self.link(dict(self.context,bib='7'))
        self.assertEqual(self.c.execute('SELECT count(*) FROM passing_timing_links').fetchone()[0],0)
    def test_model_includes_current_clock_context_and_keeps_old_snapshots(self):
        self.link();self.complete()
        model=passings.compare_event(self.c,self.f.event,offset=.1)
        cell=next(c for c in model['cells'] if c['cell_key']==self.cell['cell_key'])
        self.assertEqual(len(cell['video_timings']),1)
        self.assertFalse(next(c for c in passings.compare_event(self.c,self.f.event,offset=.2)['cells'] if c['cell_key']==self.cell['cell_key'])['video_timings'])
        self.link(dict(self.context,offset=.2));self.assertEqual(len(wheel_timing.linked_results(self.c,self.f.event)),2)
        with self.c:self.c.execute('UPDATE race_events SET start_ns=start_ns+1000000000 WHERE id=?',(self.f.event,))
        self.assertTrue(all(r['stale_race_start'] for r in wheel_timing.linked_results(self.c,self.f.event)))
        self.assertFalse(next(c for c in passings.compare_event(self.c,self.f.event,offset=.2)['cells'] if c['cell_key']==self.cell['cell_key'])['video_timings'])
    def test_evidence_keys_are_required_and_multiple_possible_passings_stay_unlinked(self):
        model=passings.compare_event(self.c,self.f.event)
        context=wheel_timing.passing_context(model,self.clip,self.entry,self.cell['cell_key'])
        self.assertEqual(context['bib'],'24')
        unrelated=dict(self.entry,key='different',source_keys=[],visual_key='different')
        self.assertIsNone(wheel_timing.passing_context(model,self.clip,unrelated,self.cell['cell_key']))
        import copy
        other=copy.deepcopy(self.cell);other['cell_key']='visual:duplicate'
        model['cells'].append(other)
        self.assertIsNone(wheel_timing.passing_context(model,self.clip,self.entry))
    def test_cached_analysis_can_link_another_context_without_running_again(self):
        import importlib.util
        if importlib.util.find_spec('cv2') is None:self.skipTest('Optional OpenCV runtime absent')
        from unittest.mock import patch
        with patch('racevideo.service.neural_runtime',return_value=None),patch('racevideo.service.launch_worker') as launch:
            ident=wheel_timing.start(self.f.path,self.clip,self.entry,context=self.context)
            self.assertEqual(self.c.execute('SELECT count(*) FROM passing_timing_links WHERE analysis_id=?',(ident,)).fetchone()[0],1)
            with self.c:self.c.execute("UPDATE wheel_analyses SET state='complete' WHERE id=?",(ident,))
            again=wheel_timing.start(self.f.path,self.clip,self.entry,context=dict(self.context,offset=.2))
            self.assertEqual(ident,again);self.assertEqual(launch.call_count,1)
            self.assertEqual(self.c.execute('SELECT count(*) FROM passing_timing_links WHERE analysis_id=?',(ident,)).fetchone()[0],2)
    def test_worker_publishes_progress_while_readers_wait_and_preserves_link(self):
        import importlib.util
        if importlib.util.find_spec('cv2') is None:self.skipTest('Optional OpenCV runtime absent')
        from unittest.mock import patch
        entry=dict(self.entry,first_ordinal=0,last_ordinal=3,points=[dict(ordinal=0,box=[0,0,40,30]),dict(ordinal=3,box=[20,0,60,30])])
        with self.c:self.c.execute('UPDATE wheel_analyses SET parameters=? WHERE id=?',(json.dumps(dict(entry=entry,line_x=.5,detector_device=None)),self.analysis))
        self.link();observed=[]
        def observe(*args):
            current=wheel_timing.active(self.c)
            observed.append(current['report']['progress'])
            return None
        with patch('racevideo.wheel_timing.detect',side_effect=observe),patch('os.sched_setaffinity'):
            wheel_timing.run(self.f.path,self.analysis)
        self.assertEqual(len(observed),4)
        self.assertTrue(all(p['stage']=='Measuring wheels' and p['total']==4 for p in observed))
        result=wheel_timing.read(self.c,self.analysis)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['report']['progress']['processed'],4)
        self.assertEqual(wheel_timing.linked_results(self.c,self.f.event)[0]['analysis_state'],'complete')
