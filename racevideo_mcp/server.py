"""Authenticated Streamable HTTP MCP + reverse WebSocket on one TCP port."""
import argparse
import asyncio
import base64
from contextlib import asynccontextmanager
import fcntl
import hashlib
import hmac
import io
import inspect
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import parse_qs,urlsplit
import uuid
from typing import Literal
from PIL import Image

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult,TextContent,ImageContent
from starlette.applications import Starlette
from starlette.responses import JSONResponse,FileResponse,Response
from starlette.routing import Route,Mount,WebSocketRoute
import uvicorn

from racevideo import storage
from racevideo.camera import CameraControls,list_devices
from racevideo.service import start_ocr
from .config import config_home,state_home,token,bootstrap
from .hub import Hub
from .journal import Journal
from .operations import Operations
from . import media


def image_result(jpeg,metadata):
    return CallToolResult(content=[TextContent(type='text',text=json.dumps(metadata)),
        ImageContent(type='image',data=base64.b64encode(jpeg).decode(),mimeType='image/jpeg')],structuredContent=metadata)


class Authentication:
    def __init__(self,app,admin_token,bridge_token):
        self.app=app;self.admin=admin_token;self.bridge=bridge_token

    def signature(self,path,expires):
        return hmac.new(self.admin.encode(),f'{path}\n{expires}'.encode(),hashlib.sha256).hexdigest()

    def media_ok(self,scope):
        if not re.fullmatch(r'/exports/[0-9a-f]{32}\.mp4',scope['path']):return False
        query=parse_qs(scope.get('query_string',b'').decode())
        try:
            expires=int(query['expires'][0]);sig=query['signature'][0]
            return time.time()<expires<=time.time()+600 and hmac.compare_digest(sig,self.signature(scope['path'],expires))
        except (KeyError,ValueError):return False

    async def __call__(self,scope,receive,send):
        if scope['type'] not in ('http','websocket'):return await self.app(scope,receive,send)
        if scope['path']=='/health' and scope['type']=='http':return await self.app(scope,receive,send)
        headers=dict(scope.get('headers',[]))
        supplied=headers.get(b'authorization',b'')
        expected=self.bridge if scope['path']=='/bridge' else self.admin
        good=hmac.compare_digest(supplied,('Bearer '+expected).encode())
        if not good and scope['type']=='http':good=self.media_ok(scope)
        if not good:
            if scope['type']=='websocket':return await send({'type':'websocket.close','code':1008})
            return await JSONResponse({'error':'Bearer token required'},401,
                headers={'WWW-Authenticate':'Bearer realm="racevideo-mcp"'})(scope,receive,send)
        return await self.app(scope,receive,send)


