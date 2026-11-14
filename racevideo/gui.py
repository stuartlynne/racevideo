"""Tk is only responsible for presentation; decoding and SQL run off its thread."""
from __future__ import annotations

import bisect
from datetime import date, datetime
import io
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

from . import storage
from .motion import DEFAULT_ROI, validate_roi
from .review import View, render


def clock(ns):
    return datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S.%f")[:-3]


def decode(jpeg, size):
    with Image.open(io.BytesIO(jpeg)) as image:
        image.draft("RGB", (max(1, size[0]), max(1, size[1])))
        image.thumbnail((max(1, size[0]), max(1, size[1])))
        return image.convert("RGB")


class BoundedEvents:
    def __init__(self, stop):
        self.stop = stop
        self.queue = queue.Queue(maxsize=32)
        self.status = None
        self.lock = threading.Lock()

    def put(self, event):
        if event[0] == 'live':
            with self.lock:
                self.status = event
            return
        while not self.stop.is_set():
            try:
                self.queue.put(event, timeout=.05)
                return
            except queue.Full:
                pass

    def empty(self):
        with self.lock:
            return self.status is None and self.queue.empty()

    def get(self):
        with self.lock:
            if self.status is not None:
                result, self.status = self.status, None
                return result
        return self.queue.get_nowait()


class Reader(threading.Thread):
    def __init__(self, path):
        super().__init__(name="review-reader", daemon=True)
        self.path = path
        self.stop = threading.Event()
        self.output = BoundedEvents(self.stop)
        self.jobs = queue.SimpleQueue()
        self.size = (1100, 650)
        self.wanted_frame = None  # Replaced, never backlogged while scrubbing.
        self.camera_pending = set()
        self.ocr_clip = None
        self.review_signature = None
        self.selection_clip=None
        self.position_cache={}
        self.navigation_signature=None
        self.wheel_watch=None;self.wheel_signature=None
        self.browse = (0, "Today", (), False)

    def run(self):
        connection = None
        next_poll = next_browse = 0
        browse_key = signature = None
        pending = []
        browse_generation = 0
        try:
            connection = storage.connect(self.path, readonly=True)
            while not self.stop.wait(0.015):
                while not self.jobs.empty():
                    name, value = self.jobs.get()
                    if name == 'locate':
                        row=connection.execute('SELECT started_ns FROM clips WHERE id=?',(value,)).fetchone()
                        self.output.put(('located',(value,datetime.fromtimestamp(row[0]/1e9).date().isoformat() if row else None)))
                    elif name=='capture_modes':
                        from .camera import list_devices
                        from .capture_modes import enumerate_modes
                        try:self.output.put(('capture_modes',dict(device=value,modes=enumerate_modes(value),devices=list_devices(),error=None)))
                        except Exception as exc:self.output.put(('capture_modes',dict(device=value,modes=[],devices=list_devices(),error=str(exc))))
                    elif name=='capture_profile':
                        from .capture_modes import save_profile
                        try:self.output.put(('capture_profile',dict(profile=save_profile(self.path,value),error=None)))
                        except Exception as exc:self.output.put(('capture_profile',dict(profile=value,error=str(exc))))
                    elif name == 'star':
                        try:
                            storage.set_star(self.path,*value)
                            self.output.put(('starred',value))
                            next_browse=0
                        except Exception as exc:self.output.put(('review_error',str(exc)))
                    elif name == 'cleanup_preview':
                        try:self.output.put(('cleanup_preview',storage.cleanup_preview(connection,value)))
                        except Exception as exc:self.output.put(('review_error',str(exc)))
                    elif name == 'cleanup_apply':
                        try:
                            self.output.put(('cleanup_done',storage.delete_previewed(self.path,value)))
                            next_browse=0
                        except Exception as exc:self.output.put(('review_error',str(exc)))
                    elif name == 'passages':
                        generation,day,bibs,stars=value
                        self.output.put(('passages',(generation,storage.bib_passages(connection,day,bibs,stars))))
                    elif name == 'passing_locate':
                        clip_id,stamp=value
                        row=connection.execute('SELECT ordinal FROM frames WHERE clip_id=? ORDER BY ABS(received_ns-?) LIMIT 1',(clip_id,stamp)).fetchone()
                        if row:self.output.put(('passing_located',(clip_id,row['ordinal'])))
                    elif name == 'passing_review':
                        try:
                            from . import passing_review
                            result=(passing_review.redo if value.get('redo') else passing_review.undo)(self.path,value['history_id']) if 'history_id' in value else passing_review.decide(self.path,**value)
                            self.output.put(('passing_review_saved',result))
                        except Exception as exc:self.output.put(('passing_review_error',str(exc)))
                    elif name=='ui_session':
                        if self.stop.is_set():continue
                        from .ui_session import save
                        try:save(self.path,value)
                        except OSError as exc:self.output.put(('error','Could not save review session: '+str(exc)))
                    elif name in ('wheel_start','wheel_peer_start'):
                        wheel_key,clip,entry,force,*contexts=value
                        if self.stop.is_set() or self.selection_clip!=clip or (name=='wheel_start' and wheel_key!=getattr(self,'wheel_requested_signature',wheel_key)):continue
                        try:
                            from .wheel_timing import start,active
                            ident=start(self.path,clip,entry,force=force,context=contexts[0] if contexts else None)
                            self.output.put(('wheel_started',(wheel_key,ident,None,active(connection) if ident is None else None)))
                            if ident:self.wheel_watch=(wheel_key,ident);self.wheel_signature=None
                        except Exception as exc:self.output.put(('wheel_started',(wheel_key,None,str(exc))))
                    elif name=='wheel_link':
                        ident,context=value
                        writer=storage.connect(self.path)
                        try:
                            from .wheel_timing import link_passing
                            with writer:link_passing(writer,ident,context)
                        except Exception as exc:self.output.put(('error','Could not attach video timing: '+str(exc)))
                        finally:writer.close()
                    elif name == "index":
                        clip_id,center,generation,target_ns=value
                        if generation!=getattr(self,'selection_generation',generation):continue
                        if self.selection_clip is not None and self.selection_clip!=clip_id:continue
                        index=storage.frame_index(connection,clip_id)
                        position=dict(ordinal=0,milliseconds=0,decoded_frames=0,method='explicit frame')
                        if target_ns is not None and index:
                            from .motion_position import locate
                            hint=target_ns if isinstance(target_ns,dict) else dict(target_ns=target_ns)
                            try:position=locate(self.path,connection,clip_id,index,hint,cancel=lambda:self.stop.is_set() or self.selection_clip!=clip_id or generation!=getattr(self,'selection_generation',generation))
                            except Exception as exc:
                                position=dict(ordinal=min(index,key=lambda r:abs(r['received_ns']-hint['target_ns']))['ordinal'],
                                    method='automatic positioning failed',milliseconds=0,decoded_frames=0,
                                    warning='Automatic rider positioning failed: '+str(exc)+'. Use Find bikes or scrub; the bib is still unconfirmed.')
                        elif center:
                            key=(clip_id,len(index))
                            if key in self.position_cache:
                                position=self.position_cache.pop(key);self.position_cache[key]=position
                                position=dict(position,milliseconds=0,decoded_frames=0,cached=True)
                            else:
                                from .review_position import choose
                                try:position=choose(connection,clip_id,index,cancel=lambda:self.stop.is_set() or self.selection_clip!=clip_id or generation!=getattr(self,'selection_generation',generation))
                                except (LookupError,OSError,ValueError):position=dict(ordinal=0,milliseconds=0,decoded_frames=0,method='position unavailable')
                                if position['method']!='cancelled':
                                    self.position_cache[key]=position
                                    if len(self.position_cache)>128:self.position_cache.pop(next(iter(self.position_cache)))
                        self.output.put(("index", (clip_id,index,position,generation)))
                    elif name == "command":
                        storage.command(self.path, value)
                    elif name == "roi":
                        storage.write_setting(self.path, "motion_roi", list(validate_roi(value)))
                    elif name == "start_recorder":
                        from .service import start_recorder
                        try:
                            start_recorder(self.path, value)
                            self.output.put(("recorder_start", None))
                        except Exception as exc:
                            self.output.put(("recorder_start", str(exc)))
                    elif name == 'ocr_select':
                        self.ocr_clip=value
                        self.navigation_signature=None
                        self.review_signature=None
                    elif name == 'bib_review':
                        from . import bib_review
                        try:
                            request=dict(value);clip_id=request.pop('clip_id')
                            bib_review.decide(self.path,clip_id,**request)
                            self.review_signature=None;next_poll=next_browse=0
                            self.output.put(('bib_review_saved',clip_id))
                        except Exception as exc:self.output.put(('bib_review_error',str(exc)))
                    elif name == 'ocr_rotations':
                        storage.write_setting(self.path,'ocr_rotations',storage.validate_ocr_rotations(value))
                    elif name == 'quiet_close':
                        storage.write_setting(self.path,'motion_quiet_close_seconds',value)
                    elif name=='motion_options':
                        try:
                            from .motion_profiles import validate_profile
                            from .retention import settings
                            import json
                            value=dict(profile=validate_profile(value['profile']),finish=list(validate_roi(value['finish'])),retention=settings(value['retention']))
                            writer=storage.connect(self.path)
                            try:
                                with writer:
                                    for key,item in (('motion_profile',value['profile']),('motion_roi',value['finish']),('retention_settings',value['retention'])):
                                        writer.execute('INSERT INTO settings(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',(key,json.dumps(item)))
                            finally:writer.close()
                            self.output.put(('motion_options_saved',(value,None)))
                        except Exception as exc:self.output.put(('motion_options_saved',(value,str(exc))))
                    elif name=='retention':
                        try:
                            from .service import start_retention
                            start_retention(self.path,value)
                        except Exception as exc:self.output.put(('ocr_error',str(exc)))
                    elif name=='find_bikes':
                        try:
                            from .service import start_bikes
                            start_bikes(self.path,value)
                        except Exception as exc:self.output.put(('ocr_error',str(exc)))
                    elif name == 'ocr_area':
                        storage.write_setting(self.path,value['key'],value['roi'])
                    elif name=='agent_release':
                        storage.revoke_control_leases(self.path,value)
                    elif name=='ocr_evidence':
                        row=connection.execute('SELECT evidence FROM ocr_observations WHERE id=?',(value,)).fetchone()
                        if row:self.output.put(('ocr_evidence',(value,decode(row[0],(300,120)))))
                    elif name == 'ocr':
                        from .service import start_ocr
                        clip_id,parameters=value
                        try:
                            start_ocr(self.path,clip_id,parameters)
                            self.ocr_clip=clip_id
                        except Exception as exc:
                            self.output.put(('ocr_error',str(exc)))
                    elif name == "camera":
                        session, control_id, requested = value
                        try:
                            request_id = storage.request_camera_control(self.path, session, control_id, requested)
                            self.camera_pending.add(request_id)
                        except Exception as exc:
                            self.output.put(("camera_result", dict(control_id=control_id, value=requested,
                                                                   actual=None, error=f"Could not queue control: {exc}")))
                request = self.wanted_frame
                if request is not None:
                    self.wanted_frame = None
                    clip_id, ordinal, token, view = request
                    try:
                        jpeg = storage.read_frame(connection, clip_id, ordinal)
                        image,bounds,position=render(jpeg,self.size,view)
                        self.output.put(("frame", (clip_id,ordinal,token,image,bounds,position)))
                    except LookupError:self.output.put(('review_error','This recording was removed.'))
                if time.monotonic() >= next_poll:
                    status = storage.read_runtime(connection)
                    status['capture_configuration']=storage.read_setting(connection,'capture_configuration',{})
                    status['configured_quiet_close']=storage.read_setting(connection,'motion_quiet_close_seconds',1.0)
                    status['configured_motion_profile']=storage.read_setting(connection,'motion_profile',{})
                    status['retention_settings']=storage.read_setting(connection,'retention_settings',{})
                    status["configured_roi"] = storage.read_setting(connection, "motion_roi", DEFAULT_ROI)
                    batch=connection.execute("SELECT completed_clips,total_clips,state FROM ocr_batches ORDER BY created_ns DESC LIMIT 1").fetchone()
                    status['ocr_batch']=dict(batch) if batch else None
                    status['ocr_area']=storage.read_setting(connection,'ocr_area',(0,0,1,1))
                    status['neural_ocr_area']=storage.read_setting(connection,'neural_ocr_area',(.05,.4,.98,.9))
                    status['ocr_rotations']=storage.read_setting(connection,'ocr_rotations',[0,180])
                    status.pop("preview", None)
                    self.output.put(('race_contexts',[dict(r) for r in connection.execute('SELECT id,name,competition_id,start_ns,end_ns FROM race_events')]))
                    self.output.put(("live", (status, None)))
                    if self.wheel_watch:
                        from .wheel_timing import read
                        wheel_key,ident=self.wheel_watch;result=read(connection,ident)
                        fingerprint=repr(result)
                        if fingerprint!=self.wheel_signature:
                            self.wheel_signature=fingerprint;self.output.put(('wheel_result',(wheel_key,result)))
                    if self.ocr_clip is not None:
                        from .bike_index import navigation
                        nav=navigation(connection,self.ocr_clip);nav_signature=repr(nav)
                        if nav_signature!=self.navigation_signature:
                            self.navigation_signature=nav_signature;self.output.put(('bike_navigation',(self.ocr_clip,nav)))
                        from .retention import latest
                        self.output.put(('retention_proposal',(self.ocr_clip,latest(connection,self.ocr_clip))))
                        self.output.put(('ocr_status',(self.ocr_clip,storage.read_ocr_run(connection,self.ocr_clip))))
                        from . import bib_review
                        rows=bib_review.list_rows(connection,self.ocr_clip)
                        review_signature=tuple((r['row_key'],r.get('decision'),r['number'],r.get('updated_ns'),r.get('historical')) for r in rows)
                        if review_signature!=self.review_signature:
                            self.review_signature=review_signature
                            self.output.put(('bib_review_rows',(self.ocr_clip,rows)))
                    for result in storage.camera_results(connection, self.camera_pending):
                        self.camera_pending.remove(result["id"])
                        self.output.put(("camera_result", result))
                    next_poll = time.monotonic() + .25
                generation,chosen,bibs,stars=self.browse
                day=date.today().isoformat() if chosen=='Today' else None if chosen=='All dates' else chosen
                key=(generation,day,bibs,stars)
                if key!=browse_key:
                    browse_key=key;signature=None;pending=[];next_browse=0
                if time.monotonic()>=next_browse:
                    rows=storage.browse_clips(connection,day,bibs,stars,thumbnails=False)
                    current=tuple((r['id'],r['starred'],r['bibs'],r['ocr_state'],r.get('confirmed_bibs')) for r in rows)
                    if current!=signature:
                        same_ids=signature is not None and tuple(r[0] for r in current)==tuple(r[0] for r in signature)
                        if same_ids:
                            updates=[row for row,old,new in zip(rows,signature,current) if old!=new]
                            self.output.put(('clip_updates',(generation,updates)))
                            update_map={r['id']:r for r in updates}
                            for waiting in pending:waiting.update(update_map.get(waiting['id'],{}))
                        else:
                            append=signature is not None and current[:len(signature)]==signature
                            if not append:self.output.put(('browse_reset',generation))
                            pending=rows[len(signature):] if append else rows
                        signature=current
                        if not pending:self.output.put(('browse_done',(generation,len(rows))))
                    self.output.put(('dates',storage.recording_dates(connection)))
                    next_browse=time.monotonic()+1
                if pending:
                    clips=[]
                    for clip in pending[:4]:
                        row=connection.execute('SELECT thumbnail FROM clips WHERE id=?',(clip['id'],)).fetchone()
                        if row:
                            clip['image']=decode(row[0],(170,96));clips.append(clip)
                    pending=pending[4:]
                    self.output.put(('clips',(generation,clips)))
                    if not pending:self.output.put(('browse_done',(generation,len(signature))))

        except Exception as exc:
            self.output.put(("error", str(exc)))
        finally:
            if connection:
                connection.close()


