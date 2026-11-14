"""Independent CPU worker for experimental front-tyre tracking and brackets."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
from . import storage
from .crossing import first_crossing

SCHEMA='''CREATE TABLE IF NOT EXISTS wheel_analyses (
 id INTEGER PRIMARY KEY,clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 subject_key TEXT NOT NULL,created_ns INTEGER NOT NULL,updated_ns INTEGER NOT NULL,
 state TEXT NOT NULL,parameters TEXT NOT NULL,report TEXT NOT NULL DEFAULT '{}',error TEXT,pid INTEGER
); CREATE INDEX IF NOT EXISTS wheel_analysis_subject ON wheel_analyses(clip_id,subject_key,id);
CREATE TABLE IF NOT EXISTS passing_timing_links (
 id INTEGER PRIMARY KEY,analysis_id INTEGER NOT NULL REFERENCES wheel_analyses(id) ON DELETE CASCADE,
 event_id INTEGER NOT NULL REFERENCES race_events(id),
 passing_id INTEGER REFERENCES race_passings(id),cell_key TEXT NOT NULL,
 clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,visual_key TEXT NOT NULL,bib TEXT NOT NULL,
 race_start_ns INTEGER NOT NULL,camera_minus_cm_ns INTEGER NOT NULL,
 identity_confirmed_at_link INTEGER NOT NULL DEFAULT 0,linked_ns INTEGER NOT NULL,
 UNIQUE(analysis_id,event_id,cell_key,visual_key,bib,race_start_ns,camera_minus_cm_ns,identity_confirmed_at_link)
);
CREATE INDEX IF NOT EXISTS passing_timing_event ON passing_timing_links(event_id,cell_key,id);
CREATE VIEW IF NOT EXISTS passing_timing_results AS
 SELECT l.*,a.state AS analysis_state,
 json_extract(a.report,'$.status') AS timing_status,
 json_extract(a.report,'$.line_x') AS line_x,
 json_extract(a.report,'$.crossing.status') AS crossing_method,
 json_extract(a.report,'$.crossing.before_ordinal') AS before_ordinal,
 json_extract(a.report,'$.crossing.first_observed_after_ordinal') AS first_after_ordinal,
 json_extract(a.report,'$.crossing.bracket_monotonic_ns') AS bracket_ns,
 json_extract(a.report,'$.crossing.estimated_received_ns') AS camera_estimate_ns,
 json_extract(a.report,'$.crossing.estimated_received_ns')-l.camera_minus_cm_ns AS cm_estimate_ns,
 json_extract(a.report,'$.crossing.estimated_received_ns')-l.camera_minus_cm_ns-l.race_start_ns AS race_elapsed_ns,
 json_extract(a.report,'$.crossing.before_received_ns')-l.camera_minus_cm_ns-l.race_start_ns AS before_race_ns,
 json_extract(a.report,'$.crossing.after_received_ns')-l.camera_minus_cm_ns-l.race_start_ns AS after_race_ns,
 json_extract(a.report,'$.timing_basis') AS timing_basis,
 0 AS operator_timing_reviewed,(l.race_start_ns!=e.start_ns) AS stale_race_start
 FROM passing_timing_links l JOIN wheel_analyses a ON a.id=l.analysis_id JOIN race_events e ON e.id=l.event_id;
'''


def direction(entry,width):
    points=sorted(entry.get('points',[]),key=lambda p:p['ordinal'])
    if len(points)<2:return 0
    dx=(points[-1]['box'][0]+points[-1]['box'][2]-points[0]['box'][0]-points[0]['box'][2])/2
    return (1 if dx>0 else -1) if abs(dx)>=width*.02 else 0


def box_at(entry,ordinal):
    points=sorted(entry.get('points',[]),key=lambda p:p['ordinal'])
    if not points:return entry.get('box')
    a=next((p for p in reversed(points) if p['ordinal']<=ordinal),points[0])
    b=next((p for p in points if p['ordinal']>=ordinal),points[-1])
    if a['ordinal']==b['ordinal']:
        if ordinal<a['ordinal'] and len(points)>1:a,b=points[:2]
        elif ordinal>b['ordinal'] and len(points)>1:a,b=points[-2:]
        else:return a['box']
    fraction=(ordinal-a['ordinal'])/(b['ordinal']-a['ordinal'])
    return [x+(y-x)*fraction for x,y in zip(a['box'],b['box'])]


def detect(image,box,travel):
    import cv2,numpy as np
    from itertools import combinations
    if not travel or box is None:return None
    height,width=image.shape[:2];x0,y0,x1,y1=box;bw=x1-x0;bh=y1-y0
    if bw<60 or bh<60:return None
    left=max(0,int(x0));top=max(0,int(y0+bh*.35));right=min(width,int(x1));bottom=min(height,int(y1))
    if right-left<60 or bottom-top<30:return None
    scale=min(.35,384/(right-left))
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    crop=cv2.resize(gray[top:bottom,left:right],None,fx=scale,fy=scale)
    crop=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(crop),(5,5),1.3)
    circles=cv2.HoughCircles(crop,cv2.HOUGH_GRADIENT,dp=1.2,minDist=max(12,bw*scale*.25),param1=90,param2=20,
        minRadius=max(6,int(max(bh*.10,bw*.08)*scale)),maxRadius=max(7,int(min(bh*.45,bw*.34)*scale)))
    if circles is None:return None
    valid=[]
    for sx,sy,sr in circles[0]:
        x,y,r=float(sx/scale+left),float(sy/scale+top),float(sr/scale)
        if not max(bh*.12,bw*.10)<=r<=min(bh*.42,bw*.32) or not y0+bh*.45<=y<=y1-bh*.10:continue
        if x-r<x0-bw*.06 or x+r>x1+bw*.06:continue
        valid.append((x,y,r))
    pairs=[]
    for a,b in combinations(valid,2):
        if not .75<=a[2]/b[2]<=1.35 or not bw*.35<=abs(a[0]-b[0])<=bw*.8:continue
        if abs(a[1]-b[1])>min(a[2],b[2])*.25:continue
        score=abs(a[1]-b[1])/min(a[2],b[2])+abs(a[2]-b[2])/min(a[2],b[2])
        pairs.append((score,sorted((a,b))))
    if not pairs:return None
    pairs.sort(key=lambda p:p[0]);pair=pairs[0][1]
    if len(pairs)>1 and pairs[1][0]-pairs[0][0]<.03:
        other=pairs[1][1][0 if travel<0 else 1]
        chosen=pair[0 if travel<0 else 1]
        if abs(other[0]-chosen[0])>chosen[2]*.5:return None
    return refine(gray,pair,travel)


def refine(gray,pair,travel):
    import cv2,numpy as np
    height,width=gray.shape[:2];x,y,r=pair[0 if travel<0 else 1]
    gray=cv2.GaussianBlur(gray,(5,5),1)
    angles=np.linspace((math.pi if travel<0 else 0)-.8,(math.pi if travel<0 else 0)+.8,181)
    cx,cy=np.cos(angles),np.sin(angles);radii=np.arange(round(r*.95),round(r*1.4)+1)
    strengths=[]
    for radius in radii:
        ix=np.rint(x+(radius-5)*cx).astype(int);iy=np.rint(y+(radius-5)*cy).astype(int)
        ox=np.rint(x+(radius+5)*cx).astype(int);oy=np.rint(y+(radius+5)*cy).astype(int)
        valid=(ix>=0)&(ix<width)&(ox>=0)&(ox<width)&(iy>=0)&(iy<height)&(oy>=0)&(oy<height)
        if valid.sum()<90:strengths.append(-1);continue
        inside=gray[iy[valid],ix[valid]].astype(float);outside=gray[oy[valid],ox[valid]].astype(float)
        strengths.append(float(np.mean(np.clip(outside-inside,-50,50))))
    quality=max(strengths)
    if quality<8:return None
    outer=float(radii[int(np.argmax(strengths))])
    return dict(center=[x,y],radius=outer,leading_x=x+travel*outer,gradient_score=quality,pair=pair)


def track(image,previous,prior,ordinal,travel):
    """Re-detect both wheel circles near their predicted locations, never fill
    a gap merely by extrapolating the tyre edge."""
    import cv2,numpy as np
    if prior is None or ordinal-previous['ordinal']>3:return None
    dt=previous['ordinal']-prior['ordinal']
    if dt<=0:return None
    steps=ordinal-previous['ordinal']
    dx=(previous['center'][0]-prior['center'][0])/dt*steps
    dy=(previous['center'][1]-prior['center'][1])/dt*steps
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);height,width=gray.shape
    pair=[]
    for x,y,r in previous['pair']:
        px,py=x+dx,y+dy;left=max(0,int(px-r*1.6));right=min(width,int(px+r*1.6));top=max(0,int(py-r*1.6));bottom=min(height,int(py+r*1.6))
        if right-left<30 or bottom-top<30:return None
        scale=min(.4,240/(right-left))
        crop=cv2.resize(gray[top:bottom,left:right],None,fx=scale,fy=scale)
        crop=cv2.GaussianBlur(cv2.createCLAHE(2,(8,8)).apply(crop),(5,5),1.2)
        circles=cv2.HoughCircles(crop,cv2.HOUGH_GRADIENT,dp=1.2,minDist=max(8,r*scale*.6),param1=90,param2=18,
            minRadius=max(5,int(r*.8*scale)),maxRadius=max(6,int(r*1.2*scale)))
        if circles is None:return None
        options=[(float(a/scale+left),float(b/scale+top),float(c/scale)) for a,b,c in circles[0]]
        chosen=min(options,key=lambda p:((p[0]-px)/r)**2+((p[1]-py)/r)**2+((p[2]-r)/r)**2)
        if abs(chosen[0]-px)>r*.5 or abs(chosen[1]-py)>r*.4:return None
        pair.append(chosen)
    pair.sort()
    if not .75<=pair[0][2]/pair[1][2]<=1.35 or abs(pair[0][1]-pair[1][1])>min(pair[0][2],pair[1][2])*.3:return None
    result=refine(gray,pair,travel)
    if result:result['tracking']='predicted region; both wheel circles re-detected'
    return result


def associate_geometry(entry,passages,width):
    """Attach geometry to this source-frame anchor without changing its identity.

    A repeated bib on a later encounter is not a candidate. Ambiguous simultaneous
    bodies remain unresolved rather than borrowing another rider's wheel.
    """
    from .bike_index import overlap,primary_stops
    ordinal=entry['ordinal'];anchor=entry.get('box')
    candidates=[p for p in passages if direction(p,width) and p['first_ordinal']-3<=ordinal<=p['last_ordinal']+3]
    if anchor:
        ranked=sorted(((overlap(anchor,box_at(p,ordinal)),p) for p in candidates),key=lambda pair:-pair[0])
        if not ranked or ranked[0][0]<.05:return None
        if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.1:return None
        return ranked[0][1]
    candidates=primary_stops(candidates)
    if len(candidates)==1:return candidates[0]
    if not candidates:return None
    ranked=sorted(candidates,key=lambda p:abs(p['ordinal']-ordinal))
    if abs(ranked[1]['ordinal']-ordinal)-abs(ranked[0]['ordinal']-ordinal)>3:return ranked[0]
    # Motion can split a rider's head and bicycle into separate regions. Only
    # prefer a dominant body when it is substantially larger than the alternative.
    def area(p):
        a,b,c,d=box_at(p,ordinal);return max(0,c-a)*max(0,d-b)
    ranked=sorted(candidates,key=area,reverse=True)
    return ranked[0] if area(ranked[0])>area(ranked[1])*2 else None


def resolve_geometry(c,clip,entry,index,width):
    if direction(entry,width):return entry,dict(source='supplied track')
    from . import bike_index,motion_position
    row=bike_index.completed_analysis(c,clip)
    report=json.loads(row['report']) if row else {}
    candidate=associate_geometry(entry,report.get('passages',[]),width)
    source='cached motion/bicycle track'
    if candidate is None:
        frame=next((r for r in index if r['ordinal']==entry['ordinal']),None)
        if frame is None:return entry,dict(source='unresolved',reason='review frame missing')
        report=motion_position.scan(c,clip,index,frame['received_ns'])
        candidate=associate_geometry(entry,report.get('passages',[]),width)
        source='source-frame motion scan'
    if candidate is None:return entry,dict(source='unresolved',reason='no unambiguous moving bike at review frame')
    resolved=dict(entry,points=candidate['points'],box=candidate.get('box'),
        first_ordinal=candidate['first_ordinal'],last_ordinal=candidate['last_ordinal'])
    return resolved,dict(source=source,track_key=candidate['key'],anchor_ordinal=entry['ordinal'])


def passing_context(model,clip,entry,cell_key=None):
    """Require matching evidence keys, never attach by clip or bib alone."""
    keys=(set(entry.get('source_keys',[]))|{entry['key'],entry.get('visual_key')})-{None}
    matches=[]
    for cell in model['cells']:
        if cell['state']=='ignored' or cell_key is not None and cell['cell_key']!=cell_key:continue
        for row in cell['captures']:
            row_keys=(set(row.get('source_keys',[]))|{row.get('key'),row.get('physical_key')})-{None}
            if row['clip_id']==clip and keys & row_keys:
                matches.append((cell,row));break
    if len(matches)!=1:return None
    cell,row=matches[0]
    return dict(event_id=model['event']['id'],cell_key=cell['cell_key'],bib=cell['bib'],offset=model['offset'],race_start_ns=model['event']['start_ns'],confirmed=bool(row.get('confirmed')))


def link_passing(c,analysis_id,context):
    """Persist a candidate association, never a CrossMgr read or timing approval.

    Caller owns the transaction. Clock/identity snapshots are retained as history.
    The view derives nanosecond race time as soon as the worker saves its report.
    """
    if not context:return None
    event=c.execute('SELECT * FROM race_events WHERE id=?',(context['event_id'],)).fetchone()
    analysis=c.execute('SELECT clip_id,parameters FROM wheel_analyses WHERE id=?',(analysis_id,)).fetchone()
    if event is None or analysis is None:raise ValueError('Timing association no longer exists')
    if context.get('race_start_ns',event['start_ns'])!=event['start_ns']:raise ValueError('Race start changed; refresh passings before linking timing')
    offset=float(context.get('offset',0))
    if not math.isfinite(offset) or abs(offset)>86400:raise ValueError('Invalid camera clock offset')
    cell=str(context['cell_key']);bib=str(context['bib']);passing=None
    if cell.startswith('cm:'):
        passing=int(cell[3:])
        row=c.execute('SELECT p.bib,s.event_id FROM race_passings p JOIN race_sources s ON s.id=p.source_id WHERE p.id=?',(passing,)).fetchone()
        if row is None or row['event_id']!=event['id'] or row['bib']!=bib:raise ValueError('Passing does not belong to this event and bib')
    entry=json.loads(analysis['parameters'])['entry'];visual=entry.get('visual_key',entry['key'])
    values=(analysis_id,event['id'],passing,cell,analysis['clip_id'],visual,bib,event['start_ns'],round(offset*1e9),int(bool(context.get('confirmed'))))
    c.execute('INSERT OR IGNORE INTO passing_timing_links(analysis_id,event_id,passing_id,cell_key,clip_id,visual_key,bib,race_start_ns,camera_minus_cm_ns,identity_confirmed_at_link,linked_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(*values,time.time_ns()))
    return c.execute('SELECT id FROM passing_timing_links WHERE analysis_id=? AND event_id=? AND cell_key=? AND visual_key=? AND bib=? AND race_start_ns=? AND camera_minus_cm_ns=? AND identity_confirmed_at_link=?',
        (analysis_id,event['id'],cell,visual,bib,event['start_ns'],round(offset*1e9),int(bool(context.get('confirmed'))))).fetchone()[0]


def linked_results(c,event_id):
    return [dict(r) for r in c.execute('SELECT * FROM passing_timing_results WHERE event_id=? ORDER BY id DESC',(event_id,))]


def start(path,clip,entry,line=.5,force=False,context=None):
    from .service import launch_worker,neural_runtime
    import importlib.util,sys
    runtime=neural_runtime()
    refine_device=runtime[1] if runtime and (runtime[1].startswith('gpu') or force) else None
    python=runtime[0] if refine_device else sys.executable if importlib.util.find_spec('cv2') else (runtime or (None,None))[0]
    if python is None:raise ValueError('OpenCV is needed for front-wheel analysis')
    if not math.isfinite(line) or not 0<line<1:raise ValueError('Finish line must be inside the image')
    entry={k:entry[k] for k in ('key','visual_key','first_ordinal','last_ordinal','ordinal','box','points') if k in entry}
    params=dict(entry=entry,line_x=line,version=6,detector_device=refine_device)
    c=storage.connect(path)
    try:
        params['models_dir']=storage.read_setting(c,'neural_models_dir',str(Path.home()/'.paddlex/official_models'))
        if not (Path(params['models_dir'])/'PicoDet-S').is_dir() and (Path.home()/'.paddlex/official_models/PicoDet-S').is_dir():
            params['models_dir']=str(Path.home()/'.paddlex/official_models')
        key=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT id,state FROM wheel_analyses WHERE clip_id=? AND subject_key=? ORDER BY id DESC LIMIT 1',(clip,key)).fetchone()
        if old and not force and old['state'] not in ('queued','running','error'):
            link_passing(c,old['id'],context);c.commit();return old['id']
        for active in c.execute("SELECT id,pid,updated_ns FROM wheel_analyses WHERE state IN ('queued','running')").fetchall():
            alive=True
            if active['pid']:
                try:os.kill(active['pid'],0)
                except ProcessLookupError:alive=False
            if alive and time.time_ns()-active['updated_ns']<120_000_000_000:
                if old and old['id']==active['id']:link_passing(c,active['id'],context)
                c.commit();return active['id'] if old and old['id']==active['id'] else None
            c.execute("UPDATE wheel_analyses SET state='error',error='Analysis worker stopped' WHERE id=?",(active['id'],))
        now=time.time_ns()
        with c:
            ident=c.execute("INSERT INTO wheel_analyses(clip_id,subject_key,created_ns,updated_ns,state,parameters) VALUES(?,?,?,?,'queued',?)",(clip,key,now,now,json.dumps(params))).lastrowid
            link_passing(c,ident,context)
        try:launch_worker([python,'-m','racevideo.wheel_timing','--db',str(Path(path).resolve()),'--analysis',str(ident)],path,'wheels-'+str(ident),Path(path).with_suffix('.wheels.log'),cwd=Path(__file__).resolve().parents[1])
        except Exception as exc:
            with c:c.execute("UPDATE wheel_analyses SET state='error',error=? WHERE id=?",(str(exc),ident))
            raise
        return ident
    finally:c.close()


def read(c,ident):
    row=c.execute('SELECT id,clip_id,state,report,error FROM wheel_analyses WHERE id=?',(ident,)).fetchone()
    return dict(row,report=json.loads(row['report'])) if row else None


def active(c):
    row=c.execute("SELECT id FROM wheel_analyses WHERE state IN ('queued','running') ORDER BY id LIMIT 1").fetchone()
    return read(c,row['id']) if row else None


def progress_label(result):
    if not result:return 'wheel worker finishing; retrying'
    progress=result.get('report',{}).get('progress',{})
    text=f"clip #{result['clip_id']} · "+progress.get('stage',result.get('state','working'))
    if progress.get('total') is not None:text+=f" · {progress.get('processed',0)}/{progress['total']} frames"
    return text


def passing_candidate(report,bib=None,event=None,offset=0):
    """Future handoff contract; this is not an operator-approved timing read."""
    crossing=report.get('crossing')
    if not crossing:return None
    estimate=crossing.get('estimated_received_ns')
    elapsed=estimate-round(offset*1e9)-event['start_ns'] if estimate is not None and event else None
    return dict(bib=bib,event_id=event.get('id') if event else None,
        event_start_ns=event['start_ns'] if event else None,camera_minus_cm_ns=round(offset*1e9),
        camera_estimate_ns=estimate,race_elapsed_ns=elapsed,
        before_ordinal=crossing['before_ordinal'],first_touch_or_past_ordinal=crossing['first_observed_after_ordinal'],
        before_camera_ns=crossing['before_received_ns'],after_camera_ns=crossing['after_received_ns'],
        bracket_ns=crossing['bracket_monotonic_ns'],method=crossing['status'],line_x=report['line_x'],
        operator_reviewed=False,calibration='camera exposure/USB offset uncalibrated',provisional=True)


def run(path,ident):
    os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['DISABLE_MODEL_SOURCE_CHECK']='True';os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:2]))
    import cv2,numpy as np
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    c=storage.connect(path)
    try:
        row=c.execute('SELECT * FROM wheel_analyses WHERE id=?',(ident,)).fetchone();clip=row['clip_id'];params=json.loads(row['parameters']);entry=params['entry']
        with c:c.execute("UPDATE wheel_analyses SET state='running',pid=?,updated_ns=? WHERE id=?",(os.getpid(),time.time_ns(),ident))
        started=time.monotonic();last_progress=0;last_stage=None
        def progress(stage,processed=0,total=None,force=False):
            nonlocal last_progress,last_stage
            now=time.monotonic()
            if not force and stage==last_stage and now-last_progress<1:return
            last_progress,last_stage=now,stage
            value=dict(progress=dict(stage=stage,processed=processed,total=total,elapsed_seconds=round(now-started,1)))
            with c:c.execute('UPDATE wheel_analyses SET report=?,updated_ns=? WHERE id=?',(json.dumps(value),time.time_ns(),ident))
        progress('Finding motion track',force=True)
        meta=c.execute('SELECT width,height FROM clips WHERE id=?',(clip,)).fetchone();w,h=meta
        index=storage.frame_index(c,clip)
        entry,geometry=resolve_geometry(c,clip,entry,index,w)
        travel=direction(entry,w);pad=max(5,round((entry['last_ordinal']-entry['first_ordinal'])*.3))
        frames=[r for r in index if entry['first_ordinal']-pad<=r['ordinal']<=entry['last_ordinal']+pad]
        truncated=len(frames)>300
        if truncated:frames=sorted(frames,key=lambda r:abs(r['ordinal']-entry['ordinal']))[:300];frames.sort(key=lambda r:r['ordinal'])
        samples=[];previous=prior=None
        model=None;detector_error=None
        def bicycle_region(image,expected):
            nonlocal model
            if not params.get('detector_device'):return None
            if model is None:
                progress('Loading bicycle detector',i,len(frames),force=True)
                from paddlex import create_model
                from paddlex.inference.utils.pp_option import PaddlePredictorOption
                device=params['detector_device']
                model=create_model('PicoDet-S',model_dir=str(Path(params['models_dir'])/'PicoDet-S'),device=device,
                    pp_option=PaddlePredictorOption(cpu_threads=1,run_mode='paddle' if device.startswith('gpu') else 'mkldnn'))
                progress('Measuring wheels',i,len(frames),force=True)
            from .neural_ocr import result_dict
            from .bike_index import overlap
            candidates=[]
            for box in result_dict(list(model.predict(input=image,threshold=.4))[0]).get('boxes',[]):
                if box['label']!='bicycle':continue
                coords=list(map(float,box['coordinate']));iou=overlap(coords,expected)
                cx,cy=(coords[0]+coords[2])/2,(coords[1]+coords[3])/2
                # Motion regions can alternate between rider and bicycle. Allow a
                # vertically displaced bicycle, retaining overlap and ambiguity checks.
                margin=max(expected[2]-expected[0],expected[3]-expected[1])
                expanded=[expected[0],expected[1]-margin,expected[2],expected[3]+margin]
                score=overlap(coords,expanded)
                if score>.15 and expanded[0]<=cx<=expanded[2] and expanded[1]<=cy<=expanded[3]:candidates.append((score,coords))
            candidates.sort(key=lambda x:-x[0])
            if not candidates:return None
            if len(candidates)>1 and candidates[0][0]-candidates[1][0]<.05:return None
            return candidates[0][1]
        if travel:
            for i,frame in enumerate(frames):
                progress('Measuring wheels',i,len(frames))
                image=cv2.imdecode(np.frombuffer(storage.read_frame(c,clip,frame['ordinal']),np.uint8),cv2.IMREAD_COLOR)
                wheel=detect(image,box_at(entry,frame['ordinal']),travel)
                if wheel is None and previous:wheel=track(image,previous,prior,frame['ordinal'],travel)
                if wheel is None and params.get('detector_device'):
                    try:region=bicycle_region(image,box_at(entry,frame['ordinal']))
                    except Exception as exc:
                        detector_error=str(exc);params['detector_device']=None;region=None
                    if region:
                        wheel=detect(image,region,travel)
                        if wheel:wheel['region_refined_by']='PicoDet-S bicycle'
                if wheel:
                    if previous and frame['ordinal']-previous['ordinal']<=2:
                        if abs(wheel['radius']/previous['radius']-1)>.3 or (wheel['leading_x']-previous['leading_x'])*travel < -previous['radius']*.25:continue
                    sample=dict(frame,**wheel,gap_px=(params['line_x']*w-wheel['leading_x'])*travel)
                    samples.append(sample);prior,previous=previous,sample
                progress('Measuring wheels',i+1,len(frames))
        crossing=first_crossing(samples) if len(samples)>=2 else None
        report=dict(source='wheel-circle-pair/tyre-edge',algorithm_version=6,detector_device=params.get('detector_device'),detector_error=detector_error,geometry=geometry,experimental=True,direction=travel,line_x=params['line_x'],
            width=w,height=h,samples=samples,crossing=crossing,truncated=truncated,
            progress=dict(stage='Complete',processed=len(frames) if travel else 0,total=len(frames),elapsed_seconds=round(time.monotonic()-started,1)),
            status='crossing_estimate' if crossing else 'wheel_track_only' if samples else 'wheel_unresolved',
            timing_basis='host receipt clock; camera exposure/USB offset uncalibrated',identity_review_separate=True)
        with c:c.execute("UPDATE wheel_analyses SET state='complete',report=?,updated_ns=? WHERE id=?",(json.dumps(report),time.time_ns(),ident))
    except Exception as exc:
        with c:c.execute("UPDATE wheel_analyses SET state='error',error=?,updated_ns=? WHERE id=?",(str(exc),time.time_ns(),ident))
        raise
    finally:c.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--analysis',type=int,required=True);a=p.parse_args();run(a.db,a.analysis)
