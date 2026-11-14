"""Operator-selectable motion experiments and non-destructive retention review."""
import json
import tkinter as tk
from tkinter import ttk
from .motion_profiles import MODES,validate_profile,active_zones
from .motion import DEFAULT_ROI,validate_roi
from .retention import MODES as TRIM_MODES,settings


def draw_overlays(app,preview=None):
    status=app.last_status;bounds=app.image_bounds();profile=validate_profile(status.get('configured_motion_profile'))
    zones=active_zones(profile,status.get('configured_roi',DEFAULT_ROI))
    if preview:zones=dict(zones,draw=preview)
    fresh=status.get('state')=='recording' and __import__('time').time()-status.get('heartbeat',0)<3
    states={s['name']:fresh and s.get('moving') for s in status.get('motion_zones',[])}
    signature=repr((app.mode,bounds,zones,states))
    if signature==getattr(app,'motion_overlay_signature',None):return
    app.motion_overlay_signature=signature;app.viewer.delete('motion_extra')
    if app.mode!='live' or not bounds:return
    left,top,w,h=bounds
    for name,roi in zones.items():
        if name=='finish':continue
        x0,y0,x1,y1=roi;color='#ff4949' if states.get(name) else '#ffe14a'
        app.viewer.create_rectangle(left+x0*w,top+y0*h,left+x1*w,top+y1*h,outline=color,dash=(5,3),width=2,tags='motion_extra')
        app.viewer.create_text(left+x0*w+4,top+y0*h+4,text=name.title(),anchor='nw',fill=color,tags='motion_extra')


