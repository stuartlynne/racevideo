import unittest
from racevideo.encounters import summarize


def frame(ordinal, numbers=('480',), x=None):
    x = 20 + ordinal * 100 if x is None else x
    quad = [[x, 20], [x + 50, 20], [x + 50, 45], [x, 45]]
    return dict(clip=123, method='riders960', ordinal=ordinal,
                received_ns=1_000_000_000 + ordinal * 33_333_333,
                monotonic_ns=ordinal * 33_333_333,
                readings=[dict(quad=quad, text=n, score=.95,
                               detector_score=.9, rotation=i * 180)
                          for i, n in enumerate(numbers)])


class FieldCandidateTests(unittest.TestCase):
    def test_short_numbers_survive_consensus_and_reappear_as_new_encounters(self):
        for number in ('7','24','024'):
            rows=[frame(i,(number,)) for i in range(4)]
            rows += [frame(i,(number,),x=20+(i-10)*100) for i in range(10,14)]
            encounters=summarize(rows)
            self.assertEqual([e['consensus']['number'] for e in encounters],[number,number])
    def test_repeated_competing_orientation_is_never_silently_accepted(self):
        frames = [frame(i, ('480', '087') if i < 2 else ('480',)) for i in range(5)]
        encounters = summarize(frames)
        self.assertEqual(len(encounters), 1)
        vote = encounters[0]['consensus']
        self.assertEqual(vote['status'], 'ambiguous')
        self.assertIsNone(vote['number'])
        self.assertEqual([(a['number'], a['frame_count']) for a in vote['alternatives']],
                         [('480', 5), ('087', 2)])

    def test_repeated_stationary_print_is_not_a_passing(self):
        self.assertEqual(summarize([frame(i, x=100) for i in range(10)]), [])

    def test_two_source_frames_are_insufficient(self):
        self.assertEqual(summarize([frame(0), frame(1)]), [])

    def test_returning_number_is_a_separate_encounter(self):
        rows = [frame(i) for i in range(4)]
        rows += [frame(i, x=20 + (i - 10) * 100) for i in range(10, 14)]
        encounters = summarize(rows)
        self.assertEqual(len(encounters), 2)
        self.assertEqual([e['first_ordinal'] for e in encounters], [0, 10])
        self.assertEqual([e['consensus']['number'] for e in encounters], ['480', '480'])

    def test_nearby_riders_are_associated_by_geometry(self):
        rows = []
        for i in range(4):
            a = frame(i, ('123',), x=20 + i * 80)
            b = frame(i, ('456',), x=250 + i * 80)
            a['readings'].extend(b['readings'])
            rows.append(a)
        encounters = summarize(rows)
        self.assertEqual(len(encounters), 2)
        self.assertEqual({e['consensus']['number'] for e in encounters}, {'123', '456'})

    def test_short_ocr_gap_can_be_bridged_while_still_in_view(self):
        rows = [frame(i, () if i in (3, 4, 5) else ('480',), x=20 + i * 60)
                for i in range(9)]
        encounters = summarize(rows, maximum_gap=8, image_size=(1000, 300))
        self.assertEqual(len(encounters), 1)
        self.assertEqual(encounters[0]['frames'], 6)

    def test_predicted_full_exit_closes_track_before_a_return(self):
        rows = [frame(i) for i in range(4)]
        rows += [frame(i, ()) for i in (4, 5)]
        rows += [frame(i, x=20 + (i - 6) * 100) for i in range(6, 10)]
        encounters = summarize(rows, maximum_gap=8, image_size=(400, 300))
        self.assertEqual(len(encounters), 2)
        self.assertEqual([e['first_ordinal'] for e in encounters], [0, 6])
