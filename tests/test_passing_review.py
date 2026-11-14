import json
import unittest
import test_passings as fixtures
from racevideo import bib_review,passings,passing_review,storage


class PassingReviewTests(unittest.TestCase):
    def test_closer_ocr_guess_cannot_claim_a_track_before_human_identification(self):
        clip=self.f.clip(60,'7');self.f.index_bikes(clip)
        with self.c:self.c.execute("UPDATE race_passings SET seconds=60,at_ns=? WHERE bib='7' AND seconds=65",(self.f.start+60*10**9,))
        self.review(clip,action='confirmed',number='24',add=True)
        model=passings.compare_event(self.c,self.event)
        self.assertTrue(any(c['bib']=='24' and c['state']=='matched' and c['confirmed'] for c in model['cells']))
        self.assertFalse(any(c['bib']=='7' and c['state']=='matched' for c in model['cells']))

    def test_two_independent_human_bibs_cannot_be_collapsed_by_one_inferred_track(self):
        clip=self.f.clip(60);self.f.index_bikes(clip)
        with self.c:self.c.execute("UPDATE race_passings SET seconds=60.2,at_ns=? WHERE bib='7' AND seconds=65",(self.f.start+60_200_000_000,))
        self.review(clip,action='confirmed',number='24',add=True)
        passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=2,action='confirmed',number='7',add=True)
        model=passings.compare_event(self.c,self.event)
        self.assertEqual({c['bib'] for c in model['cells'] if c['confirmed'] and c['state']=='matched'},{'24','7'})
        self.assertTrue(any(r['reason']=='ambiguous_manual_association' for r in model['review_reconciliations']))

    def test_inferred_track_geometry_never_overwrites_a_saved_manual_bike_box(self):
        from racevideo.bike_evidence import collect
        clip=self.f.clip(60);self.f.index_bikes(clip)
        box=[.1,.2,.8,.9]
        self.review(clip,action='confirmed',number='24',bike_box=box)
        rows,_=collect(self.c,-2**63,2**63-1,clip_id=clip,event_id=self.event)
        self.assertEqual(next(v for v in rows if v['confirmed'])['bike_box'],box)

    def ignored_physical_candidate(self,clip):
        self.f.index_bikes(clip)
        report=json.loads(self.c.execute('SELECT report FROM bike_analyses WHERE clip_id=?',(clip,)).fetchone()[0])
        report['passages'][0]['ordinal']=2
        with self.c:self.c.execute('UPDATE bike_analyses SET report=? WHERE clip_id=?',(json.dumps(report),clip))
        row=next(c for c in passings.compare_event(self.c,self.event)['cells'] if c['bib']=='?')['captures'][0]
        return self.review(clip,action='ignored',visual_key=row['key'])

    def test_new_manual_confirmation_survives_an_older_inferred_candidate_ignore(self):
        clip=self.f.clip(60);self.ignored_physical_candidate(clip)
        self.review(clip,action='confirmed',number='24')
        model=passings.compare_event(self.c,self.event)
        cell=next(c for c in model['cells'] if c['bib']=='24' and c.get('seconds')==60)
        self.assertEqual(cell['state'],'matched');self.assertTrue(cell['confirmed'])
        self.assertEqual(cell['captures'][0]['ordinal'],1)  # Saved human frame, not detector frame 2.
        self.assertFalse(any(c['bib']=='?' for c in model['cells']))
        self.assertEqual(len(model['ignored_cells']),1)  # Keep the old decision/audit.

    def test_later_explicit_ignore_still_hides_confirmation_and_reconfirmation_restores_it(self):
        clip=self.f.clip(60);self.ignored_physical_candidate(clip)
        saved=self.review(clip,action='confirmed',number='24')
        key='review:'+str(saved['review']['bib_review_id'])
        self.review(clip,action='ignored',visual_key=key)
        self.assertFalse(any(c['bib']=='24' and c['confirmed'] for c in passings.compare_event(self.c,self.event)['cells']))
        self.review(clip,action='confirmed',number='24',visual_key=key)
        self.assertTrue(any(c['bib']=='24' and c['confirmed'] for c in passings.compare_event(self.c,self.event)['cells']))

    def test_bib_review_manual_evidence_also_survives_older_inferred_ignore(self):
        clip=self.f.clip(60);self.ignored_physical_candidate(clip)
        bib_review.decide(self.path,clip,decision='manual',number='24',ordinal=1)
        self.assertTrue(any(c['bib']=='24' and c['confirmed'] for c in passings.compare_event(self.c,self.event)['cells']))

    def test_multiple_undo_redo_roundtrips_preserve_original_rows_and_identity(self):
        clip=self.f.clip(80)
        a=self.review(clip,action='confirmed',number='7',add=True)
        b=self.review(clip,action='confirmed',number='4',add=True)
        original=[dict(r) for r in self.c.execute('SELECT * FROM bib_reviews ORDER BY id')]
        ub=passing_review.undo(self.path,b['history_id'])
        ua=passing_review.undo(self.path,a['history_id'])
        self.assertEqual(bib_review.list_rows(self.c,clip),[])
        ra=passing_review.redo(self.path,ua['history_id'])
        rb=passing_review.redo(self.path,ub['history_id'])
        self.assertEqual([dict(r) for r in self.c.execute('SELECT * FROM bib_reviews ORDER BY id')],original)
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0],2)
        self.assertEqual(passing_review.history_state(self.c,self.event)['undo_review_id'],rb['history_id'])
        passing_review.undo(self.path,rb['history_id'])
        self.assertEqual({r['number'] for r in bib_review.list_rows(self.c,clip)},{'7'})

    def test_new_edit_invalidates_redo_branch(self):
        clip=self.f.clip(80)
        saved=self.review(clip,action='confirmed',number='7',add=True)
        undone=passing_review.undo(self.path,saved['history_id'])
        self.review(clip,action='confirmed',number='4',add=True)
        self.assertIsNone(passing_review.history_state(self.c,self.event)['redo_review_id'])
        with self.assertRaisesRegex(ValueError,'Nothing to redo'):passing_review.redo(self.path,undone['history_id'])

    def test_ignore_and_correct_can_be_redone_after_undo(self):
        clip=self.f.clip(60,'24');key='ocr:'+str(self.c.execute('SELECT id FROM ocr_observations').fetchone()[0])
        for action,number in (('ignored',None),('corrected','7')):
            saved=self.review(clip,action=action,number=number,visual_key=key)
            undone=passing_review.undo(self.path,saved['history_id'])
            redone=passing_review.redo(self.path,undone['history_id'])
            self.assertEqual(redone['review']['action'],action)
            passing_review.undo(self.path,redone['history_id'])

    def test_adding_multiple_bibs_on_one_frame_preserves_existing_identification(self):
        clip=self.f.clip(80,'24')
        first=self.review(clip,action='confirmed',number='7',add=True)
        second=self.review(clip,action='confirmed',number='4',add=True)
        rows=bib_review.list_rows(self.c,clip)
        self.assertEqual({r['number'] for r in rows},{'24','7','4'})
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0],2)
        self.assertNotEqual(first['review']['subject_key'],second['review']['subject_key'])
        passing_review.undo(self.path,second['history_id'])
        self.assertEqual({r['number'] for r in bib_review.list_rows(self.c,clip)},{'24','7'})

    def setUp(self):
        self.f=fixtures.PassingsTests();self.f.setUp()
        self.path,self.c,self.event=self.f.path,self.f.c,self.f.event
    def tearDown(self):self.f.tearDown()
    def review(self,clip,**kw):
        return passing_review.decide(self.path,event_id=self.event,clip_id=clip,ordinal=1,**kw)
    def test_manual_confirmation_of_missing_ocr_is_reviewed_match_and_undo_restores_missing(self):
        clip=self.f.clip(60)
        before=[tuple(r) for r in self.c.execute('SELECT * FROM race_passings')]
        saved=self.review(clip,action='confirmed',number='24')
        cell=next(c for c in passings.compare_event(self.c,self.event)['cells'] if c.get('seconds')==60)
        self.assertEqual(cell['state'],'matched');self.assertTrue(cell['confirmed'])
        self.assertEqual(bib_review.list_rows(self.c,clip)[0]['ordinal'],1)
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM race_passings')])
        passing_review.undo(self.path,saved['history_id'])
        self.assertEqual(bib_review.list_rows(self.c,clip),[])
        self.assertEqual(next(c for c in passings.compare_event(self.c,self.event)['cells'] if c.get('seconds')==60)['state'],'missing')
    def test_correcting_candidate_preserves_raw_evidence_and_excludes_track_alternatives(self):
        clip=self.f.clip(60,'42')
        row=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone());oid=row['id'];row.pop('id');row['number']='99'
        with self.c:self.c.execute('INSERT INTO ocr_observations('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        saved=self.review(clip,action='corrected',number='24',visual_key='ocr:'+str(oid))
        cells=passings.compare_event(self.c,self.event)['cells']
        self.assertTrue(any(c['bib']=='24' and c['confirmed'] for c in cells))
        self.assertFalse(any(c['state']=='extra' for c in cells))
        self.assertEqual([r[0] for r in self.c.execute('SELECT number FROM ocr_observations ORDER BY id')],['42','99'])
        passing_review.undo(self.path,saved['history_id'])
        self.assertTrue(any(c['state']=='extra' for c in passings.compare_event(self.c,self.event)['cells']))
    def test_ignore_is_event_and_encounter_scoped_not_entire_video(self):
        clip=self.f.clip(60,'999');first=self.c.execute('SELECT id FROM ocr_observations').fetchone()[0]
        row=dict(self.c.execute('SELECT * FROM ocr_observations').fetchone());row.pop('id');row.update(number='24',encounter_key='another-bike')
        with self.c:self.c.execute('INSERT INTO ocr_observations('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        saved=self.review(clip,action='ignored',visual_key='ocr:'+str(first))
        cells=passings.compare_event(self.c,self.event)['cells']
        self.assertFalse(any(c['state']=='extra' for c in cells))
        self.assertTrue(any(c['bib']=='24' and c['state']=='matched' for c in cells))
        self.assertEqual(len(passings.visual_evidence(self.c,0,2**63-1)),2)
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0],0)
        passing_review.undo(self.path,saved['history_id'])
        self.assertTrue(any(c['state']=='extra' for c in passings.compare_event(self.c,self.event)['cells']))
    def test_invalid_or_stale_review_rolls_back_all_writes(self):
        clip=self.f.clip(60,'24')
        with self.assertRaises(ValueError):self.review(clip,action='confirmed',number='oops')
        with self.assertRaisesRegex(ValueError,'changed'):self.review(clip,action='confirmed',number='24',visual_key='ocr:99999')
        self.assertEqual(self.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0],0)
    def test_undo_will_not_overwrite_external_bib_edit(self):
        clip=self.f.clip(60);saved=self.review(clip,action='confirmed',number='24')
        row=bib_review.list_rows(self.c,clip)[0]
        bib_review.decide(self.path,clip,review_id=row['review_id'],decision='manual',number='7')
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):passing_review.undo(self.path,saved['history_id'])
        self.assertEqual(bib_review.list_rows(self.c,clip)[0]['number'],'7')
    def test_ignore_without_ocr_keeps_expected_crossmgr_passing_missing(self):
        clip=self.f.clip(60)
        self.review(clip,action='ignored')
        cell=next(c for c in passings.compare_event(self.c,self.event)['cells'] if c.get('seconds')==60)
        self.assertEqual(cell['state'],'missing')
    def test_undo_correction_restores_previous_operator_review(self):
        clip=self.f.clip(60,'24');oid=self.c.execute('SELECT id FROM ocr_observations').fetchone()[0]
        bib_review.decide(self.path,clip,observation_id=oid,decision='accepted')
        saved=self.review(clip,action='corrected',number='7',visual_key='review:1')
        passing_review.undo(self.path,saved['history_id'])
        row=bib_review.list_rows(self.c,clip)[0]
        self.assertEqual(row['number'],'24');self.assertEqual(row['decision'],'accepted')
        self.assertEqual(self.c.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':unittest.main()
