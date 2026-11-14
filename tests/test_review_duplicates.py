import unittest,copy
from racevideo.review_duplicates import group


def row(key,bib='1',at=100,column=9,lap=None,confirmed=False,origin='CrossMgr',captures=None):
    captures=captures or []
    return dict(cell_key=key,bib=bib,at_ns=round(at*1e9),column=column,rider_lap=lap,confirmed=confirmed,
        origin=origin,captures=captures,visual_count=sum(bool(c.get('number')) for c in captures))


class DuplicateReviewTests(unittest.TestCase):
    def anchor(self):
        return row('confirmed',lap=9,confirmed=True,captures=[dict(clip_id=869,key='review:32',number='1',physical_key='bike:12:motion:1')])
    def test_extra_unassigned_cm_read_near_confirmed_lap_is_grouped_reversibly(self):
        anchor=self.anchor();extra=row('extra',at=128.6)
        visible,grouped=group([anchor,extra])
        self.assertEqual(visible,[anchor]);self.assertEqual(grouped,[extra])
        self.assertIs(anchor['grouped_candidates'][0],extra)
        self.assertEqual(extra['grouped_under'],'confirmed');self.assertAlmostEqual(extra['group_delta_seconds'],28.6)
        self.assertFalse(extra['confirmed'])
    def test_genuine_laps_separate_observations_other_bibs_and_distant_reads_remain(self):
        for extra in (row('lap',at=110,lap=10),row('other-column',at=110,column=10),row('other-bib',bib='15',at=110),
                      row('far',at=131),row('human',at=110,confirmed=True),row('video',at=110,captures=[dict(clip_id=870)])):
            with self.subTest(key=extra['cell_key']):
                visible,grouped=group([self.anchor(),extra]);self.assertEqual(len(visible),2);self.assertEqual(grouped,[])
    def test_without_confirmation_and_for_pre_race_reads_nothing_is_grouped(self):
        anchor=self.anchor();anchor['confirmed']=False
        self.assertEqual(group([anchor,row('extra',at=110)])[1],[])
        anchor=self.anchor();anchor['rider_lap']=None
        self.assertEqual(group([anchor,row('extra',at=110)])[1],[])
    def test_unconfirmed_same_subject_ocr_can_group_but_different_bike_must_remain(self):
        same=row('ocr',at=101,origin='Visual only',captures=[dict(clip_id=869,key='ocr:3',number='1',physical_key='bike:12:motion:1')])
        self.assertEqual(len(group([self.anchor(),same])[1]),1)
        other=copy.deepcopy(same);other['captures'][0]['physical_key']='bike:12:motion:2'
        self.assertEqual(group([self.anchor(),other])[1],[])
    def test_zero_window_exposes_all_rows(self):
        cells=[self.anchor(),row('extra',at=110)]
        self.assertEqual(group(cells,0),(cells,[]))
