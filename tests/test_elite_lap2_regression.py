"""Real five-rider capture: order/crossings, not merely a reduced row count."""
import json
from pathlib import Path
import unittest
import copy
from racevideo.bike_index import build,primary_stops
from racevideo.rider_encounters import summarize


class EliteLap2RegressionTests(unittest.TestCase):
    def test_five_distinct_crossings_and_recovered_small_plate_reads(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/elite-lap2-1872.json').read_text())
        report=build(fixture['rows'],fixture['width'],fixture['height'])
        stops=primary_stops(report['passages'])
        self.assertEqual([e['ordinal'] for e in stops],[20,24,42,55,79])
        self.assertEqual(len(stops),5)
        encounters=summarize(fixture['rows'],report)
        numbers={e['physical_track']:{a['number']:a['frame_count'] for a in e['consensus']['alternatives']} for e in encounters}
        for index,number in [(0,'5'),(1,'6'),(2,'2'),(4,'60')]:
            self.assertGreaterEqual(numbers[stops[index]['key']][number],3)
        # Rider 1 is visibly present in the fourth trajectory, but one raw read
        # on a different rider is insufficient to manufacture its OCR identity.
        self.assertNotIn('1',{n for values in numbers.values() for n in values})

    def test_review_table_has_five_ordered_positions_and_distinct_review_frames(self):
        import test_passings as fixtures
        from racevideo import storage,bike_index,passings
        from racevideo.passings_layout import layout
        fixture=json.loads((Path(__file__).parent/'fixtures/elite-lap2-1872.json').read_text())
        f=fixtures.PassingsTests();f.setUp()
        try:
            riders=[]
            for bib,ordinal in [(5,20),(6,24),(2,42),(1,55),(60,79)]:
                row=copy.deepcopy(f.source['review']['race']['rows'][0])
                t=60+(ordinal-20)/30
                row.update(bib=bib,passings=[dict(seconds=t,provenance='Unattributed',metadata=None)],
                    calculated_times=[0,t],calculated_interpolation=[False,False])
                riders.append(row)
            f.source['review']['race']['rows']=riders
            for key in ('inspect','review'):f.source[key]['inputs'][0]['sha256']='real-five-rider-regression'
            f.cache(f.source)
            rows=copy.deepcopy(fixture['rows']);first=f.start+round((60-20/30)*10**9)
            for row in rows:row['received_ns']=first+round(row['ordinal']/30*10**9)
            frames=[storage.Frame(r['received_ns'],r['monotonic_ns'],r['ordinal'],'1/30',f.jpeg) for r in rows]
            clip=storage.save_clip(f.c,frames,first,'regression',3840,2160,'fixture')
            report=build(rows,3840,2160);bike_index.save(f.c,clip,report)
            run=storage.create_ocr_run(f.path,clip,{})
            with f.c:
                for e in summarize(rows,report):
                    for a in e['consensus']['alternatives']:
                        readings=[r for v in e['views'] for r in v['readings'] if r['text']==a['number']]
                        best=max(readings,key=lambda r:r['score']);n=best['ordinal']
                        f.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,
                            ordinal,quad,evidence,status,encounter_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                            (run,a['number'],rows[e['first_ordinal']]['received_ns'],rows[e['last_ordinal']]['received_ns'],
                            a['frame_count'],99,n,json.dumps(best['quad']),f.jpeg,'repeated','fixture:track:'+e['track']))
                f.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
            model=passings.compare_event(f.c,f.event)
            table=layout(model['cells'],[1])
            displayed=[row['cells'][1] for row in table if 1 in row['cells']]
            self.assertEqual([c['bib'] for c in displayed],['5','6','2','1','60'])
            self.assertEqual([c['captures'][0]['ordinal'] for c in displayed],[20,24,42,55,79])
            self.assertFalse(any(c['confirmed'] for c in displayed))
            self.assertEqual(displayed[3]['state'],'missing')
        finally:f.tearDown()
