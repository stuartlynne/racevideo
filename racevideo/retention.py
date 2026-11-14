"""Non-destructive trimming proposals; never deletes or updates source frames."""
import argparse
import io
import json
import time
from contextlib import nullcontext
from pathlib import Path
from PIL import Image,ImageChops,ImageFilter
from . import storage
from .motion import validate_roi

MODES={'off':'Off — retain original clips','motion':'Road-motion trim proposals',
       'bicycle':'Reuse bike detections during neural OCR',
       'person_bicycle':'Reuse bike/person detections — conservative'}
SCHEMA='''CREATE TABLE IF NOT EXISTS retention_proposals (
 id INTEGER PRIMARY KEY,clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 created_ns INTEGER NOT NULL,source_run_id INTEGER REFERENCES ocr_runs(id) ON DELETE SET NULL,
 state TEXT NOT NULL,parameters TEXT NOT NULL,report TEXT NOT NULL DEFAULT '{}',error TEXT
); CREATE INDEX IF NOT EXISTS retention_clip ON retention_proposals(clip_id,id);'''


def settings(value=None):
    value=value or {};mode=value.get('mode','off')
    if mode not in MODES:raise ValueError('Unknown trim behavior')
    return dict(mode=mode,road_roi=list(validate_roi(value.get('road_roi',(.04,.3,.96,1.0)))),
                padding_seconds=.1,bridge_seconds=.4,version=1)


class MotionPresence:
    """Small thumbnails from existing OCR decode, or standalone reduced JPEG decode."""
    def __init__(self,roi):self.roi=validate_roi(roi);self.reference=None

    def add(self,image):
        if not isinstance(image,Image.Image):
            # The neural worker already decoded this BGR array; do not decode JPEG again.
            import cv2
            image=Image.fromarray(cv2.cvtColor(cv2.resize(image,(160,90)),cv2.COLOR_BGR2GRAY))
        image=image.copy();image.thumbnail((160,90));gray=image.convert('L').filter(ImageFilter.GaussianBlur(.7))
        w,h=gray.size;x0,y0,x1,y1=self.roi
        crop=gray.crop((int(x0*w),int(y0*h),max(int(x0*w)+1,int(x1*w)),max(int(y0*h)+1,int(y1*h))))
        if self.reference is None:self.reference=crop;return False
        hist=ImageChops.difference(crop,self.reference).histogram()
        return sum(hist[20:])/(crop.width*crop.height)>=.008


def propose(rows,flags,parameters):
    p=settings(parameters)
    if len(rows)!=len(flags):raise ValueError('Presence coverage must match source frames')
    if not rows:return dict(state='inconclusive',intervals=[],reason='Empty clip')
    times=[r['monotonic_ns'] for r in rows]
    if any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Source frames must have increasing monotonic timestamps')
    seen=[i for i,flag in enumerate(flags) if flag]
    if not seen:
        return dict(state='inconclusive',intervals=[dict(first_ordinal=rows[0]['ordinal'],last_ordinal=rows[-1]['ordinal'])],
            reason='No reliable presence detected; propose retaining the whole clip',parameters=p)
    padding=round(p['padding_seconds']*1e9);bridge=round(p['bridge_seconds']*1e9)
    groups=[];first=last=seen[0]
    for i in seen[1:]:
        if times[i]-times[last]<=bridge:last=i
        else:groups.append((first,last));first=last=i
    groups.append((first,last));intervals=[]
    for first,last in groups:
        a=first;b=last
        while a>0 and times[a]-times[a-1]<=500_000_000 and times[a-1]>=times[first]-padding:a-=1
        while b+1<len(rows) and times[b+1]-times[b]<=500_000_000 and times[b+1]<=times[last]+padding:b+=1
        if intervals and a<=intervals[-1][1]+1:intervals[-1]=(intervals[-1][0],b)
        else:intervals.append((a,b))
    return dict(state='proposal',parameters=p,intervals=[dict(first_ordinal=rows[a]['ordinal'],last_ordinal=rows[b]['ordinal'],
        first_ns=rows[a]['received_ns'],last_ns=rows[b]['received_ns']) for a,b in intervals],
        presence_frames=len(seen),reason='Experimental presence intervals, not verified wheel boundaries; originals retained')


