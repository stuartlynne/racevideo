from fractions import Fraction
import io
from pathlib import Path
import statistics

from PIL import Image,ImageDraw,ImageFilter,ImageStat

from racevideo import storage


def region(image,crop=None):
    if crop is None:return image.copy()
    if len(crop)!=4 or not 0<=crop[0]<crop[2]<=1 or not 0<=crop[1]<crop[3]<=1:
        raise ValueError('Crop must be normalized left,top,right,bottom inside the image')
    w,h=image.size
    return image.crop((int(crop[0]*w),int(crop[1]*h),max(int(crop[0]*w)+1,int(crop[2]*w)),
                       max(int(crop[1]*h)+1,int(crop[3]*h))))


def metrics(jpeg,crop=None):
    with Image.open(io.BytesIO(jpeg)) as source:
        image=region(source,crop).convert('L');image.thumbnail((640,480))
    histogram=image.histogram();total=sum(histogram)
    def percentile(fraction):
        count=0
        for value,n in enumerate(histogram):
            count+=n
            if count>=fraction*total:return value
        return 255
    return dict(mean=round(ImageStat.Stat(image).mean[0],2),p05=percentile(.05),median=percentile(.5),
                p95=percentile(.95),shadow_fraction=round(sum(histogram[:16])/total,4),
                highlight_fraction=round(sum(histogram[245:])/total,4),
                edge_stddev=round(ImageStat.Stat(image.filter(ImageFilter.FIND_EDGES)).stddev[0],3),
                note='Brightness and edge energy are image-quality proxies, not calibrated OCR accuracy or motion blur.')


def render(jpeg,crop=None,max_width=1280):
    if not 64<=max_width<=4096:raise ValueError('max_width must be 64–4096')
    with Image.open(io.BytesIO(jpeg)) as original:
        image=region(original,crop).convert('RGB')
        if image.width>max_width:image.thumbnail((max_width,max_width*4))
    out=io.BytesIO();image.save(out,'JPEG',quality=90)
    return out.getvalue(),dict(width=image.width,height=image.height,crop=crop)


def contact_sheet(path,clip_id,count=8):
    if not 1<=count<=12:raise ValueError('Contact sheets allow 1–12 frames')
    c=storage.connect(path,readonly=True)
    try:
        index=storage.frame_index(c,clip_id)
        if not index:raise ValueError('Unknown or empty clip')
        start,end=index[0]['monotonic_ns'],index[-1]['monotonic_ns']
        selected=[]
        for i in range(count):
            target=start+(end-start)*i/max(1,count-1)
            selected.append(min(index,key=lambda r:abs(r['monotonic_ns']-target)))
        columns=min(3,count);rows=(count+columns-1)//columns
        sheet=Image.new('RGB',(columns*400,rows*250),'#202630');draw=ImageDraw.Draw(sheet)
        for i,item in enumerate(selected):
            with Image.open(io.BytesIO(storage.read_frame(c,clip_id,item['ordinal']))) as source:
                image=source.convert('RGB');image.thumbnail((396,220))
            x,y=i%columns*400,i//columns*250
            sheet.paste(image,(x+(400-image.width)//2,y))
            draw.text((x+5,y+225),f"frame {item['ordinal']} · +{(item['monotonic_ns']-start)/1e9:.3f}s",fill='white')
        out=io.BytesIO();sheet.save(out,'JPEG',quality=88)
        return out.getvalue(),[dict(ordinal=r['ordinal'],received_ns=r['received_ns'],monotonic_ns=r['monotonic_ns']) for r in selected]
    finally:c.close()


def export_mp4(path,clip_id,output,max_width=1920):
    import av
    c=storage.connect(path,readonly=True);output=Path(output)
    temporary=output.with_suffix('.partial.mp4')
    try:
        index=storage.frame_index(c,clip_id)
        if not index:raise ValueError('Unknown or empty clip')
        first=storage.read_frame(c,clip_id,index[0]['ordinal'])
        with Image.open(io.BytesIO(first)) as image:w,h=image.size
        scale=min(1,max_width/w);w=max(2,int(w*scale)//2*2);h=max(2,int(h*scale)//2*2)
        differences=[b['monotonic_ns']-a['monotonic_ns'] for a,b in zip(index,index[1:])]
        rate=max(1,min(120,round(1e9/statistics.median(differences)))) if differences else 30
        output.parent.mkdir(parents=True,exist_ok=True)
        with av.open(str(temporary),'w',options={'movflags':'+faststart'}) as container:
            stream=container.add_stream('libx264',rate=rate)
            stream.width=w;stream.height=h;stream.pix_fmt='yuv420p'
            stream.codec_context.time_base=Fraction(1,1_000_000)
            stream.options={'preset':'ultrafast','crf':'23','threads':'1'}
            start=index[0]['monotonic_ns'];last=-1
            for item in index:
                with Image.open(io.BytesIO(storage.read_frame(c,clip_id,item['ordinal']))) as image:
                    frame=av.VideoFrame.from_image(image.convert('RGB')).reformat(width=w,height=h,format='yuv420p')
                pts=max(last+1,round((item['monotonic_ns']-start)/1000));last=pts
                frame.pts=pts;frame.time_base=Fraction(1,1_000_000)
                for packet in stream.encode(frame):container.mux(packet)
            for packet in stream.encode():container.mux(packet)
        temporary.replace(output)
        return dict(path=str(output),bytes=output.stat().st_size,width=w,height=h,frames=len(index),
                    time_coordinate='original host monotonic frame intervals',derivative=True)
    finally:
        c.close()
        temporary.unlink(missing_ok=True)
