"""Bounded measured exposure/gain trials; no claim of universal optimality."""
import asyncio
from collections import Counter
import math
import time

from . import media

EXPOSURE_MODE=0x9A0901
EXPOSURE=0x9A0902
GAIN=0x980913
DYNAMIC_FPS=0x9A0903


async def fresh_sample(ops,store,after,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        jpeg,state=await asyncio.to_thread(ops.live,store)
        if state['last_frame_ns']/1e9>after:return jpeg,state
        await asyncio.sleep(.05)
    raise TimeoutError('No sufficiently fresh frame after camera change')


def ocr_score(jpeg,area,valid_numbers):
    from racevideo.ocr import Recognizer,propose
    import cv2
    import numpy as np
    image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
    recognizer=Recognizer();reads={}
    try:
        for proposal in propose(image,area or (0,0,1,1),limit=6):
            for result in recognizer.read(image,proposal):
                number=result['number']
                if result['confidence']>=60 and (not valid_numbers or number in valid_numbers):
                    reads[number]=max(reads.get(number,0),result['confidence'])
    finally:recognizer.close()
    return reads


async def tune(ops,jid,store,exposures=None,max_gain=128,min_median=40,area=None,
               use_ocr=False,valid_numbers=None,apply_best=True,cancel=None):
    if not 0<=max_gain<=100000 or not 1<=min_median<=200:raise ValueError('Invalid gain/visibility limits')
    if valid_numbers and any(not isinstance(n,str) or not 1<=len(n)<=3 or not n.isascii() or not n.isdigit() for n in valid_numbers):raise ValueError('Start-list numbers must be 1–3 digit strings')
    lock=ops.camera_locks[store]
    if lock.locked():raise ValueError('Another camera operation is in progress')
    async with lock:
        before=await asyncio.to_thread(ops.status,store)
        if not before['fresh']:raise ValueError('Start recorder before camera trials')
        controls={c['id']:c for c in before.get('camera_controls',[])}
        if EXPOSURE_MODE not in controls or EXPOSURE not in controls:raise ValueError('Camera has no supported manual exposure controls')
        if 1 not in [v['value'] for v in controls[EXPOSURE_MODE]['choices']]:raise ValueError('Manual exposure mode is unavailable')
        current=controls[EXPOSURE]['value'];definition=controls[EXPOSURE]
        def snap(value,c):
            return min(c['maximum'],max(c['minimum'],c['minimum']+round((value-c['minimum'])/c['step'])*c['step']))
        if exposures is None:exposures=sorted({snap(v,definition) for v in (5,math.sqrt(5*current),current/2,current)})
        if not 1<=len(exposures)<=6 or any(type(v) is not int or not definition['minimum']<=v<=definition['maximum'] for v in exposures):
            raise ValueError('Provide 1–6 valid integer raw exposure values')
        base_gain=controls.get(GAIN,{}).get('value')
        gain_cap=snap(min(max_gain,controls[GAIN]['maximum']),controls[GAIN]) if GAIN in controls else None
        trials=[(exposures[0],base_gain)]
        if gain_cap is not None and gain_cap!=base_gain:trials.append((exposures[0],gain_cap))
        trials.extend((exposure,gain_cap if gain_cap is not None else base_gain) for exposure in exposures[1:])
        trials=list(dict.fromkeys(trials))[:6]
        ids=[EXPOSURE_MODE,EXPOSURE]+([GAIN] if GAIN in controls else [])+([DYNAMIC_FPS] if DYNAMIC_FPS in controls else [])
        instances=await ops.reserve(store,ids,jid)
        starting={cid:controls[cid]['value'] for cid in ids}
        report=dict(store=store,session=before['session'],device=before.get('device'),configuration=before.get('configuration',{}),
                    before=starting,trials=[],selected=None,applied=False,restored=False,
                    objective='Shortest exposure satisfying sampled human visibility; prefer stable OCR when observed',
                    limitation='A sampled heuristic, not a calibrated OCR success rate or proof at race speed. Review images.',
                    score_is_proxy=True,start_list_constrained=bool(valid_numbers),settings_units='Exposure units are 100 microseconds')
        changed=False;keep=False;uncertain=False
        try:
            for exposure,gain in trials:
                if cancel and cancel.is_set():raise RuntimeError('Camera trial cancelled')
                changes=[dict(id=EXPOSURE_MODE,value=1),dict(id=EXPOSURE,value=exposure)]
                if GAIN in controls:changes.append(dict(id=GAIN,value=gain))
                if DYNAMIC_FPS in controls:changes.append(dict(id=DYNAMIC_FPS,value=0))
                result=await ops.camera_write(store,changes,jid,before['session'])
                changed=True
                uncertain=result['state']=='unknown'
                if result['state']!='succeeded':raise RuntimeError('Camera trial write failed or is uncertain: '+str(result))
                after=result['applied_at']+.3
                samples=[];votes=Counter()
                for sample_index in range(2):
                    jpeg,state=await fresh_sample(ops,store,after)
                    after=state['last_frame_ns']/1e9+.1
                    sample=await asyncio.to_thread(media.metrics,jpeg,area)
                    sample['human_preview']=(await asyncio.to_thread(media.metrics,jpeg,None) if area else sample.copy())
                    sample['received_ns']=state['last_frame_ns']
                    if use_ocr:
                        reads=await asyncio.to_thread(ocr_score,jpeg,area,valid_numbers)
                        sample['ocr']=reads;votes.update(reads.keys())
                    directory=ops.state_dir/'trials'/jid
                    directory.mkdir(parents=True,exist_ok=True)
                    filename=f"{len(report['trials'])}-{sample_index}.jpg"
                    await asyncio.to_thread((directory/filename).write_bytes,jpeg)
                    sample['sample_path']=f'/trials/{jid}/{filename}'
                    samples.append(sample)
                visible=all(s['human_preview']['median']>=min_median and s['human_preview']['highlight_fraction']<=.15 for s in samples)
                trial=dict(exposure=exposure,nominal_seconds=exposure/10000,gain=gain,visible=visible,samples=samples,
                           stable_numbers=sorted(k for k,v in votes.items() if v>=2))
                report['trials'].append(trial)
                ops.journal.update_job(jid,'running',report)
            if cancel and cancel.is_set():raise RuntimeError('Camera trial cancelled')
            eligible=[t for t in report['trials'] if t['visible']]
            with_reads=[t for t in eligible if t['stable_numbers']]
            if with_reads:eligible=with_reads
            if eligible:
                selected=min(eligible,key=lambda t:(t['exposure'],t['gain'] if t['gain'] is not None else 0))
                report['selected']=selected
                if apply_best:
                    changes=[dict(id=EXPOSURE_MODE,value=1),dict(id=EXPOSURE,value=selected['exposure'])]
                    if GAIN in controls:changes.append(dict(id=GAIN,value=selected['gain']))
                    if DYNAMIC_FPS in controls:changes.append(dict(id=DYNAMIC_FPS,value=0))
                    result=await ops.camera_write(store,changes,jid,before['session'])
                    if result['state']!='succeeded':raise RuntimeError('Best trial could not be confirmed')
                    keep=True;report['applied']=True;report['readback']=result
            else:report['reason']='No trial met the visibility threshold; starting settings retained'
        except Exception as exc:
            report['error']=str(exc)
        finally:
            if uncertain:
                report['restore_error']='Write outcome unknown; reconcile camera requests before another change'
            elif changed and not keep:
                try:
                    restore=[dict(id=EXPOSURE_MODE,value=1),dict(id=EXPOSURE,value=starting[EXPOSURE])]
                    if GAIN in starting:restore.append(dict(id=GAIN,value=starting[GAIN]))
                    if DYNAMIC_FPS in starting:restore.append(dict(id=DYNAMIC_FPS,value=starting[DYNAMIC_FPS]))
                    restore.append(dict(id=EXPOSURE_MODE,value=starting[EXPOSURE_MODE]))
                    result=await ops.camera_write(store,restore,jid,before['session'])
                    report['restored']=result['state']=='succeeded'
                    if not report['restored']:report['restore_error']=result
                except Exception as exc:report['restore_error']=str(exc)
            await ops.release(instances,jid)
        return report
