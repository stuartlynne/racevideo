"""Approximate physical-passage navigation, independent of OCR bib strings."""
import argparse
import json
import math
import time
from contextlib import nullcontext
from pathlib import Path
from . import storage

SCHEMA='''CREATE TABLE IF NOT EXISTS bike_analyses (
 id INTEGER PRIMARY KEY,clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 created_ns INTEGER NOT NULL,source_run_id INTEGER REFERENCES ocr_runs(id) ON DELETE SET NULL,
 state TEXT NOT NULL,report TEXT NOT NULL DEFAULT '{}',error TEXT
); CREATE INDEX IF NOT EXISTS bike_analysis_clip ON bike_analyses(clip_id,id);'''


def overlap(a,b):
    x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]))
    inter=x*y;union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union else 0


def build(rows,width,height):
    tracks=[];active=[]
    for row in rows:
        objects=[]
        for obj in sorted(row.get('objects',[]),key=lambda d:-d['score']):
            box=obj['box']
            if obj['label']!='bicycle' or obj['score']<.15 or len(box)!=4 or not all(math.isfinite(v) for v in box):continue
            if box[2]-box[0]<max(2,width*.01) or box[3]-box[1]<max(2,height*.02):continue
            if not any(overlap(box,b)>.6 for b in objects):objects.append(box)
        active=[t for t in active if row['monotonic_ns']-t['points'][-1]['monotonic_ns']<=300_000_000]
        edges=[]
        for i,track in enumerate(active):
            last=track['points'][-1];old=last['box'];pred=old
            if len(track['points'])>1:
                prior=track['points'][-2];dt=last['monotonic_ns']-prior['monotonic_ns']
                if dt:
                    ratio=(row['monotonic_ns']-last['monotonic_ns'])/dt
                    dx=((old[0]+old[2]-prior['box'][0]-prior['box'][2])/2)*ratio
                    pred=[old[0]+dx,old[1],old[2]+dx,old[3]]
                    if pred[2]<0 or pred[0]>width:continue
            for j,box in enumerate(objects):
                dx=abs((box[0]+box[2]-pred[0]-pred[2])/2)/max(old[2]-old[0],width*.05)
                dy=abs((box[1]+box[3]-pred[1]-pred[3])/2)/max(old[3]-old[1],height*.05)
                if dx<.85 and dy<.5:edges.append((dx+dy-overlap(pred,box)*.5,i,j))
        used_tracks=set();used_objects=set()
        for _,i,j in sorted(edges):
            if i in used_tracks or j in used_objects:continue
            active[i]['points'].append(dict(ordinal=row['ordinal'],monotonic_ns=row['monotonic_ns'],box=objects[j]))
            used_tracks.add(i);used_objects.add(j)
        for j,box in enumerate(objects):
            if j in used_objects:continue
            track=dict(points=[dict(ordinal=row['ordinal'],monotonic_ns=row['monotonic_ns'],box=box)])
            tracks.append(track);active.append(track)
    passages=[]
    for t in tracks:
        points=t['points'];xs=[(p['box'][0]+p['box'][2])/2 for p in points]
        uncertain=len(points)<3 or max(xs)-min(xs)<width*.025 or abs(xs[-1]-xs[0])<width*.035
        center=min(points,key=lambda p:abs((p['box'][0]+p['box'][2])/2-width/2))
        passages.append(dict(key='detected:'+str(len(passages)+1),first_ordinal=points[0]['ordinal'],last_ordinal=points[-1]['ordinal'],
            ordinal=center['ordinal'],box=center['box'],points=points,numbers=[],confirmed=False,uncertain=uncertain,
            source_keys=[]))
    passages.sort(key=lambda p:(p['ordinal'],p['first_ordinal']))
    return dict(source='detector',policy='recall-v2',approximate=True,passages=passages,raw_tracks=len(tracks),
        warning='Estimated bike passages; occlusion can merge or fragment tracks. A return is a new passage, not the same lap.')


def save(connection,clip,report,source_run_id=None,analysis_id=None,commit=True):
    with connection if commit else nullcontext():
        if analysis_id:
            connection.execute("UPDATE bike_analyses SET state='complete',report=?,error=NULL WHERE id=?",(json.dumps(report),analysis_id));return analysis_id
        return connection.execute("INSERT INTO bike_analyses(clip_id,created_ns,source_run_id,state,report) VALUES(?,?,?,'complete',?)",
            (clip,time.time_ns(),source_run_id,json.dumps(report))).lastrowid


