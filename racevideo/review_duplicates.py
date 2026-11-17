"""Reversible display grouping; a proposed association never confirms identity."""
import math


def same_subject(candidate,confirmed):
    if candidate['clip_id']!=confirmed['clip_id']:return False
    if candidate.get('key') and candidate['key']==confirmed.get('key'):return True
    if candidate.get('physical_key') and confirmed.get('physical_key'):return candidate['physical_key']==confirmed['physical_key']
    return bool(candidate.get('encounter_key') and candidate['encounter_key']==confirmed.get('encounter_key') and
        candidate.get('run_id')==confirmed.get('run_id'))


def group(cells,seconds=30):
    if not math.isfinite(seconds) or not 0<=seconds<=120:raise ValueError('Duplicate grouping window must be 0–120 seconds')
    if not seconds:return cells,[]
    anchors=[c for c in cells if c['confirmed'] and c['origin']=='CrossMgr' and c.get('rider_lap') is not None]
    proposals={}
    for cell in cells:
        if cell['origin']!='CrossMgr' or cell.get('rider_lap') is None or cell['confirmed'] or cell['visual_count'] or not cell['captures']:continue
        candidate=cell['captures'][0]
        if not candidate.get('physical_key') or not candidate.get('navigation_primary') or candidate.get('uncertain',True):continue
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
            if target is None and cell['origin']=='Visual only' and cell['bib']=='?' and len(cell['captures'])==1:
                candidate=cell['captures'][0]
                choices=proposals.get((candidate['clip_id'],candidate.get('physical_key')),[])
                if len(choices)==1:
                    anchor=choices[0]
                    if anchor['column']==cell['column'] and abs(anchor['at_ns']-cell['at_ns'])<=seconds*1e9:
                        target=anchor;reason='Suggested visual candidate already offered by this CrossMgr row; bib remains unconfirmed'
                        anchor['suggested_visual']=True
        if target is None:visible.append(cell);continue
        cell['grouped_under']=target['cell_key'];cell['group_reason']=reason
        cell['group_delta_seconds']=(cell['at_ns']-target['at_ns'])/1e9
        target.setdefault('grouped_candidates',[]).append(cell);grouped.append(cell)
    return visible,grouped
