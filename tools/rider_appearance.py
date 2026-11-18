"""CPU-only, offline event appearance experiment and reviewable image report."""
import argparse
import bisect
import hashlib
import html
import json
import os
from pathlib import Path
import time
import numpy as np

from racevideo import storage
from racevideo.appearance import Encoder,POLICY,unit,colour_descriptor,describe_colours,consistent_views,rank,evaluate,review_fingerprint,result_path


def metadata(c,event_id):
    from racevideo.passings import compare_event
    from racevideo.bike_index import navigation
    model=compare_event(c,event_id);event=model['event'];subjects=[]
    times=[col['start_ns'] for col in model['columns'][1:]]
    for clip in c.execute('SELECT id,width,height FROM clips WHERE started_ns<=? AND ended_ns>=? ORDER BY started_ns,id',(event['end_ns'],event['start_ns'])):
        nav=navigation(c,clip['id'])
        for entry in nav.get('stops',[]):
            row=c.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip['id'],entry['ordinal'])).fetchone()
            if row is None or not event['start_ns']<=row[0]<=event['end_ns']:continue
            key=entry.get('visual_key') or entry['key']
            subjects.append(dict(id=hashlib.sha256(f'{clip["id"]}:{key}'.encode()).hexdigest()[:16],
                clip_id=clip['id'],ordinal=entry['ordinal'],at_ns=row[0],lap=bisect.bisect_right(times,row[0]),
                physical_key=entry.get('visual_key'),entry=entry,width=clip['width'],height=clip['height'],labels=[]))
    for cell in model['cells']:
        if cell['origin']!='CrossMgr' or not cell['visual_count']:continue
        for evidence in cell['captures'][:cell['visual_count']]:
            options=[s for s in subjects if s['clip_id']==evidence['clip_id'] and (
                evidence.get('physical_key') and s['physical_key']==evidence['physical_key'] or
                evidence['key'] in s['entry'].get('source_keys',[]))]
            if not options and evidence['confirmed']:
                # A human frame anchor remains usable even when the bicycle
                # tracker could not associate it. This is a reference crop,
                # not an extra detected passage or a new identity assignment.
                info=c.execute('SELECT width,height FROM clips WHERE id=?',(evidence['clip_id'],)).fetchone()
                stamp=c.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(evidence['clip_id'],evidence['ordinal'])).fetchone()[0]
                box=evidence.get('bike_box')
                box=[v*s for v,s in zip(box,(info[0],info[1],info[0],info[1]))] if box else None
                subject=dict(id=hashlib.sha256(f'manual:{evidence["key"]}'.encode()).hexdigest()[:16],
                    clip_id=evidence['clip_id'],ordinal=evidence['ordinal'],at_ns=stamp,lap=cell['column'],
                    physical_key=None,entry=dict(key=evidence['key'],points=[],box=box,source_keys=[evidence['key']]),
                    width=info[0],height=info[1],labels=[],reference_only=True)
                subjects.append(subject);options=[subject]
            if len(options)!=1:continue
            source='manual' if evidence['confirmed'] else 'ocr_proxy'
            if source=='ocr_proxy':
                if cell.get('ambiguous') or not evidence['key'].startswith('ocr:'):continue
                support=c.execute('SELECT frame_count,confidence FROM ocr_observations WHERE id=?',(int(evidence['key'].split(':')[1]),)).fetchone()
                if support is None or support[0]<3 or support[1]<90:continue
            options[0]['labels'].append((cell['bib'],source,cell['name'],cell['column']))
    for subject in subjects:
        labels=subject.pop('labels');manual=[x for x in labels if x[1]=='manual'];labels=manual or labels
        if labels and len({x[0] for x in labels})==1:
            bib,source,name,lap=labels[0];subject.update(label=bib,label_source=source,name=name,lap=lap)
        else:subject.update(label=None,label_source=None,name='',label_conflict=bool(labels))
        if subject['label_source']=='manual':
            conflicts=manual_ocr_conflicts(c,subject)
            if conflicts:subject.update(label_conflict=True,label_warning='Manual label conflicts with repeated OCR: '+', '.join(conflicts)+'. Excluded from automatic gallery and evaluation; original review unchanged.')
    return model,subjects