def primary_stops(entries):
    """Prioritize sustained tracks for navigation; retain every raw candidate."""
    islands=[]
    for entry in sorted(entries,key=lambda e:e['first_ordinal']):
        if not islands or entry['first_ordinal']>islands[-1]['end']+3:
            islands.append(dict(end=entry['last_ordinal'],entries=[entry]))
        else:
            islands[-1]['end']=max(islands[-1]['end'],entry['last_ordinal']);islands[-1]['entries'].append(entry)
    stops=[]
    for island in islands:
        candidates=[e for e in island['entries'] if not e.get('uncertain') or e.get('confirmed')]
        candidates=candidates or island['entries']
        support=max(len(e.get('points',[])) for e in candidates)
        stops.extend(e for e in candidates if len(e.get('points',[]))>=max(1,support*.6) or e.get('confirmed'))
    return sorted(stops,key=lambda e:(e['ordinal'],e.get('passing_order') or 1000,e['key']))


def completed_analysis(connection,clip):
    detector=motion=None
    for row in connection.execute("SELECT id,report FROM bike_analyses WHERE clip_id=? AND state='complete' ORDER BY id DESC",(clip,)):
        report=json.loads(row['report'])
        if report.get('source')=='motion':
            if motion is None:motion=row
        elif detector is None:detector=row
        if detector is not None and motion is not None:break
    if detector is not None and json.loads(detector['report']).get('passages'):return detector
    return motion if motion is not None else detector


def navigation(connection,clip):
    from . import bib_review
    meta=connection.execute('SELECT width,height FROM clips WHERE id=?',(clip,)).fetchone()
    if meta is None:return dict(passages=[],source='none',label='No capture')
    w,h=meta;analysis=connection.execute('SELECT * FROM bike_analyses WHERE clip_id=? ORDER BY id DESC LIMIT 1',(clip,)).fetchone()
    completed=completed_analysis(connection,clip)
    report=json.loads(completed['report']) if completed else None
    entries=report['passages'] if report else []
    for entry in entries:
        entry['source_keys']=[]
        entry['visual_key']=f"bike:{completed['id']}:{entry['key']}"
    primary_keys={e['key'] for e in primary_stops(entries)} if report else set()
    from .passings import visual_evidence
    effective={r['key'] for r in visual_evidence(connection,-2**63,2**63-1,clip_id=clip)}
    rows=[r for r in bib_review.list_rows(connection,clip) if r.get('decision')!='rejected' and
          ('review:'+str(r['review_id']) if r.get('decision') else 'ocr:'+str(r['observation_id'])) in effective]
    if not report:
        grouped={}
        for r in rows:
            key=(r.get('run_id'),r.get('encounter_key') or r['row_key'])
            entry=grouped.setdefault(key,dict(key='evidence:'+r['row_key'],first_ordinal=r['ordinal'],last_ordinal=r['ordinal'],ordinal=r['ordinal'],box=None,numbers=[],confirmed=False,source_keys=[],passing_order=r.get('passing_order')))
            entry['numbers'].append(r['number']);entry['confirmed']|=bool(r.get('decision'))
            entry['source_keys'].append('review:'+str(r['review_id']) if r.get('decision') else 'ocr:'+str(r['observation_id']))
            if r.get('bike_box'):
                a,b,c,d=r['bike_box'];entry['box']=[a*w,b*h,c*w,d*h]
        entries=list(grouped.values())
    else:
        for r in rows:
            order=r.get('passing_order');box=None
            if r.get('bike_box'):
                a,b,c,d=r['bike_box'];box=[a*w,b*h,c*w,d*h]
            candidates=[]
            for entry in entries:
                if entry['key'].startswith('manual:'):continue
                if not entry['first_ordinal']-2<=r['ordinal']<=entry['last_ordinal']+2:continue
                point=min(entry.get('points',[]),key=lambda p:abs(p['ordinal']-r['ordinal']),default=None)
                target=point['box'] if point else entry['box']
                if box:
                    score=overlap(box,target)
                    if score>.15:candidates.append((score,entry))
                else:
                    quad=json.loads(r['quad']) if isinstance(r.get('quad'),str) else r.get('quad')
                    if quad:
                        x=sum(p[0] for p in quad)/len(quad);y=sum(p[1] for p in quad)/len(quad)
                        if target[0]<=x<=target[2] and target[1]<=y<=target[3]:candidates.append((1,entry))
                    else:candidates.append((0,entry))
            primary=[pair for pair in candidates if pair[1]['key'] in primary_keys]
            if not box and len(primary)==1:candidates=primary
            if len(candidates)==1 or box and candidates:
                entry=max(candidates,key=lambda pair:pair[0])[1]
                entry['numbers'].append(r['number']);entry['confirmed']|=bool(r.get('decision'))
                entry['source_keys'].append('review:'+str(r['review_id']) if r.get('decision') else 'ocr:'+str(r['observation_id']))
                if order:entry['passing_order']=order
            elif r.get('decision') and not candidates:
                entries.append(dict(key='manual:'+r['row_key'],first_ordinal=r['ordinal'],last_ordinal=r['ordinal'],ordinal=r['ordinal'],box=box,numbers=[r['number']],confirmed=True,source_keys=['review:'+str(r['review_id'])],passing_order=order))
    for entry in entries:entry['numbers']=sorted(set(entry['numbers']))
    entries.sort(key=lambda e:(e['ordinal'],e.get('passing_order') or 1000,e['first_ordinal']))
    stops=primary_stops(entries) if report else entries
    for entry in entries:entry['navigation_primary']=entry in stops
    label=(f'~{len(entries)} detected/reviewed bike passages' if report else f'{len(entries)} evidence groups · bike count incomplete') if entries else 'Bike count unknown · Find bikes'
    if report:
        label=f'~{len(stops)} primary '+('motion' if report.get('source')=='motion' else 'bike')+f' stops · {len(entries)} candidates'
        if report.get('partial'):label+=' · partial scan'
    if analysis and analysis['state'] in ('queued','running','error'):label+=' · '+analysis['state']+(' '+str(analysis['error']) if analysis['error'] else '')
    if analysis and analysis['state']=='inconclusive':label+=' · no clear moving subject found'
    return dict(passages=entries,stops=stops,source=('motion' if report.get('source')=='motion' else 'detector') if report else 'evidence',label=label)


