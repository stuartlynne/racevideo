import io
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from racevideo import storage,retention


def rows(count=30):return [dict(ordinal=i,monotonic_ns=i*100_000_000,received_ns=1_800_000_000_000_000_000+i*100_000_000,objects=[]) for i in range(count)]


class RetentionTests(unittest.TestCase):
    def test_no_detections_keeps_everything_inconclusive(self):
        p=retention.propose(rows(),[False]*30,{'mode':'motion'})
        self.assertEqual(p['state'],'inconclusive');self.assertEqual(p['intervals'],[dict(first_ordinal=0,last_ordinal=29)])
    def test_short_detection_gap_bridged_long_gap_split_with_time_margin(self):
        flags=[i in (5,6,9,20,21) for i in range(30)]
        p=retention.propose(rows(),flags,{'mode':'motion'})
        self.assertEqual([(r['first_ordinal'],r['last_ordinal']) for r in p['intervals']],[(4,10),(19,22)])
    def test_bike_presence_does_not_require_any_ocr_number(self):
        frames=rows()
        for row in frames[8:16]:row['objects']=[dict(label='bicycle',score=.9,box=[20,40,80,90])]
        p=retention.from_objects(frames,{'mode':'bicycle'},(100,100))
        self.assertEqual(p['state'],'proposal');self.assertEqual(p['presence_frames'],8)
    def test_saved_proposal_only_adds_metadata_and_retains_source_timestamps_and_jpegs(self):
        with tempfile.TemporaryDirectory() as folder:
            c=storage.connect(Path(folder)/'test.sqlite3');storage.initialize(c)
            out=io.BytesIO();Image.new('RGB',(100,100),'white').save(out,'JPEG');jpeg=out.getvalue()
            source=rows();frames=[storage.Frame(r['received_ns'],r['monotonic_ns'],r['ordinal'],'1/10',jpeg) for r in source]
            clip=storage.save_clip(c,frames,frames[4].received_ns,'test',100,100,'fixture')
            before=[tuple(r) for r in c.execute('SELECT * FROM frames')]
            report=retention.propose(source,[5<=i<=12 for i in range(30)],{'mode':'motion'});retention.save(c,clip,report)
            saved=retention.latest(c,clip)['report'];self.assertLess(saved['kept_bytes'],saved['total_bytes'])
            self.assertEqual(before,[tuple(r) for r in c.execute('SELECT * FROM frames')]);c.close()
    def test_queued_trim_or_bike_analysis_protects_source_from_date_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            c=storage.connect(Path(folder)/'test.sqlite3');storage.initialize(c)
            out=io.BytesIO();Image.new('RGB',(10,10),'white').save(out,'JPEG')
            ns=1_800_000_000_000_000_000
            clip=storage.save_clip(c,[storage.Frame(ns,0,0,'1/30',out.getvalue())],ns,'test',10,10,'fixture')
            from datetime import datetime
            day=datetime.fromtimestamp(ns/1e9).date().isoformat()
            with c:c.execute("INSERT INTO retention_proposals(clip_id,created_ns,state,parameters) VALUES(?,?,'queued','{}')",(clip,ns))
            preview=storage.cleanup_preview(c,day);self.assertEqual(preview['busy'],1);self.assertEqual(preview['ids'],[])
            with c:
                c.execute("UPDATE retention_proposals SET state='proposal'")
                c.execute("INSERT INTO bike_analyses(clip_id,created_ns,state) VALUES(?,?,'running')",(clip,ns))
            self.assertEqual(storage.cleanup_preview(c,day)['busy'],1)
            with c:
                c.execute("UPDATE bike_analyses SET state='complete'")
                c.execute("INSERT INTO wheel_analyses(clip_id,subject_key,created_ns,updated_ns,state,parameters) VALUES(?,'test',?,?,'running','{}')",(clip,ns,ns))
            self.assertEqual(storage.cleanup_preview(c,day)['busy'],1);c.close()
