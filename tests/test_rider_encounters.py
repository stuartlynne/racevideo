import unittest
from racevideo.rider_encounters import summarize


class RiderEncounterTests(unittest.TestCase):
    def fixture(self):
        rows=[];points=[]
        for i in range(10):
            x=100+i*150
            points.append(dict(ordinal=i,box=[x,400,x+600,900]))
            quad=[[x+180,480],[x+195,480],[x+195,500],[x+180,500]]
            rows.append(dict(ordinal=i,received_ns=10**18+i*33_333_333,monotonic_ns=i*33_333_333,
                readings=[dict(text='5',score=.99,quad=quad,rotation=0,detector_score=.9)]))
        return rows,dict(passages=[dict(key='detected:1',points=points,review_secondary=False)])

    def test_small_fast_label_is_linked_by_bike_motion(self):
        rows,report=self.fixture();encounters=summarize(rows,report)
        self.assertEqual(len(encounters),1)
        self.assertEqual(encounters[0]['physical_track'],'detected:1')
        self.assertEqual(encounters[0]['consensus']['alternatives'][0]['frame_count'],10)
        self.assertEqual(encounters[0]['consensus']['number'],'5')

    def test_rotations_of_one_frame_are_not_repeated_support(self):
        rows,report=self.fixture()
        for row in rows[1:]:row['readings']=[]
        rows[0]['readings']*=8
        self.assertEqual(summarize(rows,report),[])

    def test_stationary_digits_are_not_plate_passages(self):
        rows,report=self.fixture()
        for row in rows:row['readings'][0]['quad']=[[900,480],[915,480],[915,500],[900,500]]
        self.assertEqual(summarize(rows,report),[])

    def test_two_physical_passages_of_same_bib_stay_separate(self):
        rows,report=self.fixture()
        later=[]
        for row in rows:later.append(dict(row,ordinal=row['ordinal']+30,received_ns=row['received_ns']+10**9))
        report['passages'].append(dict(key='detected:2',review_secondary=False,
            points=[dict(p,ordinal=p['ordinal']+30) for p in report['passages'][0]['points']]))
        self.assertEqual(len(summarize(rows+later,report)),2)