def manual_ocr_conflicts(c,subject):
    qualified=set();entry=subject['entry']
    rows=c.execute('''SELECT o.number,o.ordinal,o.quad FROM ocr_observations o JOIN ocr_runs r ON r.id=o.run_id
        WHERE r.clip_id=? AND r.id=(SELECT max(id) FROM ocr_runs WHERE clip_id=? AND state='complete')
        AND o.frame_count>=5 AND o.confidence>=90 AND o.status!='ambiguous' ''',(subject['clip_id'],subject['clip_id']))
    for row in rows:
        points=entry.get('points',[]);point=min(points,key=lambda p:abs(p['ordinal']-row['ordinal']),default=None)
        if point and abs(point['ordinal']-row['ordinal'])>2:continue
        if not point and abs(subject['ordinal']-row['ordinal'])>3:continue
        box=point['box'] if point else entry.get('box')
        if not box:continue
        quad=json.loads(row['quad']);x=sum(p[0] for p in quad)/len(quad);y=sum(p[1] for p in quad)/len(quad)
        w=box[2]-box[0];h=box[3]-box[1]
        if box[0]-.05*w<=x<=box[2]+.05*w and box[1]-.3*h<=y<=box[3]:qualified.add(row['number'])
    return sorted(qualified-{subject['label']}) if qualified and subject['label'] not in qualified else []


def person_crop(image,objects,bike):
    h,w=image.shape[:2];candidates=[]
    for obj in objects:
        if obj['label']!='person' or obj['score']<.4:continue
        box=obj['box'];x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
        if box[3]-box[1]<h*.12:continue
        if bike:
            bw=max(1,bike[2]-bike[0]);bh=max(1,bike[3]-bike[1]);bx=(bike[0]+bike[2])/2
            if not bike[0]-.15*bw<=x<=bike[2]+.15*bw or not bike[1]-.9*bh<=y<=bike[3]:continue
            score=abs(x-bx)/bw+abs(box[3]-bike[3])/bh*.15-obj['score']*.1
        else:score=abs(x-w/2)/w-obj['score']*.05
        candidates.append((score,box,obj['score']))
    if not candidates:return None
    candidates.sort(key=lambda p:p[0]);_,box,confidence=candidates[0]
    # Pad enough to include the helmet without letting the bike dominate the
    # person embedding. Preserve the unmasked source crop for human inspection.
    bw=box[2]-box[0];bh=box[3]-box[1]
    bounds=[max(0,round(box[0]-.06*bw)),max(0,round(box[1]-.05*bh)),min(w,round(box[2]+.06*bw)),min(h,round(box[3]+.03*bh))]
    overlap=0
    for _,other,_ in candidates[1:]:
        intersection=max(0,min(box[2],other[2])-max(box[0],other[0]))*max(0,min(box[3],other[3])-max(box[1],other[1]))
        overlap=max(overlap,intersection/max(1,bw*bh))
    return bounds,confidence,overlap


def extract(c,subject,report,encoder,output):
    import cv2
    entry=subject['entry'];points=entry.get('points',[])
    wanted=[subject['ordinal']+d for d in (-8,-4,0,4,8)] if points else [subject['ordinal']]
    ordinals=sorted({min(points,key=lambda p:abs(p['ordinal']-n))['ordinal'] for n in wanted}) if points else wanted
    views=[]
    for ordinal in ordinals:
        row=next((r for r in report['results'] if r['ordinal']==ordinal),None)
        if row is None:continue
        point=next((p for p in points if p['ordinal']==ordinal),None);bike=point['box'] if point else entry.get('box')
        image=cv2.imdecode(np.frombuffer(storage.read_frame(c,subject['clip_id'],ordinal),np.uint8),cv2.IMREAD_COLOR)
        crop=person_crop(image,row['objects'],bike)
        if crop is None:continue
        bounds,confidence,occlusion=crop;left,top,right,bottom=bounds
        original=image[top:bottom,left:right].copy();masked=original.copy()
        # Suppress numeric text in the descriptor so identity retrieval does
        # not get credit for simply retaining the plate digits in the crop.
        for reading in row['readings']:
            quad=np.asarray(reading['quad'],np.float32)-[left,top]
            if quad[:,0].max()<0 or quad[:,0].min()>=right-left or quad[:,1].max()<0 or quad[:,1].min()>=bottom-top:continue
            fill=tuple(map(float,np.median(masked.reshape(-1,3),axis=0)))
            cv2.fillConvexPoly(masked,np.rint(quad).astype(np.int32),fill)
        sharp=float(cv2.Laplacian(cv2.cvtColor(cv2.resize(original,(128,256)),cv2.COLOR_BGR2GRAY),cv2.CV_32F).var())
        views.append(dict(ordinal=ordinal,bounds=bounds,quality=confidence*(1-occlusion),occlusion=occlusion,
            sharpness=sharp,original=original,masked=masked))
    views.sort(key=lambda v:(v['quality'],v['sharpness']),reverse=True)
    if not views:return False
    anchor=min(range(len(views)),key=lambda i:abs(views[i]['ordinal']-subject['ordinal']))
    encoded=[encoder.encode(v['masked']) for v in views]
    indices=consistent_views(encoded,anchor)
    embeddings=[];colours=[];details=[]
    summary=describe_colours(views[anchor]['original'])
    for i in indices:
        view=views[i]
        embeddings.append(encoded[i]);colours.append(colour_descriptor(view['masked']))
        image=view.pop('original');view.pop('masked')
        filename=f'{subject["id"]}-{view["ordinal"]}.jpg'
        h,w=image.shape[:2];scale=min(1,320/h);image=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))))
        cv2.imwrite(str(output/'images'/filename),image)
        details.append(dict(view,image='images/'+filename))
    subject.update(embedding=unit(np.mean(embeddings,axis=0)),colour=unit(np.mean(colours,axis=0)),
        views=details,image=details[0]['image'],colours=summary,rejected_views=len(views)-len(indices))
    return True


