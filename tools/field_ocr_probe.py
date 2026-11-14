"""CPU/offline field OCR diagnostics on immutable originals; outputs kept separate."""
import os
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK','True');os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True');os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse,json,re,sqlite3,time,resource
from pathlib import Path
import cv2,numpy as np
from paddleocr import TextDetection,TextRecognition
from racevideo.plate_selection import crop_quad,iou,unrotate_quad
def serial(value):
 if hasattr(value,'tolist'):return value.tolist()
 if isinstance(value,Path):return str(value)
 raise TypeError(type(value).__name__)

def result_dict(result):
 value=result.json
 if callable(value):value=value()
 if isinstance(value,str):value=json.loads(value)
 return value.get('res',value)
cv2.setNumThreads(1)

def tile_starts(length,size,overlap):
 if length<=size:return [0]
 starts=list(range(0,length-size+1,size-overlap))
 if starts[-1]!=length-size:starts.append(length-size)
 return starts

def moving_regions(search,background):
 scale=min(1.,960/search.shape[1]);small=cv2.resize(search,None,fx=scale,fy=scale)
 delta=np.max(cv2.absdiff(small,background),axis=2)
 mask=(cv2.GaussianBlur(delta,(3,3),0)>18).astype(np.uint8)*255
 mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
 mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
 n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
 regions=[]
 for x,y,w,h,area in stats[1:]:
  if area<120 or w<8 or h<8:continue
  pad=16;x0=max(0,int((x-pad)/scale));y0=max(0,int((y-pad)/scale));x1=min(search.shape[1],int((x+w+pad)/scale));y1=min(search.shape[0],int((y+h+pad)/scale))
  regions.append((x0,y0,search[y0:y1,x0:x1]))
 return regions

def rider_regions(image,model,bounds):
 """Generic person/bicycle proposals; no plate coordinates or bib list."""
 left,top,right,bottom=bounds;regions=[]
 result=result_dict(list(model.predict(input=image,threshold=.3))[0])
 for box in result.get('boxes',[]):
  if box['label'] not in ('person','bicycle'):continue
  x0,y0,x1,y1=box['coordinate'];w=x1-x0;h=y1-y0
  if w<250 or h<250:continue
  px=.15*w if box['label']=='bicycle' else .35*w;py=.25*h if box['label']=='bicycle' else .1*h
  x0=max(left,round(x0-px));x1=min(right,round(x1+px));y0=max(top,round(y0-py));y1=min(bottom,round(y1+py))
  if x1<=x0 or y1<=y0:continue
  regions.append((x0-left,y0-top,image[y0:y1,x0:x1]))
 return regions


