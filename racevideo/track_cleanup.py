"""Separate physical-passage proposals from low-confidence detector debris.

Raw tracks and their keys remain available. No OCR strings or expected bibs
are used to decide which detection trajectories represent the main stops.
"""
import copy
import math


def area(box):
    return max(0,box[2]-box[0])*max(0,box[3]-box[1])


def containment(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/max(1,min(area(a),area(b)))


def agreement(first,second):
    """Simultaneous boxes must overlap; nearby timestamps alone are insufficient."""
    other={p['ordinal']:p['box'] for p in second['points']}
    hits=[]
    for point in first['points']:
        box=other.get(point['ordinal'])
        if box is None:continue
        a=point['box'];ax=(a[0]+a[2])/2;bx=(box[0]+box[2])/2
        hits.append(containment(a,box) if abs(ax-bx)<max(a[2]-a[0],box[2]-box[0])*.35 else 0)
    return sum(hits)/len(hits) if hits else 0


def crossing_or_approach(entry,line):
    xs=[(p['box'][0]+p['box'][2])/2 for p in entry['points']]
    if min(xs)<=line<=max(xs):return True
    # A real rider approaching the line at the end of a clip remains a stop.
    # Only tracks first observed moving away on the far side are exit fragments.
    return xs[-1]>xs[0] and max(xs)<line or xs[-1]<xs[0] and min(xs)>line


def clean(report,rows,width,height,track):
    report=copy.deepcopy(report)
    entries=report['passages']
    for entry in entries:
        if entry.get('raw_points'):
            entry['points']=entry.pop('raw_points')
            points=entry['points'];center=min(points,key=lambda p:abs((p['box'][0]+p['box'][2])/2-width/2))
            entry.update(first_ordinal=points[0]['ordinal'],last_ordinal=points[-1]['ordinal'],ordinal=center['ordinal'],box=center['box'])
        entry.pop('unresolved_interval',None)
    # A weak box may support an existing track later; it must not start dozens
    # of equally authoritative tracks on wheels, limbs or the background.
    filtered=[]
    for row in rows:
        objects=[]
        for obj in sorted(row.get('objects',[]),key=lambda o:-o['score']):
            box=obj['box']
            if obj['label']!='bicycle' or obj['score']<.4 or len(box)!=4 or not all(math.isfinite(v) for v in box):continue
            if any(containment(box,old['box'])>.8 for old in objects):continue
            objects.append(obj)
        filtered.append(dict(row,objects=objects))
    strong=track(filtered,width,height)['passages']
    # An exit fragment seen only beyond the line is not another crossing.
    # Keep it in raw evidence, but do not count it again as a primary stop.
    strong=[e for e in strong if len(e['points'])>=3 and not e['uncertain'] and crossing_or_approach(e,width/2)]
    for entry in entries:
        entry['review_secondary']=True
        entry.pop('grouped_track',None)
    selected=[];taken=set()
    for passage in sorted(strong,key=lambda e:-len(e['points'])):
        choices=[(agreement(passage,e),len(e['points']),e) for e in entries if e['key'] not in taken]
        score,_,entry=max(choices,key=lambda t:t[:2],default=(0,0,None))
        if entry is None or score<.5:continue
        taken.add(entry['key'])
        # Preserve the original key while replacing the noisy extrapolation
        # with the trajectory supported by confident detections.
        entry['raw_points']=entry['points']
        for key in ('points','box','first_ordinal','last_ordinal','ordinal','uncertain'):
            entry[key]=passage[key]
        entry['review_secondary']=False;selected.append(entry)
    # If a weak-only time interval has no sustained track, retain one visible
    # unresolved stop. It can be inspected without presenting every fragment
    # as an additional rider. Separated returns remain separate intervals.
    islands=[]
    for entry in sorted(entries,key=lambda e:e['first_ordinal']):
        if not islands or entry['first_ordinal']>islands[-1]['end']+3:
            islands.append(dict(end=entry['last_ordinal'],entries=[entry]))
        else:
            islands[-1]['end']=max(islands[-1]['end'],entry['last_ordinal']);islands[-1]['entries'].append(entry)
    for island in islands:
        if any(not e['review_secondary'] for e in island['entries']):continue
        def rank(e):
            xs=[(p['box'][0]+p['box'][2])/2 for p in e['points']]
            return (not e['uncertain'],abs(xs[-1]-xs[0])*min(len(xs),10),len(xs))
        entry=max(island['entries'],key=rank)
        entry['review_secondary']=False;entry['unresolved_interval']=True;selected.append(entry)
    for entry in entries:
        if not entry['review_secondary']:continue
        choices=[(agreement(entry,parent),parent) for parent in selected]
        score,parent=max(choices,key=lambda t:t[0],default=(0,None))
        if parent is not None and score>=.6:entry['grouped_track']=parent['key']
    report.update(policy='passage-v4',primary_tracks=len(selected),secondary_tracks=len(entries)-len(selected),
        warning='Sustained bicycle trajectories are review stops; weak and overlapping raw tracks remain inspectable as grouped candidates.')
    return report