def build(stores,state_dir,admin_token,bridge_token,host='127.0.0.1',port=8766,public_url=None):
    state_dir=Path(state_dir);state_dir.mkdir(parents=True,exist_ok=True)
    journal=Journal(state_dir/'service.sqlite3')
    resolved={name:Path(path).expanduser().resolve() for name,path in stores.items()}
    if len(set(resolved.values()))!=len(resolved):raise ValueError('Recording stores must use distinct databases')
    hub=Hub(journal,resolved);ops=Operations(resolved,state_dir,hub,journal)
    base_url=(public_url or f'http://127.0.0.1:{port}').rstrip('/')
    allowed=['127.0.0.1:*','localhost:*','[::1]:*']
    if urlsplit(base_url).hostname not in ('127.0.0.1','localhost','::1'):
        allowed.append(urlsplit(base_url).netloc)
    mcp=FastMCP('racevideo_mcp',host=host,port=port,stateless_http=True,json_response=True,
        instructions='RaceVideo recording evidence and camera/GUI control. Choose a configured store. '
        'Frame ordinals are zero based. OCR outputs are unverified candidates. Camera writes return actual readback. '
        'Inspect commands.get after unknown outcomes; never retry mutations with a new ID blindly. '
        'Camera tuning uses bounded sampled proxies, respects operator drafts/takeover and does not establish race-speed accuracy.',
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,allowed_hosts=allowed,
            allowed_origins=['http://'+h for h in allowed]+['https://'+h for h in allowed]))

    @mcp.tool(name='racevideo.inventory')
    async def inventory()->dict:
        """Capabilities, stores and UI instances. File reads work without a GUI."""
        return dict(service='racevideo_mcp',version='0.1.0',stores=[dict(name=n,path=str(p),exists=p.exists()) for n,p in resolved.items()],
                    instances=hub.list(),features=['offline frames/contact sheets/video exports/OCR','live samples',
                      'deadline-aware camera changes','operator-aware GUI control','bounded exposure/gain trials'],
                    limits=dict(gui_timeout_seconds=6,camera_request_deadline_seconds=4,one_heavy_job=True))

    @mcp.tool(name='racevideo.status')
    async def status(store:str='default')->dict:
        """Recorder status, fresh-frame flag, current configuration and polled camera controls."""
        return await asyncio.to_thread(ops.status,store)

    @mcp.tool(name='clips.list')
    async def clips_list(store:str='default',after_id:int=0,limit:int=25,day:str|None=None,bibs:list[str]|None=None,starred_only:bool=False)->dict:
        """Page saved clips. Optional local YYYY-MM-DD, ANY 1–3 digit bibs, and stars.

        OCR uses the latest completed run per clip. Candidate matches are not lap counts.
        Omit day for all dates; GUI defaults to Today independently.
        """
        return await asyncio.to_thread(ops.clips,store,after_id,limit,day,bibs or (),starred_only)

    @mcp.tool(name='clips.dates')
    async def clips_dates(store:str='default')->dict:
        """Available recording dates in the host's local timezone, newest first."""
        def read():
            with ops.db(store) as c:return dict(dates=storage.recording_dates(c),timezone='host local')
        return await asyncio.to_thread(read)

    @mcp.tool(name='clips.star')
    async def clips_star(clip_id:int,starred:bool=True,store:str='default',command_id:str|None=None)->dict:
        """Persist an evidence star. Starred clips are protected from date cleanup."""
        return await ops.once(store,'clips.star',dict(clip_id=clip_id,starred=starred),command_id,
                              lambda:asyncio.to_thread(ops.star,store,clip_id,starred))

    @mcp.tool(name='bibs.sightings')
    async def sightings(day:str,store:str='default',bibs:list[str]|None=None,offset:int=0,limit:int=100)->dict:
        """Candidate OCR encounters for a local date, with source frame/time. Not verified laps."""
        if offset<0 or not 1<=limit<=500:raise ValueError('Invalid pagination')
        def read():
            with ops.db(store) as c:rows=storage.bib_passages(c,day,bibs or ())
            return dict(sightings=rows[offset:offset+limit],total=len(rows),next_offset=offset+min(limit,max(0,len(rows)-offset)),evidence_note='OCR candidates, not verified laps')
        return await asyncio.to_thread(read)

    @mcp.tool(name='clips.info')
    async def clips_info(clip_id:int,store:str='default')->dict:
        """Saved clip dimensions/timestamps, acquisition metadata and latest OCR evidence."""
        return await asyncio.to_thread(ops.clip_info,store,clip_id)

    @mcp.tool(name='frames.list')
    async def frames_list(clip_id:int,store:str='default',offset:int=0,limit:int=100)->list[dict]:
        """Actual frame times and source PTS; never infer timing from nominal fps."""
        return await asyncio.to_thread(ops.frames,store,clip_id,offset,limit)

    @mcp.tool(name='frames.get')
    async def frames_get(clip_id:int,ordinal:int,store:str='default',crop:list[float]|None=None,max_width:int=1280)->CallToolResult:
        """View an original saved frame, optionally normalized crop, as an MCP image."""
        jpeg,meta=await asyncio.to_thread(ops.frame,store,clip_id,ordinal,crop,max_width)
        return image_result(jpeg,meta)

    @mcp.tool(name='clips.contact_sheet')
    async def sheet(clip_id:int,store:str='default',count:int=8)->CallToolResult:
        """View 1–12 time-ordered samples of a saved clip, with actual frame offsets."""
        jpeg,index=await asyncio.to_thread(media.contact_sheet,ops.path(store),clip_id,count)
        return image_result(jpeg,dict(store=store,clip_id=clip_id,frames=index))

    @mcp.tool(name='clips.export')
    async def export(clip_id:int,store:str='default',max_width:int=1920,command_id:str|None=None)->dict:
        """Create a playable MP4 derivative in a background job; original JPEGs stay unchanged."""
        return await job_once(store,'clips.export',dict(clip_id=clip_id,max_width=max_width),command_id,
                              lambda:ops.start_export(store,clip_id,max_width))

    @mcp.tool(name='camera.sample')
    async def sample(store:str='default',crop:list[float]|None=None,max_width:int=1280)->CallToolResult:
        """View a fresh live image and brightness/edge metrics, even with no GUI. Rejects stale frames."""
        jpeg,state=await asyncio.to_thread(ops.live,store)
        quality=await asyncio.to_thread(media.metrics,jpeg,crop)
        jpeg,size=await asyncio.to_thread(media.render,jpeg,crop,max_width)
        return image_result(jpeg,dict(store=store,received_ns=state['last_frame_ns'],session=state['session'],quality=quality,**size))

    @mcp.tool(name='camera.controls')
    async def controls(store:str='default',refresh_if_stopped:bool=False)->dict:
        """Device-reported ranges, steps, menus, readback and inactive flags. Optional stopped-camera read-only query."""
        state=await asyncio.to_thread(ops.status,store)
        if not state.get('fresh') and refresh_if_stopped:
            device=state.get('device') or configuration_device(store)
            def read():
                camera=CameraControls(device)
                try:return camera.enumerate()
                finally:camera.close()
            return dict(controls=await asyncio.to_thread(read),source='device query',recording=False)
        return dict(controls=state.get('camera_controls',[]),fresh=state.get('fresh',False),
                    observed_ns=state.get('camera_controls_observed_ns'),error=state.get('camera_controls_error'))

    @mcp.tool(name='camera.devices')
    async def devices()->list[dict]:
        """Enumerate local V4L2 nodes/stable aliases and distinguish capture from metadata nodes."""
        return await asyncio.to_thread(list_devices)

    def configuration_device(store):
        return ops.status(store).get('configuration',{}).get('device','/dev/video0')

    @mcp.tool(name='camera.set')
    async def camera_set(changes:list[dict],store:str='default',command_id:str|None=None)->dict:
        """Ordered [{id:int,value:int}] changes with driver readback, GUI reservations and deduplicated command ID."""
        return await ops.set_camera(store,changes,command_id)

    @mcp.tool(name='camera.tune')
    async def camera_tune(store:str='default',exposures:list[int]|None=None,max_gain:int=128,min_median:int=40,
                          crop:list[float]|None=None,use_ocr:bool=False,valid_numbers:list[str]|None=None,
                          apply_best:bool=True,command_id:str|None=None)->dict:
        """Background exposure/gain trials (max six), sample images and optionally OCR. Shortest visible qualifying exposure wins.

        Exposure values are 100us units. Does not tune focus. apply_best=false restores starting settings for review.
        No visibility-qualified trial also restores. Operator takeover aborts further writes. Scores are sampled proxies.
        """
        if crop is not None:media.region(Image.new('L',(100,100)),crop)
        parameters=dict(exposures=exposures,max_gain=max_gain,min_median=min_median,area=crop,
                        use_ocr=use_ocr,valid_numbers=valid_numbers,apply_best=apply_best)
        return await job_once(store,'camera.tune',parameters,command_id,lambda:ops.start_tune(store,**parameters))

    @mcp.tool(name='settings.get')
    async def settings_get(store:str='default')->dict:
        """Saved areas, recorder configuration, and camera readback."""
        return await asyncio.to_thread(ops.settings,store)

    @mcp.tool(name='settings.set')
    async def settings_set(changes:dict,store:str='default',restart:bool=False,command_id:str|None=None)->dict:
        """Set motion_roi/ocr_area live. Other validated recorder settings need explicit restart=true."""
        return await job_once(store,'settings.set',dict(changes=changes,restart=restart),command_id,
                              lambda:ops.set_settings(store,changes,restart))

    @mcp.tool(name='recorder.start')
    async def recorder_start(store:str='default',configuration:dict|None=None,command_id:str|None=None)->dict:
        """Start an independent headless recorder; no GUI needed. Existing recordings are retained."""
        return await ops.recorder(store,'start',configuration,command_id)

    @mcp.tool(name='recorder.stop')
    async def recorder_stop(store:str='default',command_id:str|None=None)->dict:
        """Queue a clean recorder stop; poll status for completion. GUI review remains available."""
        return await ops.recorder(store,'stop',command_id=command_id)

    @mcp.tool(name='recorder.capture')
    async def capture(store:str='default',command_id:str|None=None)->dict:
        """Save the recorder's recent buffer. Reuse command_id to reconcile, not duplicate capture."""
        return await ops.recorder(store,'capture',command_id=command_id)

    @mcp.tool(name='ocr.start')
    async def ocr_start(clip_id:int,store:str='default',crop:list[float]|None=None,fps:float=8,rotations:list[int]|None=None,command_id:str|None=None,engine:Literal['tesseract','paddle-rider-v1']|None=None)->dict:
        """Run OCR using the saved region/rotations unless explicitly overridden.

        [0] is an upright-only test policy; normal [0,180] also tries upside-down.
        Results remain candidates, not race edits. Choices are frozen in each job.
        Neural OCR uses every frame, all orientations and its separate saved rider search area; fps/rotations are Tesseract controls.
        """
        ops.clip_info(store,clip_id)
        if not 0<fps<=15:raise ValueError('OCR sample rate must be (0,15]')
        parameters=dict(fps=fps)
        if engine is not None:parameters['engine']=engine
        if rotations is not None:parameters['rotations']=storage.validate_ocr_rotations(rotations)
        if crop is not None:
            from racevideo.motion import validate_roi
            parameters['roi']=list(validate_roi(crop))
        async def action():return dict(run_id=await asyncio.to_thread(start_ocr,ops.path(store),clip_id,parameters),store=store)
        return await job_once(store,'ocr.start',dict(clip_id=clip_id,parameters=parameters),command_id,action)

    @mcp.tool(name='ocr.status')
    async def ocr_status(clip_id:int,store:str='default')->dict:
        """Latest OCR run, progress and source-linked candidate observations."""
        with ops.db(store) as c:return storage.read_ocr_run(c,clip_id) or dict(state='not_scanned')

    @mcp.tool(name='app.instances')
    async def instances()->list[dict]:
        """Connected/disconnected registered GUIs, actual main-thread progress and selected view."""
        return hub.list()

    @mcp.tool(name='app.control')
    async def app_control(instance:str,operation:str,arguments:dict|None=None,command_id:str|None=None)->dict:
        """Control a specific responsive GUI: view.live, view.clip/frame, playback.play/pause. No camera I/O on Tk."""
        if operation not in ('view.live','view.clip','view.frame','playback.play','playback.pause'):raise ValueError('Unsupported app operation')
        return await hub.call(instance,operation,arguments,command_id)

    @mcp.tool(name='commands.get')
    async def commands_get(command_id:str)->dict:
        """Reconcile command outcomes, including results arriving after a disconnect. Unknown is not safe to replay."""
        return journal.get_command(command_id)

    def signed_export(path):
        expires=int(time.time()+300)
        signature=authentication.signature(path,expires)
        return base_url+path+f'?expires={expires}&signature={signature}'

    async def job_once(store,operation,arguments,command_id,action):
        async def invoke():
            result=action()
            return await result if inspect.isawaitable(result) else result
        command=await ops.once(store,operation,arguments,command_id,invoke)
        if command['state']=='succeeded':return dict(command['result'],command_id=command['id'])
        return command

    @mcp.tool(name='jobs.get')
    async def jobs_get(job_id:str)->dict:
        """Background export/tuning status, trial metrics and confirmed restore/apply outcome."""
        result=journal.get_job(job_id)
        if result['kind']=='export' and result['state']=='complete':
            result['result']['download_url']=signed_export(result['result']['download_path'])
        return result

    @mcp.tool(name='jobs.cancel')
    async def cancel(job_id:str)->dict:
        """Request cancellation of camera trials; restores starting settings unless operator has taken over."""
        event=ops.cancellations.get(job_id)
        if event is None:raise ValueError('No cancellable active tuning job')
        event.set();return dict(cancellation_requested=True,job_id=job_id)

    @mcp.tool(name='jobs.frame')
    async def job_frame(job_id:str,trial:int=0,sample:int=0,max_width:int=1280)->CallToolResult:
        """Inspect a saved tuning-trial sample image, including trials after the GUI has closed."""
        job=journal.get_job(job_id)
        if job['kind']!='camera_tune' or not 0<=trial<6 or not 0<=sample<2:raise ValueError('Invalid tuning sample')
        path=state_dir/'trials'/job_id/f'{trial}-{sample}.jpg'
        jpeg,size=await asyncio.to_thread(media.render,path.read_bytes(),None,max_width)
        return image_result(jpeg,dict(job_id=job_id,trial=trial,sample=sample,**size))

    async def health(request):return JSONResponse(dict(service='racevideo_mcp',status='ok'))
    async def export_file(request):
        jid=request.path_params['job_id']
        if not re.fullmatch('[0-9a-f]{32}',jid):return Response(status_code=404)
        try:job=journal.get_job(jid)
        except ValueError:return Response(status_code=404)
        if job['kind']!='export' or job['state']!='complete':return Response(status_code=404)
        return FileResponse(state_dir/'exports'/f'{jid}.mp4',media_type='video/mp4')

    mcp_app=mcp.streamable_http_app()
    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield
            for event in ops.cancellations.values():event.set()
            if ops.tasks:
                try:await asyncio.wait_for(asyncio.gather(*ops.tasks,return_exceptions=True),12)
                except TimeoutError:pass
    application=Starlette(routes=[Route('/health',health),Route('/exports/{job_id}.mp4',export_file),
                                  WebSocketRoute('/bridge',hub.websocket),Mount('/',app=mcp_app)],lifespan=lifespan)
    authentication=Authentication(application,admin_token,bridge_token)
    authentication.ops=ops;authentication.hub=hub;authentication.mcp=mcp
    return authentication