def from_objects(rows,parameters,image_size):
    p=settings(parameters);w,h=image_size;x0,y0,x1,y1=p['road_roi'];flags=[]
    for row in rows:
        present=False
        for obj in row.get('objects',[]):
            if obj['label'] not in (('bicycle',) if p['mode']=='bicycle' else ('person','bicycle')):continue
            a,b,c,d=obj['box'];cx=(a+c)/2/w;foot=d/h
            if obj['score']>=.3 and x0<=cx<=x1 and y0<=foot<=y1:present=True
        flags.append(present)
    return propose(rows,flags,p)


def save(connection,clip_id,report,source_run_id=None,proposal_id=None,commit=True):
    rows=[dict(r) for r in connection.execute('SELECT ordinal,length(jpeg) AS bytes FROM frames WHERE clip_id=? ORDER BY ordinal',(clip_id,))]
    ranges=report['intervals'];kept=[r for r in rows if any(i['first_ordinal']<=r['ordinal']<=i['last_ordinal'] for i in ranges)]
    valid={r['ordinal'] for r in rows};last=-1
    for interval in ranges:
        a,b=interval['first_ordinal'],interval['last_ordinal']
        if type(a) is not int or type(b) is not int or a not in valid or b not in valid or a>b or a<=last:raise ValueError('Invalid/non-source trim interval')
        last=b
    result=dict(report,total_frames=len(rows),kept_frames=len(kept),total_bytes=sum(r['bytes'] for r in rows),kept_bytes=sum(r['bytes'] for r in kept))
    for interval in result['intervals']:
        chosen=[r for r in kept if interval['first_ordinal']<=r['ordinal']<=interval['last_ordinal']]
        interval.update(frame_count=len(chosen),bytes=sum(r['bytes'] for r in chosen))
    with connection if commit else nullcontext():
        if proposal_id:
            connection.execute('UPDATE retention_proposals SET state=?,report=?,error=NULL WHERE id=?',
                (result['state'],json.dumps(result),proposal_id));return proposal_id
        return connection.execute('INSERT INTO retention_proposals(clip_id,created_ns,source_run_id,state,parameters,report) VALUES(?,?,?,?,?,?)',
            (clip_id,time.time_ns(),source_run_id,result['state'],json.dumps(result.get('parameters',{})),json.dumps(result))).lastrowid


def latest(connection,clip_id):
    row=connection.execute('SELECT * FROM retention_proposals WHERE clip_id=? ORDER BY id DESC LIMIT 1',(clip_id,)).fetchone()
    if not row:return None
    value=dict(row);value['report']=json.loads(value['report']);return value


def analyze(database,proposal_id):
    c=storage.connect(database)
    try:
        row=c.execute('SELECT * FROM retention_proposals WHERE id=?',(proposal_id,)).fetchone()
        p=settings(json.loads(row['parameters']));clip=row['clip_id'];index=storage.frame_index(c,clip)
        with c:c.execute("UPDATE retention_proposals SET state='running' WHERE id=?",(proposal_id,))
        motion=MotionPresence(p['road_roi']);flags=[];started=time.perf_counter()
        for frame in index:
            with Image.open(io.BytesIO(storage.read_frame(c,clip,frame['ordinal']))) as image:
                image.draft('L',(160,90));flags.append(motion.add(image))
        report=propose(index,flags,p);report['wall_seconds']=time.perf_counter()-started
        save(c,clip,report,proposal_id=proposal_id)
    except Exception as exc:
        with c:c.execute("UPDATE retention_proposals SET state='error',error=? WHERE id=?",(str(exc),proposal_id))
        raise
    finally:c.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--proposal',type=int,required=True)
    a=p.parse_args();analyze(a.db,a.proposal)


if __name__=='__main__':main()
