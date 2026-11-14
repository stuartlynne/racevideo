"""Offline experiment for clip 109's cat-wheel fixture; not a general detector.

Requires optional numpy, opencv-python-headless and tesserocr. The main app does
not require these. Coordinates isolate the wheel; OCR is NOT constrained to the
visually checked expected numbers, so false candidates remain in the raw CSV.
"""
import argparse
from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path
import re
import sqlite3

import cv2
import numpy as np
from PIL import Image, ImageDraw
from tesserocr import PyTessBaseAPI, PSM


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--clip', type=int, default=109)
    p.add_argument('--out', required=True)
    p.add_argument('--tessdata', default='/usr/share/tesseract-ocr/5/tessdata')
    args = p.parse_args()
    out = Path(args.out)
    (out/'crops').mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f'file:{Path(args.db).resolve()}?mode=ro', uri=True)
    rows = connection.execute('SELECT ordinal,received_ns,monotonic_ns,jpeg FROM frames WHERE clip_id=? ORDER BY ordinal', (args.clip,))
    observations, candidates, start = [], 0, None
    with PyTessBaseAPI(path=args.tessdata, psm=PSM.SINGLE_WORD) as api:
        api.SetVariable('tessedit_char_whitelist', '0123456789')
        for ordinal, received, mono, jpeg in rows:
            if start is None: start = mono
            image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            white = cv2.inRange(hsv, (0,0,145), (180,90,255))
            contours, _ = cv2.findContours(white[300:715,220:650], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                contour = contour + np.array([[[220,300]]], dtype=np.int32)
                rect = cv2.minAreaRect(contour)
                (cx,cy),(w,h),angle = rect
                if not (165 <= np.hypot(cx-430,cy-520) <= 245): continue
                long,short = max(w,h),min(w,h)
                if not (22 <= long <= 90 and 10 <= short <= 45 and 1.35 <= long/max(short,1) <= 4.5): continue
                if cv2.contourArea(contour) < w*h*.42: continue
                box = cv2.boxPoints(rect)
                sums, diffs = box.sum(1), np.diff(box,axis=1).ravel()
                corners = np.array([box[np.argmin(sums)],box[np.argmin(diffs)],box[np.argmax(sums)],box[np.argmax(diffs)]],dtype='float32')
                width = round(max(np.linalg.norm(corners[1]-corners[0]),np.linalg.norm(corners[2]-corners[3])))
                height = round(max(np.linalg.norm(corners[3]-corners[0]),np.linalg.norm(corners[2]-corners[1])))
                if min(width,height)<8:continue
                dst=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],dtype='float32')
                crop = cv2.warpPerspective(image,cv2.getPerspectiveTransform(corners,dst),(width,height))
                if height>width: crop=cv2.rotate(crop,cv2.ROTATE_90_CLOCKWISE)
                candidates+=1
                name=f'{ordinal+1:04d}_{round(cx)}_{round(cy)}.png'
                for rotation in (0,180):
                    oriented=crop if rotation==0 else cv2.rotate(crop,cv2.ROTATE_180)
                    gray=cv2.cvtColor(oriented,cv2.COLOR_BGR2GRAY)
                    gray=cv2.resize(gray,None,fx=6,fy=6,interpolation=cv2.INTER_CUBIC)
                    variants={'gray':gray,'otsu':cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]}
                    for variant,patch in variants.items():
                        patch=cv2.copyMakeBorder(patch,18,18,18,18,cv2.BORDER_CONSTANT,value=255)
                        for mode in (PSM.SINGLE_WORD,PSM.SINGLE_LINE):
                            api.SetPageSegMode(mode)
                            api.SetImage(Image.fromarray(patch))
                            value=api.GetUTF8Text().strip()
                            if not re.fullmatch(r'\d{3}',value):continue
                            conf=api.MeanTextConf()
                            cv2.imwrite(str(out/'crops'/name),crop)
                            observations.append(dict(clip=args.clip,frame=ordinal+1,time_s=round((mono-start)/1e9,6),
                                                     received_ns=received,number=value,confidence=conf,
                                                     x=round(cx),y=round(cy),width=round(long),height=round(short),
                                                     rotation=rotation,variant=variant,psm=int(mode),crop='crops/'+name))
            if ordinal%50==0:print(f'frame {ordinal+1}, {candidates} regions, {len(observations)} candidate readings',flush=True)
    fields=['clip','frame','time_s','received_ns','number','confidence','x','y','width','height','rotation','variant','psm','crop']
    with (out/'ocr-candidates.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(observations)
    by_number=defaultdict(list)
    for hit in observations: by_number[hit['number']].append(hit)
    summary={number:dict(frames=len({h['frame'] for h in hits}),best_confidence=max(h['confidence'] for h in hits),
                         first_frame=min(h['frame'] for h in hits),last_frame=max(h['frame'] for h in hits),
                         best=max(hits,key=lambda h:h['confidence'])) for number,hits in by_number.items()}
    report=dict(clip=args.clip,regions=candidates,raw_readings=len(observations),numbers=summary,
                note='Targeted wheel-region experiment. Raw OCR includes false readings. Confidence is not a probability.')
    (out/'ocr-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    montage=Image.new('RGB',(960,360),'#202630');draw=ImageDraw.Draw(montage)
    for i,number in enumerate(('235','459','469')):
        hits=by_number[number]
        if not hits:continue
        best=max(hits,key=lambda h:h['confidence'])
        crop=Image.open(out/best['crop'])
        if best['rotation']==180:crop=crop.rotate(180)
        crop.thumbnail((290,150));crop=crop.resize((crop.width*5,crop.height*5))
        crop.thumbnail((290,180))
        montage.paste(crop,(i*320+15,60))
        draw.text((i*320+15,15),f"{number}: {summary[number]['frames']} frames",fill='white')
        draw.text((i*320+15,255),f"frame {best['frame']} | {best['width']}x{best['height']} native pixels",fill='white')
        draw.text((i*320+15,285),'Enlarged original crop; no detail generated',fill='#aebbc9')
    montage.save(out/'recognized-plates.jpg')
    print(json.dumps({k:{a:b for a,b in v.items() if a!='best'} for k,v in sorted(summary.items())},indent=2),flush=True)
    connection.close()


if __name__=='__main__':main()