def make_report(path,result):
    esc=lambda v:html.escape(str(v))
    by_id={s['id']:s for s in result['subjects']};articles=[]
    sources={'manual':'Manually confirmed','ocr_proxy':'OCR-supported'}
    for s in result['subjects']:
        cards=[]
        for match in s['rankings']['hybrid'][:3]:
            reference=by_id[match['reference_id']]
            cards.append(f'<figure><a href="#{esc(reference["id"])}"><img src="{esc(match["image"])}"></a><figcaption>Bib {esc(match["bib"])} · {match["score"]:.3f}<br>{esc(sources.get(match["reference_source"],match["reference_source"]))} · clip {match["reference_clip"]}</figcaption></figure>')
        lap=f"Lap {s['lap']}" if s['lap'] else 'Before Lap 1'
        articles.append(f'''<article id="{esc(s['id'])}" data-search="{esc(str(s['clip_id'])+' '+str(s.get('label') or '')+' '+s.get('name',''))}">
        <h2>{lap} · clip {s['clip_id']} · frame {s['ordinal']+1} · {esc(s.get('label') or '?')} {esc(s.get('name',''))}</h2>
        <p>{esc(sources.get(s.get('label_source'),'Identity unconfirmed'))}. {esc(s.get('label_warning',''))} Appearance is a suggestion; scores are not probabilities.</p>
        <div class="cards"><figure><img src="{esc(s['image'])}"><figcaption>Current passage</figcaption></figure>{''.join(cards) or '<p>No usable reference from another capture.</p>'}</div>
        <details><summary>All baseline rankings and source frames</summary><pre>{esc(json.dumps(dict(rankings=s['rankings'],views=s['views'],rough_region_colours=s['colours']),indent=2))}</pre></details></article>''')
    metrics=esc(json.dumps(result['metrics'],indent=2))
    warnings=''.join(f'<p><a href="#{esc(s["id"])}">Review clip {s["clip_id"]}, saved bib {esc(s["label"])}</a>: {esc(s["label_warning"])}</p>' for s in result['subjects'] if s.get('label_warning'))
    rows=[]
    for method in ('colour','embedding','hybrid'):
        manual=result['metrics']['manual'][method]['manual'];proxy=result['metrics']['supported'][method]['ocr_proxy']
        rows.append(f'<tr><td>{method}</td><td>{manual["top1"]}/{manual["eligible_queries"]}</td><td>{proxy["top1"]}/{proxy["eligible_queries"]}</td><td>{proxy["top3"]}/{proxy["eligible_queries"]}</td></tr>')
    summary='<table cellpadding="8"><tr><th>Method</th><th>Manual repeats: first choice</th><th>OCR proxy: first choice</th><th>OCR proxy: top three</th></tr>'+''.join(rows)+'</table><p>Only later, separate captures with an earlier reference are scored. Small sample; OCR proxy labels are not independent truth.</p>'
    path.write_text('''<!doctype html><meta charset="utf-8"><title>Elite rider appearance experiment</title>
    <style>body{font:16px sans-serif;background:#edf0f3;color:#17202a;margin:24px}header{position:sticky;top:0;background:#edf0f3;padding:12px;z-index:2}article{background:white;padding:16px;margin:16px 0;scroll-margin-top:260px}article:target{outline:4px solid #1269c7}.cards{display:flex;gap:16px;flex-wrap:wrap}figure{margin:0;max-width:230px}img{height:240px;max-width:230px;object-fit:contain;filter:brightness(1.6)}figcaption{max-width:230px}pre{white-space:pre-wrap;font-size:13px}input{font-size:18px;padding:8px;width:32ch;max-width:90%}</style>
    <header><h1>Elite rider appearance experiment</h1><input id="search" placeholder="Filter by query bib, name or clip"><p>CPU OSNet embedding + regional colour. Review may use earlier or later reference captures; evaluation uses earlier captures only. Recognized numeric patches masked for comparison. Images brightened for viewing. No identity or race-time updates.</p></header>
    '''+summary+warnings+'''<details><summary>Evaluation and limitations</summary><pre>'''+metrics+'</pre></details>'+''.join(articles)+'''
    <script>document.querySelector('#search').oninput=e=>{let q=e.target.value.toLowerCase();for(let a of document.querySelectorAll('article'))a.hidden=!a.dataset.search.toLowerCase().includes(q)};window.addEventListener('hashchange',()=>{let a=document.getElementById(location.hash.slice(1));if(a){a.hidden=false;a.scrollIntoView({block:'start'})}});</script>''')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--event',type=int,required=True)
    p.add_argument('--results',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--publish',action='store_true',help='Publish suggestions sidecar for the app; never modifies the video database')
    p.add_argument('--review-gallery',choices=('past','all'),default='past',help='All allows later references for post-race review; evaluation always uses earlier captures only')
    a=p.parse_args();allowed=sorted(os.sched_getaffinity(0));os.sched_setaffinity(0,{allowed[0],allowed[min(2,len(allowed)-1)]})
    import cv2;cv2.setNumThreads(1)
    a.output.mkdir(parents=True,exist_ok=True);(a.output/'images').mkdir(exist_ok=True)
    c=storage.connect(a.db,readonly=True);fingerprint=review_fingerprint(c,a.event);started=time.monotonic()
    model,subjects=metadata(c,a.event);encoder=Encoder(a.model);done=[];skipped=[]
    for subject in subjects:
        source=a.results/f'clip-{subject["clip_id"]}.json'
        if not source.exists():skipped.append(dict(id=subject['id'],clip_id=subject['clip_id'],reason='missing detections'));continue
        report=json.loads(source.read_text())
        if extract(c,subject,report,encoder,a.output):done.append(subject)
        else:skipped.append(dict(id=subject['id'],clip_id=subject['clip_id'],reason='no suitable person crop',label=subject['label']))
        if len(done)%20==0:print('Extracted',len(done),'of',len(subjects),'passages',flush=True)
    methods=('colour','embedding','hybrid');metrics={}
    for gallery_mode in ('manual','supported'):
        refs=[s for s in done if s['label'] and not s.get('label_conflict') and (gallery_mode=='supported' or s['label_source']=='manual')]
        metrics[gallery_mode]={method:{source:evaluate(done,refs,method,source) for source in ('manual','ocr_proxy')} for method in methods}
    refs=[s for s in done if s['label'] and not s.get('label_conflict')]
    for subject in done:
        subject['rankings']={method:rank(subject,refs,method,chronological=a.review_gallery=='past')[:3] for method in methods}
    np.savez_compressed(a.output/'descriptors.npz',ids=np.array([s['id'] for s in done]),embedding=np.stack([s['embedding'] for s in done]),colour=np.stack([s['colour'] for s in done]))
    for s in done:s.pop('embedding');s.pop('colour');s.pop('entry')
    result=dict(policy=POLICY,event_id=a.event,event_name=model['event']['name'],source=str(a.db.resolve()),review_gallery=a.review_gallery,
        fingerprint=fingerprint,model_sha256=encoder.sha256,model='person-reidentification-retail-0288',device='CPU',
        subjects=done,skipped=skipped,metrics=metrics,wall_seconds=time.monotonic()-started,
        report=str((a.output/'report.html').resolve()),created_ns=time.time_ns(),
        limitations='Cycling domain not trained; geometric crops may include another rider. Only manual holdouts are independent identity checks. OCR-labelled evaluations are proxy checks. Similarity is not calibrated confidence.')
    make_report(a.output/'report.html',result)
    (a.output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    if a.publish:
        if review_fingerprint(c,a.event)!=fingerprint:raise RuntimeError('Reviews changed during analysis; rerun before publishing')
        destination=result_path(a.db,a.event);temporary=destination.with_suffix('.json.tmp');temporary.write_text(json.dumps(result)+'\n');temporary.replace(destination)
    c.close()
    counts={gallery:{method:{source:{k:value[k] for k in ('eligible_queries','top1','top3','unseen_queries')}
        for source,value in sources.items()} for method,sources in methods.items()} for gallery,methods in metrics.items()}
    print(json.dumps(dict(subjects=len(done),skipped=len(skipped),wall_seconds=result['wall_seconds'],report=result['report'],metrics=counts)),flush=True)


if __name__=='__main__':main()
