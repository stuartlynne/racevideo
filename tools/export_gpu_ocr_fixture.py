"""Export the operator-reviewed wheel diagnostic fixture, read-only SQLite access.

Fixture is deliberately selected, not a held-out race accuracy dataset. Images
stay outside source control. Plate crops separate recognition from detection.
"""
import argparse,json
from pathlib import Path
from racevideo import storage
from racevideo.ocr import cv2,np,rectify

def main():
 p=argparse.ArgumentParser();p.add_argument('store');p.add_argument('output',type=Path);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=True);c=storage.connect(a.store,readonly=True);items=[]
 def source(clip,ordinal):return cv2.imdecode(np.frombuffer(storage.read_frame(c,clip,ordinal),np.uint8),cv2.IMREAD_COLOR)
 def save(name,image,expected,kind,clip,ordinal,**extra):
  cv2.imwrite(str(a.output/(name+'.png')),image)
  items.append(dict(id=name,file=name+'.png',expected=expected,kind=kind,clip=clip,ordinal=ordinal,**extra))
 for clip,run in ((50,14),(52,15)):
  for number in ('235','469'):
   r=c.execute('SELECT * FROM ocr_reads WHERE run_id=? AND number=? AND confidence>=60 ORDER BY confidence DESC LIMIT 1',(run,number)).fetchone()
   if r is None:raise RuntimeError((clip,run,number))
   quad=np.array(json.loads(r['quad']),np.float32);image=rectify(source(clip,r['ordinal']),quad)
   if r['rotation']==180:image=cv2.rotate(image,cv2.ROTATE_180)
   save(f'slow-{clip}-{number}',image,[number],'plate',clip,r['ordinal'],quad=quad.tolist(),selection='Previously visually checked fixture plates; selected from successful baseline proposals')
 image=source(81,68);save('dim-81-frame69-235',image[1010:1170,1740:2000],['235'],'plate',81,68,box=[1740,1010,2000,1170],selection='Operator-selected GUI frame69/78, manually inspected crop')
 r=c.execute("SELECT quad FROM ocr_reads WHERE run_id=26 AND ordinal=62 AND number='469' LIMIT 1").fetchone();q=np.array(json.loads(r['quad']),np.float32)
 save('dim-81-frame63-469',rectify(source(81,62),q),['469'],'plate',81,62,quad=q.tolist())
 save('blur-71-frame110-469',source(71,109)[890:1040,1710:1940],['469'],'plate',71,109,box=[1710,890,1940,1040],selection='Visually checked blurred moving plate')
 # Preserve a full search region separately. Ground truth is limited to the
 # clearly visible target; other valid fixture bibs are not called false reads.
 for clip,ordinal,target in ((81,68,'235'),(81,62,'469'),(71,109,'469')):
  image=source(clip,ordinal);h,w=image.shape[:2];box=[round(.34*w),round(.35*h),round(.60*w),round(.56*h)];x0,y0,x1,y1=box
  save(f'region-{clip}-{ordinal}',image[y0:y1,x0:x1],[target],'region',clip,ordinal,box=box,allowed_other_fixture_numbers=['235','469'])
 for clip,ordinal in ((71,95),(81,30)):
  image=source(clip,ordinal);h,w=image.shape[:2];box=[round(.34*w),round(.35*h),round(.60*w),round(.56*h)];x0,y0,x1,y1=box
  save(f'empty-{clip}-{ordinal}',image[y0:y1,x0:x1],[],'negative',clip,ordinal,box=box)
 manifest=dict(font='DIN 1451 Engschrift Regular (operator supplied identification; font file not yet located)',notes=['Selected diagnostic examples, not a held-out accuracy benchmark.','No expected numbers are passed to recognition engines. Only a digit character allowlist is used.','Regions annotate one clear target and permit the two actual fixture bibs; not exhaustive object annotations.'],items=items)
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Exported',len(items),'images');c.close()
if __name__=='__main__':main()
