"""Experimental geometry-only plate tracks and best-view selection.

No OCR text or start list enters association or image-quality ranking. Tracks
are short visible traversals, not rider identities or confirmed passings.
"""
from dataclasses import dataclass,field
import math
import re
import cv2
import numpy as np


def unrotate_quad(quad,shape,angle):
 q=np.asarray(quad,np.float32).copy();x=q[:,0].copy();y=q[:,1].copy();h,w=shape[:2]
 if angle==90:q[:,0]=w-1-y;q[:,1]=x
 elif angle==180:q[:,0]=w-1-x;q[:,1]=h-1-y
 elif angle==270:q[:,0]=y;q[:,1]=h-1-x
 return q


def crop_quad(image,quad):
 q=np.asarray(quad,np.float32)
 width=max(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3]))
 height=max(np.linalg.norm(q[3]-q[0]),np.linalg.norm(q[2]-q[1]))
 if min(width,height)<5:return None
 w,h=max(5,round(width)),max(5,round(height))
 target=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],np.float32)
 return cv2.warpPerspective(image,cv2.getPerspectiveTransform(q,target),(w,h),borderMode=cv2.BORDER_REPLICATE)


def quality(image,quad):
 patch=crop_quad(image,quad)
 if patch is None:return None
 gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
 lo,hi=np.percentile(gray,(5,95));contrast=float(hi-lo)
 normalized=cv2.resize(gray,(max(8,round(gray.shape[1]*48/gray.shape[0])),48))
 smooth=cv2.GaussianBlur(normalized,(3,3),.7)
 sharpness=float(cv2.Laplacian(smooth,cv2.CV_32F).var())/(contrast+10)**2
 q=np.asarray(quad);x0,y0=q.min(axis=0);x1,y1=q.max(axis=0)
 clipped=bool(x0<3 or y0<3 or x1>image.shape[1]-4 or y1>image.shape[0]-4)
 area=float(abs(cv2.contourArea(q.astype(np.float32))))
 score=math.log1p(sharpness*1000)*(contrast/(contrast+25))*math.log1p(area)*(0.15 if clipped else 1)
 return dict(score=score,sharpness=sharpness,contrast=contrast,area=area,clipped=clipped)


def iou(a,b):
 a=np.asarray(a);b=np.asarray(b);lo=np.maximum(a.min(axis=0),b.min(axis=0));hi=np.minimum(a.max(axis=0),b.max(axis=0))
 intersection=float(np.maximum(0,hi-lo).prod())
 return intersection/max(1,float(np.ptp(a,axis=0).prod()+np.ptp(b,axis=0).prod())-intersection)


def deduplicate(detections):
 kept=[]
 for d in sorted(detections,key=lambda d:d['quality']['score'],reverse=True):
  if not any(iou(d['quad'],old['quad'])>.45 for old in kept):kept.append(d)
 return kept


@dataclass
class Track:
 id:int
 views:list=field(default_factory=list)
 closed_at:int|None=None
 end_reason:str|None=None

 def prediction(self,ordinal):
  latest=self.views[-1];position=np.mean(latest['quad'],axis=0)
  if len(self.views)>1:
   previous=self.views[-2];dt=latest['ordinal']-previous['ordinal']
   position=position+(position-np.mean(previous['quad'],axis=0))*(ordinal-latest['ordinal'])/max(1,dt)
  return position

 def selected(self,count=5,separation=2):
  ranked=sorted(self.views,key=lambda x:x['quality']['score'],reverse=True)
  result=[]
  for view in ranked:
   if all(abs(view['ordinal']-old['ordinal'])>=separation for old in result):result.append(view)
   if len(result)>=count:break
  # A two/three-frame traversal may have its sharpest view in the middle.
  # Prefer temporal spacing, but retain a second distinct source frame rather
  # than making consensus impossible solely because both neighbours are close.
  for view in ranked:
   if len(result)>=min(2,count,len(ranked)):break
   if not any(view['ordinal']==old['ordinal'] for old in result):result.append(view)
  return result


class ViewTracker:
 def __init__(self,max_gap=3,region_size=None,initial_distance_scale=.9):
  self.max_gap=max_gap;self.region_size=region_size;self.tracks=[]
  self.initial_distance_scale=initial_distance_scale
 def close(self,track_id,ordinal,reason='left_region'):
  track=next(t for t in self.tracks if t.id==track_id)
  if track.closed_at is None:track.closed_at=ordinal;track.end_reason=reason
 def predicted_exit(self,track,ordinal):
  if self.region_size is None or len(track.views)<2:return False
  latest=np.asarray(track.views[-1]['quad'])
  predicted=latest+track.prediction(ordinal)-latest.mean(axis=0)
  lo=predicted.min(axis=0);hi=predicted.max(axis=0);w,h=self.region_size
  return bool(hi[0]<0 or hi[1]<0 or lo[0]>=w or lo[1]>=h)
 def update(self,ordinal,detections):
  detections=deduplicate(detections);edges=[]
  for ti,t in enumerate(self.tracks):
   if t.closed_at is not None:continue
   if ordinal-t.views[-1]['ordinal']>self.max_gap:
    self.close(t.id,ordinal,'detection_gap');continue
   if ordinal<=t.views[-1]['ordinal']:continue
   previous=t.views[-1];extent=np.ptp(np.asarray(previous['quad']),axis=0);scale=max(25,float(np.linalg.norm(extent)))
   for di,d in enumerate(detections):
    ratio=d['quality']['area']/max(1,previous['quality']['area'])
    distance=float(np.linalg.norm(np.mean(d['quad'],axis=0)-t.prediction(ordinal)))
    gate=self.initial_distance_scale if len(t.views)==1 else .9
    if .35<ratio<2.8 and distance<scale*gate:
     edges.append((distance/scale+abs(math.log(ratio))*.25,ti,di))
  used_tracks=set();used_detections=set()
  for _,ti,di in sorted(edges):
   if ti not in used_tracks and di not in used_detections:
    self.tracks[ti].views.append(detections[di]);used_tracks.add(ti);used_detections.add(di)
  for ti,t in enumerate(self.tracks):
   if ti not in used_tracks and t.closed_at is None and self.predicted_exit(t,ordinal):
    self.close(t.id,ordinal,'left_region')
  for di,d in enumerate(detections):
   if di not in used_detections:self.tracks.append(Track(len(self.tracks)+1,[d]))


def consensus(readings,minimum_score=.6):
 """One vote per number per source frame, irrespective of contrast variants."""
 votes={}
 for r in readings:
  text=r['text'].strip()
  if re.fullmatch(r'[0-9]{1,3}',text) and r['score']>=minimum_score:
   per_frame=votes.setdefault(text,{})
   per_frame[r['ordinal']]=max(per_frame.get(r['ordinal'],0),r['score'])
 ranked=sorted((dict(number=n,frames=sorted(v),frame_count=len(v),mean_score=sum(v.values())/len(v)) for n,v in votes.items()),key=lambda r:(-r['frame_count'],-r['mean_score'],r['number']))
 participating={f for v in votes.values() for f in v}
 repeated=bool(ranked and ranked[0]['frame_count']>=2 and ranked[0]['frame_count']/max(1,len(participating))>=.6 and (len(ranked)==1 or ranked[0]['frame_count']>ranked[1]['frame_count']))
 return dict(status='repeated_candidate' if repeated else ('ambiguous' if len(ranked)>1 else 'candidate' if ranked else 'unread'),number=ranked[0]['number'] if repeated else None,alternatives=ranked)
