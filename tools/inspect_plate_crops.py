"""Manual localization experiment on clip 109, independent of the app runtime.

The two quadrilaterals were hand-selected on frame 46 and reused on nearby
frames. OCR receives digits 0–9, not a list of expected bibs. This demonstrates
crop readability, not automatic plate detection or race accuracy.
"""
import argparse
from collections import defaultdict
import csv
import io
import json
from pathlib import Path
import re
import sqlite3

import cv2
import numpy as np
from PIL import Image,ImageDraw
from tesserocr import PyTessBaseAPI,PSM


REGIONS={'top':[(498,328),(537,343),(527,363),(487,350)],
         'next':[(568,369),(591,395),(574,410),(551,385)]}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(f'file:{Path(args.db).resolve()}?mode=ro',uri=True)
    observations=[]; crops={}
    with PyTessBaseAPI(path='/usr/share/tesseract-ocr/5/tessdata',psm=PSM.SINGLE_LINE) as api:
        api.SetVariable('tessedit_char_whitelist','0123456789')
        for frame in range(40,55):
            jpeg=c.execute('SELECT jpeg FROM frames WHERE clip_id=109 AND ordinal=?',(frame-1,)).fetchone()[0]
            image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
            for region,points in REGIONS.items():
                quad=np.array(points,np.float32)
                width=float(np.linalg.norm(quad[1]-quad[0]));height=float(np.linalg.norm(quad[3]-quad[0]))
                crop=cv2.warpPerspective(image,cv2.getPerspectiveTransform(quad,np.array([[0,0],[299,0],[299,149],[0,149]],np.float32)),(300,150))
                crops[(frame,region)]=crop
                gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
                variants={'whole':gray,'trimmed':gray[:132,5:260], 'inset':gray[4:135,10:270]}
                for variant,patch in variants.items():
                    for threshold in (False,True):
                        v=cv2.threshold(patch,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1] if threshold else patch
                        for mode in (PSM.SINGLE_WORD,PSM.SINGLE_LINE):
                            api.SetPageSegMode(mode);api.SetImage(Image.fromarray(cv2.copyMakeBorder(v,20,20,20,20,cv2.BORDER_CONSTANT,value=255)))
                            text=api.GetUTF8Text().strip()
                            observations.append(dict(frame=frame,region=region,number=text,confidence=api.MeanTextConf(),
                                                     variant=variant,threshold=threshold,psm=int(mode),
                                                     native_width=round(width,1),native_height=round(height,1)))
    with (out/'manual-crop-ocr.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(observations[0]));writer.writeheader();writer.writerows(observations)
    summary={}
    for number in ('235','469'):
        hits=[o for o in observations if o['number']==number]
        if hits:
            best=max(hits,key=lambda o:o['confidence'])
            summary[number]=dict(distinct_frames=len({o['frame'] for o in hits}),readings=len(hits),best=best)
            cv2.imwrite(str(out/f'ocr-{number}-frame-{best["frame"]}.png'),crops[(best['frame'],best['region'])])
    (out/'manual-crop-summary.json').write_text(json.dumps(dict(clip=109,regions=REGIONS,numbers=summary,
        method='Hand-selected corners from frame 46 reused on frames 40–54. Expected bibs not supplied to OCR. '+
               'No automatic detection claim; raw CSV includes blank and incorrect reads.'),indent=2)+'\n')
    montage=Image.new('RGB',(1000,330),'#202630');d=ImageDraw.Draw(montage)
    for i,number in enumerate(('235','469')):
        if number not in summary:continue
        best=summary[number]['best'];im=Image.fromarray(cv2.cvtColor(crops[(best['frame'],best['region'])],cv2.COLOR_BGR2RGB))
        montage.paste(im,(i*500+30,65))
        d.text((i*500+30,18),f"OCR candidate {number} | frame {best['frame']} | confidence {best['confidence']}",fill='white')
        d.text((i*500+30,245),f"{best['native_width']} x {best['native_height']} source pixels; enlarged",fill='white')
        d.text((i*500+30,280),'Manual localization; original image data, perspective corrected',fill='#aebbc9')
    montage.save(out/'ocr-examples.jpg')
    print(json.dumps(summary,indent=2))
    c.close()


if __name__=='__main__':main()
