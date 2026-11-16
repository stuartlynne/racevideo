import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from racevideo.idle_passings import IdlePassings


class IdlePassingsTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.app=NS(mode='replay',selected=1,displayed_ordinal=0,camera_panel=None,
            playing=False,pending_review=None,editing_text=lambda:False,
            root=NS(grab_current=lambda:None),bike_mark=None,ocr_selecting=False,roi_drag=None)
        self.follow=IdlePassings(self.app,lambda:self.now)
        def cell(clip):return dict(cell_key=str(clip),bib='24',state='missing',at_ns=clip,captures=[dict(clip_id=clip)])
        self.cells=[cell(i) for i in range(1,4)]
        self.panel=NS(event_id=7,busy=False,review_pending=False,add_target=None,
            selected_cell=self.cells[0],displayed_cells=lambda:self.cells,
            reveal_selection=Mock(),review_note=NS(get=lambda:''),review_number=NS(get=lambda:'24'))
        def select(cell):
            self.panel.selected_cell=cell;self.app.selected=cell['captures'][0]['clip_id']
            self.follow.arm(7,self.app.selected)
        self.panel.select_cell=Mock(side_effect=select)
        self.follow.arm(7,1);self.follow.tick(self.panel)

    def test_waits_then_selects_newest_and_continues_without_repeating(self):
        self.now=14.9;self.follow.tick(self.panel);self.panel.select_cell.assert_not_called()
        self.now=15;self.follow.tick(self.panel);self.assertEqual(self.app.selected,3)
        self.follow.tick(self.panel)
        self.cells.append(dict(self.cells[-1],at_ns=4,cell_key='4',captures=[dict(clip_id=4)]))
        self.now=29;self.follow.tick(self.panel);self.assertEqual(self.app.selected,3)
        self.now=30;self.follow.tick(self.panel);self.assertEqual(self.app.selected,4)
        self.now=60;self.follow.tick(self.panel);self.assertEqual(self.panel.select_cell.call_count,2)

    def test_input_restarts_idle_period_and_loading_waits_for_display(self):
        self.now=14;self.follow.activity();self.now=15;self.follow.tick(self.panel)
        self.panel.select_cell.assert_not_called()
        self.now=29;self.follow.tick(self.panel);self.assertEqual(self.app.selected,3)
        self.follow.arm(7,1);self.app.selected=1;self.app.displayed_ordinal=None
        self.now=100;self.follow.tick(self.panel);self.assertIsNone(self.follow.displayed_since)
        self.app.displayed_ordinal=0;self.follow.tick(self.panel)
        self.assertEqual(self.follow.displayed_since,100)

    def test_playback_edits_dialog_and_archives_hold_selection(self):
        self.now=30
        for field,value in [('playing',True),('bike_mark',(0,0,1,1)),('ocr_selecting',True),('roi_drag',(1,))]:
            original=getattr(self.app,field);setattr(self.app,field,value)
            self.follow.tick(self.panel);self.panel.select_cell.assert_not_called();setattr(self.app,field,original)
        for field,value in [('review_pending',True),('add_target',(7,1,0)),('busy',True)]:
            original=getattr(self.panel,field);setattr(self.panel,field,value)
            self.follow.tick(self.panel);self.panel.select_cell.assert_not_called();setattr(self.panel,field,original)
        self.app.root.grab_current=lambda:object();self.follow.tick(self.panel)
        self.app.root.grab_current=lambda:None
        self.panel.compact_owner=NS(follow=NS(get=lambda:False));self.follow.tick(self.panel)
        self.panel.select_cell.assert_not_called()

    def test_unarmed_or_other_clip_or_race_never_advances(self):
        self.now=30;self.app.selected=9;self.follow.tick(self.panel)
        self.app.selected=1;self.panel.event_id=8;self.follow.tick(self.panel)
        self.panel.event_id=7;self.follow.cancel();self.follow.tick(self.panel)
        self.panel.select_cell.assert_not_called()

    def confirm_last(self):
        self.cells[:]=self.cells[:1]
        self.follow.prepare_confirmation(self.panel,'confirmed')
        self.follow.confirmation_result(self.panel,dict(review=dict(action='confirmed',event_id=7,clip_id=1)))

    def arrival(self):
        self.cells.append(dict(self.cells[0],cell_key='2',at_ns=2,captures=[dict(clip_id=2)]))

    def test_confirmed_last_opens_arrival_immediately_then_waits_again(self):
        self.confirm_last();self.assertTrue(self.follow.confirmed_last)
        self.follow.activity(NS(type='3'))  # Release of the confirming Space.
        self.arrival();self.now=1;self.follow.tick(self.panel)
        self.assertEqual(self.app.selected,2)
        self.assertFalse(self.follow.confirmed_last)
        self.cells.append(dict(self.cells[0],cell_key='3',at_ns=3,captures=[dict(clip_id=3)]))
        self.now=2;self.follow.tick(self.panel);self.assertEqual(self.app.selected,2)

    def test_new_activity_restores_delay_after_confirmation(self):
        self.confirm_last();self.arrival();self.now=1;self.follow.activity()
        self.follow.tick(self.panel);self.panel.select_cell.assert_not_called()
        self.now=16;self.follow.tick(self.panel);self.assertEqual(self.app.selected,2)

    def test_nonlast_failed_or_interrupted_confirmation_does_not_expedite(self):
        result=dict(review=dict(action='confirmed',event_id=7,clip_id=1))
        self.follow.prepare_confirmation(self.panel,'confirmed')
        self.follow.confirmation_result(self.panel,result);self.assertFalse(self.follow.confirmed_last)
        self.cells[:]=self.cells[:1]
        self.follow.prepare_confirmation(self.panel,'confirmed')
        self.follow.confirmation_result(self.panel,'failed',error=True);self.assertFalse(self.follow.confirmed_last)
        self.follow.prepare_confirmation(self.panel,'confirmed');self.follow.activity()
        self.follow.confirmation_result(self.panel,result);self.assertFalse(self.follow.confirmed_last)
