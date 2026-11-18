"""Reversible display grouping; a proposed association never confirms identity."""
import math


def same_subject(candidate,confirmed):
    if candidate['clip_id']!=confirmed['clip_id']:return False
    if candidate.get('key') and candidate['key']==confirmed.get('key'):return True
    if candidate.get('physical_key') and confirmed.get('physical_key'):return candidate['physical_key']==confirmed['physical_key']
    return bool(candidate.get('encounter_key') and candidate['encounter_key']==confirmed.get('encounter_key') and
        candidate.get('run_id')==confirmed.get('run_id'))


def order_shared_suggestions(cells):
    """Offer distinct chronological subjects for an equal-sized shared group.

    This orders review choices only. Counts, identity and matching state remain
    untouched. Extra/uncertain subjects or simultaneous stops stay ambiguous.
    """
    expected={};visual={}
    for cell in cells:
        if not cell['captures'] or cell['confirmed']:continue
        candidate=cell['captures'][0];key=(cell['column'],candidate['clip_id'])
        if cell['origin']=='CrossMgr' and cell.get('rider_lap') is not None and not cell['visual_count'] and candidate.get('number') in (None,'?'):
            expected.setdefault(key,[]).append(cell)
        elif cell['origin']=='Visual only' and cell['bib']=='?' and len(cell['captures'])==1:
            visual.setdefault(key,[]).append(cell)
    for key,parents in expected.items():
        subjects=visual.get(key,[])
        if len(parents)<2 or len(parents)!=len(subjects):continue
        if any(not c['captures'][0].get('physical_key') or not c['captures'][0].get('navigation_primary') or c['captures'][0].get('uncertain',True) or c['captures'][0].get('in_finish_zone') is False for c in subjects):continue
        parents=sorted(parents,key=lambda c:c['at_ns'])
        subjects=sorted(subjects,key=lambda c:c['at_ns'])
        if len({c['at_ns'] for c in parents})!=len(parents) or len({c['at_ns'] for c in subjects})!=len(subjects):continue
        choices=[]
        for parent,subject in zip(parents,subjects):
            index=next((i for i,c in enumerate(parent['captures']) if same_subject(c,subject['captures'][0])),None)
            if index is None:break
            choices.append((parent,index))
        if len(choices)!=len(parents):continue
        for parent,index in choices:
            parent['captures'].insert(0,parent['captures'].pop(index))
            parent['suggestion_ordered']=True


def group(cells,seconds=30):
    if not math.isfinite(seconds) or not 0<=seconds<=120:raise ValueError('Duplicate grouping window must be 0–120 seconds')
    if not seconds:return cells,[]
    secondary=[];main=[]
    for cell in cells:
        if cell['origin']=='Visual only' and not cell['confirmed'] and cell['captures'] and all(v.get('review_secondary') for v in cell['captures']):secondary.append(cell)
        else:main.append(cell)
    # These are detector observations, not additional race positions. Keep them
    # inspectable under a nearby stop, including named OCR on a weak track.
    deferred=[]
    for cell in secondary:
        clip=cell['captures'][0]['clip_id']
        anchors=[a for a in main if any(v['clip_id']==clip for v in a['captures'])]
        if not anchors:main.append(cell);continue
        anchor=min(anchors,key=lambda a:abs(a['at_ns']-cell['at_ns']))
        cell.update(grouped_under=anchor['cell_key'],group_reason='Weak or overlapping detector track; retained for inspection, not counted as another rider',
            group_delta_seconds=(cell['at_ns']-anchor['at_ns'])/1e9)
        anchor.setdefault('grouped_candidates',[]).append(cell);deferred.append(cell)
    cells=main
    order_shared_suggestions(cells)
    anchors=[c for c in cells if c['confirmed'] and c['origin']=='CrossMgr' and c.get('rider_lap') is not None]
    proposals={}
    for cell in cells:
        if cell['origin']!='CrossMgr' or cell.get('rider_lap') is None or cell['confirmed'] or cell['visual_count'] or not cell['captures']:continue
        candidate=cell['captures'][0]
        if not candidate.get('physical_key') or not candidate.get('navigation_primary') or candidate.get('uncertain',True) or candidate.get('in_finish_zone') is False:continue
        key=(candidate['clip_id'],candidate['physical_key'])
        proposals.setdefault(key,[]).append(cell)
    grouped=[];visible=[]
    for cell in cells:
        target=None;reason=None
        if not cell['confirmed']:
            for anchor in sorted(anchors,key=lambda a:abs(a['at_ns']-cell['at_ns'])):
                if cell['bib']!=anchor['bib'] or cell['column']!=anchor['column'] or abs(cell['at_ns']-anchor['at_ns'])>seconds*1e9:continue
                if cell['origin']=='Visual only' and cell['captures']:
                    known=anchor['captures'][:anchor['visual_count']]
                    if all(any(same_subject(v,k) for k in known) for v in cell['captures']):
                        target=anchor;reason='Unconfirmed OCR candidate for the same observed subject';break
            if target is None and cell['origin']=='Visual only' and (cell['bib']=='?' or cell.get('state')=='extra' and cell.get('outside_roster_only',True)) and cell['captures']:
                candidate=cell['captures'][0]
                choices=proposals.get((candidate['clip_id'],candidate.get('physical_key')),[]) if all(same_subject(v,candidate) for v in cell['captures']) else []
                if len(choices)==1:
                    anchor=choices[0]
                    if anchor['column']==cell['column'] and abs(anchor['at_ns']-cell['at_ns'])<=seconds*1e9:
                        target=anchor;reason='Suggested visual candidate already offered by this CrossMgr row; bib remains unconfirmed'
                        anchor['suggested_visual']=True
                        if cell['bib']!='?':
                            anchor['suggested_ocr_conflicts']=sorted(set(anchor.get('suggested_ocr_conflicts',[])+cell.get('alternative_bibs',[cell['bib']])))
                            reason=f"OCR {cell['bib']} is outside the event roster on the physical track already offered for {anchor['bib']}; identity remains unconfirmed"
        if target is None:visible.append(cell);continue
        cell['grouped_under']=target['cell_key'];cell['group_reason']=reason
        cell['group_delta_seconds']=(cell['at_ns']-target['at_ns'])/1e9
        target.setdefault('grouped_candidates',[]).append(cell);grouped.append(cell)
    return visible,grouped+deferred
