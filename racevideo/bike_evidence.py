"""Join physical passage candidates to bib evidence without reading JPEGs."""
import json


def collect(connection,start,end,clip_id=None,event_id=None):
    from .passings import visual_evidence
    from .bike_index import navigation
    evidence=visual_evidence(connection,start,end,clip_id=clip_id)
    by_key={v['key']:v for v in evidence};used=set();result=[]
    clips=connection.execute('''SELECT id,width,height FROM clips WHERE started_ns<=? AND ended_ns>=?
        AND (? IS NULL OR id=?) ORDER BY started_ns,id''',(end,start,clip_id,clip_id)).fetchall()
    reviews=connection.execute('SELECT * FROM race_visual_reviews WHERE event_id=?',(event_id,)).fetchall() if event_id else []
    indexed=0
    for clip in clips:
        if not connection.execute("SELECT 1 FROM bike_analyses WHERE clip_id=? AND state='complete' LIMIT 1",(clip['id'],)).fetchone():continue
        nav=navigation(connection,clip['id'])
        if nav['source'] not in ('detector','motion'):continue
        indexed+=1
        for entry in nav['passages']:
            physical=entry.get('visual_key')
            if not physical:continue  # Independent manual entries are retained below.
            sources=set(entry['source_keys'])
            # Keep a human correction associated even if geometry is ambiguous.
            linked=[r for r in reviews if r['clip_id']==clip['id'] and physical in json.loads(r['source_keys'])]
            for r in linked:
                if r['bib_review_id']:sources.add('review:'+str(r['bib_review_id']))
            rows=[by_key[k] for k in sorted(sources) if k in by_key]
            used.update(v['key'] for v in rows)
            corrected={r['bib_review_id'] for r in linked if r['action']!='ignored'}
            if corrected:rows=[v for v in rows if v['key'] in {'review:'+str(i) for i in corrected}]
            frame=connection.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip['id'],entry['ordinal'])).fetchone()
            if frame is None or not start<=frame[0]<=end:continue
            box=entry.get('box');normalized=[box[0]/clip['width'],box[1]/clip['height'],box[2]/clip['width'],box[3]/clip['height']] if box else None
            common=dict(physical_key=physical,source_keys=sorted(sources|{physical}),
                bike_box=normalized,points=entry.get('points',[]),width=clip['width'],height=clip['height'],
                passage_ns=frame[0],passage_ordinal=entry['ordinal'],navigation_primary=entry.get('navigation_primary',False),passing_order=entry.get('passing_order'),uncertain=entry.get('uncertain',False))
            if not rows:
                rows=[dict(key=physical,number='?',first_ns=frame[0],last_ns=frame[0],ordinal=entry['ordinal'],
                    clip_id=clip['id'],confirmed=False,confidence=None,status='bike candidate',run_id=None,
                    encounter_key=physical,decision=None)]
            for row in rows:
                fields={k:v for k,v in common.items() if k!='passing_order'}
                fields['association_inferred']=not any(r['action']!='ignored' and 'review:'+str(r['bib_review_id'])==row['key'] for r in linked)
                if row['confirmed']:fields['bike_box']=row.get('bike_box')
                result.append(dict(row,**fields,
                    passing_order=row.get('passing_order') or common['passing_order']))
    result.extend(v for v in evidence if v['key'] not in used)
    # Association/filtering is heuristic. Never lose an accepted human row here;
    # the event decision resolver, rather than geometry, determines suppression.
    present={v['key'] for v in result}
    for value in evidence:
        if value['confirmed'] and value['key'] not in present:
            result.append(dict(value,recovered_manual=True));present.add(value['key'])
    grouped={}
    for value in result:
        if value['confirmed'] and value.get('physical_key'):grouped.setdefault(value['physical_key'],[]).append(value)
    for values in grouped.values():
        if len({v['number'] for v in values})>1:
            for value in values:
                if value.get('association_inferred'):
                    value['inferred_physical_key']=value.pop('physical_key')
                    value['association_reconciled']=True
    return result,dict(indexed=indexed,total=len(clips),unindexed=len(clips)-indexed)
