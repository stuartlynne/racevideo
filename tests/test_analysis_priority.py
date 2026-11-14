import copy,json,unittest
import test_passings as fixtures
from racevideo import analysis_priority as priority,storage,service
from unittest.mock import patch


class AnalysisPriorityTests(unittest.TestCase):
    def test_newest_first_and_explicit_operator_selection_first(self):
        tasks=[dict(clip_id=i,seen_ns=i,finishes=[]) for i in (1,3,2)]
        self.assertEqual([t['clip_id'] for t in priority.order(tasks)],[3,2,1])
        self.assertEqual([t['clip_id'] for t in priority.order(tasks,selected_clip=1)],[1,3,2])
    def test_category_top_five_turns_do_not_starve_another_finish(self):
        tasks=[]
        for cat,count,first in [('A',8,100),('B',3,110),('C',2,120)]:
            for rank in range(1,count+1):tasks.append(dict(clip_id=cat+str(rank),seen_ns=first+rank,finishes=[dict(category=cat,rank=rank,category_first_ns=first,at_ns=first+rank)]))
        ids=lambda tasks:[t['clip_id'] for t in priority.order(tasks)]
        self.assertEqual(ids(tasks),['A1','A2','A3','A4','A5','B1','B2','B3','C1','C2','A6','A7','A8'])
        remaining=[t for t in tasks if t['clip_id'] not in {'A1','A2','A3','A4','A5'}]
        self.assertEqual(ids(remaining)[0],'B1')
        # A newly arriving category leader is reprioritized before A's tail.
        remaining.append(dict(clip_id='D1',seen_ns=200,finishes=[dict(category='D',rank=1,category_first_ns=200,at_ns=200)]))
        self.assertLess(ids(remaining).index('D1'),ids(remaining).index('A6'))
    def test_category_start_offsets_and_lap_targets_are_independent(self):
        f=fixtures.PassingsTests();f.setUp()
        try:
            data=copy.deepcopy(f.source);data['inspect']['race']['state']='running';data['inspect']['race']['categories'][0]['laps']=2
            data['inspect']['race']['categories'].append(dict(name='Later wave',wave=True,laps=1,start_offset='1:00'))
            row=copy.deepcopy(data['review']['race']['rows'][1]);row.update(bib=90,category='Later wave',position='1',start_offset='1:00',calculated_times=[0,85],calculated_interpolation=[False,False],passings=[dict(seconds=85,provenance='test',metadata=None)])
            data['review']['race']['rows'].append(row);data['inspect']['inputs'][0]['sha256']='priority';event=f.cache(data)
            facts=priority.finish_candidates(f.c,event)['finishes']
            later=next(r for r in facts if r['bib']=='90')
            self.assertEqual(later['target_laps'],1);self.assertEqual(later['start_offset'],'1:00')
            self.assertEqual(later['at_ns'],f.start+85_000_000_000) # No second application of wave offset.
            self.assertFalse(any(r['bib']=='4' for r in facts)) # Projected lap is not a finish.
            a=f.clip(120);b=f.clip(85);recent=f.clip(160)
            clips=[dict(r) for r in f.c.execute('SELECT * FROM clips')]
            self.assertEqual([t['clip_id'] for t in priority.plan(f.c,event,clips)['tasks']],[b,a,recent])
        finally:f.tearDown()
    def test_pending_queue_rechecks_latest_race_snapshot_between_jobs(self):
        f=fixtures.PassingsTests();f.setUp()
        try:
            old=f.clip(80);new=f.clip(90)
            with patch.object(service,'neural_runtime',return_value=('/dummy/python','cpu')),patch.object(service,'launch_worker'):
                runs=service.start_bikes(f.path,event_id=f.event)
            self.assertEqual(priority.pending(f.c,runs,f.event),runs)
            data=copy.deepcopy(f.source);data['inspect']['inputs'][0]['sha256']='new-finish'
            data['inspect']['race']['state']='running';data['inspect']['race']['categories'][0]['laps']=1
            for row in data['review']['race']['rows']:
                if row['bib']==24:
                    row.update(position='1',calculated_times=[0,80],calculated_interpolation=[False,False],passings=[dict(seconds=80,provenance='test',metadata=None)])
            f.cache(data)
            self.assertEqual(priority.pending(f.c,runs,f.event),list(reversed(runs)))
            with f.c:f.c.execute("UPDATE bike_analyses SET state='complete' WHERE id=?",(runs[0],))
            self.assertEqual(priority.pending(f.c,runs,f.event),runs[1:])
            with f.c:f.c.execute("UPDATE bike_analyses SET state='cancelled' WHERE id=?",(runs[1],))
            self.assertEqual(priority.pending(f.c,runs,f.event),[])
        finally:f.tearDown()
