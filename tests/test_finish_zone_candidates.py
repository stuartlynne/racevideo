import unittest
from racevideo.bike_evidence import crosses_finish_zone


class FinishZoneTests(unittest.TestCase):
    def test_track_center_can_enter_zone_without_its_representative_box_being_inside(self):
        entry=dict(points=[dict(box=[0,20,20,60]),dict(box=[40,20,60,60]),dict(box=[80,20,100,60])])
        self.assertIs(crosses_finish_zone(entry,[.4,.2,.6,.8],100,100),True)
        self.assertIs(crosses_finish_zone(dict(points=entry['points'][:1]),[.4,.2,.6,.8],100,100),False)
    def test_missing_invalid_or_unmeasured_geometry_has_no_preference(self):
        for roi in (None,[],[0,0,0,1],[0,0,float('nan'),1],['bad',0,1,1]):
            with self.subTest(roi=roi):self.assertIsNone(crosses_finish_zone(dict(points=[]),roi,100,100))
        self.assertIsNone(crosses_finish_zone(dict(points=[]),[0,0,1,1],100,100))
