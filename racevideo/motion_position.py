"""CPU-only, bounded motion preview for unindexed passing review."""
import time
from PIL import ImageChops
from . import storage
from .review_position import small,subjects


def scan(c,clip,index,target_ns,cancel=lambda:False):
    started=time.perf_counter();decoded={}
    meta=c.execute('SELECT width,height FROM clips WHERE id=?',(clip,)).fetchone()
    if not index or meta is None:return dict(source='motion',passages=[],decoded_frames=0,milliseconds=0)
    def frame(i):
        if i not in decoded:decoded[i]=small(storage.read_frame(c,clip,index[i]['ordinal']))
        return decoded[i]
    duration=(index[-1]['monotonic_ns']-index[0]['monotonic_ns'])/1e9
    partial=duration>12
    target=min(range(len(index)),key=lambda i:abs(index[i]['received_ns']-target_ns))
    indices=list(range(len(index)))
    if partial:indices=[i for i,r in enumerate(index) if abs(r['monotonic_ns']-index[target]['monotonic_ns'])<=5_000_000_000]
    stride=max(1,(len(indices)+47)//48);samples=indices[::stride]
    if indices[-1] not in samples:samples.append(indices[-1])
    if cancel():return dict(source='motion',passages=[],cancelled=True)
    a,b,d=(frame(i) for i in (0,len(index)//2,len(index)-1))
    # Median of three pixels removes a rider present in the first frame when
    # the other reference images show the background. No extra dependency.
    background=ImageChops.lighter(ImageChops.darker(a,b),ImageChops.darker(ImageChops.lighter(a,b),d))
    detected={}
    def boxes_at(i):
        if i not in detected:detected[i]=subjects(frame(i),background)
        return detected[i]
    tracks=[];active=[]
    gap=max(500_000_000,min(1_000_000_000,round(duration/max(1,len(samples))*1.6e9)))
    for i in samples:
        if cancel():return dict(source='motion',passages=[],cancelled=True)
        stamp=index[i]['monotonic_ns'];boxes=boxes_at(i)[:8]
        active=[t for t in active if stamp-t[-1]['ns']<=gap]
        edges=[]
        for ti,track in enumerate(active):
            predicted=track[-1]['x']
            if len(track)>1:
                previous,last=track[-2:];elapsed=last['ns']-previous['ns']
                if elapsed>0:predicted+=(last['x']-previous['x'])*(stamp-last['ns'])/elapsed
            for bi,box in enumerate(boxes):
                distance=abs(box['x']-predicted)
                if distance<.35:edges.append((distance,ti,bi))
        used_tracks=set();used_boxes=set()
        for _,ti,bi in sorted(edges):
            if ti in used_tracks or bi in used_boxes:continue
            active[ti].append(dict(boxes[bi],i=i,ns=stamp));used_tracks.add(ti);used_boxes.add(bi)
        for bi,box in enumerate(boxes):
            if bi in used_boxes:continue
            track=[dict(box,i=i,ns=stamp)];tracks.append(track);active.append(track)
    passages=[];sw,sh=frame(0).size;w,h=meta
    def point(i,box):
        x0,y0,x1,y1=box['box']
        return dict(ordinal=index[i]['ordinal'],monotonic_ns=index[i]['monotonic_ns'],box=[x0*w/sw,y0*h/sh,x1*w/sw,y1*h/sh])
    for track in tracks:
        moved=max(p['x'] for p in track)-min(p['x'] for p in track)
        if len(track)>1 and moved<.035:continue
        best=min(track,key=lambda p:abs(p['x']-.5))
        if len(track)==1 and abs(best['x']-.5)>.2:continue
        points=[point(p['i'],p) for p in track]
        guess=best['i']
        for i in sorted({max(indices[0],min(indices[-1],guess+delta)) for delta in (-stride//2,-1,1,stride//2)}):
            if cancel():return dict(source='motion',passages=[],cancelled=True)
            if len(decoded)>=96:break
            boxes=boxes_at(i)
            candidate=min(boxes,key=lambda p:abs(p['x']-best['x']),default=None)
            if candidate and abs(candidate['x']-best['x'])<.25:
                points.append(point(i,candidate))
                if abs(candidate['x']-.5)<abs(best['x']-.5):best=dict(candidate,i=i)
        center=point(best['i'],best)
        passages.append(dict(key='motion:'+str(len(passages)+1),ordinal=center['ordinal'],box=center['box'],
            first_ordinal=min(p['ordinal'] for p in points),last_ordinal=max(p['ordinal'] for p in points),
            points=points,numbers=[],confirmed=False,uncertain=len(track)<2))
    passages.sort(key=lambda p:p['ordinal'])
    return dict(source='motion',policy='motion-preview-v2',approximate=True,partial=partial,passages=passages,
        start_ns=index[indices[0]]['received_ns'],end_ns=index[indices[-1]]['received_ns'],
        decoded_frames=len(decoded),milliseconds=(time.perf_counter()-started)*1000)


def locate(path,c,clip,index,hint,cancel=lambda:False):
    from . import bike_index
    started=time.perf_counter();target_ns=hint['target_ns'];decoded=0
    existing=bike_index.completed_analysis(c,clip)
    import json
    report=json.loads(existing['report']) if existing else None
    if not report or not report.get('passages'):
        empty=c.execute("SELECT report FROM bike_analyses WHERE clip_id=? AND state='inconclusive' ORDER BY id DESC LIMIT 1",(clip,)).fetchone()
        if empty and json.loads(empty['report']).get('policy') in ('motion-preview-v1','motion-preview-v2'):report=json.loads(empty['report'])
    usable=bool(report and (report.get('passages') or report.get('policy') in ('motion-preview-v1','motion-preview-v2')) and
        (not report.get('partial') or report.get('start_ns',0)<=target_ns<=report.get('end_ns',0)))
    if not usable:
        writer=storage.connect(path)
        try:
            with writer:analysis=writer.execute("INSERT INTO bike_analyses(clip_id,created_ns,state,report) VALUES(?,?,'running',?)",(clip,time.time_ns(),json.dumps(dict(source='motion')))).lastrowid
            try:
                report=scan(c,clip,index,target_ns,cancel);decoded=report.get('decoded_frames',0)
                if report.get('cancelled'):
                    with writer:writer.execute("UPDATE bike_analyses SET state='cancelled' WHERE id=?",(analysis,))
                    return dict(ordinal=0,method='cancelled',decoded_frames=decoded,milliseconds=(time.perf_counter()-started)*1000)
                # Do not supersede a neural detector which completed meanwhile.
                other=writer.execute("SELECT id,report FROM bike_analyses WHERE clip_id=? AND state='complete' AND id!=? ORDER BY id DESC LIMIT 1",(clip,analysis)).fetchone()
                if other:
                    other_report=json.loads(other['report'])
                    if not other_report.get('passages') or other['id']<analysis and other_report.get('source')=='motion':other=None
                if report['passages'] and not other:bike_index.save(writer,clip,report,analysis_id=analysis)
                else:
                    with writer:writer.execute("UPDATE bike_analyses SET state=?,report=? WHERE id=?",('superseded' if other else 'inconclusive',json.dumps(report),analysis))
            except Exception as exc:
                with writer:writer.execute("UPDATE bike_analyses SET state='error',error=? WHERE id=?",(str(exc),analysis))
                raise
        finally:writer.close()
    nav=bike_index.navigation(c,clip);stops=nav.get('stops',nav['passages'])
    by_ordinal={r['ordinal']:r for r in index};excluded=set(hint.get('exclude_keys',[]));number=hint.get('bib')
    def rank(entry):
        own=number and number in entry.get('numbers',[])
        other=bool(excluded.intersection(entry.get('source_keys',[])))
        return (0 if own else 2 if other else 1,entry.get('uncertain',False),abs(by_ordinal[entry['ordinal']]['received_ns']-target_ns))
    ignored=set(hint.get('ignore_keys',[]))
    protected=set(hint.get('protected_keys',[]))
    eligible=[e for e in stops if e['ordinal'] in by_ordinal and
        (protected.intersection(e.get('source_keys',[])) or e.get('visual_key') not in ignored and not ignored.intersection(e.get('source_keys',[]))) and (not report or not report.get('partial') or
        report['start_ns']<=by_ordinal[e['ordinal']]['received_ns']<=report['end_ns'])]
    entry=min(eligible,key=rank,default=None)
    result=dict(decoded_frames=decoded,milliseconds=(time.perf_counter()-started)*1000,navigation=nav)
    if entry:return dict(result,ordinal=entry['ordinal'],box=entry.get('box'),bike_key=entry['key'],physical_key=entry.get('visual_key'),method='moving-subject candidate near expected passing')
    return dict(result,ordinal=min(index,key=lambda r:abs(r['received_ns']-target_ns))['ordinal'] if index else 0,
        method='no moving subject found; expected-time fallback')
