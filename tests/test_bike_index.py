import unittest
from racevideo.bike_index import build,primary_stops


def frame(ordinal,xs):
    return dict(ordinal=ordinal,monotonic_ns=ordinal*33_333_333,objects=[dict(label='bicycle',score=.95,box=[x,400,x+250,800]) for x in xs])


class BikeIndexTests(unittest.TestCase):
    def test_navigation_prefers_sustained_tracks_without_deleting_weak_candidates(self):
        def track(key,start,end,weak=False):
            return dict(key=key,first_ordinal=start,last_ordinal=end,ordinal=(start+end)//2,
                uncertain=weak,points=[dict(ordinal=i) for i in range(start,end+1)])
        entries=[track('first',4,32),track('first-fragment',26,32,True),track('second',63,85)]
        self.assertEqual([e['key'] for e in primary_stops(entries)],['first','second'])
        self.assertEqual(len(entries),3)
        # Two independently sustained bikes can overlap in the same interval.
        self.assertEqual(len(primary_stops([track('a',0,20),track('b',5,25)])),2)

    def test_two_overlapping_passages_keep_separate_tracks(self):
        report=build([frame(i,[1400-i*90,1700-i*90]) for i in range(12)],2000,1000)
        self.assertEqual(len(report['passages']),2)
        self.assertNotEqual(report['passages'][0]['ordinal'],report['passages'][1]['ordinal'])
    def test_return_after_exit_is_another_passing(self):
        frames=[frame(i,[1400-i*120]) for i in range(10)]
        frames += [frame(i,[]) for i in range(10,25)]
        frames += [frame(i,[1400-(i-25)*120]) for i in range(25,35)]
        report=build(frames,2000,1000);self.assertEqual(len(report['passages']),2)
        self.assertGreater(report['passages'][1]['first_ordinal'],report['passages'][0]['last_ordinal'])
    def test_stationary_bicycle_is_retained_as_uncertain_for_human_review(self):
        passages=build([frame(i,[1000]) for i in range(20)],2000,1000)['passages']
        self.assertEqual(len(passages),1);self.assertTrue(passages[0]['uncertain'])
    def test_bouncing_false_detection_is_flagged_instead_of_silently_dropped(self):
        passages=build([frame(i,[1000+(i%3)*35]) for i in range(10)],2000,1000)['passages']
        self.assertEqual(len(passages),1);self.assertTrue(passages[0]['uncertain'])
    def test_low_confidence_one_frame_partial_bike_is_reviewable(self):
        row=frame(0,[100]);row['objects'][0]['score']=.18
        passages=build([row],2000,1000)['passages']
        self.assertEqual(len(passages),1);self.assertTrue(passages[0]['uncertain'])
