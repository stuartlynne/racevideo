import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from racevideo import storage,bib_review
from racevideo.ocr_import import prepare,import_clip


class OCRImportTests(unittest.TestCase):
    def test_trim_and_bike_metadata_commit_with_ocr_without_rewriting_frames(self):
        from racevideo import retention
        report=copy.deepcopy(self.report)
        report['retention_proposal']=retention.propose(report['results'],[True]*3,{'mode':'bicycle'})
        report['bike_index']=dict(source='detector',passages=[],approximate=True)
        before=[tuple(r) for r in self.c.execute('SELECT * FROM frames')]
        self.assertTrue(import_clip(self.c,report))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM retention_proposals').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM bike_analyses').fetchone()[0],1)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM frames')])
    def test_bad_trim_metadata_rolls_back_entire_ocr_import(self):
        report=copy.deepcopy(self.report)
        report['retention_proposal']=dict(state='proposal',intervals=[dict(first_ordinal=100,last_ordinal=200)])
        with self.assertRaises(ValueError):import_clip(self.c,report)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM ocr_reads').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM ocr_observations').fetchone()[0],0)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'import.sqlite3';self.c=storage.connect(self.path);storage.initialize(self.c)
        image=Image.new('RGB',(100,80),'white');out=io.BytesIO();image.save(out,'JPEG');self.jpeg=out.getvalue();self.ns=1_800_000_000_000_000_000
        frames=[storage.Frame(self.ns+i*30_000_000,self.ns+i*30_000_000,i,'1/30',self.jpeg) for i in range(3)]
        self.clip=storage.save_clip(self.c,frames,self.ns,'fixture',100,80,'fixture')
        self.manifest=dict(batch_id='testbatch',engine='paddle-v5-rider-native-v1',parameters={},clips=[self.clip])
        prepare(self.c,self.manifest)
        rows=[];views=[]
        for i in range(3):
            reading=dict(text='826',score=.99,quad=[[10,10],[60,10],[60,40],[10,40]],rotation=0,detector_score=.9)
            row=dict(clip=self.clip,ordinal=i,received_ns=self.ns+i*30_000_000,monotonic_ns=self.ns+i*30_000_000,readings=[reading]);rows.append(row)
            views.append(dict(row,readings=[dict(reading,ordinal=i)]))
        source={k:self.c.execute('SELECT '+k+' FROM clips WHERE id=?',(self.clip,)).fetchone()[0] for k in ('id','started_ns','ended_ns','frame_count','width','height')}
        self.report=dict(state='complete',clip=self.clip,batch_id='testbatch',engine='paddle-v5-rider-native-v1',source_clip=source,frames=3,results=rows,
                         encounters=[dict(track=1,views=views,consensus=dict(status='repeated_candidate',alternatives=[dict(number='826')]))],wall_seconds=1,cpu_seconds=.5,regions=3)
    def tearDown(self):self.c.close();self.temp.cleanup()
    def test_import_is_atomic_idempotent_and_never_changes_frames(self):
        self.assertTrue(import_clip(self.c,self.report));self.assertFalse(import_clip(self.c,self.report))
        self.assertEqual(self.c.execute('SELECT count(*) FROM ocr_runs').fetchone()[0],1)
        self.assertEqual(self.c.execute('SELECT count(*) FROM ocr_reads').fetchone()[0],3)
        row=self.c.execute('SELECT * FROM ocr_observations').fetchone();self.assertEqual((row['number'],row['frame_count'],row['confidence']),('826',3,99))
        self.assertEqual(row['encounter_key'],'testbatch:'+str(self.clip)+':track:1')
        self.assertEqual(storage.read_frame(self.c,self.clip,1),self.jpeg)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_wrong_source_and_partial_reports_cannot_replace_evidence(self):
        for change in ('timestamp','source','coverage'):
            report=copy.deepcopy(self.report)
            if change=='timestamp':report['results'][0]['received_ns']+=1
            elif change=='source':report['source_clip']['started_ns']+=1
            else:report['results'].pop()
            with self.assertRaises(ValueError):import_clip(self.c,report)
        self.assertEqual(self.c.execute('SELECT count(*) FROM ocr_reads').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT state FROM ocr_runs').fetchone()[0],'queued')
    def test_cpu_assistance_records_actual_device_instead_of_queued_gpu_source(self):
        with self.c:self.c.execute('UPDATE ocr_runs SET parameters=?',(json.dumps({'source':'zbook9 NVIDIA batch'}),))
        report=dict(self.report,device='cpu');import_clip(self.c,report)
        run=self.c.execute('SELECT parameters,summary FROM ocr_runs').fetchone()
        self.assertEqual(json.loads(run['parameters'])['device'],'cpu')
        self.assertEqual(json.loads(run['summary'])['device'],'cpu')
        self.assertNotIn('NVIDIA',run['parameters'])
    def test_two_digit_reads_import_as_two_digits(self):
        report=copy.deepcopy(self.report)
        for row in report['results']:
            for reading in row['readings']:reading['text']='24'
        for view in report['encounters'][0]['views']:
            for reading in view['readings']:reading['text']='24'
        report['encounters'][0]['consensus']['alternatives'][0]['number']='24'
        import_clip(self.c,report)
        self.assertEqual(self.c.execute('SELECT number FROM ocr_observations').fetchone()[0],'24')
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,bibs=('24',))],[self.clip])

    def test_physical_consensus_appends_missing_reads_once_and_preserves_human_decisions(self):
        from racevideo.ocr_import import append_physical_consensus
        report=copy.deepcopy(self.report);report['encounters']=[]
        for i,row in enumerate(report['results']):
            row['readings'][0].update(text='5',quad=[[10+i*10,10],[30+i*10,10],[30+i*10,35],[10+i*10,35]])
        import_clip(self.c,report)
        bib_review.decide(self.path,self.clip,decision='manual',number='24',ordinal=1)
        before=[tuple(r) for r in self.c.execute('SELECT * FROM bib_reviews')]
        run=self.c.execute('SELECT id FROM ocr_runs').fetchone()[0]
        bikes=dict(passages=[dict(key='detected:1',review_secondary=False,points=[dict(ordinal=i,box=[i*10,0,70+i*10,70]) for i in range(3)])])
        with self.c:self.assertEqual(append_physical_consensus(self.c,run,report,bikes),1)
        with self.c:self.assertEqual(append_physical_consensus(self.c,run,report,bikes),0)
        self.assertEqual([tuple(r) for r in self.c.execute('SELECT * FROM bib_reviews')],before)
        row=self.c.execute('SELECT number,frame_count,encounter_key FROM ocr_observations').fetchone()
        self.assertEqual(tuple(row),('5',3,'testbatch:1:track:physical:detected:1'))
    def test_import_rerun_keeps_operator_correction_and_does_not_duplicate_sighting(self):
        import_clip(self.c,self.report);oid=self.c.execute('SELECT id FROM ocr_observations').fetchone()[0]
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='corrected',number='155')
        manifest=dict(self.manifest,batch_id='secondbatch');prepare(self.c,manifest)
        report=copy.deepcopy(self.report);report['batch_id']='secondbatch'
        for row in report['results']:
            for reading in row['readings']:reading['text']='155'
        for view in report['encounters'][0]['views']:
            for reading in view['readings']:reading['text']='155'
        report['encounters'][0]['consensus']['alternatives'][0]['number']='155'
        import_clip(self.c,report)
        sightings=storage.bib_passages(self.c)
        self.assertEqual(len(sightings),1);self.assertEqual(sightings[0]['number'],'155')
        self.assertEqual(sightings[0]['decision'],'corrected')
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_review_history').fetchone()[0],1)
    def test_active_day_batch_protects_even_completed_clips_from_cleanup(self):
        import_clip(self.c,self.report)
        from datetime import datetime
        day=datetime.fromtimestamp(self.ns/1e9).date().isoformat()
        preview=storage.cleanup_preview(self.c,day);self.assertEqual(preview['clips'],0);self.assertEqual(preview['busy'],1)
        with self.c:self.c.execute("UPDATE ocr_batches SET state='complete'")
        self.assertEqual(storage.cleanup_preview(self.c,day)['ids'],[self.clip])


if __name__=='__main__':unittest.main()
