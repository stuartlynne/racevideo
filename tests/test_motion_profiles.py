import io
import unittest
from unittest.mock import patch
from PIL import Image,ImageDraw
from racevideo.motion_profiles import MotionBank,validate_profile


def picture(x=None):
    im=Image.new('L',(640,360),60)
    if x is not None:ImageDraw.Draw(im).rectangle((x,170,x+35,290),fill=220)
    out=io.BytesIO();im.save(out,'JPEG');return out.getvalue()


class MotionProfileTests(unittest.TestCase):
    def detector(self,mode):return MotionBank(profile={'mode':mode})
    def test_single_and_any_zones_have_different_trigger_areas(self):
        for mode,expected in (('single',False),('zones',True),('road',True)):
            detector=self.detector(mode);detector.analyze(picture())
            self.assertEqual(detector.analyze(picture(520))[0],expected)
    def test_road_fills_gaps_between_strips_and_entry_hold_does_not_start_there(self):
        for mode,active,expected in (('zones',False,False),('road',False,True),('entry_hold',False,False),('entry_hold',True,True)):
            detector=self.detector(mode);detector.analyze(picture())
            self.assertEqual(detector.analyze(picture(385),event_active=active)[0],expected)
    def test_many_zones_share_one_decode_and_reset_does_not_trigger(self):
        detector=self.detector('entry_hold')
        with patch('racevideo.motion_profiles.Image.open',wraps=Image.open) as opened:
            detector.analyze(picture(520));self.assertEqual(opened.call_count,1)
        self.assertEqual(len(detector.zone_states),4)
        detector.reset(detector.roi,{'mode':'road'})
        self.assertFalse(detector.analyze(picture(520))[0])
    def test_invalid_mode_and_zone_rejected(self):
        with self.assertRaises(ValueError):validate_profile({'mode':'wrong'})
        with self.assertRaises(ValueError):validate_profile({'zones':{'road':[-1,0,1,1]}})
