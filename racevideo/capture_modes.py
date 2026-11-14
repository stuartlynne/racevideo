"""Read-only V4L2 MJPEG mode discovery and capture-test measurements."""
import ctypes as C
import errno
import os
from .camera import call, request


class Format(C.Structure):
    _fields_=[('index',C.c_uint32),('type',C.c_uint32),('flags',C.c_uint32),
              ('description',C.c_char*32),('pixel_format',C.c_uint32),('reserved',C.c_uint32*4)]


class Size(C.Structure):
    _fields_=[('index',C.c_uint32),('pixel_format',C.c_uint32),('type',C.c_uint32),
              ('values',C.c_uint32*6),('reserved',C.c_uint32*2)]


class Interval(C.Structure):
    _fields_=[('index',C.c_uint32),('pixel_format',C.c_uint32),('width',C.c_uint32),
              ('height',C.c_uint32),('type',C.c_uint32),('values',C.c_uint32*6),('reserved',C.c_uint32*2)]


def enumerate_modes(device):
    """Discrete camera modes only. Never starts or reconfigures the stream."""
    fd=os.open(device,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC)
    modes=[]
    def query(operation,value):
        try:return call(fd,operation,value)
        except OSError as exc:
            if exc.errno==errno.EINVAL:return None
            raise
    try:
        for f in range(64):
            fmt=query(request(2,Format),Format(index=f,type=1))
            if fmt is None:break
            if fmt.pixel_format!=int.from_bytes(b'MJPG','little'):continue
            for s in range(256):
                size=query(request(74,Size),Size(index=s,pixel_format=fmt.pixel_format))
                if size is None:break
                if size.type!=1:continue  # Do not invent discrete modes for ranges.
                width,height=size.values[:2]
                for i in range(128):
                    interval=query(request(75,Interval),Interval(index=i,pixel_format=fmt.pixel_format,width=width,height=height))
                    if interval is None:break
                    numerator,denominator=interval.values[:2]
                    if interval.type!=1 or not numerator or not denominator:continue
                    mode=dict(width=width,height=height,fps=denominator/numerator,format='MJPEG')
                    if mode not in modes:modes.append(mode)
        return sorted(modes,key=lambda m:(m['width']*m['height'],m['fps']),reverse=True)
    finally:os.close(fd)


def save_profile(path,profile):
    from . import storage
    from .service import recorder_running
    if recorder_running(path):raise ValueError('Stop the recorder before changing capture mode.')
    profile={k:profile[k] for k in ('device','width','height','fps')}
    if not any(m['width']==profile['width'] and m['height']==profile['height'] and abs(m['fps']-profile['fps'])<.01 for m in enumerate_modes(profile['device'])):
        raise ValueError('This MJPEG mode is not advertised by the selected camera. Refresh modes.')
    storage.write_setting(path,'capture_configuration',profile)
    return profile


def mode_label(mode):
    return f"{mode['width']}×{mode['height']} @ {mode['fps']:g} fps · MJPEG"


def assessment(status):
    requested=status.get('configuration',{})
    measured=status.get('capture_fps')
    if status.get('state')!='recording':return 'Recorder stopped — selected mode applies at next start.'
    if measured is None or status.get('capture_window_seconds',0)<2:return 'Measuring delivered frame rate…'
    import time
    if time.time_ns()-status.get('capture_metrics_ns',0)>3_000_000_000:return 'Capture measurements stale — check camera/recorder.'
    if any(status.get(k)!=requested.get(k,status.get(k)) for k in ('width','height')):return 'WARNING: delivered dimensions differ from requested mode.'
    target=requested.get('fps',status.get('requested_fps',0))
    negotiated=status.get('negotiated_fps')
    if target and negotiated is not None and abs(negotiated-target)>target*.05:return f'WARNING: driver reports {negotiated:g} fps; requested {target:g} fps.'
    if target and measured<target*.9:return f'WARNING: delivering {measured:.1f} fps; requested {target:g} fps.'
    if status.get('analysis_overrun_frames',0) or status.get('capture_bad_packets',0) or status.get('dropped_clips',0):return 'WARNING: frame/analysis/storage losses recorded; inspect performance counters.'
    if status.get('buffer_size_evictions',0) and status.get('buffer_seconds',0)<status.get('pre_roll',.5):return 'WARNING: compressed buffer is too short for the requested pre-roll.'
    return 'Currently meeting requested rate. Run for several minutes to test sustained capture.'


def frame_metrics(frames):
    stamps=[f.monotonic_ns for f in frames]
    gaps=[(b-a)/1e6 for a,b in zip(stamps,stamps[1:])]
    duration=(stamps[-1]-stamps[0])/1e9 if len(stamps)>1 else 0
    return dict(frames=len(stamps),duration_seconds=duration,
                stored_fps=(len(stamps)-1)/duration if duration>0 else None,
                max_frame_gap_ms=max(gaps,default=0))
