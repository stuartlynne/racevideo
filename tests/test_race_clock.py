import unittest
from racevideo.race_clock import elapsed,display,context


class RaceClockTests(unittest.TestCase):
    def test_elapsed_preserves_hours_milliseconds_and_preroll(self):
        self.assertEqual(elapsed(3_838_600_903_000),'01:03:58.600')
        self.assertEqual(elapsed(-500_000_000),'-00:00:00.500')
        self.assertEqual(elapsed(90_000_000_000_000,False),'25:00:00')
    def test_camera_offset_is_subtracted_once_but_cm_rows_are_already_on_race_clock(self):
        e=dict(start_ns=1_000_000_000_000,end_ns=2_000_000_000_000)
        stamp=e['start_ns']+65_500_000_000
        self.assertEqual(display(stamp,e,1.5,camera=True),'Race 00:01:04.000')
        self.assertEqual(display(stamp,e,1.5,camera=False),'Race 00:01:05.500')
        self.assertTrue(display(stamp).startswith('Clock '))
    def test_ambiguous_cached_events_do_not_invent_a_race_context(self):
        a=dict(id=1,start_ns=100_000_000_000,end_ns=200_000_000_000)
        b=dict(a,id=2)
        self.assertEqual(context(150_000_000_000,[a,b]),(None,0))
        self.assertEqual(context(150_000_000_000,[a,b],b,1),(b,1))
        self.assertEqual(context(900_000_000_000,[a,b],a),(None,0))

    def test_compact_operator_clock_omits_unused_hours_and_padding(self):
        self.assertEqual(elapsed(454_000_000_000,False,True),'7:34')
        self.assertEqual(elapsed(4_054_999_000_000,False,True),'1:07:34')
        self.assertEqual(elapsed(5_000_000_000,False,True),'0:05')
        self.assertEqual(elapsed(-5_000_000_000,False,True),'-0:05')
        self.assertEqual(display(454_000_000_000,dict(start_ns=0),milliseconds=False,prefix=False,compact=True),'7:34')
