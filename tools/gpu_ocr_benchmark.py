"""Run independent GPU OCR diagnostics; never writes the production SQLite store.

Install neural engines in separate environments. Model downloads are from their
upstream repositories; input camera images remain local to the laptop.
"""
import argparse,json,os,re,time,platform,importlib.metadata
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('OMP_THREAD_LIMIT','2')
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK','True')
import cv2
import numpy as np
cv2.setNumThreads(2)

def serial(value):
 if hasattr(value,'tolist'):return value.tolist()
 if isinstance(value,Path):return str(value)
 raise TypeError(type(value).__name__)

def result_dict(result):
 value=result.json
 if callable(value):value=value()
 if isinstance(value,str):value=json.loads(value)
 return value.get('res',value)

def main():
 p=argparse.ArgumentParser();p.add_argument('--engine',choices=['easyocr','paddleocr'],required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--recognizer-model-dir',type=Path);a=p.parse_args()
 manifest=json.loads((a.fixture/'manifest.json').read_text());started=time.perf_counter();models={}
 if a.engine=='easyocr':
  import torch,easyocr
  torch.set_num_threads(2)
  if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; refusing silent CPU benchmark')
  models['reader']=easyocr.Reader(['en'],gpu=True,verbose=False)
  device=torch.cuda.get_device_name(0)
  def recognize(image,kind):
   if kind=='plate':results=models['reader'].recognize(image,allowlist='0123456789',detail=1,batch_size=1)
   else:results=models['reader'].readtext(image,allowlist='0123456789',detail=1,batch_size=1,min_size=5,canvas_size=1280,mag_ratio=1.5)
   return [dict(text=str(r[1]),score=float(r[2]),box=r[0]) for r in results]
 else:
  import paddle
  from paddleocr import TextRecognition,PaddleOCR
  if not paddle.is_compiled_with_cuda():raise RuntimeError('CUDA unavailable')
  paddle.set_device('gpu:0');device=paddle.device.cuda.get_device_name()
  # Keep document processors disabled: these are small race labels, not pages.
  models['rec']=TextRecognition(model_name='PP-OCRv5_mobile_rec',device='gpu:0',**({'model_dir':str(a.recognizer_model_dir.resolve())} if a.recognizer_model_dir else {}))
  models['pipeline']=PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',text_recognition_model_name='PP-OCRv5_mobile_rec',**({'text_recognition_model_dir':str(a.recognizer_model_dir.resolve())} if a.recognizer_model_dir else {}),use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,device='gpu:0')
  def recognize(image,kind):
   if kind=='plate':
    results=list(models['rec'].predict(input=image,batch_size=1));out=[]
    for r in results:
     d=result_dict(r);out.append(dict(text=d.get('rec_text',''),score=float(d.get('rec_score',0))))
    return out
   results=list(models['pipeline'].predict(input=image));out=[]
   for r in results:
    d=result_dict(r)
    for text,score in zip(d.get('rec_texts',[]),d.get('rec_scores',[])):out.append(dict(text=text,score=float(score)))
   return out
 report=dict(engine=a.engine,recognizer_model_dir=str(a.recognizer_model_dir.resolve()) if a.recognizer_model_dir else None,version=importlib.metadata.version(a.engine),python=platform.python_version(),device=device,initialization_seconds=time.perf_counter()-started,notes=manifest['notes'],results=[])
 for item in manifest['items']:
  image=cv2.imread(str(a.fixture/item['file']))
  if image is None:raise FileNotFoundError(item['file'])
  lo,hi=np.percentile(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(2,98))
  contrast=np.clip((image.astype(np.float32)-lo)*255/max(1,hi-lo),0,255).astype(np.uint8)
  for variant,view in [('raw',image),('contrast',contrast)]:
   start=time.perf_counter();readings=recognize(view,item['kind']);elapsed=time.perf_counter()-start
   numbers=list(dict.fromkeys(r['text'].strip() for r in readings if re.fullmatch(r'\d{3}',r['text'].strip())))
   allowed=set(item['expected'])|set(item.get('allowed_other_fixture_numbers',[]))
   row=dict(id=item['id'],kind=item['kind'],expected=item['expected'],variant=variant,seconds=elapsed,readings=readings,numbers=numbers,matched=[n for n in item['expected'] if n in numbers],unexpected=[n for n in numbers if n not in allowed])
   report['results'].append(row)
   a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2,default=serial)+'\n')
   print(item['id'],variant,numbers,round(elapsed,3),flush=True)
 if a.engine=='easyocr':report['peak_gpu_allocated_bytes']=torch.cuda.max_memory_allocated()
 else:report['peak_gpu_allocated_bytes']=paddle.device.cuda.max_memory_allocated()
 a.output.write_text(json.dumps(report,indent=2,default=serial)+'\n')
if __name__=='__main__':main()
