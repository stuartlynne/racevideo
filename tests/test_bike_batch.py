import unittest,json
from unittest.mock import patch
import test_passings as fixtures
from racevideo import bike_index,service


class BikeBatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PassingsTests();self.f.setUp()
    def tearDown(self):self.f.tearDown()
    def test_event_index_skips_current_policy_queues_old_and_missing_and_can_stop(self):
        f=self.f
        current=f.clip(75);old=f.clip(80);missing=f.clip(85);outside=f.clip(300)
        ident=f.index_bikes(current)
        report=json.loads(f.c.execute('SELECT report FROM bike_analyses WHERE id=?',(ident,)).fetchone()[0])
        report['policy']='passage-v4'
        with f.c:f.c.execute('UPDATE bike_analyses SET report=? WHERE id=?',(json.dumps(report),ident))
        bike_index.save(f.c,old,dict(source='detector',passages=[]))
        with patch.object(service,'neural_runtime',return_value=('/dummy/python','cpu')),patch.object(service,'launch_worker') as launch:
            runs=service.start_bikes(f.path,event_id=f.event)
            self.assertEqual(len(runs),2)
            queued=[r[0] for r in f.c.execute("SELECT clip_id FROM bike_analyses WHERE state='queued' ORDER BY id")]
            self.assertEqual(queued,[missing,old])
            args=launch.call_args.args[0]
            self.assertEqual(args[args.index('--analysis')+1:args.index('--models')],list(map(str,runs)))
            self.assertNotIn(outside,queued)
            self.assertEqual(service.stop_event_bikes(f.path,f.event),2)
            self.assertFalse(f.c.execute("SELECT 1 FROM bike_analyses WHERE state='queued'").fetchone())
            self.assertEqual(f.c.execute("SELECT count(*) FROM bike_analyses WHERE state='complete'").fetchone()[0],2)
    def test_launch_failure_marks_all_queued_jobs_error(self):
        f=self.f;f.clip(80);f.clip(90)
        with patch.object(service,'neural_runtime',return_value=('/dummy/python','cpu')),patch.object(service,'launch_worker',side_effect=RuntimeError('launch failed')):
            with self.assertRaisesRegex(RuntimeError,'launch failed'):service.start_bikes(f.path,event_id=f.event)
        self.assertEqual([r[0] for r in f.c.execute('SELECT state FROM bike_analyses')],['error','error'])
    def test_stop_finishes_active_clip_and_preserves_other_event_queue(self):
        f=self.f;a=f.clip(80);b=f.clip(90);outside=f.clip(300)
        with f.c:
            for clip,state in ((a,'running'),(b,'queued'),(outside,'queued')):
                f.c.execute('INSERT INTO bike_analyses(clip_id,created_ns,state) VALUES(?,0,?)',(clip,state))
        self.assertEqual(service.stop_event_bikes(f.path,f.event),1)
        self.assertEqual([r[0] for r in f.c.execute('SELECT state FROM bike_analyses ORDER BY id')],['running','cancelled','queued'])
