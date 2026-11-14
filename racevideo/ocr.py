"""Optional offline plate OCR. Camera capture and Tk never import this module.

Digit groups propose crops even when white labels touch tape or a rider's hand.
All proposals use image content, not fixture coordinates or expected bib numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
os.environ.setdefault('OMP_THREAD_LIMIT', '1')
import re
import json
import fcntl
from pathlib import Path
import time

from . import storage

import cv2
import numpy as np
from PIL import Image
from tesserocr import PyTessBaseAPI, PSM

cv2.setNumThreads(1)


@dataclass
class Proposal:
    quad: np.ndarray
    score: float
    kind: str


def overlap(a, b):
    x0,y0=np.maximum(a[:2],b[:2]);x1,y1=np.minimum(a[2:],b[2:])
    area=max(0,x1-x0)*max(0,y1-y0)
    return area / max(1, (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def bounds(quad):
    return np.r_[quad.min(axis=0),quad.max(axis=0)]


def rectify(image, quad):
    width=np.linalg.norm(quad[1]-quad[0]);height=np.linalg.norm(quad[3]-quad[0])
    if min(width,height)<5:return None
    # Enlargement is for recognition only, never represented as new detail.
    scale=min(8,100/height)
    w,h=max(12,round(width*scale)),max(12,round(height*scale))
    dst=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],np.float32)
    return cv2.warpPerspective(image,cv2.getPerspectiveTransform(quad.astype(np.float32),dst),(w,h),
                               borderMode=cv2.BORDER_CONSTANT,borderValue=255)


def propose(image, roi=(0,0,1,1), limit=20):
    """Return source-image quadrilaterals, including rotated digit triplets."""
    h,w=image.shape[:2]
    x0,y0,x1,y1=roi
    left,top=round(x0*w),round(y0*h)
    search=image[top:round(y1*h),left:round(x1*w)]
    if search.size==0:return []
    # Detection thresholds use one full-frame scale. A tighter ROI reduces
    # clutter/work but must not magnify glyphs beyond the detector size limits.
    scale=min(1,1280/w,900/h)
    small=cv2.resize(search,None,fx=scale,fy=scale) if scale<1 else search
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    low,high=np.percentile(gray,(2,99))
    normalized=np.clip((gray.astype(np.float32)-low)*255/max(20,high-low),0,255).astype(np.uint8)
    proposals=[]
    hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    for saturation in (40,75):
        light=((hsv[:,:,1]<saturation)&(normalized>160)).astype(np.uint8)*255
        light=cv2.morphologyEx(light,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        light=cv2.morphologyEx(light,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(light,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            rect=cv2.minAreaRect(contour);a,b=rect[1]
            long,short=max(a,b),min(a,b)
            if not (22<=long<=200 and 10<=short<=90 and 1.35<=long/max(1,short)<=4.5):continue
            coverage=cv2.contourArea(contour)/max(1,a*b)
            if coverage<.65:continue
            box=cv2.boxPoints(rect)
            edge=int(np.argmax([np.linalg.norm(box[(i+1)%4]-box[i]) for i in range(4)]))
            quad=np.roll(box,-edge,axis=0)
            if quad[1,0]<quad[0,0]:quad=np.roll(quad,-2,axis=0)
            patch=rectify(normalized,quad)
            if patch is None or np.std(patch)<20:continue
            source=quad/scale+np.array([left,top])
            proposals.append(Proposal(source,160*math.sqrt(short)*coverage,'label'))
    mser=cv2.MSER_create()
    mser.setMinArea(10);mser.setMaxArea(3000)
    regions,rectangles=mser.detectRegions(normalized)
    regions,rectangles=list(regions),list(rectangles)
    # Blurred small print is often not a stable MSER region. Complement it with
    # connected dark components at several thresholds, then deduplicate glyphs.
    for threshold in (70,105,140,175):
        for opening in (1,2):
            dark=(normalized<threshold).astype(np.uint8)
            if opening>1:dark=cv2.morphologyEx(dark,cv2.MORPH_OPEN,np.ones((opening,opening),np.uint8))
            count,labels,stats,_=cv2.connectedComponentsWithStats(dark)
            for i in range(1,count):
                x,y,cw,ch,area=stats[i]
                if not (8<=max(cw,ch)<=90 and min(cw,ch)>=2 and .12<=area/(cw*ch)<=.82):continue
                ys,xs=np.nonzero(labels[y:y+ch,x:x+cw]==i)
                regions.append(np.column_stack((xs+x,ys+y)))
                rectangles.append((x,y,cw,ch))
    glyphs=[]
    for points,(x,y,cw,ch) in zip(regions,rectangles):
        size=max(cw,ch)
        if not (8<=size<=90 and min(cw,ch)>=2 and min(cw,ch)/size>=.13):continue
        density=len(points)/(cw*ch)
        if not (.12<=density<=.82):continue
        pixels=normalized[points[:,1],points[:,0]]
        patch=normalized[max(0,y-2):y+ch+2,max(0,x-2):x+cw+2]
        contrast=float(np.percentile(patch,85)-float(np.median(pixels)))
        if contrast<35:continue
        box=np.array([x,y,x+cw,y+ch],np.float32)
        # Prefer stable dark glyphs; suppress nested MSER variants.
        quality=contrast*math.sqrt(size)
        glyphs.append((quality,box,(x+cw/2,y+ch/2),float(size)))
    glyphs.sort(key=lambda g:g[0],reverse=True)
    kept=[]
    for glyph in glyphs:
        if any(overlap(glyph[1],old[1])>.55 for old in kept):continue
        kept.append(glyph)
        if len(kept)>=600:break
    if not kept:
        return sorted(proposals,key=lambda p:p.score,reverse=True)[:limit]
    centers=np.array([g[2] for g in kept],np.float32)
    seen=set()
    for middle,g in enumerate(kept):
        vectors=centers-centers[middle]
        distances=np.linalg.norm(vectors,axis=1)
        neighbors=np.flatnonzero((distances>g[3]*.25)&(distances<g[3]*1.8))
        neighbors=sorted(neighbors,key=lambda j:distances[j])[:14]
        for ni,a in enumerate(neighbors):
            for b in neighbors[ni+1:]:
                indices=tuple(sorted((int(a),middle,int(b))))
                if indices in seen:continue
                sizes=[kept[i][3] for i in indices]
                if max(sizes)/min(sizes)>1.8:continue
                cosine=float(np.dot(vectors[a],vectors[b])/(distances[a]*distances[b]))
                if cosine>-.94 or max(distances[a],distances[b])/min(distances[a],distances[b])>2.1:continue
                seen.add(indices)
                u=centers[b]-centers[a];u=u/np.linalg.norm(u)
                if u[0]<0:u=-u
                v=np.array([-u[1],u[0]])
                points=[]
                for index in indices:
                    x,y,r,bottom=kept[index][1]
                    points.extend(((x,y),(r,y),(r,bottom),(x,bottom)))
                points=np.array(points,np.float32)
                along,across=points@u,points@v
                pad=max(1.5,np.mean(sizes)*.12)
                l,r=along.min()-pad,along.max()+pad
                t,bottom=across.min()-pad,across.max()+pad
                aspect=(r-l)/(bottom-t)
                if not 1.05<=aspect<=4.5:continue
                quad=np.array([l*u+t*v,r*u+t*v,r*u+bottom*v,l*u+bottom*v],np.float32)
                # Original image coordinates are retained for overlays/evidence.
                source=quad/scale+np.array([left,top])
                score=np.mean([kept[i][0] for i in indices])*(-cosine)
                proposals.append(Proposal(source,score,'digits'))
    proposals.sort(key=lambda p:p.score,reverse=True)
    selected=[]
    for proposal in proposals:
        if any(overlap(bounds(proposal.quad),bounds(p.quad))>.45 for p in selected):continue
        selected.append(proposal)
        if len(selected)>=limit:break
    return selected


class Recognizer:
    def __init__(self,tessdata='/usr/share/tesseract-ocr/5/tessdata',rotations=(0,180)):
        self.rotations=storage.validate_ocr_rotations(rotations)
        self.api=PyTessBaseAPI(path=tessdata,psm=PSM.SINGLE_LINE)
        self.api.SetVariable('tessedit_char_whitelist','0123456789')

    def close(self):
        self.api.End()

    def read(self,image,proposal):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        crop=rectify(gray,proposal.quad)
        if crop is None:return []
        hits=[]
        self.api.SetPageSegMode(PSM.SINGLE_LINE)
        for rotation in self.rotations:
            patch=crop if rotation==0 else cv2.rotate(crop,cv2.ROTATE_180)
            for variant in ('gray','inset','clean'):
                if variant=='inset':
                    h,w=patch.shape
                    v=patch[round(h*.1):round(h*.9),round(w*.1):round(w*.9)]
                else:
                    v=patch if variant=='gray' else clean_border(patch)
                v=cv2.copyMakeBorder(v,16,16,16,16,cv2.BORDER_CONSTANT,value=255)
                self.api.SetImage(Image.fromarray(v))
                text=self.api.GetUTF8Text().strip()
                if re.fullmatch(r'[0-9]{1,3}',text):
                    hits.append(dict(number=text,confidence=self.api.MeanTextConf(),rotation=rotation,variant=variant))
        return hits


def clean_border(gray):
    binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
    black=cv2.morphologyEx(255-binary,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    n,labels,stats,_=cv2.connectedComponentsWithStats((black>0).astype(np.uint8))
    result=255-black
    for i in range(1,n):
        x,y,w,h,_=stats[i]
        if x==0 or y==0 or x+w==gray.shape[1] or y+h==gray.shape[0]:
            result[labels==i]=255
    return result


class Tracks:
    """Spatial/temporal association and one vote per source frame.

    This is a basic text-region tracker, not rider identity or finish timing.
    Separate encounters remain separate observations even for the same number.
    """
    def __init__(self):
        self.items=[]

    def update(self, hits, width, height):
        used=set()
        for hit in sorted(hits,key=lambda h:h['confidence'],reverse=True):
            quad=np.array(hit['quad']) / np.array([width,height])
            center=quad.mean(axis=0)
            size=float(np.linalg.norm(quad.max(axis=0)-quad.min(axis=0)))
            available=[]
            for i,t in enumerate(self.items):
                gap=(hit['monotonic_ns']-t['last_mono'])/1e9
                if i in used or not 0<=gap<=.8:continue
                distance=float(np.linalg.norm(center-t['center']))
                if distance<=max(.045,size*2.5):available.append((distance,i))
            if available:
                _,index=min(available);track=self.items[index]
            else:
                index=len(self.items);track=dict(votes={},center=center,last_mono=hit['monotonic_ns'])
                self.items.append(track)
            used.add(index)
            track.update(center=center,last_mono=hit['monotonic_ns'])
            for reading in hit.get('alternatives',[hit]):
                votes=track['votes'].setdefault(reading['number'],{})
                prior=votes.get(reading['ordinal'])
                if prior is None or prior['confidence']<reading['confidence']:
                    votes[reading['ordinal']]=reading

    def observations(self,min_frames=2):
        results=[]
        for track in self.items:
            if not track['votes']:continue
            ranked=sorted(track['votes'].items(),key=lambda p:(len(p[1]),sum(h['confidence'] for h in p[1].values())),reverse=True)
            for rank,(number,by_frame) in enumerate(ranked):
                hits=list(by_frame.values())
                best=max(hits,key=lambda h:h['confidence'])
                competing=rank>0 or len(ranked)>1 and len(ranked[1][1])>=len(hits)
                results.append(dict(number=number,first_ns=min(h['received_ns'] for h in hits),
                                    last_ns=max(h['received_ns'] for h in hits),frame_count=len(hits),
                                    confidence=best['confidence'],ordinal=best['ordinal'],quad=best['quad'],
                                    status='repeated' if len(hits)>=min_frames and not competing else 'candidate'))
        return sorted(results,key=lambda h:(h['first_ns'],h['number']))


def run_job(path, run_id):
    """One separate process, bounded sampling/proposals, short DB transactions."""
    connection=storage.connect(path)
    row=connection.execute('SELECT * FROM ocr_runs WHERE id=?',(run_id,)).fetchone()
    if row is None:raise ValueError('Unknown OCR job')
    parameters=json.loads(row['parameters'])
    lock=open(str(Path(path).resolve())+'.ocr.lock','a')
    recognizer=None
    start=time.monotonic();cpu=time.process_time()
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('OCR worker busy; wait for the current clip to finish') from None
        clip_id=row['clip_id']
        clip=connection.execute('SELECT * FROM clips WHERE id=?',(clip_id,)).fetchone()
        index=storage.frame_index(connection,clip_id)
        fps=parameters.get('fps',8)
        roi=parameters.get('roi',(0,0,1,1))
        confidence=parameters.get('min_confidence',60)
        if fps<=0 or not 0<=confidence<=100:raise ValueError('Invalid OCR rate/confidence')
        if len(roi)!=4 or not 0<=roi[0]<roi[2]<=1 or not 0<=roi[1]<roi[3]<=1:raise ValueError('Invalid OCR area')
        chosen=[];last=None
        for item in index:
            if last is None or item['monotonic_ns']-last>=1e9/fps:
                chosen.append(item);last=item['monotonic_ns']
        with connection:connection.execute("UPDATE ocr_runs SET state='running' WHERE id=?",(run_id,))
        recognizer=Recognizer(parameters.get('tessdata','/usr/share/tesseract-ocr/5/tessdata'),parameters.get('rotations',(0,180)))
        tracker=Tracks();raw_count=0;regions=0
        for count,item in enumerate(chosen,1):
            image=cv2.imdecode(np.frombuffer(storage.read_frame(connection,clip_id,item['ordinal']),np.uint8),cv2.IMREAD_COLOR)
            if image is None:raise ValueError('Saved JPEG did not decode')
            proposals=propose(image,roi,parameters.get('max_regions',20))
            regions+=len(proposals);frame_hits=[];raw=[]
            for proposal in proposals:
                readings=recognizer.read(image,proposal)
                qualified=[]
                for hit in readings:
                    hit.update(ordinal=item['ordinal'],received_ns=item['received_ns'],monotonic_ns=item['monotonic_ns'],
                               quad=proposal.quad.tolist())
                    raw.append((run_id,hit['ordinal'],hit['received_ns'],hit['monotonic_ns'],hit['number'],hit['confidence'],
                                json.dumps(hit['quad']),hit['rotation'],hit['variant']))
                    if hit['confidence']>=confidence:qualified.append(hit)
                if qualified:
                    primary=dict(max(qualified,key=lambda h:h['confidence']))
                    primary['alternatives']=qualified
                    frame_hits.append(primary)
            tracker.update(frame_hits,clip['width'],clip['height'])
            raw_count+=len(raw)
            summary=dict(sampled_frames=count,total_samples=len(chosen),raw_reads=raw_count,regions=regions,
                         wall_seconds=round(time.monotonic()-start,3),cpu_seconds=round(time.process_time()-cpu,3))
            with connection:
                connection.executemany('INSERT INTO ocr_reads(run_id,ordinal,received_ns,monotonic_ns,number,confidence,quad,rotation,variant) '
                                       'VALUES(?,?,?,?,?,?,?,?,?)',raw)
                connection.execute('UPDATE ocr_runs SET summary=? WHERE id=?',(json.dumps(summary),run_id))
        results=tracker.observations(parameters.get('min_frames',2))
        evidence=[]
        for result in results:
            image=cv2.imdecode(np.frombuffer(storage.read_frame(connection,clip_id,result['ordinal']),np.uint8),cv2.IMREAD_COLOR)
            crop=rectify(image,np.array(result['quad'],np.float32))
            ok,jpeg=cv2.imencode('.jpg',crop)
            if not ok:raise RuntimeError('Could not save OCR evidence')
            evidence.append((run_id,result['number'],result['first_ns'],result['last_ns'],result['frame_count'],
                             result['confidence'],result['ordinal'],json.dumps(result['quad']),jpeg.tobytes(),result['status']))
        summary.update(wall_seconds=round(time.monotonic()-start,3),cpu_seconds=round(time.process_time()-cpu,3),
                       engine='mser-components-tesseract-v5',number_lengths=[1,2,3],observations=len(results))
        trim=parameters.get('retention',{})
        if trim.get('mode')=='motion':
            from . import retention
            with connection:
                proposal_id=connection.execute("INSERT INTO retention_proposals(clip_id,created_ns,source_run_id,state,parameters) VALUES(?,?,?,'queued',?)",(clip_id,time.time_ns(),run_id,json.dumps(trim))).lastrowid
            retention.analyze(path,proposal_id)
        with connection:
            connection.executemany('INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status) '
                                   'VALUES(?,?,?,?,?,?,?,?,?,?)',evidence)
            connection.execute("UPDATE ocr_runs SET state='complete',summary=? WHERE id=?",(json.dumps(summary),run_id))
        return storage.read_ocr_run(connection,clip_id,run_id)
    except Exception as exc:
        with connection:connection.execute("UPDATE ocr_runs SET state='error',error=? WHERE id=?",(str(exc),run_id))
        raise
    finally:
        if recognizer:recognizer.close()
        lock.close();connection.close()
