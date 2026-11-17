import io
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
import test_review_position as fixtures
from racevideo import storage,bike_index
from racevideo.motion_position import locate,scan


class MotionPositionTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReviewPositionTests();self.f.setUp();self.c=self.f.c;self.path=self.f.path
    def tearDown(self):self.f.tearDown()
    def test_velocity_bridges_brief_silhouette_loss_without_creating_another_bike(self):
        frames=[]
        for i in range(50):
            image=Image.new('RGB',(320,180),(i*4,)*3);buffer=io.BytesIO();image.save(buffer,'JPEG')
            frames.append(storage.Frame(1_000_000_000+i*33_333_333,i*33_333_333,i,'1/30',buffer.getvalue()))
        clip=storage.save_clip(self.c,frames,frames[10].received_ns,'test',320,180,'test')
        def blobs(image,background):
            i=round(image.getpixel((0,0))/4)
            if not (4<=i<=18 or 32<=i<=36):return []
            x=.05+(i-4)*.027
            return [dict(x=x,area=100,box=(x*160-8,25,x*160+8,70))]
        with patch('racevideo.motion_position.subjects',side_effect=blobs):
            report=scan(self.c,clip,storage.frame_index(self.c,clip),frames[20].received_ns)
        self.assertEqual(len(report['passages']),1)
        self.assertLessEqual(report['passages'][0]['first_ordinal'],4)
        self.assertGreaterEqual(report['passages'][0]['last_ordinal'],36)
    def test_empty_expected_time_finds_centered_rider_and_caches_both_passages(self):
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        result=locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns'],bib='4'))
        self.assertLessEqual(abs(result['ordinal']-10),2)
        nav=bike_index.navigation(self.c,clip)
        self.assertEqual(nav['source'],'motion');self.assertEqual(len(nav['stops']),2)
        with patch('racevideo.motion_position.scan',side_effect=AssertionError('must use cached preview')):
            later=locate(self.path,self.c,clip,index,dict(target_ns=index[28]['received_ns'],bib='4'))
        self.assertLessEqual(abs(later['ordinal']-35),2);self.assertEqual(later['decoded_frames'],0)
    def test_another_matched_rider_is_deprioritized_when_choosing_a_missing_rider(self):
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        run=storage.create_ocr_run(self.path,clip,{})
        with self.c:
            oid=self.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(run,'499',index[8]['received_ns'],index[13]['received_ns'],6,95,10,'[]',storage.read_frame(self.c,clip,10),'repeated','first')).lastrowid
            self.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
        result=locate(self.path,self.c,clip,index,dict(target_ns=index[15]['received_ns'],bib='4',exclude_keys=['ocr:'+str(oid)]))
        self.assertLessEqual(abs(result['ordinal']-35),2)
    def test_static_video_reports_no_subject_instead_of_claiming_a_rider(self):
        clip=self.f.clip(static=True);index=storage.frame_index(self.c,clip)
        result=locate(self.path,self.c,clip,index,dict(target_ns=index[25]['received_ns']))
        self.assertEqual(result['ordinal'],25);self.assertTrue(result['method'].startswith('no moving subject'))
        self.assertEqual(self.c.execute('SELECT state FROM bike_analyses').fetchone()[0],'inconclusive')
        with patch('racevideo.motion_position.scan',side_effect=AssertionError('static preview must also be cached')):
            again=locate(self.path,self.c,clip,index,dict(target_ns=index[30]['received_ns']))
        self.assertEqual(again['ordinal'],30);self.assertEqual(again['decoded_frames'],0)
    def test_positioning_does_not_reselect_an_ignored_subject(self):
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        first=locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns']))
        later=locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns'],ignore_keys=[first['physical_key']]))
        self.assertLessEqual(abs(later['ordinal']-35),2)
    def test_positioning_keeps_visible_newer_human_evidence_despite_an_old_candidate_ignore(self):
        from racevideo import bib_review
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        first=locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns']))
        reviewed=bib_review.decide(self.path,clip,ordinal=10,number='24',decision='manual')
        again=locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns'],bib='24',
            ignore_keys=[first['physical_key']],protected_keys=['review:'+str(reviewed['id'])]))
        self.assertLessEqual(abs(again['ordinal']-10),2)
    def test_cancellation_does_not_publish_a_partial_complete_index(self):
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        result=locate(self.path,self.c,clip,index,dict(target_ns=index[20]['received_ns']),cancel=lambda:True)
        self.assertEqual(result['method'],'cancelled')
        self.assertFalse(self.c.execute("SELECT 1 FROM bike_analyses WHERE state='complete'").fetchone())
        self.assertEqual(self.c.execute('SELECT state FROM bike_analyses').fetchone()[0],'cancelled')
    def test_late_neural_completion_takes_precedence_over_a_newer_preview_id(self):
        import json
        clip=self.f.clip();index=storage.frame_index(self.c,clip)
        with self.c:neural=self.c.execute("INSERT INTO bike_analyses(clip_id,created_ns,state) VALUES(?,0,'queued')",(clip,)).lastrowid
        locate(self.path,self.c,clip,index,dict(target_ns=index[0]['received_ns']))
        report=json.loads(self.c.execute("SELECT report FROM bike_analyses WHERE state='complete'").fetchone()[0])
        report.update(source='detector',policy='recall-v2')
        bike_index.save(self.c,clip,report,analysis_id=neural)
        self.assertEqual(bike_index.completed_analysis(self.c,clip)['id'],neural)
        self.assertEqual(bike_index.navigation(self.c,clip)['source'],'detector')
    def test_long_clip_searches_near_target_after_the_first_four_seconds(self):
        frames=[]
        for i in range(100):
            image=Image.new('RGB',(320,180),'#aaaaaa')
            if 70<=i<=80:
                x=320-(i-70)*32;ImageDraw.Draw(image).rectangle((x-25,60,x+25,165),fill='#111111')
            buf=io.BytesIO();image.save(buf,'JPEG')
            frames.append(storage.Frame(1_000_000_000+i*200_000_000,i*200_000_000,i,'1/5',buf.getvalue()))
        clip=storage.save_clip(self.c,frames,frames[0].received_ns,'test',320,180,'test');index=storage.frame_index(self.c,clip)
        report=scan(self.c,clip,index,index[75]['received_ns'])
        self.assertTrue(report['partial']);self.assertLessEqual(report['decoded_frames'],96)
        self.assertTrue(any(abs(e['ordinal']-75)<=2 for e in report['passages']))