class MotionOptions:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root);self.window.title('Motion and storage experiments')
        self.window.geometry('790x650');self.window.minsize(700,570);self.drawing=None;self.start=None;self.preview=None;self.dirty=False
        self.mode=tk.StringVar();self.trim=tk.StringVar();self.road_fraction=tk.StringVar();self.coordinates={name:tk.StringVar() for name in ('finish','entry','exit','road')}
        self.message=tk.StringVar();self.result=tk.StringVar(value='Choose a saved capture to review trim proposals. Originals are retained.')
        outer=ttk.Frame(self.window,padding=10);outer.pack(fill='both',expand=True)
        ttk.Label(outer,textvariable=self.message,wraplength=750).pack(side='bottom',fill='x',pady=6)
        actions=ttk.Frame(outer);actions.pack(side='bottom',fill='x',pady=6)
        ttk.Button(actions,text='Apply choices',command=self.apply).pack(side='left')
        ttk.Button(actions,text='Reload saved choices',command=self.load).pack(side='left',padx=5)
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        body=ttk.Frame(self.tabs,padding=8);self.tabs.add(body,text='Recording / zones')
        self.storage_tab=ttk.Frame(self.tabs,padding=8);self.tabs.add(self.storage_tab,text='Storage proposals')
        ttk.Label(body,text='Recording behavior · one small grayscale decode shared by all zones').pack(anchor='w')
        self.mode_picker=ttk.Combobox(body,state='readonly',textvariable=self.mode,values=list(MODES.values()),width=63)
        self.mode_picker.pack(fill='x',pady=5)
        grid=ttk.Frame(body);grid.pack(fill='x')
        for row,name in enumerate(self.coordinates):
            ttk.Label(grid,text=name.title(),width=9).grid(row=row,column=0,sticky='w')
            ttk.Entry(grid,textvariable=self.coordinates[name],width=47).grid(row=row,column=1,pady=3,sticky='ew')
            ttk.Button(grid,text='Draw on Live…',command=lambda n=name:self.begin_draw(n)).grid(row=row,column=2,padx=6)
        grid.columnconfigure(1,weight=1)
        ttk.Label(body,text='Coordinates: left, top, right, bottom (0–1). Move zones away from flags and spectators.\nFinish also retains the existing draggable Live rectangle. Apply saves all shown zones.').pack(anchor='w',pady=5)
        threshold=ttk.Frame(body);threshold.pack(fill='x')
        ttk.Label(threshold,text='Road changed fraction (smaller is more sensitive):').pack(side='left')
        ttk.Entry(threshold,textvariable=self.road_fraction,width=8).pack(side='left',padx=5)
        body=self.storage_tab
        ttk.Label(body,text='Post-processing storage experiment · proposals only, no source deletion').pack(anchor='w',pady=(10,0))
        ttk.Combobox(body,state='readonly',textvariable=self.trim,values=list(TRIM_MODES.values()),width=63).pack(fill='x',pady=5)
        ttk.Button(body,text='Analyze selected capture',command=self.analyze).pack(anchor='w',pady=5)
        ttk.Separator(body).pack(fill='x',pady=5)
        ttk.Label(body,textvariable=self.result,wraplength=750).pack(fill='x')
        self.tree=ttk.Treeview(body,columns=('start','end','frames','mb'),show='headings',height=6)
        for key,label in (('start','First source frame'),('end','Last source frame'),('frames','Retained frames'),('mb','JPEG MB')):
            self.tree.heading(key,text=label);self.tree.column(key,width=150,anchor='center')
        self.tree.pack(fill='both',expand=True,pady=5)
        jumps=ttk.Frame(body);jumps.pack(fill='x')
        for label,where in (('Before start','before'),('Start','start'),('Middle','middle'),('End','end'),('After end','after')):
            ttk.Button(jumps,text=label,command=lambda w=where:self.jump(w)).pack(side='left',padx=3)
        ttk.Label(body,text='Check boundaries and groups before trusting savings. A missing detection is not proof of an empty frame.',wraplength=750).pack(anchor='w',pady=6)
        self.signature=None;self.proposal=None
        self.load()
        for variable in [self.mode,self.trim,self.road_fraction,*self.coordinates.values()]:variable.trace_add('write',lambda *a:setattr(self,'dirty',True))
        self.window.protocol('WM_DELETE_WINDOW',self.close)

    def saved(self):
        status=self.app.last_status
        return dict(profile=validate_profile(status.get('configured_motion_profile')),finish=list(status.get('configured_roi',DEFAULT_ROI)),
                    retention=settings(status.get('retention_settings')))

    def load(self):
        saved=self.saved();self.base=saved;self.mode.set(MODES[saved['profile']['mode']]);self.trim.set(TRIM_MODES[saved['retention']['mode']])
        self.road_fraction.set(str(saved['profile']['fractions']['road'] or .005))
        for name,var in self.coordinates.items():var.set(', '.join(str(v) for v in (saved['finish'] if name=='finish' else saved['profile']['zones'][name])))
        self.dirty=False;self.message.set('Choices loaded. Draw or edit zones, then Apply. Road also sets the trim analysis area.')

    def apply(self):
        try:
            if self.saved()!=self.base:raise ValueError('Saved motion choices changed while editing. Reload saved choices before applying.')
            zones={n:list(validate_roi([float(v.strip()) for v in var.get().split(',')])) for n,var in self.coordinates.items()}
            profile=validate_profile(dict(mode=next(k for k,v in MODES.items() if v==self.mode.get()),zones=zones,
                fractions=dict(self.base['profile']['fractions'],road=float(self.road_fraction.get()))))
            retention=settings(dict(mode=next(k for k,v in TRIM_MODES.items() if v==self.trim.get()),road_roi=zones['road']))
            value=dict(profile=profile,finish=zones['finish'],retention=retention)
            self.app.reader.jobs.put(('motion_options',value));self.message.set('Saving choices…')
        except (ValueError,StopIteration) as exc:self.message.set(str(exc))

    def applied(self,value,error=None):
        if error:self.message.set(error);return
        self.base=value;self.dirty=False
        self.message.set('Saved. Running recorder switches at a clip boundary; stored metadata identifies the behavior. Trim choices affect new OCR/analysis jobs only.')

    def begin_draw(self,name):
        self.app.go_live();self.drawing=name;self.start=None;self.preview=None
        self.message.set('Drag '+name+' zone in the main Live image; Apply choices when finished.');self.app.viewer.configure(cursor='crosshair')

    def press(self,event):
        if not self.drawing:return False
        if self.app.image_bounds():self.start=self.app.ocr_point(event)
        return True

    def move(self,event):
        if not self.drawing:return False
        if self.start:
            x,y=self.app.ocr_point(event);a,b=self.start;self.preview=(min(a,x),min(b,y),max(a,x),max(b,y));self.overlays()
        return True

    def release(self,event):
        if not self.drawing:return False
        self.move(event)
        if self.preview:
            try:
                roi=validate_roi(self.preview);self.coordinates[self.drawing].set(', '.join(f'{v:.4f}' for v in roi))
                self.message.set('Zone drawn. Apply choices to use it.')
            except ValueError as exc:self.message.set(str(exc))
        self.drawing=None;self.start=None;self.preview=None;self.app.viewer.configure(cursor='');self.overlays();return True

    def overlays(self):
        draw_overlays(self.app,self.preview)

    def analyze(self):
        self.tabs.select(self.storage_tab)
        if self.dirty:self.message.set('Apply your choices before starting analysis.');return
        if self.app.mode!='replay' or self.app.selected is None:self.message.set('Select a saved capture in the main window first.');return
        mode=self.base['retention']['mode']
        if mode=='off':self.message.set('Select a trim-proposal behavior and Apply first.');return
        if mode=='motion':self.app.reader.jobs.put(('retention',self.app.selected))
        else:
            self.app.reader.jobs.put(('ocr',(self.app.selected,dict(engine='paddle-rider-v1',retention=self.base['retention']))))
        self.message.set('Analysis requested; capture and Live continue independently.')

    def receive(self,clip_id,proposal):
        signature=repr((clip_id,proposal))
        if signature==self.signature:return
        self.signature=signature;self.proposal=proposal;self.proposal_clip=clip_id;self.tree.delete(*self.tree.get_children())
        if not proposal:self.result.set(f'Capture {clip_id}: no trim proposal yet. Analyze this capture or run neural OCR with proposals enabled.');return
        if proposal['state'] in ('queued','running','error'):
            self.result.set('Capture '+str(clip_id)+': '+proposal['state']+' '+str(proposal.get('error') or ''));return
        report=proposal['report'];saved=1-report['kept_bytes']/report['total_bytes'] if report['total_bytes'] else 0
        self.result.set(f"Capture {clip_id}: {report['kept_frames']}/{report['total_frames']} frames, {report['kept_bytes']/1e6:.1f}/{report['total_bytes']/1e6:.1f} MB; proposed saving {saved:.0%}. {report['reason']}")
        for i,r in enumerate(report['intervals']):self.tree.insert('','end',iid=str(i),values=(r['first_ordinal']+1,r['last_ordinal']+1,r['frame_count'],f"{r['bytes']/1e6:.1f}"))

    def jump(self,where):
        selected=self.tree.selection()
        if not selected or not self.proposal:return
        r=self.proposal['report']['intervals'][int(selected[0])];a,b=r['first_ordinal'],r['last_ordinal']
        ordinal={'before':max(0,a-1),'start':a,'middle':(a+b)//2,'end':b,'after':b+1}[where]
        self.app.pending_seek=(self.proposal_clip,ordinal);self.app.select(self.proposal_clip,focus_view=False)

    def close(self):
        self.drawing=None;self.preview=None;self.overlays();self.app.viewer.configure(cursor='');self.window.destroy()
