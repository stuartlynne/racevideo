"""Offline appearance descriptors and chronological, event-scoped suggestions.

No classifier output is an identity confirmation. OpenVINO is imported only by
the optional analysis worker; the GUI reads its small published result file.
"""
import hashlib
import json
from pathlib import Path

POLICY='rider-appearance-v1'


def unit(vector):
    import numpy as np
    vector=np.asarray(vector,dtype=np.float32)
    return vector/max(float(np.linalg.norm(vector)),1e-12)


def colour_descriptor(image):
    import cv2
    import numpy as np
    parts=[]
    # Helmet, torso, shorts. Separate regions retain black/white distinctions
    # and prevent a large background area from dominating the descriptor.
    for top,bottom in ((0,.23),(.23,.6),(.6,.9)):
        h,w=image.shape[:2];patch=image[int(top*h):max(int(bottom*h),int(top*h)+1),int(.15*w):max(int(.85*w),int(.15*w)+1)]
        hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
        hist=cv2.calcHist([hsv],[0,1,2],None,[12,4,4],[0,180,0,256,0,256]).ravel()
        parts.append(np.sqrt(hist/max(float(hist.sum()),1)))
    return unit(np.concatenate(parts))


def describe_colours(image):
    import cv2
    names=[]
    for top,bottom in ((0,.23),(.23,.6),(.6,.9)):
        h,w=image.shape[:2];patch=image[int(top*h):max(int(bottom*h),int(top*h)+1),int(.2*w):max(int(.8*w),int(.2*w)+1)]
        hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV).reshape(-1,3)
        counts={}
        for hue,sat,val in hsv[::max(1,len(hsv)//2000)]:
            hue,sat,val=map(int,(hue,sat,val))
            name=('black' if val<65 else 'white' if sat<45 and val>180 else 'grey' if sat<45 else
                'red' if hue<10 or hue>=170 else 'orange' if hue<22 else 'yellow' if hue<38 else
                'green' if hue<85 else 'blue' if hue<132 else 'purple')
            counts[name]=counts.get(name,0)+1
        names.append('/'.join(sorted(counts,key=counts.get,reverse=True)[:2]))
    return dict(zip(('helmet','torso','shorts'),names))


class Encoder:
    def __init__(self,model):
        import openvino as ov
        self.model=ov.Core().compile_model(str(model),'CPU',{'INFERENCE_NUM_THREADS':2,'NUM_STREAMS':1})
        self.output=self.model.output(0)
        self.sha256=hashlib.sha256(Path(model).read_bytes()+Path(model).with_suffix('.bin').read_bytes()).hexdigest()

    def encode(self,image):
        import cv2
        import numpy as np
        # Model expects raw BGR NCHW, 1x3x256x128; preprocessing is in the IR.
        tensor=cv2.resize(image,(128,256),interpolation=cv2.INTER_AREA).transpose(2,0,1)[None].astype(np.float32)
        return unit(self.model(tensor)[self.output].ravel())


def score(query,reference,method):
    import numpy as np
    learned=float(np.dot(query['embedding'],reference['embedding']))
    colour=float(np.dot(query['colour'],reference['colour']))
    return colour if method=='colour' else learned if method=='embedding' else .7*learned+.3*colour


def consistent_views(embeddings,anchor,maximum=3):
    """Do not average a neighbouring rider into a passage's appearance."""
    import numpy as np
    others=[i for i,v in enumerate(embeddings) if i!=anchor and float(np.dot(v,embeddings[anchor]))>=.8]
    return [anchor,*others][:maximum]


def rank(query,references,method,chronological=True):
    """One earliest reference passage per bib; never use the query's capture.

    This excludes all images from the held-out capture, not just one frame.
    Suggestions are never fed back into the gallery.
    """
    earliest={}
    for reference in sorted(references,key=lambda r:(r['at_ns'],r['id'])):
        if not reference.get('label') or reference.get('label_conflict'):continue
        if chronological and reference['at_ns']>=query['at_ns'] or reference['clip_id']==query['clip_id']:continue
        earliest.setdefault(reference['label'],reference)
    results=[]
    for bib,reference in earliest.items():
        results.append(dict(bib=bib,score=score(query,reference,method),reference_id=reference['id'],
            reference_clip=reference['clip_id'],reference_ordinal=reference['ordinal'],
            reference_source=reference['label_source'],image=reference['image']))
    results.sort(key=lambda r:(-r['score'],r['bib']))
    return results


def evaluate(subjects,references,method,source):
    reachable=[];unseen=0;high_wrong=[];unseen_high=[]
    for query in subjects:
        if query.get('label_source')!=source or query.get('label_conflict'):continue
        results=rank(query,references,method)
        margin=results[0]['score']-results[1]['score'] if len(results)>1 else 0
        if query['label'] not in {r['bib'] for r in results}:
            unseen+=1
            if results and results[0]['score']>=.9 and margin>=.05:unseen_high.append(query['id'])
            continue
        labels=[r['bib'] for r in results];position=labels.index(query['label'])+1
        reachable.append(dict(id=query['id'],bib=query['label'],rank=position,predicted=labels[0],clip_id=query['clip_id']))
        if position!=1 and results[0]['score']>=.9 and margin>=.05:high_wrong.append(query['id'])
    count=len(reachable)
    return dict(label_source=source,eligible_queries=count,unseen_queries=unseen,
        top1=sum(r['rank']==1 for r in reachable),top3=sum(r['rank']<=3 for r in reachable),
        top1_rate=sum(r['rank']==1 for r in reachable)/count if count else None,
        top3_rate=sum(r['rank']<=3 for r in reachable)/count if count else None,
        high_score_wrong_ids=high_wrong,unseen_high_score_ids=unseen_high,queries=reachable,
        interpretation='Appearance-only chronological retrieval; OCR labels are proxy labels, not independent ground truth. Scores are similarities, not probabilities.')


def review_fingerprint(connection,event_id):
    event=connection.execute('SELECT current_source_id,start_ns,end_ns,source_key FROM race_events WHERE id=?',(event_id,)).fetchone()
    reviews=connection.execute('SELECT count(*),COALESCE(max(updated_ns),0) FROM race_visual_reviews WHERE event_id=?',(event_id,)).fetchone()
    bibs=connection.execute('SELECT count(*),COALESCE(max(updated_ns),0) FROM bib_reviews').fetchone()
    return [*event,*reviews,*bibs]


def result_path(database,event_id):
    return Path(str(database)+f'.appearance-{event_id}.json')


def attach(connection,event_id,cells):
    """Lightweight optional results loading, called on the passings worker."""
    database=connection.execute('PRAGMA database_list').fetchone()[2]
    path=result_path(database,event_id)
    if not path.exists():return None
    try:
        result=json.loads(path.read_text())
        if result['fingerprint']!=review_fingerprint(connection,event_id):return dict(state='stale',report=result['report'])
        by_key={s['physical_key']:s for s in result['subjects'] if s.get('physical_key')}
        for cell in cells:
            if cell['captures']:
                candidate=cell['captures'][0];subject=by_key.get(candidate.get('physical_key'))
                ordinal=candidate.get('passage_ordinal',candidate.get('ordinal'))
                if subject and subject['clip_id']==candidate['clip_id'] and subject.get('ordinal',ordinal)==ordinal:
                    cell['appearance']=dict(subject_id=subject['id'],rankings=subject['rankings'],report=result['report'])
        return dict(state='complete',report=result['report'],subjects=len(result['subjects']),policy=result['policy'])
    except (OSError,ValueError,KeyError,TypeError):return dict(state='unavailable')
