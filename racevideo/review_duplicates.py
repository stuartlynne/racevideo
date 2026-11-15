"""Reversible display grouping of possible duplicates around confirmed passings."""
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
        if target is None:visible.append(cell);continue
        cell['grouped_under']=target['cell_key'];cell['group_reason']=reason
        cell['group_delta_seconds']=(cell['at_ns']-target['at_ns'])/1e9
        target.setdefault('grouped_candidates',[]).append(cell);grouped.append(cell)
    return visible,grouped
