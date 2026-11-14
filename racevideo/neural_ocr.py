"""Optional rider-first neural inference. Imported only in the analysis process."""
import json
import time

def result_dict(result):
 value=result.json
 if callable(value):value=value()
 if isinstance(value,str):value=json.loads(value)
 return value.get('res',value)

def rider_regions(image,model,bounds,presence=None):
 """Generic person/bicycle proposals; no plate coordinates or bib list."""
 left,top,right,bottom=bounds;regions=[]
 result=result_dict(list(model.predict(input=image,threshold=.15 if presence is not None else .3))[0])
 for box in result.get('boxes',[]):
  if box['label'] not in ('person','bicycle'):continue
  if presence is not None:presence.append(dict(label=box['label'],score=float(box.get('score',0)),box=list(map(float,box['coordinate']))))
  if float(box.get('score',0))<.3:continue
  x0,y0,x1,y1=box['coordinate'];w=x1-x0;h=y1-y0
  if w<250 or h<250:continue
  px=.15*w if box['label']=='bicycle' else .35*w;py=.25*h if box['label']=='bicycle' else .1*h
  x0=max(left,round(x0-px));x1=min(right,round(x1+px));y0=max(top,round(y0-py));y1=min(bottom,round(y1+py))
  if x1<=x0 or y1<=y0:continue
  regions.append((x0-left,y0-top,image[y0:y1,x0:x1]))
 return regions

class Scanner:
    def __init__(self, models, device, parameters=None, cpu_threads=1):
        self.parameters=parameters or {}
        self.device=device
        import cv2
        from paddleocr import TextDetection, TextRecognition
        from paddlex import create_model
        from paddlex.inference.utils.pp_option import PaddlePredictorOption
        cv2.setNumThreads(1)
        settings = dict(device=device, cpu_threads=cpu_threads, enable_mkldnn=device=='cpu')
        self.det = TextDetection(model_name='PP-OCRv5_mobile_det', model_dir=str(models/'PP-OCRv5_mobile_det'), **settings)
        self.rec = TextRecognition(model_name='PP-OCRv5_mobile_rec', model_dir=str(models/'PP-OCRv5_mobile_rec'), **settings)
        self.object = create_model('PicoDet-S', device=device, pp_option=PaddlePredictorOption(cpu_threads=cpu_threads,run_mode='mkldnn' if device=='cpu' else 'paddle'))

    def scan(self, connection, clip, progress=None):
        import cv2
        import numpy as np
        import re
        from racevideo.plate_selection import crop_quad, iou, unrotate_quad
        from .encounters import summarize
        start = time.perf_counter(); cpu = time.process_time()
        metadata = connection.execute('SELECT id,started_ns,ended_ns,frame_count,width,height FROM clips WHERE id=?',(clip,)).fetchone()
        if metadata is None:raise ValueError(f'Unknown clip {clip}')
        keys = ['id','started_ns','ended_ns','frame_count','width','height']
        metadata = dict(zip(keys, metadata)); rows=[]; regions_count=0; detections_count=0
        # Separate metadata cursor: never hold a SELECT containing all JPEG blobs.
        index=connection.execute('SELECT ordinal,received_ns,monotonic_ns FROM frames WHERE clip_id=? ORDER BY ordinal',(clip,)).fetchall()
        from . import retention
        trim=retention.settings(self.parameters.get('retention'));motion=retention.MotionPresence(trim['road_roi']) if trim['mode']=='motion' else None
        presence_flags=[]
        for ordinal,received,monotonic in index:
            jpeg=connection.execute('SELECT jpeg FROM frames WHERE clip_id=? AND ordinal=?',(clip,ordinal)).fetchone()[0]
            image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
            if image is None:raise ValueError(f'Bad JPEG {clip}:{ordinal}')
            h,w=image.shape[:2];left,top,right,bottom=[round(v*s) for v,s in zip(self.parameters.get('roi',[.05,.4,.98,.9]),(w,h,w,h))]
            objects=[]
            regions=rider_regions(image,self.object,(left,top,right,bottom),presence=objects);regions_count+=len(regions)
            if motion:presence_flags.append(motion.add(image))
            candidates=[]
            for x,y,region in regions:
                for angle in self.parameters.get('detector_rotations',[0,90]):
                    rotated=np.ascontiguousarray(np.rot90(region,angle//90))
                    detected=result_dict(list(self.det.predict(input=rotated,limit_side_len=960,limit_type='max'))[0])
                    for quad,score in zip(detected.get('dt_polys',[]),detected.get('dt_scores',[])):
                        q=unrotate_quad(quad,region.shape,angle)+[left+x,top+y]
                        if min(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[3]-q[0]))<5:continue
                        candidates.append(dict(quad=q.tolist(),detector_score=float(score),detector_rotation=angle))
            kept=[]
            for proposal in sorted(candidates,key=lambda d:-d['detector_score']):
                if not any(iou(proposal['quad'],old['quad'])>.5 for old in kept):kept.append(proposal)
            detections_count+=len(kept);patches=[];details=[]
            for proposal in kept:
                patch=crop_quad(image,proposal['quad'])
                if patch is None or max(patch.shape[:2])>1200:continue
                for angle in self.parameters.get('recognizer_rotations',[0,90,180,270]):
                    patches.append(np.ascontiguousarray(np.rot90(patch,angle//90)))
                    details.append(dict(proposal,rotation=angle))
            output=list(self.rec.predict(input=patches,batch_size=8)) if patches else []
            if len(output)!=len(details):raise RuntimeError('Recognition count mismatch')
            readings=[]
            for detail,value in zip(details,output):
                value=result_dict(value);text=value.get('rec_text','').strip();score=float(value.get('rec_score',0))
                if re.fullmatch('[0-9]{1,3}',text):readings.append(dict(detail,text=text,score=score))
            rows.append(dict(clip=clip,ordinal=ordinal,received_ns=received,monotonic_ns=monotonic,method='riders960',readings=readings,objects=objects))
            if progress and ordinal%30==0:progress(ordinal,len(index))
        if len(index)!=metadata['frame_count']:raise ValueError('Clip/frame count mismatch')
        encounters=summarize(rows,maximum_gap=8,image_size=(metadata['width'],metadata['height']))
        proposal=(retention.propose(rows,presence_flags,trim) if motion else retention.from_objects(rows,trim,(w,h))) if trim['mode']!='off' else None
        from .bike_index import build
        bikes=build(rows,w,h)
        return dict(state='complete',bike_index=bikes,retention_proposal=proposal,device=self.device,clip=clip,source_clip=metadata,frames=len(index),wall_seconds=time.perf_counter()-start,
                    cpu_seconds=time.process_time()-cpu,regions=regions_count,detections=detections_count,
                    results=rows,encounters=encounters)
