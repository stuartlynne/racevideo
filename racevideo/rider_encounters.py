"""Join small moving OCR patches through their physical bicycle trajectory."""
from collections import defaultdict
import math
import re
from .plate_selection import consensus


def summarize(rows,report,minimum_score=.85,minimum_frames=3):
    tracks=[e for e in report['passages'] if not e.get('review_secondary')]
    points={e['key']:{p['ordinal']:p['box'] for p in e['points']} for e in tracks}
    views=defaultdict(dict)
    directions={}
    for e in tracks:
        first,last=e['points'][0]['box'],e['points'][-1]['box']
        directions[e['key']]=1 if last[0]+last[2]>first[0]+first[2] else -1
    for row in rows:
        for reading in row['readings']:
            if reading['score']<minimum_score or not re.fullmatch('[0-9]{1,3}',reading['text']):continue
            quad=reading['quad'];x=sum(p[0] for p in quad)/4;y=sum(p[1] for p in quad)/4
            if not math.isfinite(x+y):continue
            choices=[]
            for key,index in points.items():
                box=index.get(row['ordinal'])
                if box is None:continue
                left,top,right,bottom=box;w=right-left;h=bottom-top
                if w<=0 or h<=0 or not left-.05*w<=x<=right+.05*w or not top-.3*h<=y<=bottom:continue
                # Seatpost labels normally trail the bicycle centre. This is
                # only geometric association, never a guess from expected bibs.
                px=(left+right)/2-directions[key]*.15*w
                score=abs(x-px)/w+abs(y-(top+.25*h))/h*.2
                choices.append((score,key))
            if not choices:continue
            choices.sort()
            if len(choices)>1 and choices[1][0]-choices[0][0]<.08:continue
            key=choices[0][1]
            view=views[key].setdefault(row['ordinal'],dict(ordinal=row['ordinal'],received_ns=row['received_ns'],
                monotonic_ns=row['monotonic_ns'],readings=[]))
            view['readings'].append(dict(reading,ordinal=row['ordinal']))
    encounters=[]
    for key,frames in views.items():
        readings=[r for view in frames.values() for r in view['readings']]
        numbers=defaultdict(dict)
        for reading in readings:
            old=numbers[reading['text']].get(reading['ordinal'])
            if old is None or reading['score']>old['score']:numbers[reading['text']][reading['ordinal']]=reading
        qualified=[]
        for number,support in numbers.items():
            if len(support)<minimum_frames:continue
            centers=[(sum(p[0] for p in r['quad'])/4,sum(p[1] for p in r['quad'])/4) for r in support.values()]
            travel=math.hypot(max(p[0] for p in centers)-min(p[0] for p in centers),max(p[1] for p in centers)-min(p[1] for p in centers))
            if travel<20:continue  # A stationary background digit is not a plate passage.
            qualified.extend(support.values())
        if not qualified:continue
        vote=consensus(qualified,minimum_score=minimum_score)
        repeated=[a for a in vote['alternatives'] if a['frame_count']>=minimum_frames]
        vote['alternatives']=repeated
        if len(repeated)>1:vote.update(status='ambiguous',number=None)
        accepted={a['number'] for a in repeated}
        selected=[dict(v,readings=[r for r in v['readings'] if r['text'] in accepted]) for _,v in sorted(frames.items())]
        selected=[v for v in selected if v['readings']]
        encounters.append(dict(track='physical:'+key,physical_track=key,views=selected,consensus=vote,
            first_ordinal=selected[0]['ordinal'],last_ordinal=selected[-1]['ordinal'],
            first_received_ns=selected[0]['received_ns'],last_received_ns=selected[-1]['received_ns']))
    return encounters