class ReviewWindow:
    def __init__(self, root, path):
        self.root, self.path = root, path
        from .ui_session import load
        self.saved_session=load(path);self.last_passings_state=self.saved_session.get('passings',{})
        self.restore_view=None;self.pending_session_clip=None
        self.reader = Reader(path)
        from .pipeline import LivePreview
        from .performance import Performance
        self.preview = LivePreview(path)
        self.performance = Performance()
        self.performance_snapshot = {}
        self.performance_window = None
        self.next_metrics = 0
        self.expected_poll = time.monotonic() + .03
        self.previous_live_stamp = 0
        self.previous_presented = None
        self.previous_produced = 0
        self.last_preview_received_ns = 0
        self.mode = "live"
        self.clips, self.index = [], []
        self.selected = None
        self.ordinal = 0
        self.token = 0
        self.playing = False
        self.live_image = None
        self.shown_image = None
        self.thumb_images = {}
        self.last_status = {}
        self.race_events=[]
        import os
        self.wheel_enabled=tk.BooleanVar(value=self.saved_session.get('wheel_enabled',os.environ.get('RACEVIDEO_WHEEL_AUTO','1')!='0'))
        self.wheel_data=None;self.wheel_request_signature=None;self.wheel_retry_at=0
        self.wheel_reports={};self.wheel_peer_request=None;self.wheel_peer_items={};self.wheel_link_signature=None;self.wheel_open_alignment=None
        self.dragging = False
        self.closing = False
        self.roi = DEFAULT_ROI
        self.roi_drag = None
        self.pending_roi = None
        self.display_size = None
        self.camera_panel = None
        self.motion_options=None
        self.bike_navigation=dict(passages=[],source='none',label='Bike count unknown')
        self.active_bike_key=None
        self.review_day=tk.StringVar(value=self.saved_session.get('date','Today'))
        self.bib_filter=tk.StringVar(value=self.saved_session.get('bibs',''))
        self.stars_only=tk.BooleanVar(value=self.saved_session.get('stars',False))
        self.browse_generation=0
        self.pending_review=None
        self.view=View()
        self.review_bounds=None
        self.pan_drag=None
        self.last_render_token=-1
        self.cleanup_pending=False
        self.cleanup_panel=None
        self.passages_window=None
        self.passings_panel=None
        self.ocr_area=(0,0,1,1)
        self.ocr_upright=tk.BooleanVar(value=False)
        from .service import neural_runtime
        self.neural_available=neural_runtime() is not None
        self.ocr_engine=tk.StringVar(value='Neural OCR' if self.neural_available else 'Tesseract')
        self.pending_ocr_rotations=None
        self.ocr_selecting=False
        self.ocr_drag=None
        self.ocr_area_pending=None
        self.ocr_run=None
        self.ocr_window=None
        self.bib_review_rows=[]
        self.plate_evidence=None
        self.bike_mark=None
        self.bike_marking=False
        self.bike_drag=None
        self.bike_mark_anchor=None
        self.bike_order=tk.StringVar()
        self.pending_bike_mark_save=None
        from .mcp_bridge import AppBridge
        self.remote=AppBridge(self)
        root.title("RaceVideo — Live")
        root.geometry("1200x850")
        try:
            if self.saved_session.get('geometry'):root.geometry(self.saved_session['geometry'])
            if self.saved_session.get('maximized'):root.attributes('-zoomed',True)
        except tk.TclError:pass
        root.minsize(700, 520)
        root.configure(background="#15191f")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#202630")
        style.configure("TLabel", background="#202630", foreground="#e4e9f0")
        style.configure("TButton", padding=(12, 6))
        style.configure("TCheckbutton", background="#202630", foreground="#e4e9f0")
        style.configure("Treeview",background="#15191f",fieldbackground="#15191f",foreground="#e4e9f0",rowheight=25)
        style.map("Treeview",background=[("selected","#35536d")],foreground=[("selected","#ffffff")])

        toolbar = ttk.Frame(root, padding=8)
        toolbar.pack(fill="x")
        self.live_button = ttk.Button(toolbar, text="●  Live  (L)", command=lambda:self.go_live(follow_race=True))
        self.live_button.pack(side="left")
        ttk.Button(toolbar, text="Save recent 2s", command=lambda: self.send("capture")).pack(side="left", padx=8)
        self.play_button = ttk.Button(toolbar, text="▶  Play  (Space)", command=self.toggle_play)
        self.play_button.pack(side="left")
        self.mode_label = ttk.Label(toolbar, text="LIVE", font=("Sans", 12, "bold"))
        self.mode_label.pack(side="left", padx=20)
        self.recorder_button = ttk.Button(toolbar, text="Start recorder", command=self.toggle_recorder)
        self.recorder_button.pack(side="right")
        ttk.Button(toolbar, text="Camera…", command=self.open_camera).pack(side="right", padx=6)
        ttk.Button(toolbar,text="Performance…",command=self.show_performance).pack(side="right",padx=6)
        self.mcp_label=ttk.Label(toolbar,text='MCP offline')
        self.mcp_label.pack(side='right',padx=6)

        self.compact_passings=None
        self.compact_enabled=tk.BooleanVar(value=self.saved_session.get('compact_passings',True) and os.environ.get('RACEVIDEO_COMPACT_PASSINGS','1')!='0')
        style.configure('Compact.TButton',padding=(4,3))
        ttk.Checkbutton(toolbar,text='Passings',variable=self.compact_enabled,command=self.toggle_compact_passings).pack(side='right',padx=4)
        self.video_area=ttk.Panedwindow(root,orient='horizontal',height=1);self.video_area.pack(fill='both',expand=True)
        self.viewer = tk.Canvas(self.video_area, background="#0b0e12", highlightthickness=0, takefocus=True)
        self.video_area.add(self.viewer,weight=1)
        self.viewer.bind("<ButtonPress-1>", self.roi_press)
        self.viewer.bind("<B1-Motion>", self.roi_move)
        self.viewer.bind("<ButtonRelease-1>", self.roi_release)
        self.viewer.bind("<Motion>", self.roi_cursor)
        self.viewer.bind("<Configure>", self.resize)
        self.viewer.bind('<MouseWheel>',self.zoom_wheel)
        self.viewer.bind('<Button-4>',lambda e:self.zoom_wheel(e,1))
        self.viewer.bind('<Button-5>',lambda e:self.zoom_wheel(e,-1))
        self.viewer.bind('<Double-Button-1>',lambda e:self.fit_review())
        self.picture = self.viewer.create_image(0, 0, anchor="center")
        self.empty = self.viewer.create_text(200, 180, text="Waiting for camera…",
                                             fill="#aebbc9", font=("Sans", 18))
        self.warning = self.viewer.create_text(18, 20, anchor="nw", text="",
                                               fill="#ffcd70", font=("Sans", 16, "bold"))
        self.roi_outline = self.viewer.create_rectangle(0, 0, 1, 1, outline="#ffe14a", width=3,
                                                         tags="motion_roi", state="hidden")
        self.roi_handles = [self.viewer.create_rectangle(0, 0, 1, 1, fill="#ffe14a", outline="#181818",
                                                        tags="motion_roi", state="hidden") for _ in range(4)]
        self.plate_evidence_outline=self.viewer.create_polygon(0,0,1,0,1,1,0,1,fill='',outline='#6be4ab',width=3,state='hidden')
        self.bike_mark_outline=self.viewer.create_rectangle(0,0,1,1,outline='#65d5ff',width=3,dash=(6,3),state='hidden')
        self.ocr_box=self.viewer.create_rectangle(0,0,1,1,outline='#66cfff',width=2,dash=(5,3),state='hidden')
        self.bib_overlay_back=self.viewer.create_rectangle(12,12,13,13,fill='#080b10',outline='',state='hidden')
        self.bib_overlay_text=self.viewer.create_text(24,18,anchor='nw',text='',font=('Sans',48,'bold'),state='hidden')
        self.race_time_overlay=self.viewer.create_text(24,94,anchor='nw',text='',fill='#ffffff',font=('Sans',24,'bold'),state='hidden')
        self.race_time_back=self.viewer.create_rectangle(14,88,15,89,fill='#080b10',outline='',state='hidden')
        self.finish_line=self.viewer.create_line(0,0,0,1,fill='#ffe14a',width=2,dash=(8,5),state='hidden')
        self.front_wheel_line=self.viewer.create_line(0,0,0,1,fill='#ffe14a',width=3,state='hidden')
        self.front_wheel_circle=self.viewer.create_oval(0,0,1,1,outline='#52ebf5',width=2,state='hidden')

        ocr_bar=ttk.Frame(root,padding=(10,4))
        ocr_bar.pack(fill='x')
        self.ocr_engine_picker=ttk.Combobox(ocr_bar,textvariable=self.ocr_engine,values=('Neural OCR','Tesseract') if self.neural_available else ('Tesseract',),state='readonly',width=12)
        self.ocr_engine_picker.pack(side='left',padx=(0,6))
        self.ocr_engine_picker.bind('<<ComboboxSelected>>',self.update_ocr_engine)
        ttk.Button(ocr_bar,text='Select OCR area',command=self.select_ocr_area).pack(side='left')
        self.ocr_button=ttk.Button(ocr_bar,text='Read plates',command=self.read_plates)
        self.ocr_button.pack(side='left',padx=6)
        review_actions=ttk.Frame(root,padding=(10,3));review_actions.pack(fill='x')
        self.suggestion_label=ttk.Label(review_actions,text='Select a passing to confirm its suggested bib.')
        self.suggestion_label.pack(side='left')
        self.quick_confirm_button=ttk.Button(review_actions,text='Confirm bib',command=self.quick_confirm,state='disabled')
        self.quick_confirm_button.pack(side='left',padx=8)
        self.next_bike_button=ttk.Button(review_actions,text='Next bike ›',command=lambda:self.jump_bike(1));self.next_bike_button.pack(side='right')
        self.previous_bike_button=ttk.Button(review_actions,text='‹ Previous bike',command=lambda:self.jump_bike(-1));self.previous_bike_button.pack(side='right',padx=4)
        ttk.Button(review_actions,text='Find bikes',command=self.find_bikes).pack(side='right',padx=5)
        self.bike_count_label=ttk.Label(review_actions,text='Bike count unknown');self.bike_count_label.pack(side='right',padx=5)
        timing_bar=ttk.Frame(root,padding=(10,2));timing_bar.pack(fill='x')
        ttk.Checkbutton(timing_bar,text='Track front wheel',variable=self.wheel_enabled,command=self.toggle_wheel_timing).pack(side='left')
        ttk.Button(timing_bar,text='Analyze wheels',command=lambda:self.request_wheels(force=True)).pack(side='left',padx=5)
        self.crossing_button=ttk.Button(timing_bar,text='Crossing frame',command=self.jump_crossing,state='disabled');self.crossing_button.pack(side='left',padx=5)
        self.wheel_status=ttk.Label(timing_bar,text='Centreline = finish · wheel timing pending');self.wheel_status.pack(side='left',padx=8)
        ttk.Button(ocr_bar,text='Review bibs…',command=self.show_ocr_results).pack(side='left')
        self.ocr_label=ttk.Label(ocr_bar,text='Select a saved clip and an area containing the plates.')
        self.ocr_label.pack(side='left',padx=10)
        self.batch_label=ttk.Label(ocr_bar,text='');self.batch_label.pack(side='right',padx=6)
        self.upright_control=ttk.Checkbutton(ocr_bar,text='Upright only (test)',variable=self.ocr_upright,command=self.set_ocr_upright)
        self.orientation_label=ttk.Label(ocr_bar,text='All orientations')
        self.update_ocr_engine()

        review_controls=ttk.Frame(root,padding=(10,3));review_controls.pack(fill='x')
        self.star_button=ttk.Button(review_controls,text='☆ Star clip',command=self.toggle_star,state='disabled')
        self.star_button.pack(side='left')
        ttk.Button(review_controls,text='−',width=3,command=lambda:self.zoom_review(1/1.25)).pack(side='left',padx=(12,2))
        ttk.Button(review_controls,text='+',width=3,command=lambda:self.zoom_review(1.25)).pack(side='left')
        ttk.Button(review_controls,text='Fit (Esc)',command=self.fit_review).pack(side='left',padx=4)
        self.zoom_label=ttk.Label(review_controls,text='100%');self.zoom_label.pack(side='left')
        self.review_help=ttk.Label(review_controls,text='Review: scroll to zoom at pointer · drag to pan · + / − / 0');self.review_help.pack(side='right')

        transport = ttk.Frame(root, padding=(10, 6))
        transport.pack(fill="x")
        self.position_label = ttk.Label(transport, text="Live camera", width=37)
        self.position_label.pack(side="left")
        self.scale = ttk.Scale(transport, from_=0, to=1, command=self.scale_changed)
        self.scale.pack(side="left", fill="x", expand=True, padx=10)
        self.updating_scale = False
        self.frame_label = ttk.Label(transport, text="", width=19, anchor="e")
        self.frame_label.pack(side="right")

        self.browser_area=ttk.Frame(root);self.browser_area.pack(fill='x')
        browser=ttk.Frame(self.browser_area,padding=(10,4));browser.pack(fill='x')
        ttk.Label(browser,text='Date').pack(side='left')
        self.date_picker=ttk.Combobox(browser,textvariable=self.review_day,values=('Today','All dates'),width=12)
        self.date_picker.pack(side='left',padx=4)
        self.date_picker.bind('<<ComboboxSelected>>',lambda e:self.apply_browser())
        self.date_picker.bind('<Return>',lambda e:self.apply_browser())
        ttk.Button(browser,text='Today',command=self.browse_today).pack(side='left')
        ttk.Label(browser,text='Bibs').pack(side='left',padx=(12,0))
        self.bib_entry=ttk.Entry(browser,textvariable=self.bib_filter,width=16);self.bib_entry.pack(side='left',padx=4)
        self.bib_entry.bind('<Return>',lambda e:self.apply_browser())
        ttk.Button(browser,text='Filter',command=self.apply_browser).pack(side='left')
        ttk.Checkbutton(browser,text='★ only',variable=self.stars_only,command=self.apply_browser).pack(side='left',padx=6)
        ttk.Button(browser,text='Sightings…',command=self.show_passages).pack(side='left')
        ttk.Button(browser,text='Event passings…',command=self.show_event_passings).pack(side='left',padx=4)
        ttk.Button(browser,text='Motion / storage…',command=self.show_motion_options).pack(side='right',padx=4)
        menu=tk.Menu(root);self.cleanup_menu=tk.Menu(menu,tearoff=False)
        self.cleanup_menu.add_command(label='Delete recordings for selected date…',command=self.preview_cleanup)
        self.cleanup_menu.add_separator()
        self.cleanup_menu.add_command(label='Motion quiet-tail limit…',command=self.set_quiet_close)
        menu.add_cascade(label='Maintenance',menu=self.cleanup_menu);root.configure(menu=menu)

        strip_header = ttk.Frame(self.browser_area, padding=(10, 4))
        strip_header.pack(fill="x")
        self.count_label = ttk.Label(strip_header, text="Saved clips · 0")
        self.count_label.pack(side="left")
        ttk.Label(strip_header, text="Bibs match any entered number · ✓ operator-confirmed · ? unreviewed").pack(side="right")
        self.strip = tk.Canvas(self.browser_area, height=143, background="#151b23", highlightthickness=2,
                               highlightbackground="#303a48", highlightcolor="#66b9ff", takefocus=True)
        self.strip.pack(fill="x")
        self.scroll = ttk.Scrollbar(self.browser_area, orient="horizontal", command=self.strip.xview)
        self.scroll.pack(fill="x")
        self.strip.configure(xscrollcommand=self.scroll.set)
        self.strip.bind("<ButtonPress-1>", self.strip_press)
        self.strip.bind("<B1-Motion>", self.strip_drag)
        self.strip.bind("<ButtonRelease-1>", self.strip_release)
        self.strip.bind("<MouseWheel>", lambda e: self.strip.xview_scroll(-int(e.delta / 120), "units"))
        self.strip.bind("<Button-4>", lambda _: self.strip.xview_scroll(-2, "units"))
        self.strip.bind("<Button-5>", lambda _: self.strip.xview_scroll(2, "units"))
        for key, amount in (("Left", -1), ("Right", 1), ("Prior", "page-back"), ("Next", "page-forward"),
                            ("Home", -10**9), ("End", 10**9)):
            self.strip.bind(f"<{key}>", lambda e, n=amount: self.move_clip(n))
        self.strip.bind("<Return>", lambda _: self.viewer.focus_set())

        self.status_label = ttk.Label(self.browser_area, text="Starting recorder…", padding=(10, 7))
        self.status_label.pack(fill="x")
        for key, amount in (("Left", -1), ("Right", 1), ("Prior", -10), ("Next", 10),
                            ("Home", -10**9), ("End", 10**9)):
            root.bind(f"<{key}>", lambda e, n=amount: self.step(n))
        root.bind("<space>", lambda _: self.toggle_play())
        root.bind('<Return>',lambda e:self.quick_confirm() if self.root.focus_get()==self.viewer else None)
        root.bind('<Control-Left>',lambda e:None if self.editing_text() else self.jump_bike(-1))
        root.bind('<Control-Right>',lambda e:None if self.editing_text() else self.jump_bike(1))
        root.bind("<Escape>", self.escape_review)
        root.bind("+",lambda e:self.zoom_key(e,1.25))
        root.bind("=",lambda e:self.zoom_key(e,1.25))
        root.bind("-",lambda e:self.zoom_key(e,1/1.25))
        root.bind("0",lambda e:self.zoom_key(e,0))
        root.bind("l", lambda e: None if self.editing_text() else self.go_live(follow_race=True))
        self.review_shortcut_tag='RaceVideoReview'+str(id(self))
        for sequence,action in (('<space>','confirmed'),('<plus>','add'),('<KP_Add>','add'),('<minus>','ignored'),('<KP_Subtract>','ignored'),('<Delete>','ignored'),('<KP_Delete>','ignored')):
            root.bind_class(self.review_shortcut_tag,sequence,lambda e,action=action:self.review_shortcut(e,action))
        root.bind_class(self.review_shortcut_tag,'<KeyRelease-space>',lambda e:self.review_shortcut(e,'release'))
        for sequence,action in (('<Control-z>','undo'),('<Control-r>','redo')):
            root.bind_class(self.review_shortcut_tag,sequence,lambda e,action=action:self.review_shortcut(e,action))
        for key,dx,dy in (('Left',-1,0),('Right',1,0),('Up',0,-1),('Down',0,1)):
            root.bind_class(self.review_shortcut_tag,'<'+key+'>',lambda e,dx=dx,dy=dy:self.review_navigation(e,dx,dy))
        self.install_review_shortcuts(root)
        self.reader.start()
        self.viewer.focus_set()
        root.after(30, self.poll)
        root.after(50,self.restore_session)
        root.after(100,self.toggle_compact_passings)
        root.after(1000,self.persist_session)

    def session_snapshot(self):
        panel=self.passings_panel;opened=panel is not None and panel.window.winfo_exists()
        if opened:self.last_passings_state=panel.session_snapshot()
        try:maximized=bool(self.root.attributes('-zoomed'))
        except tk.TclError:maximized=False
        return dict(version=1,geometry=self.root.geometry(),maximized=maximized,date=self.review_day.get(),bibs=self.bib_filter.get(),stars=self.stars_only.get(),
            mode=self.mode,clip=self.selected,ordinal=getattr(self,'displayed_ordinal',None),view=vars(self.view).copy(),wheel_enabled=self.wheel_enabled.get(),
            compact_view=dict(x=self.compact_passings.canvas.xview()[0],y=self.compact_passings.canvas.yview()[0],width=self.video_area.sashpos(0)) if self.compact_passings and self.compact_passings.visible else self.saved_session.get('compact_view',{}),
            passings_open=opened,passings=self.last_passings_state,compact_passings=self.compact_enabled.get(),passings_window_open=bool(opened and panel.window.state()!='withdrawn'))

    def persist_session(self):
        if self.closing:return
        state=self.session_snapshot()
        if state!=getattr(self,'last_saved_session',None):
            self.last_saved_session=state;self.reader.jobs.put(('ui_session',state))
        self.root.after(1000,self.persist_session)

    def restore_session(self):
        state=self.saved_session
        if not state:return
        self.apply_browser()
        if state.get('mode')=='replay' and state.get('clip'):
            self.pending_seek=(state['clip'],state.get('ordinal') or 0)
            self.restore_view=(state['clip'],state.get('view',{}))
            self.pending_session_clip=state['clip']
        if state.get('passings_open') and state.get('passings_window_open',not self.compact_enabled.get()):self.show_event_passings(state.get('passings'))

    def editing_text(self):
        widget=self.root.focus_get()
        return widget is not None and widget.winfo_class() in ('Entry','TEntry','TCombobox','Text','Spinbox','TSpinbox')

    def install_review_shortcuts(self,widget):
        # Before widget/class bindings, so Space cannot activate a focused
        # Ignore button and then confirm the resulting selection as well.
        tags=widget.bindtags()
        if self.review_shortcut_tag not in tags:widget.bindtags((self.review_shortcut_tag,*tags))
        for child in widget.winfo_children():
            if not isinstance(child,tk.Toplevel):self.install_review_shortcuts(child)

    def review_shortcut(self,event,action):
        panel=self.passings_panel
        if panel is None or not panel.window.winfo_exists():return
        if (event.state & 0x0c and action not in ('undo','redo')) or event.widget.winfo_class() in ('Entry','TEntry','TCombobox','Text','Spinbox','TSpinbox'):return
        if action=='add':panel.begin_add_bib()
        elif action=='undo':panel.undo_review()
        elif action=='redo':panel.redo_review()
        elif action!='release':panel.review_action(action,advance=action in ('confirmed','ignored'))
        return 'break'

    def review_navigation(self,event,dx,dy):
        panel=self.passings_panel
        if panel is None or not panel.window.winfo_exists() or event.state & 0x0c:return
        return panel.move_selection(event,dx,dy)

    def set_passings_layout(self,active):
        if active:self.browser_area.pack_forget()
        else:self.browser_area.pack(fill='x')
        self.review_help.configure(text='Review: scroll to zoom · drag to pan · Space confirm · + add bib · Del ignore + next · − ignore' if active else 'Review: scroll to zoom at pointer · drag to pan · + / − / 0')
        self.refresh_play_button()
        self.update_bib_overlay()

    def refresh_play_button(self):
        active=self.passings_panel is not None and self.passings_panel.window.winfo_exists()
        self.play_button.configure(text=('Ⅱ  Pause' if self.playing else '▶  Play')+('' if active else '  (Space)'))

    def timing_context(self,ns):
        from .race_clock import context
        panel=self.passings_panel
        model=panel.model if panel is not None and panel.window.winfo_exists() and panel.model and panel.model['event']['id']==panel.event_id else None
        preferred=model['event'] if model else next((e for e in self.race_events if e['id']==self.last_passings_state.get('event_id')),None)
        import math
        try:offset=model['offset'] if model else float(self.last_passings_state.get('offset',0) or 0)
        except (TypeError,ValueError):offset=0
        if not math.isfinite(offset) or abs(offset)>86400:offset=0
        return context(ns,self.race_events,preferred,offset)

    def refresh_time_displays(self):
        for clip in self.clips:self.strip.itemconfigure(f"caption:{clip['id']}",text=f"{'★ ' if clip.get('starred') else ''}#{clip['id']}  {self.display_time(clip['started_ns'],milliseconds=False)}")
        self.time_overlay_signature=None;self.draw_time_overlay();self.draw_wheel_overlay()
        if self.passages_window is not None and self.passages_window.winfo_exists():
            for key,row in getattr(self,'passage_rows',{}).items():
                if self.passages_tree.exists(key):self.passages_tree.set(key,'time',self.display_time(row['first_ns']))

    def display_time(self,ns,camera=True,milliseconds=True,compact=False,prefix=True):
        from .race_clock import display
        event,offset=self.timing_context(ns)
        return display(ns,event,offset,camera,milliseconds,prefix,compact)

    def draw_time_overlay(self):
        ordinal=getattr(self,'displayed_ordinal',None)
        stamp=self.index[ordinal]['received_ns'] if self.mode=='replay' and ordinal is not None and 0<=ordinal<len(self.index) else self.last_preview_received_ns if self.mode=='live' else None
        if not stamp:
            self.time_overlay_signature=None
            for item in (self.race_time_overlay,self.race_time_back):self.viewer.itemconfigure(item,state='hidden')
            if self.compact_passings and self.compact_passings.visible:self.compact_passings.clock.configure(text='')
            return
        crossing=self.current_wheel_report().get('crossing') if self.wheel_enabled.get() else None
        # Left overlay stays uncluttered. Detailed frame/estimate/bracket labels
        # remain in the status controls; all stored timing retains nanoseconds.
        value=self.wheel_time_label(self.current_wheel_report(),stamp) if crossing else self.display_time(stamp,milliseconds=False,compact=True,prefix=False)
        if self.wheel_enabled.get():
            for entry,report,sample,label in self.visible_wheel_peers():
                value+='\n'+label+'  '+self.wheel_time_label(report,stamp)
        signature=(value,self.mode)
        if signature!=getattr(self,'time_overlay_signature',None):
            self.time_overlay_signature=signature;self.viewer.itemconfigure(self.race_time_overlay,text=value,state='normal')
            x0,y0,x1,y1=self.viewer.bbox(self.race_time_overlay)
            self.viewer.coords(self.race_time_back,x0-10,y0-6,x1+10,y1+6);self.viewer.itemconfigure(self.race_time_back,state='normal')
            if self.mode=='replay':self.frame_caption(ordinal)
            else:self.position_label.configure(text=value.splitlines()[0])
        self.viewer.tag_raise(self.race_time_back);self.viewer.tag_raise(self.race_time_overlay)
        if self.compact_passings and self.compact_passings.visible:
            if self.compact_passings.clock.cget('text')!=value:self.compact_passings.clock.configure(text=value)
            for item in (self.race_time_overlay,self.race_time_back):self.viewer.itemconfigure(item,state='hidden')

    def wheel_subject(self):
        if self.mode!='replay' or not self.index or getattr(self,'displayed_ordinal',None) is None:return None
        entries=self.navigation_stops();ordinal=self.displayed_ordinal
        def includes(e):
            first,last=e['first_ordinal'],e['last_ordinal']
            key=(self.selected,e.get('visual_key',e['key']),first,last)
            if self.wheel_data and self.wheel_data.get('clip_id')==self.selected and key==self.wheel_request_signature:
                measured=[s['ordinal'] for s in self.wheel_data.get('report',{}).get('samples',[])]
                if measured:first=min(first,min(measured));last=max(last,max(measured))
            pad=max(5,round((last-first)*.3))
            return first-pad<=ordinal<=last+pad
        active=next((e for e in entries if e['key']==self.active_bike_key and includes(e)),None)
        if active:return active
        possible=[e for e in entries if includes(e)]
        return possible[0] if len(possible)==1 else None

    def current_wheel_report(self):
        if not self.wheel_data or self.wheel_data.get('clip_id')!=self.selected:return {}
        entry=self.wheel_subject()
        if entry is None:return {}
        signature=(self.selected,entry.get('visual_key',entry['key']),entry['first_ordinal'],entry['last_ordinal'])
        return self.wheel_data.get('report',{}) if signature==self.wheel_request_signature else {}

    def toggle_wheel_timing(self):
        self.wheel_open_alignment=None
        self.wheel_request_signature=None;self.wheel_data=None;self.wheel_peer_request=None
        self.draw_wheel_overlay();self.draw_time_overlay()

    def wheel_passing_context(self,entry,peer=False):
        panel=self.passings_panel
        if panel is None or not panel.window.winfo_exists() or not panel.model or panel.model['event']['id']!=panel.event_id:return None
        if not peer and panel.selected_cell is None:return None
        from .wheel_timing import passing_context
        return passing_context(panel.model,self.selected,entry,None if peer else panel.selected_cell['cell_key'])

    def request_wheels(self,force=False):
        if force:self.wheel_enabled.set(True);self.wheel_retry_at=0
        if not self.wheel_enabled.get() or time.monotonic()<self.wheel_retry_at:return
        entry=self.wheel_subject()
        if entry is None:return
        signature=(self.selected,entry.get('visual_key',entry['key']),entry['first_ordinal'],entry['last_ordinal'])
        context=self.wheel_passing_context(entry)
        if self.wheel_data and self.wheel_data.get('id') and signature==self.wheel_request_signature and context:
            link_signature=(self.wheel_data['id'],repr(context))
            if link_signature!=self.wheel_link_signature:
                self.wheel_link_signature=link_signature;self.reader.jobs.put(('wheel_link',(self.wheel_data['id'],context)))
        if self.source_size()[0]<640 and not force:return
        if signature==self.wheel_request_signature and not force:
            if self.wheel_data and self.wheel_data['state'] in ('complete','error') and self.wheel_peer_request is None:
                ordinal=self.displayed_ordinal
                for peer in self.navigation_stops():
                    peer_key=(self.selected,peer.get('visual_key',peer['key']),peer['first_ordinal'],peer['last_ordinal'])
                    if peer_key==signature or peer_key in self.wheel_reports or not peer.get('points'):continue
                    if not peer['first_ordinal']<=ordinal<=peer['last_ordinal']:continue
                    self.wheel_peer_request=peer_key
                    self.reader.jobs.put(('wheel_peer_start',(peer_key,self.selected,peer,False,self.wheel_passing_context(peer,peer=True))));break
            return
        self.wheel_request_signature=signature;self.wheel_data=None
        self.reader.wheel_requested_signature=signature
        self.reader.jobs.put(('wheel_start',(signature,self.selected,entry,force,context)))
        self.wheel_status.configure(text='Front-wheel analysis queued · identity confirmation is separate')

    def draw_wheel_overlay(self):
        for item in (self.finish_line,self.front_wheel_line,self.front_wheel_circle):self.viewer.itemconfigure(item,state='hidden')
        for items in self.wheel_peer_items.values():
            for item in items:self.viewer.itemconfigure(item,state='hidden')
        self.crossing_button.configure(state='disabled',text='Crossing frame')
        if not self.wheel_enabled.get() or not self.image_bounds():return
        left,top,width,height=self.image_bounds();canvas_height=self.viewer.winfo_height()
        data=self.wheel_data
        if not data or data.get('clip_id')!=self.selected:return
        report=data.get('report',{});ordinal=getattr(self,'displayed_ordinal',None)
        entry=self.wheel_subject()
        if entry is None:return
        signature=(self.selected,entry.get('visual_key',entry['key']),entry['first_ordinal'],entry['last_ordinal'])
        if signature!=self.wheel_request_signature:return
        crossing=report.get('crossing')
        if crossing:
            self.crossing_button.configure(state='normal')
            estimate=crossing.get('estimated_received_ns')
            message=('Finish ≈ '+self.display_time(estimate)) if estimate is not None else 'Crossing bracket; insufficient frames for interpolation'
            self.wheel_status.configure(text=message+f" · {crossing['bracket_monotonic_ns']/1e6:.1f} ms bracket · camera clock")
        elif data['state']=='complete':self.wheel_status.configure(text='Front wheel unresolved'+(': '+report['geometry']['reason'] if report.get('geometry',{}).get('reason') else '') if not report.get('samples') else 'Wheel tracked; crossing not bracketed')
        elif data['state']=='error':self.wheel_status.configure(text='Wheel analysis: '+str(data.get('error')))
        else:
            from .wheel_timing import progress_label
            self.wheel_status.configure(text='Analysing '+progress_label(data))
        if not crossing and report.get('samples'):self.crossing_button.configure(state='normal',text='Wheel frame')
        for peer,peer_report,peer_sample,label in self.visible_wheel_peers():
            key=peer.get('visual_key',peer['key'])
            if key not in self.wheel_peer_items:
                self.wheel_peer_items[key]=(self.viewer.create_line(0,0,0,1,fill='#ffe14a',width=2),self.viewer.create_text(0,0,anchor='nw',fill='#ffe14a',font=('TkDefaultFont',12,'bold')))
            line,caption=self.wheel_peer_items[key];px=left+peer_sample['leading_x']*width/peer_report['width']
            self.viewer.coords(line,px,max(0,top),px,min(canvas_height,top+height))
            self.viewer.coords(caption,px+4,max(0,top)+8);self.viewer.itemconfigure(caption,text=label,state='normal')
            self.viewer.itemconfigure(line,state='normal');self.viewer.tag_raise(line);self.viewer.tag_raise(caption)
        sample=next((s for s in report.get('samples',[]) if s['ordinal']==ordinal),None)
        if not sample:
            if data['state']=='complete' and report.get('samples'):self.wheel_status.configure(text=self.wheel_status.cget('text')+' · no wheel measurement in this frame')
            return
        sw,sh=report['width'],report['height'];x=left+sample['leading_x']*width/sw
        self.viewer.coords(self.front_wheel_line,x,max(0,top),x,min(canvas_height,top+height))
        self.viewer.itemconfigure(self.front_wheel_line,state='normal');self.viewer.tag_raise(self.front_wheel_line)


    def wheel_time_label(self,report,stamp):
        crossing=report.get('crossing') or {}
        estimate=crossing.get('estimated_received_ns')
        if crossing and estimate is None:
            before=self.display_time(crossing['before_received_ns'],milliseconds=False,compact=True,prefix=False)
            after=self.display_time(crossing['after_received_ns'],milliseconds=False,compact=True,prefix=False)
            return before if before==after else before+' – '+after
        return self.display_time(estimate if estimate is not None else stamp,milliseconds=False,compact=True,prefix=False)

    def visible_wheel_peers(self):
        if self.mode!='replay':return []
        ordinal=getattr(self,'displayed_ordinal',None);result=[]
        for i,entry in enumerate(self.navigation_stops(),1):
            key=(self.selected,entry.get('visual_key',entry['key']),entry['first_ordinal'],entry['last_ordinal'])
            if key==self.wheel_request_signature:continue
            report=self.wheel_reports.get(key,{}).get('report',{})
            sample=next((s for s in report.get('samples',[]) if s['ordinal']==ordinal),None)
            if sample:
                numbers=entry.get('numbers',[])
                label='/'.join(map(str,numbers)) if numbers else 'Bike '+str(i)
                result.append((entry,report,sample,label))
        return result

    def align_open_wheel(self):
        pending=self.wheel_open_alignment
        if not pending or not self.wheel_data or self.wheel_data['state'] not in ('complete','error'):return
        if self.mode!='replay' or self.selected!=pending['clip'] or self.selection_generation!=pending['generation'] or self.playing or self.ordinal!=pending['ordinal']:
            self.wheel_open_alignment=None;return
        report=self.current_wheel_report()
        if not report:return
        self.wheel_open_alignment=None
        samples=report.get('samples',[])
        if not samples or any(s['ordinal']==self.ordinal for s in samples):return
        nearest=min(samples,key=lambda s:abs(s['ordinal']-self.ordinal))['ordinal']
        if not 0<=nearest<len(self.index):return
        self.ordinal=nearest;self.request_frame()
        self.status_label.configure(text=f'Opened measured wheel frame {nearest+1}; original review frame {pending["ordinal"]+1} has no wheel measurement.')

    def jump_crossing(self):
        if self.mode!='replay':return
        report=self.current_wheel_report();crossing=report.get('crossing')
        if crossing:ordinal=crossing['first_observed_after_ordinal']
        elif report.get('samples'):
            ordinal=min(report['samples'],key=lambda s:abs(s['ordinal']-self.displayed_ordinal))['ordinal']
        else:return
        self.playing=False;self.refresh_play_button();self.ordinal=ordinal;self.request_frame()

    def browse_today(self):
        self.review_day.set('Today');self.apply_browser()

    def apply_browser(self, preserve_pending=False):
        chosen=self.review_day.get().strip()
        try:
            if chosen not in ('Today','All dates'):date.fromisoformat(chosen)
            bibs=storage.bib_numbers(self.bib_filter.get())
        except ValueError as exc:
            self.status_label.configure(text=str(exc),foreground='#ff9b87');return 'break'
        pending=self.pending_review if preserve_pending else None
        self.browse_generation+=1
        self.reader.browse=(self.browse_generation,chosen,bibs,bool(self.stars_only.get()))
        self.go_live()
        self.pending_review=pending
        if self.passages_window is not None and self.passages_window.winfo_exists():self.show_passages(raise_window=False)
        return 'break'

    def source_size(self):
        return getattr(self,'review_source_size',(1280,720))

    def zoom_key(self,event,factor):
        if self.editing_text():return None
        return self.fit_review() if factor==0 else self.zoom_review(factor)

    def zoom_wheel(self,event,direction=None):
        if self.mode!='replay' or self.ocr_selecting:return None
        delta=direction if direction is not None else max(-3,min(3,event.delta/120))
        if delta:self.zoom_review(1.25**delta,(event.x,event.y))
        return 'break'

    def zoom_review(self,factor,point=None):
        if self.mode!='replay' or not self.index:return 'break'
        canvas=self.reader.size
        self.view.zoom_at(factor,point or (canvas[0]/2,canvas[1]/2),self.source_size(),canvas)
        self.zoom_label.configure(text=f'{self.view.zoom*100:.0f}%')
        self.request_frame()
        return 'break'

    def fit_review(self):
        if self.mode=='replay':
            self.view=View();self.pan_drag=None;self.zoom_label.configure(text='100%');self.request_frame()
        return 'break'

    def escape_review(self,event=None):
        if self.motion_options is not None and self.motion_options.window.winfo_exists() and self.motion_options.drawing:
            self.motion_options.drawing=None;self.motion_options.preview=None;self.motion_options.start=None
            self.motion_options.overlays();self.viewer.configure(cursor='');return 'break'
        if self.bike_marking:
            self.clear_bike_mark();return 'break'
        if self.mode=='replay' and self.view.zoom>1:return self.fit_review()
        self.pending_review=None;self.go_live();return 'break'

    def update_star_button(self,clip_id):
        clip=next((c for c in self.clips if c['id']==clip_id),None)
        self.star_button.configure(text='★ Starred' if clip and clip.get('starred') else '☆ Star clip')
        self.star_button.state(['!disabled'] if self.mode=='replay' and clip else ['disabled'])

    def toggle_star(self):
        clip=next((c for c in self.clips if c['id']==self.selected),None)
        if self.mode=='replay' and clip:
            self.star_button.state(['disabled'])
            self.reader.jobs.put(('star',(clip['id'],not bool(clip.get('starred')))))

    def preview_cleanup(self):
        if self.cleanup_pending:return
        chosen=self.review_day.get().strip()
        if chosen=='All dates':
            self.status_label.configure(text='Select one date before cleaning up recordings.');return
        day=date.today().isoformat() if chosen=='Today' else chosen
        try:storage.local_day_bounds(day)
        except ValueError:
            self.status_label.configure(text='Enter a date as YYYY-MM-DD.');return
        self.set_cleanup_pending(True)
        self.reader.jobs.put(('cleanup_preview',day))

    def set_quiet_close(self):
        from tkinter import simpledialog
        value=simpledialog.askfloat('Motion quiet-tail limit',
            'Close future motion captures after this many quiet seconds.\n0 retains the full configured post-roll.\nApplies on the next recorder start; existing videos are unchanged.',
            initialvalue=self.last_status.get('configured_quiet_close',1.0),minvalue=0,maxvalue=30,parent=self.root)
        if value is not None:
            import math
            if math.isfinite(value):self.reader.jobs.put(('quiet_close',value))

    def set_cleanup_pending(self,pending):
        self.cleanup_pending=pending
        self.cleanup_menu.entryconfigure(0,state='disabled' if pending else 'normal')

    def confirm_cleanup(self,preview):
        if not preview['clips']:
            self.set_cleanup_pending(False)
            messagebox.showinfo('Clean up recordings',f"No deletable clips on {preview['day']}.\n{preview['starred']} starred and {preview['busy']} active-analysis clips retained.",parent=self.root)
            return
        from .cleanup_panel import CleanupPanel
        def finish(approved):
            self.cleanup_panel=None
            if approved:self.reader.jobs.put(('cleanup_apply',preview))
            else:self.set_cleanup_pending(False)
        self.cleanup_panel=CleanupPanel(self.root,preview,self.path,finish)

    def toggle_compact_passings(self):
        if self.compact_enabled.get():
            if self.compact_passings is None:
                from .compact_passings import CompactPassings
                self.compact_passings=CompactPassings(self,self.video_area)
            compact=self.compact_passings;compact.visible=True
            if str(compact.frame) not in self.video_area.panes():self.video_area.insert(0,compact.frame,weight=0)
            self.video_area.sashpos(0,self.saved_session.get('compact_view',{}).get('width',min(440,max(260,self.root.winfo_width()//3))))
            compact.signature=None
        elif self.compact_passings:
            compact=self.compact_passings;compact.visible=False
            if str(compact.frame) in self.video_area.panes():self.video_area.forget(compact.frame)
            panel=self.passings_panel
            if panel and panel.window.winfo_exists() and panel.window.state()=='withdrawn':panel.close()
        self.bib_overlay_signature=None;self.time_overlay_signature=None;self.update_bib_overlay()

    def show_event_passings(self,restore=None,embedded=False):
        if self.passings_panel is not None and self.passings_panel.window.winfo_exists():
            if not embedded:self.passings_panel.window.deiconify();self.passings_panel.window.lift();self.passings_panel.paint()
            return
        from .passings_panel import PassingsPanel
        day=self.review_day.get().strip()
        if day in ('Today','All dates'):day=date.today().isoformat()
        if restore is None and self.last_passings_state.get('day')==day:restore=self.last_passings_state
        try:
            self.passings_panel=PassingsPanel(self,day,restore=restore)
            if embedded:self.passings_panel.window.withdraw()
            self.set_passings_layout(True)
        except Exception as exc:messagebox.showerror('Event passings',str(exc),parent=self.root)

    def show_passages(self,raise_window=True):
        generation,chosen,bibs,stars=self.reader.browse
        day=date.today().isoformat() if chosen=='Today' else None if chosen=='All dates' else chosen
        if self.passages_window is None or not self.passages_window.winfo_exists():
            self.passages_window=tk.Toplevel(self.root);self.passages_window.title('OCR sightings — candidate evidence')
            ttk.Label(self.passages_window,text='Latest completed OCR per clip. Intervals are between candidate sightings, not verified laps.\nDouble-click to review the source frame.').pack(padx=10,pady=8)
            self.passages_tree=ttk.Treeview(self.passages_window,columns=('bib','time','interval','clip','status'),show='headings',height=14)
            for key,title,width in [('bib','Bib',65),('time','Race time / clock',190),('interval','Since previous sighting',160),('clip','Clip',70),('status','OCR evidence',110)]:
                self.passages_tree.heading(key,text=title);self.passages_tree.column(key,width=width,anchor='center')
            self.passages_tree.pack(fill='both',expand=True,padx=10,pady=8)
            self.passages_tree.bind('<Double-1>',self.jump_passage)
        if raise_window:self.passages_window.lift()
        self.passages_day=day or 'All dates'
        self.passages_window.title(f'OCR sightings — {self.passages_day} — loading')
        self.passages_tree.delete(*self.passages_tree.get_children())
        self.reader.jobs.put(('passages',(generation,day,bibs,stars)))

    def receive_passages(self,generation,rows):
        if generation!=self.browse_generation or self.passages_window is None or not self.passages_window.winfo_exists():return
        self.passage_rows={str(r['id']):r for r in rows}
        from collections import Counter
        counts=Counter(r['number'] for r in rows)
        self.passages_window.title(f'OCR sightings — {self.passages_day} — {len(rows)} candidate encounters'+(' · '+', '.join(f'{number}: {count}' for number,count in sorted(counts.items())) if counts else ''))
        self.passages_tree.delete(*self.passages_tree.get_children());previous={}
        for row in rows:
            last=previous.get(row['number'])
            seconds=(row['first_ns']-last)/1e9 if last is not None else None
            delta='—' if seconds is None else f'{seconds:.1f}s' if seconds<60 else f'{seconds/60:.2f} min'
            previous[row['number']]=row['first_ns']
            stamp=self.display_time(row['first_ns'])
            self.passages_tree.insert('', 'end',iid=str(row['id']),values=(row['number'],stamp,delta,row['clip_id'],row['status']))

    def jump_passage(self,event=None):
        selection=self.passages_tree.selection()
        if selection:
            row=self.passage_rows[selection[0]]
            self.pending_seek=(row['clip_id'],row['ordinal'])
            self.select(row['clip_id'])

    def send(self, name):
        self.reader.jobs.put(("command", name))

    def start_recorder(self):
        from .service import configuration
        self.reader.jobs.put(("start_recorder", configuration(self.last_status)))
        self.status_label.configure(text="Starting recorder…")
        if self.camera_panel:
            self.camera_panel.message.set("Starting recorder…")

    def toggle_recorder(self):
        active = (self.last_status.get('state') in ('recording', 'starting') and
                  time.time() - self.last_status.get('heartbeat', 0) < 3)
        if active:
            self.send('stop')
        else:
            self.start_recorder()

    def open_camera(self):
        if self.camera_panel:
            self.camera_panel.window.lift()
        else:
            from .camera_panel import CameraPanel
            self.camera_panel = CameraPanel(self)

    def show_motion_options(self):
        if self.motion_options is not None and self.motion_options.window.winfo_exists():self.motion_options.window.lift();return
        from .motion_options import MotionOptions
        self.motion_options=MotionOptions(self)

    def quick_confirm(self):
        panel=self.passings_panel
        if panel is not None and panel.window.winfo_exists():panel.review_action('confirmed')
        self.update_quick_confirm()

    def update_quick_confirm(self):
        self.update_bib_overlay()
        if not hasattr(self,'quick_confirm_button'):return
        panel=self.passings_panel
        valid=panel is not None and panel.window.winfo_exists() and panel.selected_cell is not None
        number=panel.review_number.get().strip() if valid else ''
        index=panel.capture_picker.current() if valid else -1
        row=panel.capture_rows[index] if valid and 0<=index<len(panel.capture_rows) else None
        valid=bool(row and panel.model and panel.model['event']['id']==panel.event_id and self.mode=='replay' and self.selected==row['clip_id'] and getattr(self,'displayed_ordinal',None) is not None and number.isascii() and number.isdigit() and 1<=len(number)<=3)
        confirmed=bool(valid and row.get('confirmed') and row.get('number')==number)
        signature=(valid,number,confirmed,bool(panel and panel.review_pending))
        if signature==getattr(self,'quick_confirm_signature',None):return
        self.quick_confirm_signature=signature
        self.suggestion_label.configure(text=f'Suggested bib {number}' if valid else 'Select a passing to confirm its suggested bib.')
        self.quick_confirm_button.configure(text=('Confirmed ' if confirmed else 'Confirm ')+number+' ✓' if valid else 'Confirm bib',
            state='normal' if valid and not confirmed and not panel.review_pending else 'disabled')

    def update_bib_overlay(self):
        self.draw_time_overlay()
        panel=self.passings_panel
        cell=panel.selected_cell if panel is not None and panel.window.winfo_exists() else None
        index=panel.capture_picker.current() if cell else -1
        row=panel.capture_rows[index] if cell and 0<=index<len(panel.capture_rows) else None
        visible=bool(cell and row and self.mode=='replay' and self.selected==row['clip_id'] and getattr(self,'displayed_ordinal',None) is not None)
        signature=(visible,cell['bib'] if cell else None,cell['state'] if cell else None)
        compact=self.compact_passings
        if compact and compact.visible:
            colours=dict(matched='#65e894',missing='#ffe14a',video_only='#ffe14a',extra='#ff6b6b',ignored='#bbbbbb')
            header=(cell['bib'] if visible else 'Live' if self.mode=='live' else '—',colours.get(cell['state'],'#ffe14a') if visible else '#ffe14a')
            if header!=getattr(compact,'bib_signature',None):
                compact.bib_signature=header;compact.bib.configure(text=header[0],fg=header[1])
            for item in (self.bib_overlay_text,self.bib_overlay_back):self.viewer.itemconfigure(item,state='hidden')
            return
        if signature==getattr(self,'bib_overlay_signature',None):return
        self.bib_overlay_signature=signature
        if not visible:
            for item in (self.bib_overlay_text,self.bib_overlay_back):self.viewer.itemconfigure(item,state='hidden')
            return
        colours=dict(matched='#65e894',missing='#ffe14a',video_only='#ffe14a',extra='#ff6b6b',ignored='#bbbbbb')
        self.viewer.itemconfigure(self.bib_overlay_text,text=cell['bib'],fill=colours[cell['state']],state='normal')
        x0,y0,x1,y1=self.viewer.bbox(self.bib_overlay_text)
        self.viewer.coords(self.bib_overlay_back,x0-10,y0-6,x1+10,y1+6)
        self.viewer.itemconfigure(self.bib_overlay_back,state='normal')
        self.viewer.tag_raise(self.bib_overlay_back);self.viewer.tag_raise(self.bib_overlay_text)

    def find_bikes(self):
        if self.mode=='replay' and self.selected is not None:self.reader.jobs.put(('find_bikes',self.selected))

    def update_bike_controls(self):
        if not hasattr(self,'bike_count_label'):return
        entries=self.navigation_stops() if self.mode=='replay' else []
        self.bike_count_label.configure(text=self.bike_navigation.get('label','Bike count unknown') if self.mode=='replay' else '')
        for button,direction in ((self.previous_bike_button,-1),(self.next_bike_button,1)):
            button.configure(state='normal' if entries and self.bike_target(direction) is not None else 'disabled')

    def navigation_stops(self):
        return self.bike_navigation.get('stops',self.bike_navigation.get('passages',[]))

    def bike_target(self,direction):
        entries=self.navigation_stops()
        current=next((i for i,e in enumerate(entries) if e['key']==self.active_bike_key and (e['ordinal']==self.ordinal or getattr(self,'active_bike_anchor',None)==self.ordinal)),None)
        if current is None:current=next((i for i,e in enumerate(entries) if e['ordinal']==self.ordinal),None)
        if current is not None:
            target=current+direction
            return target if 0<=target<len(entries) else None
        candidates=[i for i,e in enumerate(entries) if (e['ordinal']-self.ordinal)*direction>0]
        return min(candidates,key=lambda i:abs(entries[i]['ordinal']-self.ordinal)) if candidates else None

    def align_bike_selection(self):
        panel=self.passings_panel
        if panel is None or not panel.window.winfo_exists():return
        index=panel.capture_picker.current()
        row=panel.capture_rows[index] if 0<=index<len(panel.capture_rows) else None
        if not row or row['clip_id']!=self.selected:return
        matches=[e for e in self.navigation_stops() if e['first_ordinal']<=self.ordinal<=e['last_ordinal'] and
                 ((row.get('physical_key') and row['physical_key']==e.get('visual_key')) or row.get('key') in e.get('source_keys',[]))]
        if len(matches)==1:
            self.active_bike_key=matches[0]['key']
            # An OCR source frame can precede its bike's centered frame.
            self.active_bike_anchor=self.ordinal

    def jump_bike(self,direction):
        entries=self.navigation_stops()
        if self.mode!='replay' or not self.index or not entries:return
        target=self.bike_target(direction)
        if target is None:return 'break'
        entry=entries[target]
        self.active_bike_key=entry['key'];self.playing=False;self.ordinal=entry['ordinal']
        self.active_bike_anchor=self.ordinal
        box=entry.get('box')
        self.plate_evidence=(self.selected,self.ordinal,[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]]) if box else None
        self.request_frame()
        self.update_bike_controls()
        labels='/'.join(entry.get('numbers',[]))
        self.bike_count_label.configure(text=f'Bike {target+1}/{len(entries)}'+(' · '+labels if labels else '')+' · estimated')
        return 'break'

    def select_ocr_area(self):
        if self.mode=='live':
            if not self.clips:
                self.ocr_label.configure(text='Save a clip first.')
                return
            self.select(self.clips[-1]['id'])
        self.ocr_selecting=True
        self.viewer.configure(cursor='crosshair')
        self.ocr_label.configure(text='Drag a box around the search area; individual plates are found automatically.')

    def ocr_point(self,event):
        left,top,w,h=self.image_bounds()
        return max(0,min(1,(event.x-left)/w)),max(0,min(1,(event.y-top)/h))

    def draw_ocr_area(self):
        bounds=self.image_bounds()
        if self.mode!='replay' or bounds is None:
            self.viewer.itemconfigure(self.ocr_box,state='hidden')
            return
        left,top,w,h=bounds
        x0,y0,x1,y1=self.ocr_area
        self.viewer.coords(self.ocr_box,left+x0*w,top+y0*h,left+x1*w,top+y1*h)
        self.viewer.itemconfigure(self.ocr_box,state='normal')
        self.viewer.tag_raise(self.ocr_box)

    def set_ocr_upright(self):
        self.pending_ocr_rotations=[0] if self.ocr_upright.get() else [0,180]
        self.reader.jobs.put(('ocr_rotations',self.pending_ocr_rotations))

    def update_ocr_engine(self,event=None):
        self.upright_control.pack_forget();self.orientation_label.pack_forget()
        if self.ocr_engine.get()=='Neural OCR':self.orientation_label.pack(side='right',padx=6)
        else:self.upright_control.pack(side='right',padx=6)
        if event is not None:
            self.ocr_area_pending=None
            self.ocr_area=tuple(self.last_status.get('neural_ocr_area',(.05,.4,.98,.9)) if self.ocr_engine.get()=='Neural OCR' else self.last_status.get('ocr_area',(0,0,1,1)))
            self.draw_ocr_area()

    def read_plates(self):
        if self.mode=='live':
            if not self.clips:
                self.ocr_label.configure(text='Save a clip first.')
                return
            self.select(self.clips[-1]['id'])
        self.reader.jobs.put(('ocr',(self.selected,dict(engine='paddle-rider-v1' if self.ocr_engine.get()=='Neural OCR' else 'tesseract',roi=self.ocr_area,fps=8,rotations=[0] if self.ocr_upright.get() else [0,180]))))
        self.ocr_label.configure(text='OCR queued — capture continues.')
        self.ocr_button.state(['disabled'])

    def show_ocr_results(self):
        if self.ocr_window is not None and self.ocr_window.winfo_exists():
            self.ocr_window.lift();return
        self.ocr_window=tk.Toplevel(self.root)
        self.ocr_window.title('Review bibs — OCR and operator evidence')
        width=min(980,self.root.winfo_screenwidth()-30)
        x=max(0,min(self.root.winfo_rootx()+self.root.winfo_width()+12,self.root.winfo_screenwidth()-width-15))
        self.ocr_window.geometry(f'{width}x610+{x}+{max(20,self.root.winfo_rooty()+60)}')
        ttk.Label(self.ocr_window,text='Select a candidate to inspect its original frame and crop. Decisions are saved separately from OCR.\nYou can confirm several bibs in one capture, including alternatives from an overlapping group.',padding=10,wraplength=width-25).pack(fill='x')
        table=ttk.Frame(self.ocr_window);table.pack(fill='both',expand=True,padx=10,pady=5)
        self.ocr_tree=ttk.Treeview(table,columns=('number','group','frames','confidence','status','frame'),show='headings')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.ocr_tree.yview)
        self.ocr_tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y')
        for key,title,width in [('number','Bib / correction',145),('group','Encounter',110),('frames','OCR frames',85),('confidence','OCR score',90),('status','Operator review',210),('frame','Source frame',95)]:
            self.ocr_tree.heading(key,text=title);self.ocr_tree.column(key,width=width,anchor='center')
        self.ocr_tree.tag_configure('confirmed',foreground='#62dba4')
        self.ocr_tree.tag_configure('rejected',foreground='#adabb2')
        self.ocr_tree.pack(side='left',fill='both',expand=True)
        self.ocr_tree.bind('<Double-1>',self.jump_ocr)
        self.ocr_tree.bind('<<TreeviewSelect>>',self.preview_ocr)
        controls=ttk.Frame(self.ocr_window,padding=8);controls.pack(fill='x')
        self.review_yes=ttk.Button(controls,text='Yes — correct',command=lambda:self.review_bib('accepted'));self.review_yes.pack(side='left')
        self.review_no=ttk.Button(controls,text='No — reject',command=lambda:self.review_bib('rejected'));self.review_no.pack(side='left',padx=5)
        ttk.Label(controls,text='Bib:').pack(side='left',padx=(10,3))
        self.review_number=tk.StringVar()
        self.review_number_entry=ttk.Entry(controls,textvariable=self.review_number,width=7);self.review_number_entry.pack(side='left')
        self.review_number_entry.bind('<Return>',lambda event:self.add_manual_bib() if self.bike_mark or not self.ocr_tree.selection() else self.review_bib('corrected'))
        ttk.Button(controls,text='Correct selected',command=lambda:self.review_bib('corrected')).pack(side='left',padx=5)
        ttk.Button(controls,text='Clear review / remove manual',command=lambda:self.review_bib('reset')).pack(side='left',padx=5)
        extra=ttk.Frame(self.ocr_window,padding=(8,0,8,8));extra.pack(fill='x')
        self.manual_bib_button=ttk.Button(extra,text='Add bib at displayed frame',command=self.add_manual_bib);self.manual_bib_button.pack(side='left')
        ttk.Button(extra,text='Mark bike…',command=self.begin_bike_mark).pack(side='left',padx=4)
        ttk.Button(extra,text='Clear mark',command=self.clear_bike_mark).pack(side='left')
        ttk.Label(extra,text='Bike order in capture:').pack(side='left',padx=(8,3))
        ttk.Entry(extra,textvariable=self.bike_order,width=4).pack(side='left')
        self.review_message=tk.StringVar(value='Select a saved capture to review or add bibs.')
        ttk.Label(self.ocr_window,textvariable=self.review_message,padding=8).pack(fill='x')
        self.ocr_evidence_label=ttk.Label(self.ocr_window,text='Select a reading to see its machine crop.',anchor='center')
        self.ocr_evidence_label.pack(fill='x',pady=8)
        self.refresh_ocr_tree()

    def selected_bib_row(self):
        if self.ocr_window is None or not self.ocr_window.winfo_exists():return None
        selection=self.ocr_tree.selection()
        return next((r for r in self.bib_review_rows if selection and r['row_key']==selection[0]),None)

    def bike_feedback(self,text):
        if self.ocr_window is not None and self.ocr_window.winfo_exists():self.review_message.set(text)
        if self.passings_panel is not None and self.passings_panel.window.winfo_exists():self.passings_panel.review_message.set(text)

    def begin_bike_mark(self):
        if self.mode!='replay' or getattr(self,'displayed_ordinal',None) is None:
            self.bike_feedback('Display a saved frame first.');return
        self.clear_bike_mark();self.playing=False;self.ocr_selecting=False;self.bike_marking=True
        self.bike_order.set(str(max([r.get('passing_order') or 0 for r in self.bib_review_rows]+[0])+1))
        self.viewer.configure(cursor='crosshair')
        self.bike_feedback('Drag a rectangle around the intended bike in the main image; Escape cancels.')

    def clear_bike_mark(self):
        self.bike_mark=None;self.bike_drag=None;self.bike_marking=False;self.bike_mark_anchor=None
        if hasattr(self,'bike_mark_outline'):self.viewer.itemconfigure(self.bike_mark_outline,state='hidden')

    def draw_bike_mark(self):
        self.viewer.itemconfigure(self.bike_mark_outline,state='hidden')
        if not self.bike_mark or self.mode!='replay' or not self.image_bounds():return
        clip,ordinal,box=self.bike_mark
        if clip!=self.selected or ordinal!=getattr(self,'displayed_ordinal',None):return
        left,top,w,h=self.image_bounds();x0,y0,x1,y1=box
        self.viewer.coords(self.bike_mark_outline,left+x0*w,top+y0*h,left+x1*w,top+y1*h)
        self.viewer.itemconfigure(self.bike_mark_outline,state='normal');self.viewer.tag_raise(self.bike_mark_outline)

    def bike_annotation(self):
        from .bib_review import validate_bike
        box=None
        if self.bike_mark:
            clip,ordinal,box=self.bike_mark
            if clip!=self.selected or ordinal!=getattr(self,'displayed_ordinal',None):raise ValueError('Bike mark belongs to another frame; return to that frame, or clear/mark again.')
        text=self.bike_order.get().strip()
        if text and (not text.isascii() or not text.isdigit()):raise ValueError('Bike order must be a whole number')
        box,order=validate_bike(box,int(text) if text else None)
        return dict(bike_box=box,passing_order=order)

    def review_bib(self,decision):
        row=self.selected_bib_row()
        if self.mode!='replay' or row is None:
            self.review_message.set('Select a candidate in this capture first.');return
        number=self.review_number.get().strip() if decision=='corrected' else row['number'] if decision=='accepted' else None
        try:
            if number is not None:
                from .bib_review import validate_number
                validate_number(number)
        except ValueError as exc:self.review_message.set(str(exc));return
        request=dict(clip_id=self.selected,observation_id=row.get('observation_id'),review_id=row.get('review_id'),decision=decision,number=number)
        if self.bike_mark and decision in ('accepted','corrected') and row['ordinal']!=self.displayed_ordinal:
            self.review_message.set('The selected review belongs to another frame. Add this marked bike as separate manual evidence.');return
        if row.get('observation_id') is None and decision in ('accepted','corrected'):
            try:request.update(self.bike_annotation())
            except ValueError as exc:self.review_message.set(str(exc));return
        self.reader.jobs.put(('bib_review',request))
        self.review_message.set('Saving operator review…')

    def add_manual_bib(self):
        if self.mode!='replay' or not self.index or getattr(self,'displayed_ordinal',None) is None:
            self.review_message.set('Select a saved capture and wait for its source frame to display.');return
        number=self.review_number.get().strip()
        try:
            from .bib_review import validate_number
            validate_number(number)
        except ValueError as exc:self.review_message.set(str(exc));return
        try:annotation=self.bike_annotation()
        except ValueError as exc:self.review_message.set(str(exc));return
        self.pending_bike_mark_save=(self.bike_mark,self.bike_order.get())
        self.reader.jobs.put(('bib_review',dict(clip_id=self.selected,decision='manual',number=number,ordinal=self.displayed_ordinal,**annotation)))
        self.review_message.set(f'Adding {number} at displayed frame {self.displayed_ordinal+1}…')

    def preview_ocr(self,event=None):
        row=self.selected_bib_row()
        if row is None:return
        self.clear_bike_mark()
        self.review_number.set(row['number'])
        self.bike_order.set(str(row.get('passing_order') or ''))
        self.ocr_evidence_photo=None;self.ocr_evidence_label.configure(image='',text='Loading machine crop…' if row.get('observation_id') else 'Human-entered evidence: inspect the original source frame.')
        if row.get('observation_id'):self.reader.jobs.put(('ocr_evidence',row['observation_id']))
        self.jump_ocr()

    def refresh_ocr_tree(self):
        if self.ocr_window is None or not self.ocr_window.winfo_exists():return
        started=time.perf_counter()
        wanted={row['row_key'] for row in self.bib_review_rows}
        for key in self.ocr_tree.get_children():
            if key not in wanted:self.ocr_tree.delete(key)
        for position,row in enumerate(self.bib_review_rows):
            number=row['number'];original=row.get('ocr_number')
            if row.get('decision')=='corrected' and original:number=f'{original} → {number}'
            decision=row.get('decision');status={'accepted':'Confirmed','rejected':'Rejected','corrected':'Corrected','manual':'Manual confirmation'}.get(decision,'Unreviewed · '+row['status'])
            if row.get('historical'):status+=' · earlier scan'
            group=f"Bike {row['passing_order']}" if row.get('passing_order') else 'Manual' if row.get('observation_id') is None else (row.get('encounter_key') or '').split(':track:')[-1] if row.get('encounter_key') else '—'
            tags=('rejected',) if decision=='rejected' else ('confirmed',) if decision else ()
            values=tuple(map(str,(number,group,row['frame_count'] or '—',row['confidence'] if row['confidence'] is not None else '—',status,row['ordinal']+1)))
            if self.ocr_tree.exists(row['row_key']):
                if tuple(map(str,self.ocr_tree.item(row['row_key'],'values')))!=values or tuple(self.ocr_tree.item(row['row_key'],'tags'))!=tags:self.ocr_tree.item(row['row_key'],values=values,tags=tags)
                if self.ocr_tree.index(row['row_key'])!=position:self.ocr_tree.move(row['row_key'],'',position)
            else:self.ocr_tree.insert('',position,iid=row['row_key'],values=values,tags=tags)
        self.performance.observe('bib_review_render_ms',(time.perf_counter()-started)*1000)
        self.ocr_window.title(f'Review bibs — capture {self.selected if self.mode=="replay" else "not selected"} — {len(self.bib_review_rows)} entries')

    def jump_ocr(self,event=None):
        row=self.selected_bib_row()
        if row and self.index and self.mode=='replay':
            import json
            self.playing=False;self.ordinal=row['ordinal']
            quad=json.loads(row['quad']) if isinstance(row['quad'],str) else row['quad']
            self.plate_evidence=(self.selected,row['ordinal'],quad) if quad else None
            self.draw_plate_evidence();self.request_frame()

    def draw_plate_evidence(self):
        self.viewer.itemconfigure(self.plate_evidence_outline,state='hidden')
        if not self.plate_evidence or self.mode!='replay' or not self.image_bounds():return
        clip,ordinal,quad=self.plate_evidence
        if clip!=self.selected or ordinal!=getattr(self,'displayed_ordinal',None) or len(quad)!=4:return
        left,top,w,h=self.image_bounds();sw,sh=self.source_size()
        self.viewer.coords(self.plate_evidence_outline,*[value for x,y in quad for value in (left+x*w/sw,top+y*h/sh)])
        self.viewer.itemconfigure(self.plate_evidence_outline,state='normal');self.viewer.tag_raise(self.plate_evidence_outline)

    def receive_ocr(self,clip_id,result):
        if clip_id!=self.selected:return
        previous=(self.ocr_run or {}).get('state')
        previous_id=(self.ocr_run or {}).get('id')
        self.ocr_run=result
        state=result['state'] if result else 'none'
        self.ocr_button.state(['disabled'] if state in ('queued','running') else ['!disabled'])
        if result is None:
            self.ocr_label.configure(text='Select a search area, then Read plates.')
        elif state=='error':
            self.ocr_label.configure(text='OCR error: '+str(result['error']))
        elif state in ('queued','running'):
            p=result['summary'];self.ocr_label.configure(text=f"OCR {state}: {p.get('sampled_frames',0)}/{p.get('total_samples','?')} samples")
        else:
            observations=result['observations']
            labels=sorted({r['number'] for r in observations})
            self.ocr_label.configure(text=('Candidates: '+', '.join(labels) if labels else 'No confident numeric bib reads.')+
                                     f" · {result['summary'].get('wall_seconds',0):.1f}s · review required")
        if state not in ('queued','running') and self.bib_review_rows:self.update_bib_summary()
        if state!=previous or (result and result['id']!=previous_id):self.refresh_ocr_tree()

    def update_bib_summary(self):
        if (self.ocr_run or {}).get('state') in ('queued','running'):return
        confirmed=sorted({r['number'] for r in self.bib_review_rows if r.get('decision') and r['decision']!='rejected'})
        candidates=sorted({r['number'] for r in self.bib_review_rows if not r.get('decision')}-set(confirmed))
        labels=['✓'+n for n in confirmed]+['?'+n for n in candidates]
        self.ocr_label.configure(text='Bibs: '+', '.join(labels) if labels else 'All listed candidates rejected; add a bib if visible.' if self.bib_review_rows else 'No bib entries; scan or add a visible bib.')

    def resize(self, event):
        self.reader.size = (event.width, event.height)
        self.preview.resize(event.width, event.height)
        self.viewer.coords(self.picture, event.width / 2, event.height / 2)
        self.viewer.coords(self.empty, event.width / 2, event.height / 2)
        self.draw_roi()
        self.draw_ocr_area()
        if self.mode == "replay" and self.index:
            self.view.clamp(self.source_size(),self.reader.size)
            self.request_frame()

    def display(self, image, bounds=None, position=None):
        started = time.perf_counter()
        self.review_bounds=bounds
        self.display_size = image.size
        self.viewer.coords(self.picture,*(position or (self.viewer.winfo_width()/2,self.viewer.winfo_height()/2)))
        self.shown_image = ImageTk.PhotoImage(image)
        self.viewer.itemconfigure(self.picture, image=self.shown_image, state='normal')
        self.viewer.itemconfigure(self.empty, state="hidden")
        self.draw_roi()
        self.draw_ocr_area()
        self.draw_plate_evidence()
        self.draw_bike_mark()
        self.draw_wheel_overlay()
        self.update_bib_overlay()
        self.viewer.tag_raise(self.bib_overlay_back);self.viewer.tag_raise(self.bib_overlay_text)
        self.performance.observe("tk_image_submit_ms", (time.perf_counter()-started)*1000)

    def image_bounds(self):
        if self.display_size is None:
            return None
        if self.mode=='replay' and self.review_bounds is not None:
            return self.review_bounds
        w, h = self.display_size
        cx, cy = self.viewer.winfo_width() / 2, self.viewer.winfo_height() / 2
        return (cx - w / 2, cy - h / 2, w, h)

    def roi_points(self):
        bounds = self.image_bounds()
        if bounds is None:
            return None
        left, top, w, h = bounds
        x0, y0, x1, y1 = self.roi
        return left + x0 * w, top + y0 * h, left + x1 * w, top + y1 * h

    def draw_roi(self):
        from .motion_options import draw_overlays
        panel=self.motion_options if self.motion_options is not None and self.motion_options.window.winfo_exists() else None
        draw_overlays(self,panel.preview if panel else None)
        points = self.roi_points()
        road_only=self.last_status.get('configured_motion_profile',{}).get('mode')=='road'
        if self.mode != "live" or points is None or road_only:
            self.viewer.itemconfigure("motion_roi", state="hidden")
            self.viewer.configure(cursor='crosshair' if self.ocr_selecting else 'fleur' if self.mode=='replay' and self.view.zoom>1 else '')
            return
        x0, y0, x1, y1 = points
        # Ignore an old area's motion status while a changed ROI is in flight.
        actual_roi = tuple(self.last_status.get("roi", DEFAULT_ROI))
        alive = (self.last_status.get("state") == "recording" and
                 time.time() - self.last_status.get("heartbeat", 0) < 3 and
                 time.time() - self.last_status.get("last_frame_ns", time.time_ns()) / 1e9 < 3)
        zone_moving=next((z['moving'] for z in self.last_status.get('motion_zones',[]) if z['name']=='finish'),False)
        activity=self.last_status.get('moving',False) if self.last_status.get('configured_motion_profile',{}).get('mode','single')=='single' else zone_moving
        moving = (alive and activity and actual_roi == tuple(self.roi)
                  and self.roi_drag is None)
        color = "#ff4949" if moving else "#ffe14a"
        self.viewer.coords(self.roi_outline, x0, y0, x1, y1)
        self.viewer.itemconfigure(self.roi_outline, outline=color)
        for handle, (x, y) in zip(self.roi_handles, ((x0, y0), (x1, y0), (x0, y1), (x1, y1))):
            self.viewer.coords(handle, x - 4, y - 4, x + 4, y + 4)
            self.viewer.itemconfigure(handle, fill=color)
        self.viewer.itemconfigure("motion_roi", state="normal")
        self.viewer.tag_raise("motion_roi")
        self.viewer.tag_raise(self.warning)

    def roi_hit(self, x, y):
        if self.last_status.get('configured_motion_profile',{}).get('mode')=='road':return None
        points = self.roi_points()
        if self.mode != "live" or points is None:
            return None
        x0, y0, x1, y1 = points
        corners = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
        nearest = min(range(4), key=lambda i: (corners[i][0] - x)**2 + (corners[i][1] - y)**2)
        if (corners[nearest][0] - x)**2 + (corners[nearest][1] - y)**2 <= 14**2:
            return nearest
        if x0 <= x <= x1 and y0 <= y <= y1:
            return "move"
        return None

    def roi_cursor(self, event):
        if self.motion_options is not None and self.motion_options.window.winfo_exists() and self.motion_options.drawing:
            self.viewer.configure(cursor='crosshair');return
        if self.ocr_selecting or self.bike_marking:
            self.viewer.configure(cursor='crosshair');return
        if self.mode=='replay' and self.view.zoom>1:
            self.viewer.configure(cursor='fleur');return
        hit = self.roi_hit(event.x, event.y)
        self.viewer.configure(cursor="fleur" if hit == "move" else "sizing" if hit is not None else "")

    def roi_press(self, event):
        self.viewer.focus_set()
        if self.motion_options is not None and self.motion_options.window.winfo_exists() and self.motion_options.press(event):return
        if self.bike_marking and self.mode=='replay' and self.image_bounds():
            self.bike_drag=self.ocr_point(event)
            self.bike_mark_anchor=(self.selected,self.displayed_ordinal)
            return
        if self.mode=='replay' and not self.ocr_selecting:
            self.playing=False;self.refresh_play_button()
            if self.view.zoom>1:
                self.pan_drag=(event.x,event.y);self.viewer.configure(cursor='fleur')
            return
        if self.ocr_selecting and self.image_bounds():
            self.ocr_drag=self.ocr_point(event)
            return
        hit = self.roi_hit(event.x, event.y)
        if hit is not None:
            self.roi_drag = (hit, event.x, event.y, self.roi)

    def roi_move(self, event):
        if self.motion_options is not None and self.motion_options.window.winfo_exists() and self.motion_options.move(event):return
        if self.bike_drag is not None:
            x,y=self.ocr_point(event);a,b=self.bike_drag
            self.bike_mark=(*self.bike_mark_anchor,(min(a,x),min(b,y),max(a,x),max(b,y)))
            self.draw_bike_mark();return
        if self.pan_drag is not None:
            x,y=self.pan_drag;self.pan_drag=(event.x,event.y)
            self.view.pan(event.x-x,event.y-y,self.source_size(),self.reader.size)
            self.request_frame();return
        if self.ocr_drag is not None:
            x,y=self.ocr_point(event);a,b=self.ocr_drag
            self.ocr_area=(min(a,x),min(b,y),max(a,x),max(b,y))
            self.draw_ocr_area();return
        if self.roi_drag is None:
            return
        hit, press_x, press_y, original = self.roi_drag
        _, _, w, h = self.image_bounds()
        dx, dy = (event.x - press_x) / w, (event.y - press_y) / h
        x0, y0, x1, y1 = original
        if hit == "move":
            dx, dy = max(-x0, min(1 - x1, dx)), max(-y0, min(1 - y1, dy))
            self.roi = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        else:
            if hit in (0, 2):
                x0 = max(0, min(x1 - 0.02, x0 + dx))
            else:
                x1 = min(1, max(x0 + 0.02, x1 + dx))
            if hit in (0, 1):
                y0 = max(0, min(y1 - 0.02, y0 + dy))
            else:
                y1 = min(1, max(y0 + 0.02, y1 + dy))
            self.roi = (x0, y0, x1, y1)
        self.draw_roi()

    def roi_release(self, event):
        if self.motion_options is not None and self.motion_options.window.winfo_exists() and self.motion_options.release(event):return
        if self.bike_drag is not None:
            self.roi_move(event);self.bike_drag=None;self.bike_marking=False;self.viewer.configure(cursor='')
            box=self.bike_mark[2]
            if box[2]-box[0]<.01 or box[3]-box[1]<.01:
                self.clear_bike_mark();self.bike_feedback('Mark too small; drag a box around one bike.');return
            self.bike_feedback(f'Bike marked at frame {self.bike_mark[1]+1}. Enter its bib and optional passing order, then save.');return
        if self.pan_drag is not None:
            self.roi_move(event);self.pan_drag=None;return
        if self.ocr_drag is not None:
            self.roi_move(event)
            self.ocr_drag=None;self.ocr_selecting=False
            x0,y0,x1,y1=self.ocr_area
            if x1-x0>=.02 and y1-y0>=.02:
                self.ocr_area_pending=self.ocr_area
                self.reader.jobs.put(('ocr_area',dict(key='neural_ocr_area' if self.ocr_engine.get()=='Neural OCR' else 'ocr_area',roi=self.ocr_area)))
                self.ocr_label.configure(text='OCR search area saved. Click Read plates.')
            else:
                self.ocr_area=(0,0,1,1)
                self.ocr_label.configure(text='Area too small; using the full image.')
            self.viewer.configure(cursor='');self.draw_ocr_area();return
        if self.roi_drag is not None:
            self.roi_move(event)
            changed = self.roi != self.roi_drag[3]
            self.roi_drag = None
            if changed:
                self.pending_roi = self.roi
                self.reader.jobs.put(("roi", self.roi))
            self.draw_roi()

    def go_live(self,follow_race=False):
        if follow_race and self.compact_passings:self.compact_passings.follow_current()
        self.clear_bike_mark()
        self.bike_order.set('')
        self.reader.selection_clip=None
        self.pending_review=None
        self.ocr_selecting=False;self.ocr_drag=None
        self.mode = "live"
        self.update_bike_controls();self.update_quick_confirm()
        self.plate_evidence=None;self.draw_plate_evidence()
        self.pan_drag=None
        self.view=View()
        self.review_bounds=None
        self.star_button.state(['disabled'])
        self.zoom_label.configure(text='100%')
        self.playing = False
        self.token += 1
        self.mode_label.configure(text="● LIVE", foreground="#6be4ab")
        self.update_status(self.last_status)
        self.root.title("RaceVideo — Live")
        self.position_label.configure(text="Live camera")
        self.frame_label.configure(text="")
        self.scale.state(["disabled"])
        self.refresh_play_button()
        if self.live_image:
            self.display(self.live_image)
        self.draw_roi()
        self.viewer.focus_set()

    def select(self, clip_id, *, focus_view=True,auto_position=True,target_ns=None,align_wheel=False):
        self.clear_bike_mark()
        self.ocr_selecting=False;self.ocr_drag=None
        if self.motion_options is not None and self.motion_options.window.winfo_exists():
            self.motion_options.drawing=None;self.motion_options.start=None;self.motion_options.preview=None
        self.bike_order.set('')
        self.reader.selection_clip=clip_id
        if target_ns is not None:self.pending_open_target=(clip_id,target_ns)
        if align_wheel:self.pending_wheel_open_clip=clip_id
        if not any(c['id']==clip_id for c in self.clips):
            self.pending_review=clip_id
            self.reader.jobs.put(('locate',clip_id))
            return
        self.pending_review=None
        align_wheel=align_wheel or getattr(self,'pending_wheel_open_clip',None)==clip_id
        self.pending_wheel_open_clip=None
        clip=next(c for c in self.clips if c['id']==clip_id)
        self.review_source_size=(clip['width'],clip['height'])
        self.view=View();self.review_bounds=None;self.pan_drag=None
        self.zoom_label.configure(text='100%')
        self.star_button.state(['!disabled'])
        self.roi_drag = None
        self.mode, self.selected = "replay", clip_id
        self.active_bike_key=None;self.bike_navigation=dict(passages=[],label='Reading bike index…');self.update_bike_controls()
        self.wheel_data=None;self.wheel_request_signature=None;self.wheel_reports={};self.wheel_peer_request=None
        for items in self.wheel_peer_items.values():
            for item in items:self.viewer.delete(item)
        self.wheel_peer_items.clear()
        self.displayed_ordinal=None
        self.display_size=None
        self.viewer.itemconfigure(self.picture,state='hidden')
        self.viewer.itemconfigure(self.empty,state='normal',text=f'Loading clip #{clip_id}…')
        self.frame_label.configure(text='Loading…')
        self.update_star_button(clip_id)
        self.playing = False
        self.index = []
        self.token += 1
        self.last_render_token=self.token  # Ignore in-flight frames from an earlier selection.
        self.selection_generation=self.token
        self.reader.selection_generation=self.selection_generation
        self.wheel_open_alignment=dict(clip=clip_id,generation=self.selection_generation,ordinal=None) if align_wheel and self.wheel_enabled.get() and not self.restore_view else None
        self.refresh_play_button()
        self.mode_label.configure(text=f"REVIEW · clip {clip_id}", foreground="#ffcd70")
        self.viewer.itemconfigure(self.warning, text="")
        self.draw_roi()
        self.root.title(f"RaceVideo — Review clip {clip_id} · capture continues")
        explicit=getattr(self,'pending_seek',None)
        if explicit and explicit[0]!=clip_id:self.pending_seek=None;explicit=None
        pending=getattr(self,'pending_open_target',None)
        if pending and pending[0]==clip_id:target_ns=pending[1]
        self.pending_open_target=None
        self.reader.jobs.put(("index", (clip_id,auto_position and not explicit,self.selection_generation,target_ns if not explicit else None)))
        self.reader.jobs.put(('ocr_select',clip_id))
        self.ocr_run=None
        self.bib_review_rows=[];self.plate_evidence=None;self.draw_plate_evidence();self.refresh_ocr_tree()
        self.highlight()
        if focus_view:
            self.viewer.focus_set()

    def highlight(self):
        for clip in self.clips:
            self.strip.itemconfigure(f"border:{clip['id']}",
                                     outline="#ffcd70" if clip["id"] == self.selected else "#364353",
                                     width=3 if clip["id"] == self.selected else 1)

    @staticmethod
    def clip_detail(clip):
        state=clip.get('ocr_state')
        confirmed=set((clip.get('confirmed_bibs') or '').split(','))
        bib_labels=', '.join(('✓' if bib in confirmed else '?')+bib for bib in (clip.get('bibs') or '').split(',') if bib)
        note=bib_labels or {'complete':'no candidates','running':'running','queued':'queued','error':'failed'}.get(state,'not scanned')
        if clip.get('bibs') and state in ('queued','running','error'):note+=' · '+state
        duration=(clip['ended_ns']-clip['started_ns'])/1e9
        text=f'{duration:.2f}s · Bibs {note}'
        return text if len(text)<=31 else text[:30]+'…'

    def update_clip_details(self,rows):
        by_id={clip['id']:clip for clip in self.clips}
        for row in rows:
            clip=by_id.get(row['id'])
            if clip is None:continue
            clip.update(row)
            self.strip.itemconfigure(f"caption:{clip['id']}",text=f"{'★ ' if clip.get('starred') else ''}#{clip['id']}  {self.display_time(clip['started_ns'],milliseconds=False)}")
            self.strip.itemconfigure(f"ocr:{clip['id']}",text=self.clip_detail(clip))
        if self.mode=='replay':self.update_star_button(self.selected)

    def add_clips(self, clips):
        follow = self.strip.xview()[1] >= 0.98 and not self.dragging
        for clip in clips:
            i = len(self.clips)
            self.clips.append(clip)
            x = i * 190 + 8
            self.strip.create_rectangle(x, 5, x + 180, 137, fill="#202a36",
                                         outline="#364353", tags=f"border:{clip['id']}")
            photo = ImageTk.PhotoImage(clip.pop("image"))
            self.thumb_images[clip["id"]] = photo
            self.strip.create_image(x + 90, 56, image=photo)
            duration = (clip["ended_ns"] - clip["started_ns"]) / 1e9
            self.strip.create_text(x + 8, 111, anchor="w", fill="#eef3f8",
                                   text=f"{'★ ' if clip.get('starred') else ''}#{clip['id']}  {self.display_time(clip['started_ns'],milliseconds=False)}", font=("Sans", 10),tags=f"caption:{clip['id']}")
            self.strip.create_text(x + 8, 128, anchor="w", fill="#9aabbf",
                                   text=self.clip_detail(clip),
                                   font=("Sans", 9),tags=f"ocr:{clip['id']}")
        self.strip.configure(scrollregion=(0, 0, max(len(self.clips) * 190 + 8, 1), 143))
        self.count_label.configure(text=f"Saved clips · {len(self.clips)}")
        if follow:
            self.strip.xview_moveto(1)
        self.highlight()
        if self.pending_review is not None and any(c['id']==self.pending_review for c in self.clips):
            self.select(self.pending_review)

    def strip_press(self, event):
        self.strip.focus_set()
        self.press_x = event.x
        self.dragging = False
        self.strip.scan_mark(event.x, event.y)

    def strip_drag(self, event):
        if abs(event.x - self.press_x) > 5:
            self.dragging = True
            self.strip.scan_dragto(event.x, event.y, gain=1)

    def strip_release(self, event):
        if not self.dragging:
            position = int(self.strip.canvasx(event.x) // 190)
            if 0 <= position < len(self.clips):
                self.select(self.clips[position]["id"], focus_view=False)
        self.dragging = False

    def move_clip(self, amount):
        if isinstance(amount, str):
            page = max(1, self.strip.winfo_width() // 190)
            amount = -page if amount == "page-back" else page
        if self.clips:
            position = next((i for i, c in enumerate(self.clips) if c["id"] == self.selected),
                            len(self.clips) if amount < 0 else -1)
            position = max(0, min(len(self.clips) - 1, position + amount))
            self.select(self.clips[position]["id"], focus_view=False)
            left = position * 190
            visible_left = self.strip.canvasx(0)
            width = self.strip.winfo_width()
            if left < visible_left:
                self.strip.xview_moveto(left / (len(self.clips) * 190 + 8))
            elif left + 190 > visible_left + width:
                self.strip.xview_moveto((left + 190 - width) / (len(self.clips) * 190 + 8))
        return "break"

    def request_frame(self):
        pending=self.wheel_open_alignment
        if pending and pending['ordinal'] is not None and (self.ordinal!=pending['ordinal'] or vars(self.view)!=pending.get('view',vars(self.view))):self.wheel_open_alignment=None
        if not self.index:
            return
        self.update_bike_controls()
        self.token += 1
        self.reader.wanted_frame = (self.selected,self.ordinal,self.token,vars(self.view).copy())
        self.updating_scale = True
        self.scale.set(self.ordinal)
        self.updating_scale = False

    def frame_caption(self,ordinal):
        row=self.index[ordinal]
        elapsed=(row['monotonic_ns']-self.index[0]['monotonic_ns'])/1e9
        self.position_label.configure(text=f"{self.display_time(row['received_ns'])}  ·  clip +{elapsed:.3f}s")
        self.frame_label.configure(text=f'Frame {ordinal+1} / {len(self.index)}')

    def step(self, amount):
        if self.editing_text():return None
        if self.mode == "live":
            self.move_clip(-1 if amount < 0 else 1)
            self.viewer.focus_set()
        elif self.index:
            self.playing = False
            self.refresh_play_button()
            self.ordinal = max(0, min(len(self.index) - 1, self.ordinal + amount))
            self.request_frame()
        return "break"

    def scale_changed(self, value):
        if not self.updating_scale and self.mode == "replay" and self.index:
            ordinal = round(float(value))
            if ordinal != self.ordinal:
                self.playing = False
                self.refresh_play_button()
                self.ordinal = ordinal
                self.request_frame()

    def toggle_play(self):
        if self.editing_text():return None
        if self.mode == "live" or not self.index:
            return "break"
        self.wheel_open_alignment=None
        self.playing = not self.playing
        if self.playing:
            if self.ordinal == len(self.index) - 1:
                self.ordinal = 0
                self.request_frame()
            self.play_start = time.monotonic()
            self.play_offset = self.index[self.ordinal]["monotonic_ns"]
        self.refresh_play_button()
        return "break"

    def update_status(self, status):
        self.last_status = status
        batch=status.get('ocr_batch')
        self.batch_label.configure(text=(f"Day OCR complete · {batch['total_clips']} clips" if batch['state']=='complete' else f"Day OCR {batch['completed_clips']}/{batch['total_clips']}") if batch else '')
        active = (status.get('state') in ('recording', 'starting') and
                  time.time() - status.get('heartbeat', 0) < 3)
        self.recorder_button.configure(text='Stop recorder' if active else 'Start recorder')
        rotations=status.get('ocr_rotations',[0,180])
        if rotations==self.pending_ocr_rotations:self.pending_ocr_rotations=None
        if self.pending_ocr_rotations is None:self.ocr_upright.set(rotations==[0])
        area=tuple(status.get('neural_ocr_area',(.05,.4,.98,.9)) if self.ocr_engine.get()=='Neural OCR' else status.get('ocr_area',self.ocr_area))
        if self.ocr_area_pending==area:self.ocr_area_pending=None
        if self.ocr_drag is None and self.ocr_area_pending is None:self.ocr_area=area
        if self.camera_panel:
            self.camera_panel.update(status)
        configured = tuple(status.get("configured_roi", self.roi))
        if self.pending_roi is not None and configured == self.pending_roi:
            self.pending_roi = None
        if self.roi_drag is None and self.pending_roi is None:
            self.roi = validate_roi(configured)
        age = time.time() - status.get("heartbeat", 0)
        state = status.get("state", "waiting")
        stale = age > 3 and state not in ("stopped", "error")
        frame_stale = (state == "recording" and status.get("last_frame_ns") and
                       time.time() - status["last_frame_ns"] / 1e9 > 3)
        stale = stale or frame_stale
        if stale:
            state = "OFFLINE / recorder not responding"
        text = (f"{state.upper()}  ·  {status.get('device', '')}  ·  "
                f"{status.get('width', 0)}×{status.get('height', 0)}  MJPEG  ·  "
                f"{status.get('fps', 0):.1f} fps actual  ·  "
                f"buffer {status.get('buffer_seconds', 0):.2f}s  ·  "
                f"saved {status.get('saved_clips', 0)}  ·  skipped {status.get('dropped_clips', 0)}")
        if status.get("trigger") == "motion":
            text += ("  ·  MOTION" if status.get("moving") else
                     "  ·  saving tail" if status.get("event_active") else "  ·  watching")
        if status.get('analysis_lag_ms', 0) > 1000:
            text += f"  ·  analysis +{status['analysis_lag_ms']/1000:.1f}s"
        if status.get('analysis_overrun_frames', 0):
            text += f"  ·  ANALYSIS GAP: {status['analysis_overrun_frames']} overwritten frames"
        if status.get('capture_bad_packets',0):
            text+=f"  ·  CAMERA GAPS: {status['capture_bad_packets']} bad packets"
        if status.get("error"):
            text += "  ·  " + status["error"]
        self.status_label.configure(text=text, foreground="#ff9b87" if stale or state == "error" or status.get("analysis_overrun_frames",0) or status.get("capture_bad_packets",0) else "#c0cddb")
        if self.mode == "live":
            self.viewer.itemconfigure(self.warning, text="" if state == "recording" and not stale
                                      else f"{state.upper()} — showing last frame" if self.live_image
                                      else state.upper())
            self.viewer.tag_raise(self.warning)
        self.draw_roi()
        self.draw_ocr_area()

    def poll(self):
        if self.closing:
            return
        # A callback error must not permanently stop live/status polling.
        callback_started = time.perf_counter()
        now = time.monotonic()
        self.performance.observe('callback_delay_ms', max(0, now-self.expected_poll)*1000)
        self.expected_poll = now + .03
        self.root.after(30, self.poll)
        prepared = self.preview.latest()
        if prepared is not None:
            self.last_preview_received_ns = prepared['received_ns']
            self.live_image = Image.frombytes('RGB', prepared['size'], prepared['rgb'])
            self.performance.observe('preview_decode_ms', prepared['decode_ms'])
            self.performance.observe('preview_handoff_ms', (time.monotonic_ns()-prepared['prepared_ns'])/1e6)
            self.performance.counters['preview_superseded'] += max(0, prepared['produced']-self.previous_produced-1)
            self.previous_produced = prepared['produced']
            self.performance.counters['preview_worker_produced'] = prepared['produced']
            self.performance.counters['preview_pid'] = prepared['pid']
            if self.mode == 'live':
                self.display(self.live_image)
                self.performance.observe('preview_age_ms', (time.time_ns()-prepared['received_ns'])/1e6)
                if self.previous_presented is not None:
                    self.performance.observe('preview_interval_ms', (now-self.previous_presented)*1000)
                self.previous_presented = now
                self.performance.counters['preview_presented'] += 1
        if now >= self.next_metrics:
            self.performance.counters['preview_worker_alive'] = self.preview.process.is_alive()
            self.performance_snapshot = self.performance.snapshot()
            self.performance_snapshot["preview_current_age_ms"] = ((time.time_ns()-self.last_preview_received_ns)/1e6 if self.last_preview_received_ns else None)
            self.next_metrics = now + 1
        self.remote.tick()
        self.mcp_label.configure(text='MCP linked' if self.remote.connected else 'MCP offline')
        handled = 0
        while not self.reader.output.empty() and handled < 8 and (handled == 0 or time.perf_counter()-callback_started < .010):
            handled += 1
            name, value = self.reader.output.get()
            if name=='wheel_started':
                signature,ident,error,*busy=value
                if signature==self.wheel_peer_request and ident is None:
                    self.wheel_peer_request=None;self.wheel_retry_at=time.monotonic()+1
                    if error:self.wheel_reports[signature]={'state':'error','report':{}}
                if signature==self.wheel_request_signature:
                    if ident is None:
                        from .wheel_timing import progress_label
                        self.wheel_status.configure(text='Wheel analysis: '+error if error else 'Waiting for '+progress_label(busy[0] if busy else None))
                        self.wheel_retry_at=time.monotonic()+(10 if error else 1);self.wheel_request_signature=None
            elif name=='wheel_result':
                signature,result=value
                if result and result.get('clip_id')==self.selected:
                    if result['state'] in ('complete','error'):self.wheel_reports[signature]=result
                    if signature==self.wheel_peer_request and result['state'] in ('complete','error'):self.wheel_peer_request=None
                    if signature==self.wheel_request_signature:
                        self.wheel_data=result;self.align_open_wheel()
                    self.draw_wheel_overlay();self.draw_time_overlay()
            if name=='race_contexts':
                signature=repr(value)
                if signature!=getattr(self,'race_events_signature',None):
                    self.race_events_signature=signature;self.race_events=value
                    for clip in self.clips:self.strip.itemconfigure(f"caption:{clip['id']}",text=f"{'★ ' if clip.get('starred') else ''}#{clip['id']}  {self.display_time(clip['started_ns'],milliseconds=False)}")
            if name == "live":
                status, image = value
                self.update_status(status)
                # Live pixels arrive through the independent latest-only worker.
            elif name == "clips":
                generation,clips=value
                if generation==self.browse_generation:self.add_clips(clips)
            elif name=='clip_updates':
                generation,rows=value
                if generation==self.browse_generation:self.update_clip_details(rows)
            elif name=='browse_reset':
                if value==self.browse_generation:
                    self.clips=[];self.thumb_images.clear();self.strip.delete('all')
                    self.strip.configure(scrollregion=(0,0,1,143))
                    self.count_label.configure(text='Saved clips · 0')
            elif name=='browse_done':
                generation,count=value
                if generation==self.browse_generation:
                    self.count_label.configure(text=f'{self.review_day.get()} · {count} clip'+('' if count==1 else 's')+(' · matching bib evidence' if self.bib_filter.get().strip() else ''))
                    if self.mode=='replay' and not any(c['id']==self.selected for c in self.clips) and not (self.ocr_window is not None and self.ocr_window.winfo_exists()):self.go_live()
                    if self.mode=='replay':self.update_star_button(self.selected)
                    if self.pending_session_clip is not None:
                        clip=self.pending_session_clip;self.pending_session_clip=None
                        if any(c['id']==clip for c in self.clips):self.select(clip,focus_view=False,auto_position=False)
                        else:self.status_label.configure(text='Previous recording is no longer in the selected date/filter.')
            elif name=='dates':
                choices=('Today','All dates',*value)
                if tuple(self.date_picker.cget('values'))!=choices:self.date_picker.configure(values=choices)
            elif name=='located':
                clip_id,day=value
                if self.pending_review==clip_id:
                    if day is None:
                        self.pending_review=None;self.status_label.configure(text='Recording no longer exists.')
                    else:
                        self.review_day.set(day);self.bib_filter.set('');self.stars_only.set(False)
                        self.apply_browser(preserve_pending=True)
            elif name=='starred':
                clip_id,starred=value
                for clip in self.clips:
                    if clip['id']==clip_id:clip['starred']=int(starred)
                if self.selected==clip_id:self.update_star_button(clip_id)
            elif name=='cleanup_preview':self.confirm_cleanup(value)
            elif name=='cleanup_done':
                self.set_cleanup_pending(False)
                self.status_label.configure(text=f"Deleted {len(value['deleted'])} clips; {value['skipped']} changed/protected clips retained.")
            elif name=='review_error':
                self.set_cleanup_pending(False)
                self.status_label.configure(text=value,foreground='#ff9b87')
            elif name=='capture_modes':
                if self.camera_panel:self.camera_panel.receive_modes(value)
            elif name=='motion_options_saved':
                if self.motion_options is not None and self.motion_options.window.winfo_exists():self.motion_options.applied(*value)
            elif name=='retention_proposal':
                if self.motion_options is not None and self.motion_options.window.winfo_exists():self.motion_options.receive(*value)
            elif name=='bike_navigation':
                clip_id,nav=value
                if self.selected==clip_id:
                    self.bike_navigation=nav;self.align_bike_selection();self.update_bike_controls()
            elif name=='capture_profile':
                if self.camera_panel:self.camera_panel.profile_saved(value)
            elif name=='passages':self.receive_passages(*value)
            elif name=='passing_located':
                self.pending_seek=value
                self.select(value[0],focus_view=False)
            elif name in ('passing_review_saved','passing_review_error'):
                if self.passings_panel is not None and self.passings_panel.window.winfo_exists():
                    self.passings_panel.review_result(value,error=name=='passing_review_error')
            elif name == "index":
                clip_id,index,position,generation=value
                if self.mode == "replay" and clip_id == self.selected and generation==self.selection_generation:
                    self.index,self.ordinal=index,min(max(position['ordinal'],0),max(0,len(index)-1))
                    if self.restore_view and self.restore_view[0]==clip_id:
                        try:self.view=View(**self.restore_view[1]);self.view.clamp(self.source_size(),self.reader.size)
                        except (TypeError,ValueError):self.view=View()
                        self.restore_view=None;self.zoom_label.configure(text=f'{self.view.zoom*100:.0f}%')
                    self.performance.observe('review_position_ms',position['milliseconds'])
                    self.performance.counters['review_position_decoded_frames']=position['decoded_frames']
                    self.performance.counters['review_position_cached']=position.get('cached',False)
                    if len(index)>1:
                        seconds=(index[-1]['monotonic_ns']-index[0]['monotonic_ns'])/1e9
                        if seconds>0:self.mode_label.configure(text=f"REVIEW · clip {clip_id} · {(len(index)-1)/seconds:.1f} fps saved")
                    if getattr(self,'pending_seek',None) and self.pending_seek[0]==clip_id:
                        self.ordinal=min(max(0,self.pending_seek[1]),max(0,len(index)-1));self.pending_seek=None
                    if self.wheel_open_alignment and self.wheel_open_alignment['generation']==generation:self.wheel_open_alignment.update(ordinal=self.ordinal,view=vars(self.view).copy())
                    self.scale.configure(to=max(1, len(index) - 1))
                    self.scale.state(["!disabled"])
                    self.request_frame()
                    self.align_bike_selection();self.update_bike_controls()
                    if position.get('navigation'):
                        self.bike_navigation=position['navigation']
                    if position.get('bike_key'):
                        self.active_bike_key=position['bike_key'];self.active_bike_anchor=self.ordinal
                    if self.passings_panel is not None and self.passings_panel.window.winfo_exists():
                        self.passings_panel.position_candidate(clip_id,position,index)
                    if position.get('box'):
                        x0,y0,x1,y1=position['box'];self.plate_evidence=(clip_id,self.ordinal,[[x0,y0],[x1,y0],[x1,y1],[x0,y1]])
                    self.update_bike_controls()
                    if position['method'].startswith('no moving') and self.passings_panel is not None and self.passings_panel.window.winfo_exists():
                        self.passings_panel.review_message.set('No clear moving subject found automatically. Use Find bikes or scrub this candidate clip; the bib is still unconfirmed.')
                    if position.get('warning') and self.passings_panel is not None and self.passings_panel.window.winfo_exists():
                        self.passings_panel.review_message.set(position['warning'])
            elif name == "frame":
                clip_id,ordinal,token,image,bounds,position=value
                if (self.mode=='replay' and clip_id==self.selected
                        and 0<=ordinal<len(self.index)
                        and (self.playing or token==self.token)
                        and (ordinal==self.ordinal or self.playing and ordinal<=self.ordinal)
                        and token>self.last_render_token):
                    self.last_render_token=token
                    self.displayed_ordinal=ordinal
                    self.display(image,bounds,position)
                    self.frame_caption(ordinal)
            elif name == "error":
                self.status_label.configure(text=f"Review reader failed: {value}", foreground="#ff9b87")
            elif name == "camera_result" and self.camera_panel:
                self.camera_panel.result(value)
            elif name == "recorder_start" and value:
                self.status_label.configure(text=f"Could not start recorder: {value}")
                if self.camera_panel:
                    self.camera_panel.message.set(f"Could not start recorder: {value}")
            elif name=='bib_review_rows':
                clip_id,rows=value
                if clip_id==self.selected:
                    self.bib_review_rows=rows;self.refresh_ocr_tree();self.update_bib_summary()
            elif name=='bib_review_saved':
                if self.pending_bike_mark_save:
                    mark,order=self.pending_bike_mark_save;self.pending_bike_mark_save=None
                    if self.bike_mark==mark:self.clear_bike_mark()
                    if self.bike_order.get()==order:self.bike_order.set('')
                if self.ocr_window is not None and self.ocr_window.winfo_exists():self.review_message.set('Saved. Operator decisions and manual bibs are retained across OCR reruns.')
                if self.passages_window is not None and self.passages_window.winfo_exists():self.show_passages(raise_window=False)
            elif name=='bib_review_error':
                if self.ocr_window is not None and self.ocr_window.winfo_exists():self.review_message.set(value)
                else:self.status_label.configure(text=value,foreground='#ff9b87')
            elif name=='ocr_status':
                self.receive_ocr(*value)
            elif name=='ocr_error':
                self.ocr_label.configure(text='OCR error: '+value)
                self.ocr_button.state(['!disabled'])
            elif name=='ocr_evidence':
                oid,picture=value
                if (self.ocr_window is not None and self.ocr_window.winfo_exists() and
                        (self.selected_bib_row() or {}).get('observation_id')==oid):
                    self.ocr_evidence_photo=ImageTk.PhotoImage(picture)
                    self.ocr_evidence_label.configure(image=self.ocr_evidence_photo,text='')
        if self.playing and self.index:
            target = self.play_offset + int((time.monotonic() - self.play_start) * 1e9)
            position = bisect.bisect_right([f["monotonic_ns"] for f in self.index], target) - 1
            position = min(len(self.index) - 1, max(0, position))
            if position != self.ordinal:
                self.ordinal = position
                self.request_frame()
            if target >= self.index[-1]["monotonic_ns"]:
                self.playing = False
                self.refresh_play_button()

        if (self.mode == 'live' and self.last_status.get('state') == 'recording'
                and time.time()-self.last_status.get('heartbeat',0) < 3
                and self.last_preview_received_ns
                and (time.time_ns()-self.last_preview_received_ns)/1e9 > 1.5):
            self.viewer.itemconfigure(self.warning, text='PREVIEW STALE — see Performance')
            self.viewer.tag_raise(self.warning)
        self.performance.observe("callback_work_ms", (time.perf_counter()-callback_started)*1000)
        self.request_wheels()
        self.update_quick_confirm()

    def show_performance(self):
        if self.performance_window is not None and self.performance_window.winfo_exists():
            self.performance_window.lift()
            return
        import json
        window = self.performance_window = tk.Toplevel(self.root)
        window.title('RaceVideo performance — rolling 300 samples')
        text = tk.Text(window, width=88, height=35, background='#15191f', foreground='#e4e9f0')
        text.pack(fill='both', expand=True)
        def refresh():
            if self.closing or not window.winfo_exists():
                return
            values = dict(gui=self.performance_snapshot,
                          recorder={k:v for k,v in self.last_status.items() if k.startswith(('ring_', 'analysis_', 'capture_', 'motion_', 'writer_', 'last_clip_write_'))})
            text.configure(state='normal'); text.delete('1.0', 'end')
            text.insert('end', json.dumps(values, indent=2)); text.configure(state='disabled')
            window.after(1000, refresh)
        refresh()

    def close(self):
        state=self.session_snapshot()
        self.closing = True
        if self.passings_panel is not None and self.passings_panel.window.winfo_exists():self.passings_panel.close()
        if self.compact_passings:self.compact_passings.close()
        self.remote.close()
        self.reader.stop.set()
        self.preview.close()
        self.reader.join(timeout=1)
        from .ui_session import save
        try:save(self.path,state)
        except OSError:pass
        for timer in self.root.tk.call('after','info'):self.root.after_cancel(timer)
        self.root.destroy()


def run(path, open_camera=False, review_clip=None, open_passings=False):
    root = tk.Tk()
    app = ReviewWindow(root, path)
    if open_camera:
        root.after(750, app.open_camera)
    if review_clip is not None:
        root.after(500,lambda:app.select(review_clip))
    if open_passings:
        root.after(1200,app.show_event_passings)
    root.mainloop()
