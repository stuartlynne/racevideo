"""Evaluate a baseline or exported model against fixed synthetic held-out labels."""
import os
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK','True');os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True');os.environ.setdefault('OMP_NUM_THREADS','2')
import argparse,json,time
from pathlib import Path
import cv2
from paddleocr import TextRecognition
from tools.gpu_ocr_benchmark import result_dict

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--model-dir',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 rows=[line.split('\t') for line in (a.data/'val.txt').read_text().splitlines()]
 model=TextRecognition(model_name='PP-OCRv5_mobile_rec',device='gpu:0',**({'model_dir':str(a.model_dir.resolve())} if a.model_dir else {}))
 started=time.perf_counter();results=[]
 for first in range(0,len(rows),8):
  group=rows[first:first+8];images=[cv2.imread(str(a.data/file)) for file,label in group]
  predicted=list(model.predict(input=images,batch_size=8))
  for (file,label),prediction in zip(group,predicted):
   d=result_dict(prediction);text=d.get('rec_text','').strip();results.append(dict(file=file,label=label,text=text,score=float(d.get('rec_score',0)),correct=text==label))
 report=dict(model_dir=str(a.model_dir.resolve()) if a.model_dir else 'upstream cached PP-OCRv5_mobile_rec',samples=len(results),correct=sum(r['correct'] for r in results),accuracy=sum(r['correct'] for r in results)/len(results),wall_seconds=time.perf_counter()-started,results=results)
 a.output.write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='results'})
if __name__=='__main__':main()
