import importlib.util
import io
import tempfile
from pathlib import Path
import unittest

from PIL import Image,ImageDraw,ImageFont
from racevideo import storage

AVAILABLE=bool(importlib.util.find_spec('cv2') and importlib.util.find_spec('tesserocr'))


@unittest.skipUnless(AVAILABLE,'Optional OCR dependencies not installed')
class OCRTests(unittest.TestCase):
    def test_one_vote_per_frame_and_separate_encounters(self):
        from racevideo.ocr import Tracks
        tracker=Tracks()
        def hit(frame,ns,number='007'):
            return dict(number=number,confidence=90,ordinal=frame,received_ns=ns,
                        monotonic_ns=ns,quad=[[100,100],[160,100],[160,130],[100,130]])
        tracker.update([hit(0,0)],640,480)
        tracker.update([hit(0,0)],640,480)
        self.assertEqual(tracker.observations()[0]['frame_count'],1)
        self.assertEqual(tracker.observations()[0]['status'],'candidate')
        tracker.update([hit(1,200_000_000)],640,480)
        self.assertEqual(tracker.observations()[0]['number'],'007')
        self.assertEqual(tracker.observations()[0]['status'],'repeated')
        tracker.update([hit(20,3_000_000_000)],640,480)
        self.assertEqual(len(tracker.observations()),2)

    def test_competing_numbers_need_review(self):
        from racevideo.ocr import Tracks
        tracker=Tracks()
        for i,number in enumerate(('235','233','235','233')):
            tracker.update([dict(number=number,confidence=90,ordinal=i,received_ns=i*200_000_000,
                                 monotonic_ns=i*200_000_000,quad=[[10,10],[60,10],[60,40],[10,40]])],640,480)
        self.assertEqual(tracker.observations()[0]['status'],'candidate')

    def test_competing_rotation_reads_are_retained_without_extra_frame_votes(self):
        from racevideo.ocr import Tracks
        tracker=Tracks()
        for frame in range(3):
            def reading(number,score):
                return dict(number=number,confidence=score,ordinal=frame,received_ns=frame*200_000_000,
                            monotonic_ns=frame*200_000_000,quad=[[100,100],[160,100],[160,130],[100,130]])
            high=reading('697',95);correct=reading('469',90)
            primary=dict(high,alternatives=[high,correct,reading('469',85)])
            tracker.update([primary],640,480)
        observations={r['number']:r for r in tracker.observations()}
        self.assertEqual(set(observations),{'469','697'})
        self.assertEqual(observations['469']['frame_count'],3)
        self.assertEqual(observations['697']['frame_count'],3)
        self.assertEqual(observations['469']['status'],'candidate')
        self.assertEqual(observations['697']['status'],'candidate')

    def test_upright_only_setting_recognizes_469_without_inverted_attempts(self):
        import numpy as np
        from racevideo.ocr import Recognizer,Proposal
        image=Image.new('RGB',(240,100),'white')
        ImageDraw.Draw(image).text((5,2),'469',fill='black',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',78))
        pixels=np.array(image)[:,:,::-1].copy()
        proposal=Proposal(np.array([[0,0],[239,0],[239,99],[0,99]],np.float32),1,'fixture')
        recognizer=Recognizer(rotations=[0])
        try:
            hits=recognizer.read(pixels,proposal)
            self.assertTrue(any(h['number']=='469' for h in hits),hits)
            self.assertTrue(all(h['rotation']==0 for h in hits),hits)
        finally:recognizer.close()
        default=Recognizer()
        try:self.assertEqual(default.rotations,[0,180])
        finally:default.close()

    def test_tight_roi_retains_large_source_plate_detection(self):
        import numpy as np
        from racevideo.ocr import propose,Recognizer,bounds
        image=Image.new('RGB',(3840,2160),'#303b40')
        draw=ImageDraw.Draw(image)
        draw.rectangle((1650,950,2190,1190),fill='white')
        draw.text((1680,960),'235',fill='black',font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',170))
        pixels=np.array(image)[:,:,::-1].copy()
        recognizer=Recognizer()
        try:
            for roi in ((0,0,1,1),(.35,.35,.65,.65)):
                proposals=propose(pixels,roi,20)
                hits=[hit for proposal in proposals for hit in recognizer.read(pixels,proposal)]
                self.assertTrue(any(h['number']=='235' and h['confidence']>=60 for h in hits),(roi,hits))
        finally:recognizer.close()

    def test_real_detector_recognizer_and_sqlite_job(self):
        from racevideo.ocr import run_job
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fixture.sqlite3'
            c=storage.connect(path);storage.initialize(c)
            frames=[]
            for i in range(6):
                image=Image.new('RGB',(640,480),'#303b40')
                plate=Image.new('RGB',(90,42),'white')
                ImageDraw.Draw(plate).text((5,2),'235',fill='black',font=ImageFont.truetype(
                    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',30))
                image.paste(plate,(200+i*2,150))
                out=io.BytesIO();image.save(out,'JPEG',quality=95)
                frames.append(storage.Frame(100_000_000_000+i*200_000_000,i*200_000_000,i,'1/5',out.getvalue()))
            clip_id=storage.save_clip(c,frames,100_000_000_000,'motion',640,480,'fixture')
            c.close()
            run_id=storage.create_ocr_run(path,clip_id,dict(roi=[0,0,1,1],fps=8))
            result=run_job(path,run_id)
            self.assertEqual(result['state'],'complete')
            matches=[r for r in result['observations'] if r['number']=='235']
            self.assertTrue(matches,result)
            self.assertTrue(any(r['status']=='repeated' for r in matches),matches)
            c=storage.connect(path,readonly=True)
            evidence=c.execute('SELECT evidence FROM ocr_observations WHERE run_id=?',(run_id,)).fetchone()[0]
            Image.open(io.BytesIO(evidence)).verify()
            self.assertEqual(storage.read_frame(c,clip_id,0),frames[0].jpeg)
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            c.close()


if __name__=='__main__':unittest.main()
