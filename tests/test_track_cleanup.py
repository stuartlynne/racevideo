import unittest
from racevideo.bike_index import build,primary_stops


def frame(i,boxes):
    return dict(ordinal=i,monotonic_ns=i*33_333_333,objects=[
        dict(label='bicycle',score=score,box=box) for score,box in boxes])


class TrackCleanupTests(unittest.TestCase):
    def test_overlapping_weak_parts_do_not_become_additional_primary_riders(self):
        rows=[]
        for i in range(20):
            x=100+i*40
            rows.append(frame(i,[(.9,[x,200,x+400,650]),(.18,[x+150,250,x+350,550]),
                (.22,[20,50,120,180]),(.19,[x+100,300,x+200,500])]))
        report=build(rows,2000,1000)
        self.assertGreater(len(report['passages']),1)
        self.assertEqual(len(primary_stops(report['passages'])),1)
        self.assertEqual(report['policy'],'passage-v3')
        self.assertTrue(any(e['review_secondary'] for e in report['passages']))

    def test_two_close_riders_are_separate_despite_overlapping_boxes(self):
        rows=[frame(i,[(.9,[100+i*30,200,500+i*30,650]),
            (.85,[350+i*30,200,750+i*30,650])]) for i in range(20)]
        self.assertEqual(len(primary_stops(build(rows,2000,1000)['passages'])),2)

    def test_return_after_exit_is_a_new_stop(self):
        rows=[frame(i,[(.9,[100+i*60,200,500+i*60,650])]) for i in range(15)]
        rows += [frame(i,[]) for i in range(15,40)]
        rows += [frame(i,[(.9,[100+(i-40)*60,200,500+(i-40)*60,650])]) for i in range(40,55)]
        self.assertEqual(len(primary_stops(build(rows,2000,1000)['passages'])),2)

    def test_weak_only_interval_still_has_a_visible_unresolved_stop(self):
        rows=[frame(i,[(.2,[100+i*40,200,500+i*40,650]),
            (.18,[150+i*40,250,350+i*40,550])]) for i in range(10)]
        stops=primary_stops(build(rows,2000,1000)['passages'])
        self.assertEqual(len(stops),1)
        self.assertTrue(stops[0]['unresolved_interval'])