def main(argv=None):
    p=argparse.ArgumentParser(description='Persistent RaceVideo MCP and app bridge service')
    p.add_argument('--config',type=Path)
    p.add_argument('--db',action='append',help='NAME=PATH (or PATH for default store)')
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8766)
    p.add_argument('--state-dir',type=Path,default=state_home())
    p.add_argument('--config-dir',type=Path,default=config_home())
    p.add_argument('--public-url')
    args=p.parse_args(argv)
    settings=json.loads(args.config.read_text()) if args.config else {}
    host=settings.get('host',args.host);port=settings.get('port',args.port)
    config_dir=Path(settings.get('config_dir',args.config_dir));state_dir=Path(settings.get('state_dir',args.state_dir))
    stores=settings.get('stores',{})
    for value in args.db or []:
        name,path=value.split('=',1) if '=' in value else ('default',value)
        if not re.fullmatch('[A-Za-z0-9_-]{1,40}',name):p.error('Invalid store name')
        stores[name]=str(Path(path).expanduser().resolve())
    if not stores:p.error('Configure at least one --db')
    config_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(config_dir/'service.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:p.error('Another service owns this bridge descriptor')
    admin=token(config_dir/'token');bridge=token(config_dir/'bridge-token')
    public=settings.get('public_url',args.public_url)
    application=build(stores,state_dir,admin,bridge,host,port,public)
    connect_host='127.0.0.1' if host in ('0.0.0.0','127.0.0.1') else host
    bootstrap(config_dir/'bridge.json',f'ws://{connect_host}:{port}/bridge',bridge,uuid.uuid4().hex)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    uvicorn.run(application,host=host,port=port,access_log=False,ws_max_size=1_000_000)


if __name__=='__main__':main()