def run(database,analysis_id,models,device,event_id=None,offset=0):
    import os,fcntl
    os.environ['OMP_NUM_THREADS']='2';os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:2]))
    analysis_ids=[analysis_id] if isinstance(analysis_id,int) else list(analysis_id)
    c=storage.connect(database);lock=open(str(Path(database).resolve())+'.ocr.lock','a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        import cv2,numpy as np
        from paddlex import create_model
        from paddlex.inference.utils.pp_option import PaddlePredictorOption
        cv2.setNumThreads(1)
        model=create_model('PicoDet-S',model_dir=str(Path(models)/'PicoDet-S'),device=device,
            pp_option=PaddlePredictorOption(cpu_threads=2,run_mode='mkldnn' if device=='cpu' else 'paddle'))
        remaining=list(analysis_ids)
        while remaining:
            if event_id is not None:
                from .analysis_priority import pending
                remaining=pending(c,remaining,event_id,offset)
                if not remaining:break
            analysis_id=remaining.pop(0)
            row=c.execute('SELECT clip_id,state FROM bike_analyses WHERE id=?',(analysis_id,)).fetchone()
            if row is None or row['state']!='queued':continue
            clip=row['clip_id']
            with c:claimed=c.execute("UPDATE bike_analyses SET state='running' WHERE id=? AND state='queued'",(analysis_id,)).rowcount
            if not claimed:continue
            metadata=c.execute('SELECT width,height FROM clips WHERE id=?',(clip,)).fetchone();rows=[]
            from .neural_ocr import result_dict
            for frame in storage.frame_index(c,clip):
                image=cv2.imdecode(np.frombuffer(storage.read_frame(c,clip,frame['ordinal']),np.uint8),cv2.IMREAD_COLOR)
                result=result_dict(list(model.predict(input=image,threshold=.15))[0])
                objects=[dict(label=o['label'],score=float(o['score']),box=list(map(float,o['coordinate']))) for o in result.get('boxes',[]) if o['label']=='bicycle']
                rows.append(dict(frame,objects=objects))
            save(c,clip,build(rows,*metadata),analysis_id=analysis_id)
    except Exception as exc:
        with c:
            for analysis_id in analysis_ids:
                c.execute("UPDATE bike_analyses SET state='error',error=? WHERE id=? AND state IN ('queued','running')",(str(exc),analysis_id))
        raise
    finally:lock.close();c.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--analysis',type=int,nargs='+',required=True)
    p.add_argument('--models',required=True);p.add_argument('--device',required=True);p.add_argument('--event',type=int);p.add_argument('--offset',type=float,default=0);a=p.parse_args()
    run(a.db,a.analysis,a.models,a.device,a.event,a.offset)


if __name__=='__main__':main()
