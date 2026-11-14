"""Read-only, category-aware analysis ordering. Priorities are never timing reads."""
import argparse,json,math,re
from . import storage


def order(tasks,*,selected_clip=None,quantum=5):
    """Finish groups rotate in blocks of five places; ordinary work is newest first.

    Rebuild from current facts after each bounded job. One clip can satisfy several
    finish tasks and is scheduled once at its highest applicable priority.
    """
    if not isinstance(quantum,int) or quantum<1:raise ValueError('Finish turn must be a positive number of places')
    def priority(task):
        if task['clip_id']==selected_clip:return (0,)
        finishes=task.get('finishes',[])
        if finishes:
            f=min(finishes,key=lambda f:((max(1,f['rank'])-1)//quantum,f['category_first_ns'],f['rank'],f['at_ns'],f['category'],f.get('distance_ns',0)))
            return (1,(max(1,f['rank'])-1)//quantum,f['category_first_ns'],f['rank'],f['at_ns'],f['category'],f.get('distance_ns',0),-task['seen_ns'],task['clip_id'])
        return (2,-task['seen_ns'],-task['clip_id'])
    return sorted(tasks,key=priority)


def finish_candidates(c,event_id):
    event=c.execute('SELECT * FROM race_events WHERE id=?',(event_id,)).fetchone()
    source=c.execute('SELECT payload FROM race_sources WHERE id=?',(event['current_source_id'],)).fetchone()
    payload=json.loads(source[0]);info=payload['inspect']['race'];race=payload['review']['race']
    state=info.get('state','finished' if info.get('finish_time') else 'running')
    finished=state=='finished';categories={r['name']:r for r in info.get('categories',[])}
    by_bib={}
    for row in race.get('rows',[]):by_bib.setdefault(str(row['bib']),[]).append(row)
    observed={}
    for row in c.execute('SELECT bib,at_ns,rider_lap FROM race_passings WHERE source_id=? ORDER BY at_ns',(event['current_source_id'],)):
        observed.setdefault(row['bib'],[]).append(dict(row))
    riders=[];wave_first={}
    for bib,rows in by_bib.items():
        waves=[r for r in rows if categories.get(r['category'],{}).get('wave')]
        if len(waves)!=1 or not observed.get(bib):continue
        wave=waves[0]
        if wave.get('status')!='Finisher':continue
        last=observed[bib][-1];lap=max((p['rider_lap'] or 0 for p in observed[bib]),default=0)
        target=categories[wave['category']].get('laps')
        reached=bool(target and lap>=target)
        if reached:last=next(p for p in observed[bib] if (p['rider_lap'] or 0)>=target)
        if reached:wave_first[wave['category']]=min(wave_first.get(wave['category'],last['at_ns']),last['at_ns'])
        riders.append((bib,rows,wave,last,lap,target,reached))
    groups={}
    for bib,rows,wave,last,lap,target,reached in riders:
        # In a running race Finisher status alone proves nothing. A real final
        # lap or observed post-leader crossing is required even for prioritizing.
        leader=wave_first.get(wave['category'])
        if not finished and not reached and not (leader is not None and last['at_ns']>=leader):continue
        components=[r for r in rows if not categories.get(r['category'],{}).get('wave')]
        for row in components or [wave]:
            if row.get('status')!='Finisher':continue
            position=re.match(r'^\s*(\d+)',str(row.get('position','')))
            groups.setdefault(row['category'],[]).append(dict(category=row['category'],bib=bib,at_ns=last['at_ns'],
                rank=int(position[1]) if position else None,target_laps=target,observed_lap=lap,
                wave=wave['category'],start_offset=wave.get('start_offset'),provisional=True))
    result=[]
    for name,rows in groups.items():
        rows.sort(key=lambda r:(r['rank'] is None,r['rank'] or 0,r['at_ns'],r['bib']))
        first=rows[0]['at_ns'] # Category leader's observed last crossing, not a lapped tail's earlier read.
        for i,row in enumerate(rows,1):
            row.update(rank=row['rank'] or i,category_first_ns=first);result.append(row)
    return dict(event_id=event_id,state=state,finishes=result)


def plan(c,event_id,clips,*,offset=0,selected_clip=None,tolerance=3):
    if not math.isfinite(offset) or abs(offset)>86400:raise ValueError('Invalid camera offset')
    if not math.isfinite(tolerance) or not 0<=tolerance<=60:raise ValueError('Invalid matching tolerance')
    facts=finish_candidates(c,event_id);shift=round(offset*1e9);margin=round(tolerance*1e9);tasks=[]
    for clip in clips:
        # Source timestamps are already on the race clock; category start
        # offsets must NOT be added again to CrossMgr's absolute passing times.
        matches=[dict(f,distance_ns=max(clip['started_ns']-shift-f['at_ns'],f['at_ns']-(clip['ended_ns']-shift),0)) for f in facts['finishes'] if clip['started_ns']-shift-margin<=f['at_ns']<=clip['ended_ns']-shift+margin]
        tasks.append(dict(clip_id=clip['id'],seen_ns=clip['ended_ns'],finishes=matches))
    return dict(event_id=event_id,state=facts['state'],tasks=order(tasks,selected_clip=selected_clip))


def pending(c,analysis_ids,event_id,offset=0):
    ids=list(analysis_ids)
    if not ids:return []
    slots=','.join('?' for _ in ids)
    rows=[dict(r) for r in c.execute('SELECT a.id AS analysis_id,c.* FROM bike_analyses a JOIN clips c ON c.id=a.clip_id WHERE a.state=\'queued\' AND a.id IN ('+slots+')',ids)]
    by_clip={r['id']:r['analysis_id'] for r in rows}
    return [by_clip[t['clip_id']] for t in plan(c,event_id,rows,offset=offset)['tasks']]


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--event',required=True,type=int);p.add_argument('--offset',default=0,type=float);a=p.parse_args()
    c=storage.connect(a.db,readonly=True);event=c.execute('SELECT start_ns,end_ns FROM race_events WHERE id=?',(a.event,)).fetchone();shift=round(a.offset*1e9)
    clips=[dict(r) for r in c.execute('SELECT id,started_ns,ended_ns FROM clips WHERE started_ns<=? AND ended_ns>=?',(event['end_ns']+shift,event['start_ns']+shift))]
    print(json.dumps(plan(c,a.event,clips,offset=a.offset),indent=2));c.close()
