"""Deterministic qllabels-derived recognition data; real videos never enter it."""
import argparse,hashlib,importlib,json,sys,random
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw

def split_numbers():
 train=[];validation=[]
 for n in range(1000):
  text=f'{n:03d}'
  held= text in ('235','469') or int(hashlib.sha256(('racevideo-v1:'+text).encode()).hexdigest()[:8],16)%5==0
  (validation if held else train).append(text)
 return train,validation

def augment(master,seed):
 rng=np.random.default_rng(seed)
 h,w=master.shape;target_h=int(rng.integers(24,81));target_w=max(30,round(w/h*target_h*rng.uniform(.85,1.2)))
 im=cv2.resize(master,(target_w,target_h),interpolation=cv2.INTER_AREA)
 pad_x=int(rng.integers(2,max(4,target_w//8)));pad_y=int(rng.integers(1,max(3,target_h//10)))
 im=cv2.copyMakeBorder(im,pad_y,pad_y,pad_x,pad_x,cv2.BORDER_CONSTANT,value=255);h,w=im.shape
 src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
 offsets=rng.uniform(-1,1,(4,2)).astype(np.float32)*[w*.035,h*.06]
 im=cv2.warpPerspective(im,cv2.getPerspectiveTransform(src,(src+offsets).astype(np.float32)),(w,h),borderValue=255)
 angle=float(rng.uniform(-10,10));matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
 im=cv2.warpAffine(im,matrix,(w,h),borderValue=255)
 if rng.random()<.45:
  k=int(rng.choice([3,5,7]));kernel=np.zeros((k,k),np.float32)
  if rng.random()<.75:kernel[k//2,:]=1/k
  else:kernel[:,k//2]=1/k
  im=cv2.filter2D(im,-1,kernel)
 if rng.random()<.35:im=cv2.GaussianBlur(im,(3,3),float(rng.uniform(.3,1.2)))
 black=float(rng.uniform(0,38));white=float(rng.uniform(65,250));im=black+(white-black)*im.astype(np.float32)/255
 shading=np.linspace(float(rng.uniform(.7,1.1)),float(rng.uniform(.7,1.1)),w)[None,:]
 im=np.clip(im*shading+rng.normal(0,rng.uniform(.2,3),im.shape),0,255).astype(np.uint8)
 ok,encoded=cv2.imencode('.jpg',im,[cv2.IMWRITE_JPEG_QUALITY,int(rng.integers(50,96))])
 if not ok:raise RuntimeError('JPEG encode failed')
 return cv2.imdecode(encoded,cv2.IMREAD_GRAYSCALE)

def main():
 p=argparse.ArgumentParser();p.add_argument('--qllabels-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--variants',type=int,default=4);p.add_argument('--seed',type=int,default=20261105);a=p.parse_args()
 if a.output.exists():raise FileExistsError('Use a fresh output directory to retain prior data')
 sys.path.insert(0,str(a.qllabels_root.resolve()));ql=importlib.import_module('qllabels.qllabels');ql.LABEL_DPI=300
 # Obtain actual digit-area dimensions from both real layout functions.
 original=ql._render_bib_block;dimensions=[]
 def capture(text,width,height):dimensions.append((width,height));return original(text,width,height)
 ql._render_bib_block=capture;fields=ql.LabelFields(bib='000',event='RACEVIDEO TEST',participant='TEST RIDER')
 ql.render_frame_label(fields,ql.IMAGESIZE_300['62x100'],vertical_side='left');ql.render_body_label(fields,ql.IMAGESIZE_300['102x152']);ql._render_bib_block=original
 a.output.mkdir(parents=True);(a.output/'images').mkdir();train_numbers,val_numbers=split_numbers();rows={};cards=[]
 for split,numbers,count in [('train',train_numbers,a.variants),('val',val_numbers,2)]:
  lines=[]
  for number in numbers:
   for variant in range(count):
    dims=dimensions[variant%len(dimensions)];master=np.asarray(original(number,*dims))
    image=augment(master,a.seed+int(number)*100+variant+(0 if split=='train' else 10000000))
    filename=f'images/{split}-{number}-{variant}.png';cv2.imwrite(str(a.output/filename),image);lines.append(filename+'\t'+number)
    if len(cards)<36 and (int(number)%29==0 or number in ('235','469')):cards.append((number,image.copy()))
   if int(number)%200==0:print(split,number,flush=True)
  rows[split]=len(lines);(a.output/f'{split}.txt').write_text('\n'.join(lines)+'\n')
 manifest=dict(seed=a.seed,variants=a.variants,source=str(ql.__file__),source_sha256=hashlib.sha256(Path(ql.__file__).read_bytes()).hexdigest(),font=str(ql.DIN_ENG_FONT),font_sha256=hashlib.sha256(ql.DIN_ENG_FONT.read_bytes()).hexdigest(),digit_area_dimensions=dimensions,train_numbers=train_numbers,validation_numbers=val_numbers,real_test_numbers_excluded_from_training=['235','469'],counts=rows,notes=['Synthetic only. No real-video pixels or OCR labels enter training.','No180degree rotation augmentation: physical609/906ambiguity cannot be solved by forcing a label.','Includes geometric distortion, moderate directional blur, illumination/noise and JPEG degradation.'])
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 sheet=Image.new('RGB',(1000,((len(cards)+4)//5)*130),'#202630');d=ImageDraw.Draw(sheet)
 for i,(number,image) in enumerate(cards):
  im=Image.fromarray(image).convert('RGB');im.thumbnail((190,95));x=i%5*200;y=i//5*130;sheet.paste(im,(x+5,y+25));d.text((x+5,y+5),number,fill='white')
 sheet.save(a.output/'samples.jpg');print('Counts',rows,flush=True)
if __name__=='__main__':main()
