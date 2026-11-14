import io
from pathlib import Path
import tempfile
import unittest
from PIL import Image,ImageDraw
from racevideo import storage,review_position


class ReviewPositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'video.sqlite3'
        self.c=storage.connect(self.path);storage.initialize(self.c)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def clip(self,direction=-1,static=False):
        frames=[]
        for i in range(50):
            image=Image.new('RGB',(320,180),'#aaaaaa');draw=ImageDraw.Draw(image)
            # Fixed high-contrast scenery is not a moving subject.
            draw.rectangle((285,25,302,150),fill='white')
            if not static and 3<=i<=20:
                x=320-(i-3)*22 if direction<0 else (i-3)*22
                draw.rectangle((x-23,65,x+23,155),fill='#202020')
            # A larger later rider must not replace the first passage.
            if not static and 30<=i<=40:
                x=320-(i-30)*32
                draw.rectangle((x-45,50,x+45,165),fill='#111111')
            buf=io.BytesIO();image.save(buf,'JPEG')
            frames.append(storage.Frame(1_000_000_000+i*33_333_333,i*33_333_333,i,'1/30',buf.getvalue()))
        return storage.save_clip(self.c,frames,frames[10].received_ns,'motion',320,180,'test')
    def test_first_rider_opens_near_middle_in_both_directions_not_later_larger_rider(self):
        for direction in (-1,1):
            clip=self.clip(direction)
            result=review_position.choose(self.c,clip,storage.frame_index(self.c,clip))
            self.assertEqual(result['method'],'first moving subject')
            self.assertLessEqual(abs(result['ordinal']-10),2)
            self.assertLessEqual(result['decoded_frames'],18)
    def test_static_scene_falls_back_to_trigger_not_empty_tail(self):
        clip=self.clip(static=True)
        result=review_position.choose(self.c,clip,storage.frame_index(self.c,clip))
        self.assertEqual(result['ordinal'],10);self.assertEqual(result['method'],'trigger fallback')
    def test_empty_and_cancelled_selections_are_bounded(self):
        self.assertEqual(review_position.choose(self.c,1,[])['ordinal'],0)
        clip=self.clip();result=review_position.choose(self.c,clip,storage.frame_index(self.c,clip),cancel=lambda:True)
        self.assertEqual(result['method'],'cancelled');self.assertLessEqual(result['decoded_frames'],1)


if __name__=='__main__':unittest.main()
