import json
import unittest
from racevideo.review_resolution import resolve


def evidence(key='review:7',confirmed=True,when=20,physical='bike:1:motion:1'):
    return dict(key=key,confirmed=confirmed,reviewed_ns=when,physical_key=physical,clip_id=1,number='24',ordinal=17)


def decision(action='ignored',when=10,keys=('bike:1:motion:1',),bib_review_id=None,ident=1):
    return dict(id=ident,updated_ns=when,source_keys=json.dumps(keys),action=action,bib_review_id=bib_review_id)


class ReviewResolutionTests(unittest.TestCase):
    def test_newer_manual_confirmation_is_retained_and_reconciliation_is_reported(self):
        v=evidence();result=resolve([v],[decision()])
        self.assertEqual(result['evidence'],[v])
        self.assertEqual(result['reconciliations'][0]['reason'],'newer_manual_confirmation')
        self.assertEqual(result['reconciliations'][0]['ordinal'],17)
    def test_newer_explicit_ignore_is_honored_without_recreating_a_confirmation(self):
        result=resolve([evidence()],[decision(when=30,keys=('review:7','bike:1:motion:1'))])
        self.assertEqual(result,dict(evidence=[],reconciliations=[]))
    def test_new_confirmation_rules_do_not_resurrect_old_ocr_alternatives(self):
        human=evidence();ocr=evidence(key='ocr:99',confirmed=False,when=100)
        result=resolve([human,ocr],[decision(),decision(action='confirmed',when=21,keys=('review:7','ocr:99','bike:1:motion:1'),bib_review_id=7,ident=2)])
        self.assertEqual(result['evidence'],[human])
    def test_duplicate_geometry_associations_cannot_duplicate_the_human_observation(self):
        v=evidence();duplicate=dict(v,physical_key='bike:1:motion:2')
        result=resolve([v,duplicate],[])
        self.assertEqual(result['evidence'],[v]);self.assertEqual(result['reconciliations'][0]['reason'],'duplicate_manual_association')
    def test_recovered_manual_evidence_is_visible_but_newer_explicit_suppression_still_applies(self):
        v=dict(evidence(physical=None),recovered_manual=True)
        result=resolve([v],[])
        self.assertEqual(result['reconciliations'][0]['reason'],'recovered_manual_evidence')
        self.assertEqual(resolve([v],[decision(when=30,keys=('review:7',))])['evidence'],[])
