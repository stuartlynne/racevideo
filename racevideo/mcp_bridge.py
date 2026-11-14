"""Optional outward TCP/WebSocket bridge. Tk work stays in poll(), never here."""
from collections import OrderedDict
import json
import os
from pathlib import Path
import queue
import threading
import time
import uuid


def descriptor_path():
    return Path(os.environ.get('RACEVIDEO_MCP_BRIDGE_FILE',
        str(Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'racevideo-mcp'/'bridge.json')))


class AppBridge:
    def __init__(self,app):
        self.app=app
        self.instance=uuid.uuid4().hex
        self.stop_event=threading.Event()
        self.incoming=queue.Queue(maxsize=32)
        self.outgoing=queue.Queue(maxsize=256)
        self.lock=threading.Lock()
        self.snapshot={}
        self.gui_tick=0
        self.connected=False
        self.results=OrderedDict()
        self.pending=set()
        self.leases={}
        self.revoked=set()
        self.views={}
        self.thread=threading.Thread(target=self.run,name='mcp-bridge',daemon=True)
        self.thread.start()

    def reserved(self,cid):
        now=time.monotonic()
        return any(now<lease['expires'] and cid in lease['ids'] for lease in self.leases.values())

    def revoke(self):
        revoked=list(self.leases)
        self.revoked.update(self.leases)
        self.leases.clear()
        if revoked and hasattr(self.app.reader,'jobs'):
            self.app.reader.jobs.put(('agent_release',revoked))
        if len(self.revoked)>1024:self.revoked=set(list(self.revoked)[-512:])

    def reply(self,command_id,result=None,error=None):
        message=dict(type='result',id=command_id,result=result,error=error)
        with self.lock:
            self.pending.discard(command_id)
            self.results[command_id]=message
            while len(self.results)>128:self.results.popitem(last=False)
        try:self.outgoing.put_nowait(message)
        except queue.Full:pass  # Completed results are resent on reconnect.

    def tick(self):
        self.gui_tick+=1
        now=time.monotonic()
        self.leases={key:value for key,value in self.leases.items() if value['expires']>now}
        for _ in range(8):
            try:command=self.incoming.get_nowait()
            except queue.Empty:break
            try:
                if time.time()>command['expires_at']:raise ValueError('Command expired before GUI execution')
                result=self.dispatch(command)
                if result is not None:self.reply(command['id'],result)
            except Exception as exc:self.reply(command['id'],error=str(exc))
        for cid,request in list(self.views.items()):
            try:
                if now>request['deadline']:raise TimeoutError('View did not load before deadline')
                if getattr(self.app,'pending_review',None)==request['clip']:continue
                if self.app.selected!=request['clip']:raise ValueError('Operator selected another clip')
                if self.app.index and not request['sent']:
                    if not 0<=request['frame']<len(self.app.index):raise ValueError('Frame is outside this clip')
                    self.app.ordinal=request['frame'];self.app.request_frame();request['sent']=True
                if request['sent'] and getattr(self.app,'displayed_ordinal',None)==request['frame']:
                    self.reply(cid,dict(clip_id=request['clip'],frame=request['frame'],displayed=True))
                    del self.views[cid]
            except Exception as exc:
                if getattr(self.app,'pending_review',None)==request['clip']:self.app.pending_review=None
                self.reply(cid,error=str(exc));del self.views[cid]
        panel=self.app.camera_panel
        snapshot=dict(instance=self.instance,pid=os.getpid(),database=str(Path(self.app.path).resolve()),
                      gui_tick=self.gui_tick,mode=self.app.mode,clip_id=self.app.selected,
                      review_date=self.app.review_day.get(),bib_filter=self.app.bib_filter.get(),review_zoom=self.app.view.zoom,
                      gui_metrics=getattr(self.app,'performance_snapshot',{}), camera_lease_protocol=2,
                      requested_frame=self.app.ordinal,displayed_frame=getattr(self.app,'displayed_ordinal',None),
                      playing=self.app.playing,camera_drafts=sorted(panel.drafts) if panel else [],
                      capture_mode_editing=bool(panel and getattr(panel,'mode_draft',False)),
                      capture_mode_pending=bool(panel and getattr(panel,'mode_pending',False)),
                      motion_editing=self.app.roi_drag is not None or bool(getattr(self.app,'motion_options',None) and self.app.motion_options.window.winfo_exists() and (self.app.motion_options.dirty or self.app.motion_options.drawing)),ocr_area_editing=self.app.ocr_selecting,
                      camera_pending=bool(self.app.reader.camera_pending) or bool(panel and panel.pending),
                      camera_leases=sorted(self.leases),
                      camera_reserved=sorted({cid for lease in self.leases.values() for cid in lease['ids']}))
        with self.lock:self.snapshot=snapshot

    def dispatch(self,command):
        app=self.app;op=command['operation'];args=command.get('arguments',{})
        if op=='view.live':app.go_live();return dict(mode='live')
        if op in ('view.clip','view.frame'):
            clip_id=int(args.get('clip_id',app.selected or 0));ordinal=int(args.get('frame',0))
            app.displayed_ordinal=None
            if app.selected!=clip_id or app.mode!='replay':app.select(clip_id,auto_position=False)
            else:app.playing=False
            self.views[command['id']]=dict(clip=clip_id,frame=ordinal,deadline=time.monotonic()+4,sent=False)
            return None
        if op=='playback.play':
            if app.mode!='replay' or not app.index:raise ValueError('Select a saved clip first')
            if not app.playing:app.toggle_play()
            return dict(playing=app.playing)
        if op=='playback.pause':
            app.playing=False;app.play_button.configure(text='▶  Play  (Space)')
            return dict(playing=False)
        if op=='camera.reserve':
            lease_id=str(args['lease_id']);ids=set(map(int,args['control_ids']))
            if not 1<=len(ids)<=20:raise ValueError('Invalid control reservation')
            if lease_id in self.revoked:raise ValueError('Operator released this agent control lease')
            panel=app.camera_panel
            if panel and (getattr(panel,'mode_draft',False) or getattr(panel,'mode_pending',False)):
                raise ValueError('Operator is editing capture mode')
            if panel and (ids & (panel.drafts | panel.pending)):raise ValueError('Operator is editing a requested camera control')
            if app.reader.camera_pending:raise ValueError('A camera setting is already pending')
            if any(key!=lease_id and ids & value['ids'] for key,value in self.leases.items()):raise ValueError('Camera controls are reserved')
            self.leases[lease_id]=dict(ids=ids,expires=time.monotonic()+25)
            return dict(lease_id=lease_id,expires_in=25)
        if op=='camera.release':
            self.leases.pop(str(args['lease_id']),None);return dict(released=True)
        raise ValueError('Unsupported GUI operation')

    def run(self):
        try:from websockets.sync.client import connect
        except ImportError:return
        while not self.stop_event.is_set():
            try:
                path=descriptor_path()
                if path.stat().st_mode & 0o077:raise ValueError('Bridge descriptor must be private')
                info=json.loads(path.read_text())
                if info.get('protocol')!=1:raise ValueError('Unsupported bridge protocol')
                with connect(info['url'],additional_headers={'Authorization':'Bearer '+info['token']},
                             open_timeout=2,close_timeout=1,max_size=1_000_000) as ws:
                    self.connected=True
                    ws.send(json.dumps(dict(type='hello',protocol=1,instance=self.instance,pid=os.getpid(),
                                             database=str(Path(self.app.path).resolve()))))
                    with self.lock:completed=list(self.results.values())
                    for result in completed:ws.send(json.dumps(result))
                    last_heartbeat=0
                    while not self.stop_event.is_set():
                        if time.monotonic()-last_heartbeat>=.4:
                            with self.lock:snapshot=self.snapshot.copy()
                            ws.send(json.dumps(dict(type='heartbeat',snapshot=snapshot)))
                            last_heartbeat=time.monotonic()
                        while not self.outgoing.empty():ws.send(json.dumps(self.outgoing.get_nowait()))
                        try:message=json.loads(ws.recv(timeout=.1))
                        except TimeoutError:continue
                        if message.get('type')!='command':continue
                        cid=message['id']
                        with self.lock:
                            result=self.results.get(cid);pending=cid in self.pending
                            if result is None and not pending:self.pending.add(cid)
                        if result:ws.send(json.dumps(result))
                        elif not pending:
                            try:self.incoming.put_nowait(message)
                            except queue.Full:self.reply(cid,error='GUI command queue full')
                    ws.send(json.dumps(dict(type='goodbye')))
            except Exception:
                self.connected=False
                self.stop_event.wait(1)
        self.connected=False

    def close(self):
        self.stop_event.set();self.thread.join(timeout=.5)
