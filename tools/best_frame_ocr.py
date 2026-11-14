"""All-frame detection, geometry tracks, best-view GPU OCR. Read-only prototype."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2');os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK','True');os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
import argparse,json,sqlite3,time,resource,uuid
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw
from paddleocr import TextDetection,TextRecognition
import paddle
from racevideo.plate_selection import quality,ViewTracker,crop_quad,consensus,unrotate_quad
from tools.field_ocr_probe import result_dict,serial,tile_starts
cv2.setNumThreads(1)

def normalized(image):
 lo,hi=np.percentile(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(2,98))
 return np.clip((image.astype(np.float32)-lo)*255/max(1,hi-lo),0,255).astype(np.uint8)

def main():
 p=argparse.ArgumentParser();p.add_argument('store');p.add_argument('--clips',nargs='+',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--roi',nargs=4,type=float,default=[.34,.35,.60,.56]);p.add_argument('--best',type=int,default=5);p.add_argument('--cpu-cores',type=int,default=2);p.add_argument('--recognizer-model-dir',type=Path);p.add_argument('--models',type=Path);p.add_argument('--tiles',action='store_true');p.add_argument('--device',default='gpu:0');p.add_argument('--detector-limit',type=int,default=960);p.add_argument('--detector-rotations',nargs='+',type=int,choices=[0,90,180,270],default=[0]);p.add_argument('--recognizer-rotations',nargs='+',type=int,choices=[0,90,180,270],default=[0]);p.add_argument('--variants',nargs='+',choices=['raw','contrast'],default=['raw','contrast']);a=p.parse_args()
 if not 0<a.best<=10:p.error('best must be1..10')
 x0,y0,x1,y1=a.roi
 if not 0<=x0<x1<=1 or not 0<=y0<y1<=1:p.error('invalid ROI')
 if a.cpu_cores<1:p.error('cpu-cores must be positive')
 if hasattr(os,'sched_setaffinity'):os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:a.cpu_cores]))
 if a.device.startswith('gpu') and not paddle.is_compiled_with_cuda():raise RuntimeError('CUDA required for requested GPU device')
 paddle.set_device(a.device);a.output.mkdir(parents=True,exist_ok=True)
 start=time.perf_counter()
 runtime=dict(device=a.device,cpu_threads=a.cpu_cores,enable_mkldnn=False)
 det=TextDetection(model_name='PP-OCRv5_mobile_det',**runtime,**({'model_dir':str(a.models/'PP-OCRv5_mobile_det')} if a.models else {}))
 rec_path=a.recognizer_model_dir or (a.models/'PP-OCRv5_mobile_rec' if a.models else None)
 rec=TextRecognition(model_name='PP-OCRv5_mobile_rec',**runtime,**({'model_dir':str(rec_path.resolve())} if rec_path else {}));load=time.perf_counter()-start
 c=sqlite3.connect(Path(a.store).resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
 report=dict(recognizer_model_dir=str(a.recognizer_model_dir.resolve()) if a.recognizer_model_dir else None,run_id=uuid.uuid4().hex,engine='PP-OCRv5_mobile_det+rec',device=a.device,cpu_affinity=sorted(os.sched_getaffinity(0)),initialization_seconds=load,roi=a.roi,rotations=a.recognizer_rotations,detector_rotations=a.detector_rotations,detector_limit=a.detector_limit,tiles=a.tiles,variants=a.variants,best_views=a.best,clips=[])
 def get_image(clip,ordinal):
  row=c.execute('SELECT jpeg FROM frames WHERE clip_id=? AND ordinal=?',(clip,ordinal)).fetchone()
  return cv2.imdecode(np.frombuffer(row[0],np.uint8),cv2.IMREAD_COLOR)
 for clip in a.clips:
  started=time.perf_counter();cpu_start=resource.getrusage(resource.RUSAGE_SELF);times=dict(decode=0.,detection=0.,quality=0.,recognition=0.)
  frames=[dict(r) for r in c.execute('SELECT ordinal,received_ns,monotonic_ns FROM frames WHERE clip_id=? ORDER BY ordinal',(clip,))]
  if not frames or len(frames)>2000:raise ValueError('Clip must contain1..2000frames')
  tracker=ViewTracker(max_gap=3);counts=0;attempts=0
  for f in frames:
   begin=time.perf_counter();image=get_image(clip,f['ordinal']);h,w=image.shape[:2];left,top,right,bottom=round(x0*w),round(y0*h),round(x1*w),round(y1*h);search=image[top:bottom,left:right];times['decode']+=time.perf_counter()-begin
   found=[]
   regions=[(0,0,search)]
   if a.tiles:
    regions=[(x,y,search[y:y+640,x:x+960]) for y in tile_starts(search.shape[0],640,192) for x in tile_starts(search.shape[1],960,256)]
   for x,y,region in regions:
    for variant in a.variants:
     view=region if variant=='raw' else normalized(region)
     for angle in a.detector_rotations:
      begin=time.perf_counter();rotated=np.ascontiguousarray(np.rot90(view,angle//90));d=result_dict(list(det.predict(input=rotated,limit_side_len=a.detector_limit,limit_type='max'))[0]);attempts+=1;times['detection']+=time.perf_counter()-begin
      for quad in d.get('dt_polys',[]):
       q=unrotate_quad(quad,view.shape,angle)+[x,y];extent=np.ptp(q,axis=0)
       if min(extent)<8 or max(extent)<25:continue
       begin=time.perf_counter();metrics=quality(search,q);times['quality']+=time.perf_counter()-begin
       if metrics is None:continue
       found.append(dict(**f,quad=q.tolist(),source_quad=(q+[left,top]).tolist(),quality=metrics,detector_variant=variant,detector_rotation=angle))
   tracker.region_size=(search.shape[1],search.shape[0])
   counts+=len(found);tracker.update(f['ordinal'],found)
   if (f['ordinal']+1)%60==0:print(f"clip {clip}: detected through frame {f['ordinal']+1}/{len(frames)}",flush=True)
  results=[];cards=[];ocr_images=0
  for track in tracker.tracks:
   centers=np.array([np.mean(v['quad'],axis=0) for v in track.views]);motion=float(np.linalg.norm(np.ptp(centers,axis=0)))
   heights=[np.linalg.norm(np.array(v['quad'])[3]-np.array(v['quad'])[0]) for v in track.views]
   stationary=motion<max(8,float(np.median(heights))*.25)
   # Do not turn one isolated detection or stationary shelf print into a passing.
   eligible=len(track.views)>=2 and not stationary
   selected=track.selected(a.best) if eligible else []
   row=dict(encounter_id=f"{report['run_id']}:{clip}:{track.id}",track_id=track.id,closed_at=track.closed_at,end_reason=track.end_reason,first_ordinal=track.views[0]['ordinal'],last_ordinal=track.views[-1]['ordinal'],first_received_ns=track.views[0]['received_ns'],last_received_ns=track.views[-1]['received_ns'],detected_frames=len(track.views),motion_pixels=motion,stationary=stationary,selected=selected,readings=[])
   if selected:
    patches=[];metadata=[]
    for v in selected:
     begin=time.perf_counter();patch=crop_quad(get_image(clip,v['ordinal']),v['source_quad']);times['decode']+=time.perf_counter()-begin
     filename=f'clip-{clip}-track-{track.id}-frame-{v["ordinal"]}.png';cv2.imwrite(str(a.output/filename),patch);v['crop_file']=filename
     card=Image.fromarray(cv2.cvtColor(patch,cv2.COLOR_BGR2RGB));card.thumbnail((240,110));cards.append((track.id,v['ordinal'],card))
     for variant in a.variants:
      view=patch if variant=='raw' else normalized(patch)
      for angle in a.recognizer_rotations:patches.append(np.ascontiguousarray(np.rot90(view,angle//90)));metadata.append((v,variant,angle))
    begin=time.perf_counter();reads=list(rec.predict(input=patches,batch_size=8));times['recognition']+=time.perf_counter()-begin;ocr_images+=len(patches)
    if len(reads)!=len(metadata):raise RuntimeError('Recognition result/input count mismatch')
    for r,(v,variant,angle) in zip(reads,metadata):
     d=result_dict(r);row['readings'].append(dict(ordinal=v['ordinal'],received_ns=v['received_ns'],monotonic_ns=v['monotonic_ns'],variant=variant,rotation=angle,text=d.get('rec_text',''),score=float(d.get('rec_score',0)),source_quad=v['source_quad']))
   row['consensus']=consensus(row['readings']);results.append(row)
  cpu_end=resource.getrusage(resource.RUSAGE_SELF);wall=time.perf_counter()-started
  item=dict(clip=clip,frames=len(frames),detection_attempts=attempts,raw_detections=counts,tracks=len(results),recognition_images=ocr_images,wall_seconds=wall,cpu_seconds=(cpu_end.ru_utime+cpu_end.ru_stime-cpu_start.ru_utime-cpu_start.ru_stime),stage_seconds=times,results=results)
  report['clips'].append(item);report['peak_gpu_allocated_bytes']=paddle.device.cuda.max_memory_allocated() if a.device.startswith('gpu') else None;(a.output/'results.json').write_text(json.dumps(report,indent=2,default=serial)+'\n')
  sheet=Image.new('RGB',(1250,max(1,(len(cards)+4)//5)*145),'#202630');draw=ImageDraw.Draw(sheet)
  for i,(tid,ordinal,card) in enumerate(cards):
   x=i%5*250;y=i//5*145;sheet.paste(card,(x,y+30));draw.text((x+5,y+5),f'Track {tid} / GUI frame{ordinal+1}',fill='white')
  sheet.save(a.output/f'clip-{clip}-selected.jpg')
  print('clip',clip,'frames',len(frames),'seconds',round(wall,2),'recognition_images',ocr_images,'tracks',[(r['track_id'],r['consensus'],[v['ordinal'] for v in r['selected']]) for r in results if r['selected']],flush=True)
 c.close()
if __name__=='__main__':main()
