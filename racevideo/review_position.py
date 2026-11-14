"""Bounded, low-resolution first-subject positioning for newly opened clips.

This is a display convenience, not a bike detector or finish-time measurement.
Pillow motion silhouettes avoid starting an inference model when opening a clip.
"""
import io
import time
from PIL import Image, ImageChops, ImageFilter
from . import storage


def small(jpeg):
    with Image.open(io.BytesIO(jpeg)) as image:
        image.draft('L',(160,90));image.thumbnail((160,90))
        return image.convert('L').filter(ImageFilter.GaussianBlur(.7))


def subjects(image,background):
    if image.size!=background.size:return []
    w,h=image.size
    mask=ImageChops.difference(image,background).point([0]*20+[255]*236)
    # Ignore the sky and the outermost image borders. Join small silhouette gaps
    # before measuring blobs; wheels/rider need not be solid regions.
    mask=mask.filter(ImageFilter.MaxFilter(5))
    pixels=mask.load();seen=set();boxes=[]
    for y in range(int(h*.25),h-2):
        for x in range(2,w-2):
            if (x,y) in seen or not pixels[x,y]:continue
            stack=[(x,y)];seen.add((x,y));x0=x1=x;y0=y1=y;area=0
            while stack:
                px,py=stack.pop();area+=1
                x0=min(x0,px);x1=max(x1,px);y0=min(y0,py);y1=max(y1,py)
                for nx,ny in ((px-1,py),(px+1,py),(px,py-1),(px,py+1)):
                    if 2<=nx<w-2 and int(h*.25)<=ny<h-2 and (nx,ny) not in seen and pixels[nx,ny]:
                        seen.add((nx,ny));stack.append((nx,ny))
            if area>=80 and y1-y0>=h*.16 and x1-x0>=w*.08 and x0>=w*.05 and x1<=w*.95 and area<w*h*.55:
                boxes.append(dict(x=(x0+x1)/2/w,area=area,box=(x0,y0,x1,y1)))
    return sorted(boxes,key=lambda b:-b['area'])


def choose(connection,clip_id,index,cancel=lambda:False):
    started=time.perf_counter();decoded={}
    def result(ordinal,method):
        return dict(ordinal=ordinal,method=method,decoded_frames=len(decoded),milliseconds=(time.perf_counter()-started)*1000)
    if not index:return result(0,'empty')
    def frame(i):
        if i not in decoded:decoded[i]=small(storage.read_frame(connection,clip_id,index[i]['ordinal']))
        return decoded[i]
    # Long recordings/groups need only their first few seconds. Bound both frame
    # count and elapsed source time, rather than scanning an entire recording.
    first=index[0]['monotonic_ns'];end=next((i for i,r in enumerate(index) if r['monotonic_ns']-first>4_000_000_000),len(index))-1
    end=max(0,end);step=max(1,(end+11)//12)
    background=frame(0)
    samples=[];previous=None;lost=0
    for i in range(0,end+1,step):
        if cancel():return result(0,'cancelled')
        boxes=subjects(frame(i),background)
        if previous is None:
            if not boxes:continue
            selected=boxes[0]
        else:
            if not boxes:
                lost+=1
                if lost>=2:break
                continue
            selected=min(boxes,key=lambda b:abs(b['x']-previous))
            if abs(selected['x']-previous)>.5:break
        previous=selected['x'];lost=0;samples.append((i,selected))
        # Stop following once the first subject has passed centre; later bikes
        # must not replace it merely because their silhouette is larger.
        if len(samples)>1 and (samples[-2][1]['x']-.5)*(selected['x']-.5)<=0:break
    if samples:
        best=min(samples,key=lambda s:abs(s[1]['x']-.5))
        if len(samples)>=2 and max(s[1]['x'] for s in samples)-min(s[1]['x'] for s in samples)>.025:
            guess=best[0]
            if len(samples)>1:
                left,right=samples[-2:]
                if (left[1]['x']-.5)*(right[1]['x']-.5)<=0 and right[1]['x']!=left[1]['x']:
                    guess=round(left[0]+(.5-left[1]['x'])/(right[1]['x']-left[1]['x'])*(right[0]-left[0]))
            for i in sorted({max(0,min(end,guess+delta)) for delta in (-1,0,1)}):
                if cancel():return result(0,'cancelled')
                boxes=subjects(frame(i),background)
                if boxes:
                    candidate=min(boxes,key=lambda b:abs(b['x']-best[1]['x']))
                    if abs(candidate['x']-.5)<abs(best[1]['x']-.5):best=(i,candidate)
            return result(index[best[0]]['ordinal'],'first moving subject')
    # If foreground extraction is inconclusive, prefer evidence from the first
    # OCR encounter, then trigger/motion metadata. Never use a whole-clip midpoint
    # that may contain a later rider or an empty post-roll tail.
    rows=connection.execute('''SELECT o.ordinal,o.first_ns FROM ocr_observations o JOIN ocr_runs r ON r.id=o.run_id
      WHERE r.clip_id=? AND r.id=(SELECT MAX(id) FROM ocr_runs WHERE clip_id=? AND state='complete') ORDER BY o.first_ns,o.ordinal''',(clip_id,clip_id)).fetchall()
    if rows:return result(rows[0]['ordinal'],'first OCR encounter')
    clip=connection.execute('SELECT trigger_ns FROM clips WHERE id=?',(clip_id,)).fetchone()
    if clip:
        closest=min(index,key=lambda r:abs(r['received_ns']-clip['trigger_ns']))
        return result(closest['ordinal'],'trigger fallback')
    return result(index[0]['ordinal'],'first frame fallback')
