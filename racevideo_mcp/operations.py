import asyncio
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import uuid

from racevideo import storage
from racevideo.motion import validate_roi
from racevideo.service import configuration,recorder_running,start_recorder,start_ocr,OPTIONS
from . import media


class Operations:
    def __init__(self,stores,state_dir,hub,journal):
        self.stores={name:Path(path).expanduser().resolve() for name,path in stores.items()}
        self.state_dir=Path(state_dir);self.hub=hub;self.journal=journal
        self.camera_locks={name:asyncio.Lock() for name in stores}
        self.tasks=set();self.heavy=asyncio.Semaphore(1)
        self.cancellations={}
        self.lease_owners={}
        self.lease_stores={}
        for path in self.stores.values():
            if path.exists():
                c=storage.connect(path)
                try:storage.initialize(c)
                finally:c.close()

    def path(self,store):
        if store not in self.stores:raise ValueError('Unknown configured recording store')
        return self.stores[store]

    @contextmanager
    def db(self,store,write=False):
        c=storage.connect(self.path(store),readonly=not write)
        try:yield c
        finally:c.close()

    def status(self,store='default'):
        path=self.path(store)
        if not path.exists():return dict(store=store,exists=False,recorder_running=False)
        with self.db(store) as c:
            result=storage.read_runtime(c);result.pop('preview',None)
            result['capture_configuration']=storage.read_setting(c,'capture_configuration',{})
            result.update(store=store,exists=True,recorder_running=recorder_running(path),
                          clips=c.execute('SELECT COUNT(*) FROM clips').fetchone()[0])
        result['fresh']=bool(result.get('state')=='recording' and time.time()-result.get('heartbeat',0)<2.5 and
                             time.time()-result.get('last_frame_ns',0)/1e9<2.5)
        return result

    def live(self,store='default'):
        with self.db(store) as c:state=storage.read_runtime(c)
        jpeg=state.pop('preview',None)
        # Original live JPEGs have their own latest-only channel. A large clip
        # transaction must not make an otherwise current camera sample stale.
        from racevideo.pipeline import PreviewSource
        source = None
        try:
            source = PreviewSource(self.path(store))
            sample = source.read(0)
            if sample and time.time()-sample[0]/1e9 < 2.5 and recorder_running(self.path(store)):
                state['last_frame_ns'] = sample[0]
                state['runtime_stale'] = time.time()-state.get('heartbeat',0) > 2.5
                return sample[2],state
        except (OSError,ValueError):
            pass
        finally:
            if source: source.close()
        if (state.get('state')!='recording' or time.time()-state.get('heartbeat',0)>2.5 or
                time.time()-state.get('last_frame_ns',0)/1e9>2.5 or jpeg is None):
            raise ValueError('No fresh live frame; start or reconnect the recorder')
        return jpeg,state

    def clips(self,store='default',after_id=0,limit=25,day=None,bibs=(),starred_only=False):
        if not 1<=limit<=100:raise ValueError('limit must be 1–100')
        with self.db(store) as c:
            rows=storage.browse_clips(c,day,bibs,starred_only,thumbnails=False,after_id=after_id,limit=limit)
        for row in rows:row['started_utc']=datetime.fromtimestamp(row['started_ns']/1e9,timezone.utc).isoformat()
        return dict(store=store,clips=rows,next_after=rows[-1]['id'] if rows else after_id,
                    day=day,bibs=list(bibs),evidence_note='Machine candidates plus operator bib reviews; matching clips are not verified lap counts')

    def star(self,store,clip_id,starred):
        storage.set_star(self.path(store),clip_id,starred)
        return dict(clip_id=clip_id,starred=starred)

    def clip_info(self,store,clip_id):
        with self.db(store) as c:
            row=c.execute('SELECT * FROM clips WHERE id=?',(clip_id,)).fetchone()
            if not row:raise ValueError('Unknown clip')
            result=dict(row);result.pop('thumbnail')
            metadata=c.execute('SELECT metadata FROM clip_details WHERE clip_id=?',(clip_id,)).fetchone()
            result['metadata']=json.loads(metadata[0]) if metadata else None
            result['ocr']=storage.read_ocr_run(c,clip_id)
            result['tag_matches']=[dict(r) for r in c.execute('SELECT * FROM reviewed_video_tag_matches WHERE video_set_id=? ORDER BY tag_id',(clip_id,))]
            result['machine_tag_matches']=[dict(r) for r in c.execute('SELECT * FROM video_tag_matches WHERE video_set_id=? ORDER BY tag_id',(clip_id,))]
            from racevideo import bib_review
            result['bib_reviews']=bib_review.list_rows(c,clip_id)
            annotation=c.execute('SELECT starred FROM clip_annotations WHERE clip_id=?',(clip_id,)).fetchone()
            result['starred']=bool(annotation and annotation[0])
            result['timestamp_note']='Host receipt/monotonic times; not calibrated finish-line or exposure times'
            return result

    def frames(self,store,clip_id,offset=0,limit=100):
        if offset<0 or not 1<=limit<=200:raise ValueError('Invalid frame pagination')
        with self.db(store) as c:
            return [dict(row) for row in c.execute('SELECT ordinal,received_ns,monotonic_ns,source_pts,time_base '
                                                  'FROM frames WHERE clip_id=? ORDER BY ordinal LIMIT ? OFFSET ?',
                                                  (clip_id,limit,offset))]

    def frame(self,store,clip_id,ordinal,crop=None,max_width=1280):
        with self.db(store) as c:
            row=c.execute('SELECT received_ns,monotonic_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip_id,ordinal)).fetchone()
            if row is None:raise ValueError('Unknown frame (ordinals are zero based)')
            jpeg=storage.read_frame(c,clip_id,ordinal)
        rendered,metadata=media.render(jpeg,crop,max_width)
        return rendered,dict(metadata,store=store,clip_id=clip_id,ordinal=ordinal,**dict(row))

    def settings(self,store):
        result=self.status(store)
        with self.db(store) as c:
            return dict(configuration=configuration(result),motion_roi=storage.read_setting(c,'motion_roi',(.425,.15,.575,.85)),
                        ocr_area=storage.read_setting(c,'ocr_area',(0,0,1,1)),ocr_rotations=storage.read_setting(c,'ocr_rotations',[0,180]),camera=result.get('camera_controls',[]),
                        fresh=result['fresh'])

    async def reserve(self,store,ids,lease_id):
        instances=self.hub.for_store(store)
        acquired=[]
        try:
            for iid in instances:
                if self.hub.instances[iid].get('snapshot',{}).get('camera_lease_protocol',0)<2:
                    raise ValueError('Restart this GUI to enable queued camera-request revocation')
                result=await self.hub.call(iid,'camera.reserve',dict(control_ids=list(ids),lease_id=lease_id))
                if result['state']!='succeeded':raise ValueError(result.get('error') or 'Camera reservation failed')
                acquired.append(iid)
            await asyncio.to_thread(storage.renew_control_lease,self.path(store),lease_id)
            self.lease_owners.setdefault(lease_id,set()).update(acquired)
            self.lease_stores[lease_id]=store
            return acquired
        except Exception:
            await self.release(acquired,lease_id)
            raise

    async def release(self,instances,lease_id):
        instances=set(instances)|self.lease_owners.pop(lease_id,set())
        store=self.lease_stores.pop(lease_id,None)
        if store is not None:await asyncio.to_thread(storage.revoke_control_leases,self.path(store),[lease_id])
        for iid in instances:
            if iid in self.hub.instances and self.hub.ready(self.hub.instances[iid]):
                await self.hub.call(iid,'camera.release',dict(lease_id=lease_id))

    async def camera_write(self,store,changes,lease_id,expected_session=None):
        state=await asyncio.to_thread(self.status,store)
        if not state['fresh']:raise ValueError('Recorder must be running and delivering fresh frames')
        if state.get('control_protocol',0)<3:raise ValueError('Restart recorder to enable deadline/lease-aware camera commands')
        if expected_session and state['session']!=expected_session:raise ValueError('Recorder session changed')
        known={c['id']:c for c in state.get('camera_controls',[])}
        if not 1<=len(changes)<=16:raise ValueError('Provide 1–16 ordered changes')
        for change in changes:
            cid,value=change.get('id'),change.get('value')
            if cid not in known or type(value) is not int:raise ValueError('Unknown camera control or noninteger value')
            control=known[cid]
            if not control['minimum']<=value<=control['maximum']:raise ValueError('Camera value outside range')
            if control['type'] in (3,9):
                if value not in [choice['value'] for choice in control['choices']]:raise ValueError('Invalid camera menu value')
            elif (value-control['minimum'])%control['step']:raise ValueError('Camera value does not match supported step')
        await self.reserve(store,[c['id'] for c in changes],lease_id)  # Renew/check operator takeover.
        def submit():
            return storage.request_camera_batch(self.path(store),state['session'],changes,time.time()+4,lease_id)
        request_ids=await asyncio.to_thread(submit)
        deadline=time.monotonic()+5;results=[]
        while time.monotonic()<deadline:
            with self.db(store) as c:results=storage.camera_results(c,set(request_ids))
            if len(results)==len(request_ids):break
            await asyncio.sleep(.05)
        if len(results)!=len(request_ids):
            return dict(state='unknown',request_ids=request_ids,error='Camera reply unavailable; reconcile requests, do not replay')
        return dict(state='failed' if any(r['error'] for r in results) else 'succeeded',requests=results,
                    session=state['session'],applied_at=max(r['processed'] for r in results))

    async def set_camera(self,store,changes,command_id=None):
        self.path(store)
        cid=command_id or uuid.uuid4().hex
        record,new=self.journal.command(cid,store,'camera.set',changes)
        if not new:return record
        if self.camera_locks[store].locked():
            self.journal.command_result(cid,'failed',error='Camera operation already in progress')
            return self.journal.get_command(cid)
        async with self.camera_locks[store]:
            instances=[]
            try:
                instances=await self.reserve(store,[c['id'] for c in changes],cid)
                result=await self.camera_write(store,changes,cid)
                self.journal.command_result(cid,result['state'],result,error=result.get('error'))
            except Exception as exc:self.journal.command_result(cid,'failed',error=str(exc))
            finally:await self.release(instances,cid)
        return self.journal.get_command(cid)

    async def recorder(self,store,operation,changes=None,command_id=None):
        cid=command_id or uuid.uuid4().hex;changes=changes or {}
        record,new=self.journal.command(cid,store,'recorder.'+operation,changes)
        if not new:return record
        try:
            state=await asyncio.to_thread(self.status,store)
            if operation=='start':
                for iid in self.hub.for_store(store):
                    snapshot=self.hub.instances[iid].get('snapshot',{})
                    if snapshot.get('capture_mode_editing') or snapshot.get('capture_mode_pending'):
                        raise ValueError('Operator capture-mode edits must finish before starting capture')
                settings=configuration(state);settings.update(changes)
                self.validate_configuration(settings)
                if state.get('recorder_running') and any(configuration(state).get(k)!=v for k,v in changes.items()):
                    raise ValueError('Recorder already running; use settings.set with restart=true for mode changes')
                launched=await asyncio.to_thread(start_recorder,self.path(store),settings)
                if launched:
                    deadline=time.monotonic()+4
                    while time.monotonic()<deadline:
                        current=await asyncio.to_thread(self.status,store)
                        if current.get('session')!=state.get('session') and current.get('state') in ('recording','error'):
                            if current['state']=='error':raise ValueError('Recorder start failed: '+str(current.get('error')))
                            break
                        await asyncio.sleep(.05)
            elif operation in ('stop','capture'):
                if not state.get('recorder_running'):raise ValueError('Recorder is not running')
                await asyncio.to_thread(storage.command,self.path(store),operation)
            else:raise ValueError('Unsupported recorder operation')
            self.journal.command_result(cid,'succeeded',dict(accepted=True,status=self.status(store)))
        except Exception as exc:self.journal.command_result(cid,'failed',error=str(exc))
        return self.journal.get_command(cid)

    @staticmethod
    def validate_configuration(values):
        if set(values)-set(OPTIONS):raise ValueError('Unsupported recorder configuration key')
        for key,value in values.items():
            if key=='device':
                import re
                if not re.fullmatch(r'/dev/video\d+',str(Path(value).resolve())):raise ValueError('Camera device must resolve to /dev/videoN')
            elif key=='trigger':
                if value not in ('motion','timer'):raise ValueError('Invalid trigger mode')
            else:
                import math
                if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (value==0 and key!='pre_roll'):
                    raise ValueError('Invalid numeric recorder setting')
                if key in ('width','height','buffer_mb','motion_delta','event_mb') and type(value) is not int:
                    raise ValueError('Integer setting required')
        if values.get('motion_fraction',.025)>1 or values.get('motion_delta',18)>255:raise ValueError('Invalid motion sensitivity')
        if values.get('width',1280)>7680 or values.get('height',720)>4320 or values.get('fps',30)>120:raise ValueError('Capture mode exceeds service limits')
        if values.get('buffer_mb',64)>512 or values.get('event_mb',128)>512 or values.get('event_seconds',30)>120:
            raise ValueError('Capture memory/duration exceeds service limits')

    async def once(self,store,operation,arguments,command_id,action):
        self.path(store);cid=command_id or uuid.uuid4().hex
        record,new=self.journal.command(cid,store,operation,arguments)
        if not new:return record
        try:
            result=await action()
            self.journal.command_result(cid,'succeeded',result)
        except Exception as exc:self.journal.command_result(cid,'failed',error=str(exc))
        return self.journal.get_command(cid)

    async def set_settings(self,store,changes,restart=False):
        live={};configuration_changes={}
        for key,value in changes.items():
            if key in ('motion_roi','ocr_area'):live[key]=list(validate_roi(value))
            elif key=='ocr_rotations':live[key]=storage.validate_ocr_rotations(value)
            else:configuration_changes[key]=value
        for iid in self.hub.for_store(store):
            snapshot=self.hub.instances[iid].get('snapshot',{})
            if ('motion_roi' in live and snapshot.get('motion_editing')) or ('ocr_area' in live and snapshot.get('ocr_area_editing')):
                raise ValueError('Operator is editing the requested area')
            if configuration_changes and restart and (snapshot.get('camera_drafts') or snapshot.get('camera_pending') or snapshot.get('capture_mode_editing') or snapshot.get('capture_mode_pending')):
                raise ValueError('Operator camera edits must finish before restarting capture')
        if configuration_changes:
            state=await asyncio.to_thread(self.status,store)
            config=configuration(state);config.update(configuration_changes);self.validate_configuration(config)
            if not restart:return dict(applied=False,requires_restart=configuration_changes,live_changes=live)
            if self.camera_locks[store].locked():raise ValueError('Camera operation in progress; cancel it before reconfiguring')
            if state.get('recorder_running'):
                await self.recorder(store,'stop')
                deadline=time.monotonic()+5
                while recorder_running(self.path(store)) and time.monotonic()<deadline:await asyncio.sleep(.1)
                if recorder_running(self.path(store)):raise ValueError('Recorder did not stop; settings not restarted')
            started=await self.recorder(store,'start',config)
            if started['state']!='succeeded':return started
        for key,value in live.items():await asyncio.to_thread(storage.write_setting,self.path(store),key,value)
        return dict(applied=True,live_changes=live,restarted=bool(configuration_changes))

    def start_export(self,store,clip_id,max_width=1920):
        if not 320<=max_width<=1920:raise ValueError('Export width must be 320–1920')
        self.clip_info(store,clip_id)
        jid=uuid.uuid4().hex;self.journal.create_job(jid,'export',store)
        async def work():
            async with self.heavy:
                self.journal.update_job(jid,'running')
                try:
                    result=await asyncio.to_thread(media.export_mp4,self.path(store),clip_id,self.state_dir/'exports'/f'{jid}.mp4',max_width)
                    result.update(clip_id=clip_id,download_path=f'/exports/{jid}.mp4')
                    self.journal.update_job(jid,'complete',result)
                except Exception as exc:self.journal.update_job(jid,'error',error=str(exc))
        task=asyncio.create_task(work());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return self.journal.get_job(jid)

    def start_tune(self,store,**parameters):
        from .tuning import tune
        self.path(store)
        jid=uuid.uuid4().hex;self.journal.create_job(jid,'camera_tune',store)
        cancellation=asyncio.Event();self.cancellations[jid]=cancellation
        async def work():
            async with self.heavy:
                self.journal.update_job(jid,'running')
                try:
                    result=await tune(self,jid,store,cancel=cancellation,**parameters)
                    self.journal.update_job(jid,'error' if result.get('error') else 'complete',result,result.get('error'))
                except Exception as exc:self.journal.update_job(jid,'error',error=str(exc))
                finally:self.cancellations.pop(jid,None)
        task=asyncio.create_task(work());self.tasks.add(task);task.add_done_callback(self.tasks.discard)
        return self.journal.get_job(jid)
