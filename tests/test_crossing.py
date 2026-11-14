import unittest
from racevideo.crossing import first_crossing


def sample(ordinal,gap,received=None):
    return dict(ordinal=ordinal,gap_px=gap,monotonic_ns=ordinal*30_000_000,
                received_ns=received if received is not None else 1_800_000_000_000_000_000+ordinal*30_000_000,
                source_pts=ordinal*30000,time_base='1/1000000')


class CrossingTests(unittest.TestCase):
    def test_front_edge_bracket_and_subframe_time_keep_integer_timestamp_precision(self):
        result=first_crossing([sample(10,100),sample(11,-50)])
        self.assertEqual(result['before_ordinal'],10);self.assertEqual(result['first_observed_after_ordinal'],11)
        self.assertEqual(result['estimated_received_ns'],1_800_000_000_320_000_000)
        self.assertEqual(result['after_source_pts'],330000)
    def test_exact_touch_is_first_observed_frame(self):
        r=first_crossing([sample(1,20),sample(2,0),sample(3,0),sample(4,-10)])
        self.assertEqual(r['first_observed_after_ordinal'],2)
        self.assertEqual(r['estimated_received_ns'],sample(2,0)['received_ns'])
    def test_occlusion_retains_bracket_without_false_subframe_precision(self):
        r=first_crossing([sample(1,20),sample(4,-20)])
        self.assertEqual(r['status'],'missing_frames');self.assertIsNone(r['estimated_received_ns'])
        self.assertEqual(r['bracket_monotonic_ns'],90_000_000)
    def test_camera_clock_jump_does_not_generate_interpolated_wall_time(self):
        r=first_crossing([sample(1,20),sample(2,-20,received=sample(2,0)['received_ns']+1_000_000_000)])
        self.assertEqual(r['status'],'clock_discontinuity');self.assertIsNone(r['estimated_received_ns'])
    def test_already_crossed_stationary_or_reversed_order(self):
        self.assertIsNone(first_crossing([sample(1,-10),sample(2,-20)]))
        self.assertIsNone(first_crossing([sample(1,20),sample(2,20)]))
        with self.assertRaises(ValueError):first_crossing([sample(2,20),sample(1,-20)])


if __name__=='__main__':unittest.main()
