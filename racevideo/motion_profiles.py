"""One reduced decode, multiple motion comparisons and selectable event logic."""
import io
import time
import math
from PIL import Image,ImageChops,ImageFilter
from .motion import DEFAULT_ROI,validate_roi

MODES={'single':'Finish zone only','zones':'Entry / finish / exit — any zone',
       'road':'Wide road zone','entry_hold':'Entry / finish trigger, wide road hold'}


def validate_profile(value=None):
    value=value or {};mode=value.get('mode','single')
    if mode not in MODES:raise ValueError('Unknown motion behavior')
    defaults=dict(entry=(.78,.3,.95,1.0),exit=(.05,.3,.22,1.0),road=(.04,.3,.96,1.0))
    zones={name:list(validate_roi(value.get('zones',{}).get(name,roi))) for name,roi in defaults.items()}
    fractions={name:value.get('fractions',{}).get(name,.005 if name=='road' else None) for name in ('finish','entry','exit','road')}
    for fraction in fractions.values():
        if fraction is not None and (not isinstance(fraction,(int,float)) or not math.isfinite(fraction) or not 0<fraction<=1):raise ValueError('Changed fractions must be greater than 0 and at most 1')
    return dict(mode=mode,zones=zones,fractions=fractions)


def active_zones(profile,finish=DEFAULT_ROI):
    p=validate_profile(profile);zones=dict(p['zones'],finish=list(validate_roi(finish)))
    names={'single':('finish',),'zones':('entry','finish','exit'),'road':('road',),
           'entry_hold':('entry','finish','exit','road')}[p['mode']]
    return {name:zones[name] for name in names}


class MotionBank:
    def __init__(self,roi=DEFAULT_ROI,delta=18,fraction=.025,profile=None):
        self.delta=delta;self.fraction=fraction;self.reset(roi,profile)

    def reset(self,roi,profile=None):
        self.roi=validate_roi(roi)
        self.profile=validate_profile(profile if profile is not None else getattr(self,'profile',None))
        self.previous=None;self.zone_states=[];self.decode_ms=0;self.compare_ms=0

    def analyze(self,jpeg,event_active=False):
        began=time.perf_counter()
        with Image.open(io.BytesIO(jpeg)) as image:
            image.draft('L',(320,180));image.thumbnail((320,180))
            gray=image.convert('L').filter(ImageFilter.GaussianBlur(.8))
        self.decode_ms=(time.perf_counter()-began)*1000;began=time.perf_counter()
        previous,self.previous=self.previous,gray;w,h=gray.size;states=[]
        for name,roi in active_zones(self.profile,self.roi).items():
            x0,y0,x1,y1=roi;box=(int(x0*w),int(y0*h),max(int(x0*w)+1,int(x1*w)),max(int(y0*h)+1,int(y1*h)))
            current=gray.crop(box);score=0
            if previous is not None and previous.size==gray.size:
                histogram=ImageChops.difference(previous.crop(box),current).histogram()
                score=sum(histogram[self.delta:])/(current.width*current.height)
            threshold=self.profile['fractions'][name] if self.profile['fractions'][name] is not None else self.fraction
            states.append(dict(name=name,roi=list(roi),score=score,threshold=threshold,moving=score>=threshold))
        self.zone_states=states;by_name={s['name']:s['moving'] for s in states}
        detected=any(by_name.values())
        if self.profile['mode']=='entry_hold' and not event_active:
            detected=by_name.get('entry',False) or by_name.get('finish',False)
        self.compare_ms=(time.perf_counter()-began)*1000
        return detected,max((s['score'] for s in states),default=0)