def main():
 p=argparse.ArgumentParser();p.add_argument('store',type=Path);p.add_argument('--models',type=Path,required=True);p.add_argument('--device',default='cpu');p.add_argument('--cpu-affinity-count',type=int);p.add_argument('--clips',nargs='+',type=int);p.add_argument('--case',action='append',help='CLIP:ORDINAL or CLIP:START:STOP:STEP (zero based, exclusive stop)');p.add_argument('--roi',nargs=4,type=float,default=[.05,.4,.98,.9]);p.add_argument('--output',type=Path,required=True);p.add_argument('--methods',nargs='+',choices=['band960','band1536','band2048','band3072','tiles960','motion960','riders960'],default=['band960','band1536','tiles960','motion960']);p.add_argument('--threads',type=int,default=2);p.add_argument('--mkldnn',action='store_true');p.add_argument('--try-rotations',action='store_true');p.add_argument('--detector-rotations',nargs='+',type=int,choices=[0,90,180,270],default=[0]);a=p.parse_args()
 if a.cpu_affinity_count:
  os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:a.cpu_affinity_count]))
 run_started=time.perf_counter();cpu_started=time.process_time()
 a.output.mkdir(parents=True,exist_ok=True)
 if (a.output/'results.json').exists():raise FileExistsError(a.output/'results.json')
 conn=sqlite3.connect(a.store.resolve().as_uri()+'?mode=ro',uri=True)
 det=TextDetection(model_name='PP-OCRv5_mobile_det',model_dir=str(a.models/'PP-OCRv5_mobile_det'),device=a.device,cpu_threads=a.threads,enable_mkldnn=a.mkldnn)
 rec=TextRecognition(model_name='PP-OCRv5_mobile_rec',model_dir=str(a.models/'PP-OCRv5_mobile_rec'),device=a.device,cpu_threads=a.threads,enable_mkldnn=a.mkldnn)
 object_model=None
 if 'riders960' in a.methods:
  from paddlex import create_model
  from paddlex.inference.utils.pp_option import PaddlePredictorOption
  object_model=create_model('PicoDet-S',device=a.device,pp_option=PaddlePredictorOption(cpu_threads=a.threads,run_mode='mkldnn' if a.mkldnn else 'paddle'))
 backgrounds={}
 report=dict(store=str(a.store.resolve()),state='running',model_initialization_seconds=time.perf_counter()-run_started,cpu_affinity=sorted(os.sched_getaffinity(0)),device=a.device,threads=a.threads,roi=a.roi,try_rotations=a.try_rotations,detector_rotations=a.detector_rotations,enable_mkldnn=a.mkldnn,notes=['No valid bib list supplied to models. Exact three-digit outputs remain candidates.','Methods and rotations are separate diagnostics, not independent votes.'],results=[])
 cases=[]
 for clip in a.clips or []:
  cases.extend(conn.execute('SELECT clip_id,ordinal FROM frames WHERE clip_id=? ORDER BY ordinal',(clip,)).fetchall())
 for case in a.case or []:
  values=list(map(int,case.split(':')))
  if len(values)==2:cases.append(values)
  elif len(values)==4:cases.extend((values[0],ordinal) for ordinal in range(*values[1:]))
  else:p.error('Expected CLIP:ORDINAL or CLIP:START:STOP:STEP')
 if not cases:p.error('Provide --case or --clips')
 for clip,ordinal in cases:
  row=conn.execute('SELECT jpeg,received_ns,monotonic_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip,ordinal)).fetchone()
  if row is None:raise ValueError(f'Missing frame {clip}:{ordinal}')
  image=cv2.imdecode(np.frombuffer(row[0],np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2];l,t,r,b=[round(x*y) for x,y in zip(a.roi,(w,h,w,h))];search=image[t:b,l:r]
  if clip not in backgrounds:
   count=conn.execute('SELECT count(*) FROM frames WHERE clip_id=?',(clip,)).fetchone()[0];samples=[]
   for f in sorted({round((count-1)*v) for v in (0,.25,.5,.75,1)}):
    jpeg=conn.execute('SELECT jpeg FROM frames WHERE clip_id=? AND ordinal=?',(clip,f)).fetchone()[0]
    frame=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)[t:b,l:r]
    samples.append(cv2.resize(frame,None,fx=min(1.,960/search.shape[1]),fy=min(1.,960/search.shape[1])))
   backgrounds[clip]=np.median(np.array(samples),axis=0).astype(np.uint8)
  for method in a.methods:
   limit=int(method[4:]) if method.startswith('band') else 960
   started=time.perf_counter();regions=[]
   if method=='riders960':regions=rider_regions(image,object_model,(l,t,r,b))
   elif method=='motion960':regions=moving_regions(search,backgrounds[clip])
   elif method=='tiles960':
    for y in tile_starts(search.shape[0],640,192):
     for x in tile_starts(search.shape[1],960,256):regions.append((x,y,search[y:y+640,x:x+960]))
   else:regions=[(0,0,search)]
   candidates=[]
   for x,y,view in regions:
    for angle in a.detector_rotations:
     rotated=np.ascontiguousarray(np.rot90(view,angle//90))
     d=result_dict(list(det.predict(input=rotated,limit_side_len=limit,limit_type='max'))[0])
     for quad,score in zip(d.get('dt_polys',[]),d.get('dt_scores',[])):
      q=unrotate_quad(quad,view.shape,angle)+[l+x,t+y]
      if min(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[3]-q[0]))<5:continue
      candidates.append(dict(quad=q.tolist(),detector_score=float(score),detector_rotation=angle))
   kept=[]
   for d in sorted(candidates,key=lambda d:d['detector_score'],reverse=True):
    if not any(iou(d['quad'],k['quad'])>.5 for k in kept):kept.append(d)
   patches=[];metadata=[]
   for d in kept:
    patch=crop_quad(image,d['quad'])
    if patch is None:continue
    if max(patch.shape[:2])>1200:continue
    patches.append(patch);metadata.append(dict(**d,rotation=0))
    if a.try_rotations:
     for angle in (90,180,270):
      patches.append(np.ascontiguousarray(np.rot90(patch,angle//90)));metadata.append(dict(**d,rotation=angle))
   outputs=list(rec.predict(input=patches,batch_size=8)) if patches else [];reads=[]
   for index,(d,output,patch) in enumerate(zip(metadata,outputs,patches)):
    parsed=result_dict(output);text=parsed.get('rec_text','').strip();item=dict(**d,text=text,score=float(parsed.get('rec_score',0)));reads.append(item)
    if re.fullmatch('[0-9]{3}',text):
     filename=f'{clip}-{ordinal}-{method}-{index}-{text}.png';cv2.imwrite(str(a.output/filename),patch);item['crop_file']=filename
   result=dict(clip=clip,ordinal=ordinal,image_size=[w,h],received_ns=row[1],monotonic_ns=row[2],method=method,tile_count=len(regions),detections=len(kept),seconds=time.perf_counter()-started,readings=reads,numbers=[r['text'] for r in reads if re.fullmatch('[0-9]{3}',r['text'])])
   report['results'].append(result);report.update(total_wall_seconds=time.perf_counter()-run_started,total_cpu_seconds=time.process_time()-cpu_started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
   with (a.output/'frames.jsonl').open('a') as stream:stream.write(json.dumps(result,default=serial)+'\n')
   if len(report['results'])%20==0 or len(report['results'])==1:(a.output/'results.json').write_text(json.dumps(report,indent=2,default=serial)+'\n')
   print(clip,ordinal,method,'detections',len(kept),'numbers',[(r['text'],round(r['score'],3)) for r in reads if re.fullmatch('[0-9]{3}',r['text'])],'seconds',round(result['seconds'],2),flush=True)
 report['state']='complete';(a.output/'results.json').write_text(json.dumps(report,indent=2,default=serial)+'\n')
 conn.close()
if __name__=='__main__':main()
