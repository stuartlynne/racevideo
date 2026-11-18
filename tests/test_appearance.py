import copy
import json
import unittest
from pathlib import Path
import numpy as np
from racevideo.appearance import rank,evaluate,attach,result_path,review_fingerprint,colour_descriptor,consistent_views


def subject(key,bib,stamp,clip,vector,source='manual'):
    v=np.asarray(vector,dtype=np.float32)
    return dict(id=key,label=bib,label_source=source,at_ns=stamp,clip_id=clip,ordinal=0,
        embedding=v,colour=v,image=key+'.jpg')


class AppearanceTests(unittest.TestCase):
    def test_neighbouring_rider_view_does_not_contaminate_passage_descriptor(self):
        views=[np.array([1,0]),np.array([0,1]),np.array([.99,.01])]
        self.assertEqual(consistent_views(views,0),[0,2])

    def test_gui_results_reader_does_not_require_numpy_or_openvino(self):
        import subprocess,sys
        subprocess.run([sys.executable,'-c',"import sys;sys.modules['numpy']=None;sys.modules['openvino']=None;from racevideo.appearance import attach,result_path"],check=True)

    def test_gui_result_reader_has_no_neural_or_numpy_import_requirement(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-c',"import sys;sys.modules['numpy']=None;sys.modules['openvino']=None;from racevideo.appearance import attach;print('ok')"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_no_future_or_same_capture_leakage_and_one_reference_per_bib(self):
        query=subject('q','1',100,10,[1,0])
        references=[subject('future','1',101,11,[1,0]),subject('same-clip','1',80,10,[1,0]),
            subject('first','2',50,5,[0,1]),subject('later','2',70,7,[1,0])]
        results=rank(query,references,'embedding')
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]['reference_id'],'first')
        self.assertEqual(results[0]['score'],0)

    def test_held_out_manual_and_ocr_proxy_metrics_are_separate(self):
        reference=subject('ref','1',10,1,[1,0])
        manual=subject('m','1',20,2,[1,0])
        proxy=subject('p','1',30,3,[1,0],source='ocr_proxy')
        unseen=subject('u','99',40,4,[1,0])
        result=evaluate([reference,manual,proxy,unseen],[reference],'embedding','manual')
        self.assertEqual(result['eligible_queries'],1);self.assertEqual(result['top1'],1)
        self.assertEqual(result['unseen_queries'],2)

    def test_postrace_review_can_use_later_reference_but_never_its_own_capture(self):
        query=subject('q','1',10,1,[1,0])
        future=subject('later','1',20,2,[1,0])
        same=subject('same','2',5,1,[1,0])
        self.assertEqual(rank(query,[future,same],'embedding'),[])
        ranked=rank(query,[future,same],'embedding',chronological=False)
        self.assertEqual([r['bib'] for r in ranked],['1'])

    def test_unseen_identity_high_similarity_is_reported_as_a_risk(self):
        references=[subject('one','1',10,1,[1,0]),subject('two','2',11,2,[0,1])]
        query=subject('new','99',20,3,[1,0])
        result=evaluate([query],references,'embedding','manual')
        self.assertEqual(result['eligible_queries'],0)
        self.assertEqual(result['unseen_high_score_ids'],['new'])

    def test_conflicting_reference_labels_are_never_used(self):
        ref=subject('ref','1',10,1,[1,0]);ref['label_conflict']=True
        self.assertEqual(rank(subject('query','1',20,2,[1,0]),[ref],'embedding'),[])

    def test_colour_baseline_distinguishes_black_white_and_red(self):
        images=[np.full((256,128,3),v,np.uint8) for v in [(0,0,0),(255,255,255),(0,0,255)]]
        a,b,c=map(colour_descriptor,images)
        self.assertGreater(float(np.dot(a,a)),.99)
        self.assertLess(float(np.dot(a,b)),.1)
        self.assertLess(float(np.dot(b,c)),.1)

    def test_conflicting_labels_are_not_evaluation_ground_truth(self):
        reference=subject('ref','1',10,1,[1,0]);query=subject('q','1',20,2,[1,0]);query['label_conflict']=True
        self.assertEqual(evaluate([query],[reference],'embedding','manual')['eligible_queries'],0)

    def test_published_suggestions_do_not_change_identity_and_stale_reviews_disable_them(self):
        import test_passings as fixtures
        from racevideo import passings,bib_review
        f=fixtures.PassingsTests();f.setUp()
        try:
            clip=f.clip(60);f.index_bikes(clip)
            model=passings.compare_event(f.c,f.event);cell=next(c for c in model['cells'] if c['cell_key'].startswith('cm:') and c['bib']=='24' and c.get('seconds')==60)
            candidate=cell['captures'][0]
            sidecar=dict(policy='test',fingerprint=review_fingerprint(f.c,f.event),report='/tmp/report.html',subjects=[
                dict(id='subject',physical_key=candidate['physical_key'],clip_id=clip,rankings={'hybrid':[{'bib':'7','score':.95}]})])
            result_path(f.path,f.event).write_text(json.dumps(sidecar))
            fresh=passings.compare_event(f.c,f.event);cell=next(c for c in fresh['cells'] if c['cell_key']==cell['cell_key'])
            self.assertEqual(cell['appearance']['rankings']['hybrid'][0]['bib'],'7')
            self.assertEqual(cell['bib'],'24');self.assertFalse(cell['confirmed']);self.assertEqual(cell['state'],'missing')
            bib_review.decide(f.path,clip,decision='manual',number='24',ordinal=1)
            changed=passings.compare_event(f.c,f.event)
            self.assertEqual(changed['appearance']['state'],'stale')
            self.assertFalse(any(c.get('appearance') for c in changed['cells']))
        finally:f.tearDown()
