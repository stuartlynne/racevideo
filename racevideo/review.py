"""Review geometry and off-thread rendering from original JPEG pixels."""
from dataclasses import dataclass
import io
import math
from PIL import Image, ImageEnhance


DISPLAY_DEFAULTS = dict(brightness=1.0, contrast=1.0, sharpness=1.0)
DISPLAY_RANGES = dict(brightness=(0.25, 3.0), contrast=(0.25, 3.0), sharpness=(0.0, 4.0))


def validate_display_adjustments(values=None):
    values=values or {};result={}
    for name,default in DISPLAY_DEFAULTS.items():
        value=values.get(name,default)
        if type(value) not in (int,float) or not math.isfinite(value) or not DISPLAY_RANGES[name][0]<=value<=DISPLAY_RANGES[name][1]:
            raise ValueError('Invalid display '+name)
        result[name]=float(value)
    return result


def adjust_display(image, values=None):
    """Enhance a bounded display image only; source JPEG evidence is untouched."""
    values=validate_display_adjustments(values)
    if values['brightness']!=1: image=ImageEnhance.Brightness(image).enhance(values['brightness'])
    if values['contrast']!=1: image=ImageEnhance.Contrast(image).enhance(values['contrast'])
    if values['sharpness']!=1: image=ImageEnhance.Sharpness(image).enhance(values['sharpness'])
    return image


@dataclass
class View:
    zoom: float = 1
    cx: float = .5
    cy: float = .5

    def bounds(self, source, canvas):
        sw,sh=source;cw,ch=canvas
        scale=min(cw/sw,ch/sh)*self.zoom
        w,h=sw*scale,sh*scale
        return cw/2-self.cx*w,ch/2-self.cy*h,w,h

    def clamp(self, source, canvas):
        _,_,w,h=self.bounds(source,canvas);cw,ch=canvas
        self.cx=max(cw/(2*w),min(1-cw/(2*w),self.cx)) if w>cw else .5
        self.cy=max(ch/(2*h),min(1-ch/(2*h),self.cy)) if h>ch else .5

    def zoom_at(self, factor, point, source, canvas):
        left,top,w,h=self.bounds(source,canvas);x,y=point;cw,ch=canvas
        u,v=(x-left)/w,(y-top)/h
        self.zoom=max(1,min(16,self.zoom*factor))
        _,_,w,h=self.bounds(source,canvas)
        self.cx=u-(x-cw/2)/w;self.cy=v-(y-ch/2)/h
        self.clamp(source,canvas)

    def pan(self, dx, dy, source, canvas):
        _,_,w,h=self.bounds(source,canvas)
        self.cx-=dx/w;self.cy-=dy/h
        self.clamp(source,canvas)


def render(jpeg, canvas, view, adjustments=None):
    with Image.open(io.BytesIO(jpeg)) as image:
        source=image.size
        transform=View(**view);transform.clamp(source,canvas)
        left,top,w,h=transform.bounds(source,canvas)
        cw,ch=canvas
        x0,y0=max(0,left),max(0,top)
        x1,y1=min(cw,left+w),min(ch,top+h)
        # Crop BEFORE enlargement: never allocate a zoom-sized full-frame image.
        box=(max(0,math.floor((x0-left)*source[0]/w)),max(0,math.floor((y0-top)*source[1]/h)),
             min(source[0],math.ceil((x1-left)*source[0]/w)),min(source[1],math.ceil((y1-top)*source[1]/h)))
        picture=image.crop(box).convert('RGB')
        picture=picture.resize((max(1,round(x1-x0)),max(1,round(y1-y0))),Image.Resampling.BILINEAR)
        picture=adjust_display(picture,adjustments)
        return picture,(left,top,w,h),((x0+x1)/2,(y0+y1)/2)
