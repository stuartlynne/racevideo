"""Read-only export of sampled top-wheel regions for sequence diagnostics."""
import argparse,json
from pathlib import Path
from racevideo import storage
from racevideo.ocr import cv2,np

def main():
 p=argparse.ArgumentParser();p.add_argument('store');p.add_argument('output',type=Path);p.add_argument('--clips',type=int,nargs='+',required=True);p.add_argument('--stride',type=int,default=3);a=p.parse_args()
 if a.stride<1:p.error('stride must be positive')
 a.output.mkdir(parents=True,exist_ok=True);c=storage.connect(a.store,readonly=True);items=[]
 for clip in a.clips:
  for f in storage.frame_index(c,clip)[::a.stride]:
   image=cv2.imdecode(np.frombuffer(storage.read_frame(c,clip,f['ordinal']),np.uint8),cv2.IMREAD_COLOR);h,w=image.shape[:2]
   box=[round(.34*w),round(.35*h),round(.60*w),round(.56*h)];x0,y0,x1,y1=box
   name=f"clip-{clip}-frame-{f['ordinal']}";cv2.imwrite(str(a.output/(name+'.png')),image[y0:y1,x0:x1])
   items.append(dict(id=name,file=name+'.png',kind='region',expected=[],allowed_other_fixture_numbers=['235','469'],clip=clip,ordinal=f['ordinal'],received_ns=f['received_ns'],monotonic_ns=f['monotonic_ns'],box=box))
 manifest=dict(notes=['Unlabelled sequence diagnostic, not passing-level accuracy. Expected list empty means no exhaustive frame annotation.','Two physical fixture bibs are 235 and469; these are not passed to recognition.','Every third source frame by default: approximately10fps on30fps capture.'],items=items)
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Exported',len(items),'sampled regions')
 c.close()
if __name__=='__main__':main()
