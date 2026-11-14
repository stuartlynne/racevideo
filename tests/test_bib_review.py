import io
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from racevideo import storage,bib_review


class BibReviewTests(unittest.TestCase):
    def test_two_bikes_same_frame_have_separate_boxes_order_and_audit(self):
        a=bib_review.decide(self.path,self.clip,decision='manual',number='4',ordinal=1,bike_box=[.1,.2,.4,.8],passing_order=1)
        b=bib_review.decide(self.path,self.clip,decision='manual',number='1',ordinal=1,bike_box=[.5,.2,.9,.8],passing_order=2)
        rows=bib_review.list_rows(self.c,self.clip)
        self.assertEqual([(r['number'],r['passing_order']) for r in rows],[('4',1),('1',2)])
        self.assertNotEqual(rows[0]['quad'],rows[1]['quad'])
        self.assertEqual(rows[0]['ordinal'],rows[1]['ordinal'])
        self.assertEqual(json.loads(a['provenance'])['bike_box'],[.1,.2,.4,.8])
        with self.assertRaisesRegex(ValueError,'already assigned'):
            bib_review.decide(self.path,self.clip,decision='manual',number='589',ordinal=2,passing_order=1)
        self.assertEqual(len(bib_review.list_rows(self.c,self.clip)),2)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM bib_review_history').fetchone()[0],2)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'review.sqlite3'
        self.c=storage.connect(self.path);storage.initialize(self.c)
        out=io.BytesIO();Image.new('RGB',(100,80),'white').save(out,'JPEG');self.jpeg=out.getvalue()
        self.ns=1_800_000_000_000_000_000
        frames=[storage.Frame(self.ns+i*30_000_000,self.ns+i*30_000_000,i,'1/30',self.jpeg) for i in range(5)]
        self.clip=storage.save_clip(self.c,frames,self.ns,'test',100,80,'fixture')
    def tearDown(self):self.c.close();self.temp.cleanup()
    def scan(self,number,encounter='pass1'):
        run=storage.create_ocr_run(self.path,self.clip,{})
        with self.c:
            oid=self.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                               (run,number,self.ns,self.ns+60_000_000,3,95,1,'[]',self.jpeg,'ambiguous',encounter)).lastrowid
            self.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
        return run,oid
    def matches(self):return [r[0] for r in self.c.execute('SELECT tag_id FROM reviewed_video_tag_matches ORDER BY tag_id')]
    def test_accept_reject_correct_preserve_machine_evidence_and_update_filters(self):
        run,oid=self.scan('755');self.assertEqual(self.matches(),['755'])
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='corrected',number='155')
        self.assertEqual(self.matches(),['155']);self.assertEqual(self.c.execute('SELECT number FROM ocr_observations WHERE id=?',(oid,)).fetchone()[0],'755')
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,bibs=('155',))],[self.clip])
        self.assertEqual(storage.browse_clips(self.c,bibs=('755',)),[])
        self.assertEqual(storage.bib_passages(self.c)[0]['number'],'155')
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='rejected')
        self.assertEqual(self.matches(),[])
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='accepted')
        self.assertEqual(self.matches(),['755'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_review_history').fetchone()[0],3)
    def test_manual_bib_without_any_ocr_uses_original_frame_and_can_be_removed(self):
        row=bib_review.decide(self.path,self.clip,decision='manual',number='042',ordinal=3,note='partly obscured')
        self.assertEqual(row['received_ns'],self.ns+90_000_000)
        self.assertEqual(self.matches(),['042']);self.assertEqual(bib_review.list_rows(self.c,self.clip)[0]['number'],'042')
        with self.assertRaises(ValueError):bib_review.decide(self.path,self.clip,decision='manual',number='042',ordinal=3)
        bib_review.decide(self.path,self.clip,review_id=row['id'],decision='reset')
        self.assertEqual(self.matches(),[]);self.assertEqual(self.c.execute('SELECT count(*) FROM bib_review_history').fetchone()[0],2)
    def test_decisions_survive_new_ocr_runs_and_even_source_observation_removal(self):
        run,oid=self.scan('755')
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='corrected',number='155')
        self.scan('333','newpass');self.assertEqual(self.matches(),['155','333'])
        rows=bib_review.list_rows(self.c,self.clip);self.assertTrue(next(r for r in rows if r['number']=='155')['historical'])
        with self.c:self.c.execute('DELETE FROM ocr_observations WHERE id=?',(oid,))
        self.assertEqual(self.matches(),['155','333'])
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_removed_review_ids_are_not_reused_in_retained_history(self):
        first=bib_review.decide(self.path,self.clip,decision='manual',number='042',ordinal=0)
        bib_review.decide(self.path,self.clip,review_id=first['id'],decision='reset')
        second=bib_review.decide(self.path,self.clip,decision='manual',number='123',ordinal=1)
        self.assertGreater(second['id'],first['id'])
        history=self.c.execute('SELECT review_id,action FROM bib_review_history ORDER BY id').fetchall()
        self.assertEqual([tuple(r) for r in history],[(first['id'],'manual'),(first['id'],'reset'),(second['id'],'manual')])
    def test_one_two_and_three_digit_bibs_keep_exact_strings(self):
        for number,ordinal in (('7',0),('24',1),('024',2)):
            bib_review.decide(self.path,self.clip,decision='manual',number=number,ordinal=ordinal)
        self.assertEqual(self.matches(),['024','24','7'])
        self.assertEqual(storage.bib_numbers('7, 24, 024'),('7','24','024'))
        self.assertEqual([r['id'] for r in storage.browse_clips(self.c,bibs=('24',))],[self.clip])
    def test_v10_constraint_migration_preserves_reviews_audit_and_original_frames(self):
        _,oid=self.scan('755');original=bib_review.decide(self.path,self.clip,observation_id=oid,decision='corrected',number='155')
        history=[tuple(r) for r in self.c.execute('SELECT * FROM bib_review_history')]
        drops=['DROP TRIGGER '+r[0]+';' for r in self.c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'reviewed_%'")]
        old=bib_review.REVIEW_TABLE.replace('IF NOT EXISTS bib_reviews','bib_reviews_v10').replace('length(number) BETWEEN 1 AND 3','length(number)=3')
        self.c.executescript('BEGIN;'+''.join(drops)+old+'INSERT INTO bib_reviews_v10 SELECT * FROM bib_reviews;DROP TABLE bib_reviews;ALTER TABLE bib_reviews_v10 RENAME TO bib_reviews;PRAGMA user_version=10;COMMIT;')
        with self.assertRaises(Exception):self.c.execute("UPDATE bib_reviews SET number='24'")
        self.c.rollback();storage.initialize(self.c)
        self.assertEqual(dict(self.c.execute('SELECT * FROM bib_reviews').fetchone()),original)
        self.assertEqual([tuple(r) for r in self.c.execute('SELECT * FROM bib_review_history')],history)
        bib_review.decide(self.path,self.clip,decision='manual',number='24',ordinal=3)
        self.assertEqual(self.matches(),['155','24'])
        self.assertEqual(storage.read_frame(self.c,self.clip,0),self.jpeg)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_invalid_bib_frame_and_wrong_clip_do_not_write(self):
        _,oid=self.scan('123')
        for number in ['','1234','12x','123 OR 1=1']:
            with self.assertRaises(ValueError):bib_review.decide(self.path,self.clip,decision='manual',number=number,ordinal=1)
        with self.assertRaises(ValueError):bib_review.decide(self.path,self.clip,decision='manual',number='042',ordinal=99)
        with self.assertRaises(ValueError):bib_review.decide(self.path,self.clip+1,observation_id=oid,decision='rejected')
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0],0)
    def test_two_confirmed_bibs_in_one_merged_encounter_and_duplicate_number_not_double_counted(self):
        run,a=self.scan('838')
        with self.c:
            b=self.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key) SELECT run_id,'826',first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key FROM ocr_observations WHERE id=?''',(a,)).lastrowid
        bib_review.decide(self.path,self.clip,observation_id=a,decision='accepted')
        bib_review.decide(self.path,self.clip,observation_id=b,decision='accepted')
        self.assertEqual(self.matches(),['826','838'])
        bib_review.decide(self.path,self.clip,observation_id=a,decision='corrected',number='826')
        self.assertEqual(len(storage.bib_passages(self.c)),1)
        self.assertEqual(self.c.execute('SELECT encounter_count FROM reviewed_video_tag_matches').fetchone()[0],1)
    def test_clear_restores_candidate_and_cleanup_removes_reviews_with_history(self):
        run,oid=self.scan('123');bib_review.decide(self.path,self.clip,observation_id=oid,decision='rejected')
        bib_review.decide(self.path,self.clip,observation_id=oid,decision='reset');self.assertEqual(self.matches(),['123'])
        bib_review.decide(self.path,self.clip,decision='manual',number='042',ordinal=0)
        with self.c:
            self.c.execute('DELETE FROM ocr_observations');self.c.execute('DELETE FROM ocr_runs');self.c.execute('DELETE FROM clips')
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_review_history').fetchone()[0],0)
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':unittest.main()
