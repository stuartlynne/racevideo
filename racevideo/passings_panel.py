"""Scrollable, per-cell-coloured lap chart; SQL and MCP stay off Tk's thread."""
from datetime import date, datetime
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font

from . import passings, storage
from .crossmgr_client import Configuration


COLOURS = dict(matched='#d6efd9', missing='#fff2bd', extra='#f4c5c5', video_only='#fff2bd',ignored='#dedede')


class PassingsPanel:
    def __init__(self, app, day,restore=None):
        restore=restore or {};self.restore_state=restore
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('Event passings — visual evidence review')
        self.window.geometry('1180x720')
        try:
            if restore.get('geometry'):self.window.geometry(restore['geometry'])
        except tk.TclError:pass
        self.config = Configuration.load()
        self.day = tk.StringVar(value=restore.get('day',day))
        self.root_path = tk.StringVar(value=restore.get('root',self.config.root))
        self.event_name = tk.StringVar()
        self.competition_name = tk.StringVar()
        self.competition_id = restore.get('competition_id')
        self.competitions = []
        self.event_options = []
        self.category = tk.StringVar(value=restore.get('category','All categories'))
        self.tolerance = tk.StringVar(value=restore.get('tolerance','3'))
        self.offset = tk.StringVar(value=restore.get('offset','0'))
        self.show_ignored=tk.BooleanVar(value=restore.get('show_ignored',False))
        self.show_grouped=tk.BooleanVar(value=restore.get('show_grouped',False))
        self.status = tk.StringVar(value='Loading cached events…')
        self.detail = tk.StringVar(value='Select a passing cell to open matching or nearby captures in the main window.')
        self.jobs = queue.Queue(maxsize=1)
        self.results = queue.SimpleQueue()
        self.stop = threading.Event()
        self.busy = False
        self.pending_job = None
        self.model = None
        self.events = []
        self.event_id = restore.get('event_id')
        self.selected_cell = None
        self.locations={}
        self.capture_rows = []
        self.next_refresh = 0
        self.last_signature = None
        self.fonts={False:Font(family='TkDefaultFont',size=9),True:Font(family='TkDefaultFont',size=10,weight='bold')}
        self.pending_error = ''
        self.review_pending=False
        self.submitted_bike=None
        self.last_review_history=None
        self.last_redo_history=None
        self.add_target=None;self.add_pending=False
        self.add_number=tk.StringVar()
        self.submitted_advance=None;self.hold_removed_selection=None
        self.positioned_candidates=set()
        self.review_number=tk.StringVar()
        self.review_note=tk.StringVar()
        self.review_message=tk.StringVar(value='Review the displayed frame, then confirm, correct, or ignore the selected visual encounter.')
        top = ttk.Frame(self.window,padding=8);top.pack(fill='x')
        ttk.Label(top,text='Date').pack(side='left')
        ttk.Entry(top,textvariable=self.day,width=12).pack(side='left',padx=4)
        ttk.Label(top,text='CMN base').pack(side='left')
        ttk.Entry(top,textvariable=self.root_path).pack(side='left',fill='x',expand=True,padx=4)
        self.import_button=ttk.Button(top,text='Import / refresh CMNs',command=lambda:self.request('import'))
        self.import_button.pack(side='left')
        ttk.Button(top,text='Load cached date',command=lambda:self.request('events')).pack(side='left',padx=4)
        controls=ttk.Frame(self.window,padding=(8,0));controls.pack(fill='x')
        ttk.Label(controls,text='Competition').pack(side='left')
        self.competition_picker=ttk.Combobox(controls,textvariable=self.competition_name,state='readonly',width=22)
        self.competition_picker.pack(side='left',padx=4);self.competition_picker.bind('<<ComboboxSelected>>',self.choose_competition)
        ttk.Label(controls,text='Event').pack(side='left')
        self.event_picker=ttk.Combobox(controls,textvariable=self.event_name,state='readonly',width=32)
        self.event_picker.pack(side='left',padx=4);self.event_picker.bind('<<ComboboxSelected>>',self.choose_event)
        self.category_picker=ttk.Combobox(controls,textvariable=self.category,state='readonly',width=24,values=('All categories',))
        self.category_picker.pack(side='left',padx=4);self.category_picker.bind('<<ComboboxSelected>>',lambda e:self.request('compare'))
        controls=ttk.Frame(self.window,padding=(8,4));controls.pack(fill='x')
        ttk.Label(controls,text='± match seconds').pack(side='left')
        ttk.Entry(controls,textvariable=self.tolerance,width=5).pack(side='left',padx=4)
        ttk.Label(controls,text='Camera − CM seconds').pack(side='left')
        ttk.Entry(controls,textvariable=self.offset,width=7).pack(side='left',padx=4)
        ttk.Button(controls,text='Update matches',command=lambda:self.request('compare')).pack(side='left')
        ttk.Checkbutton(controls,text='Show ignored',variable=self.show_ignored,command=self.paint).pack(side='left',padx=8)
        ttk.Checkbutton(controls,text='Show grouped',variable=self.show_grouped,command=self.toggle_grouped).pack(side='left',padx=4)
        ttk.Button(controls,text='Index event bikes',command=lambda:self.request('index_bikes')).pack(side='left',padx=3)
        ttk.Button(controls,text='Stop indexing',command=lambda:self.request('stop_bikes')).pack(side='left',padx=3)
        ttk.Label(self.window,text='Green: bib/time match · Yellow: needs visual review · Red: visual bib outside event roster\nColumns follow the overall race leader; each column is independently ordered by passing time. Start reads are separate.',padding=8).pack(fill='x')
        area=ttk.Frame(self.window);area.pack(fill='both',expand=True)
        self.header_canvas=tk.Canvas(area,height=44,background='#dce3eb',highlightthickness=0)
        self.header_canvas.grid(row=0,column=0,sticky='ew')
        self.canvas=tk.Canvas(area,background='#f5f5f5',highlightthickness=0,takefocus=True)
        self.canvas.grid(row=1,column=0,sticky='nsew')
        xbar=ttk.Scrollbar(area,orient='horizontal',command=self.canvas.xview)
        ybar=ttk.Scrollbar(area,orient='vertical',command=self.canvas.yview)
        xbar.grid(row=2,column=0,sticky='ew');ybar.grid(row=1,column=1,sticky='ns')
        def sync_x(first,last):
            xbar.set(first,last);self.header_canvas.xview_moveto(float(first))
        self.canvas.configure(xscrollcommand=sync_x,yscrollcommand=ybar.set)
        area.rowconfigure(1,weight=1);area.columnconfigure(0,weight=1)
        self.canvas.bind('<Configure>',lambda e:self.paint())
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.canvas.bind('<Button-4>',lambda e:self.canvas.yview_scroll(-1,'units'))
        self.canvas.bind('<Button-5>',lambda e:self.canvas.yview_scroll(1,'units'))
        for key,dx,dy in (('Left',-1,0),('Right',1,0),('Up',0,-1),('Down',0,1)):
            self.window.bind('<'+key+'>',lambda e,dx=dx,dy=dy:self.move_selection(e,dx,dy))
        bottom=ttk.Frame(self.window,padding=8);bottom.pack(side='bottom',fill='x',before=area)
        ttk.Label(bottom,textvariable=self.detail,wraplength=1100).pack(fill='x')
        self.capture_picker=ttk.Combobox(bottom,state='readonly')
        self.capture_picker.pack(fill='x',pady=4);self.capture_picker.bind('<<ComboboxSelected>>',lambda e:self.open_capture(self.capture_picker.current()))
        actions=ttk.Frame(bottom);actions.pack(fill='x',pady=4);self.action_bar=actions
        ttk.Label(actions,text='Visible bib').pack(side='left')
        self.number_entry=ttk.Entry(actions,textvariable=self.review_number,width=8)
        self.number_entry.pack(side='left',padx=4)
        self.confirm_button=ttk.Button(actions,text='Confirm bib',command=lambda:self.review_action('confirmed'))
        self.confirm_button.pack(side='left',padx=3)
        self.correct_button=ttk.Button(actions,text='Save different bib',command=lambda:self.review_action('corrected'))
        self.correct_button.pack(side='left',padx=3)
        self.ignore_button=ttk.Button(actions,text='Ignore / bystander',command=lambda:self.review_action('ignored'))
        self.ignore_button.pack(side='left',padx=3)
        self.undo_button=ttk.Button(actions,text='Undo last review',command=self.undo_review,state='disabled')
        self.undo_button.pack(side='left',padx=3)
        self.redo_button=ttk.Button(actions,text='Redo (Ctrl+R)',command=self.redo_review,state='disabled');self.redo_button.pack(side='left',padx=3)
        self.restore_button=ttk.Button(actions,text='Restore ignored',command=self.restore_ignored,state='disabled')
        self.restore_button.pack(side='left',padx=3)
        ttk.Label(actions,text='Note').pack(side='left',padx=(8,0))
        ttk.Entry(actions,textvariable=self.review_note).pack(side='left',fill='x',expand=True,padx=4)
        ttk.Label(bottom,textvariable=self.review_message,wraplength=1100).pack(fill='x')
        self.add_bar=ttk.Frame(bottom)
        ttk.Label(self.add_bar,text='Add bib at displayed frame:').pack(side='left')
        self.add_entry=ttk.Entry(self.add_bar,textvariable=self.add_number,width=8);self.add_entry.pack(side='left',padx=4)
        self.add_entry.bind('<Return>',self.submit_add_bib)
        self.add_entry.bind('<KP_Enter>',self.submit_add_bib)
        self.add_entry.bind('<Escape>',self.cancel_add_bib)
        ttk.Button(self.add_bar,text='Add (Enter)',command=self.submit_add_bib).pack(side='left')
        ttk.Button(self.add_bar,text='Cancel (Esc)',command=self.cancel_add_bib).pack(side='left',padx=4)
        bike_controls=ttk.Frame(bottom);bike_controls.pack(fill='x',pady=2)
        ttk.Button(bike_controls,text='Mark bike in main image…',command=self.app.begin_bike_mark).pack(side='left')
        ttk.Button(bike_controls,text='Clear mark',command=self.app.clear_bike_mark).pack(side='left',padx=4)
        ttk.Label(bike_controls,text='Bike order in capture:').pack(side='left',padx=(8,3))
        ttk.Entry(bike_controls,textvariable=self.app.bike_order,width=4).pack(side='left')
        ttk.Label(bottom,textvariable=self.status,wraplength=1100).pack(fill='x')
        ttk.Label(bottom,text='Space: confirm · + then bib and Enter: add · −: ignore · Esc: cancel add').pack(fill='x')
        self.app.install_review_shortcuts(self.window)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.worker=threading.Thread(target=self.work,name='passings-review',daemon=True);self.worker.start()
        self.request('restore' if restore else 'events')
        self.poll_timer=self.window.after(100,self.poll)

    def displayed_cells(self):
        if not self.model:return []
        return sorted(self.model['cells']+(self.model.get('grouped_cells',[]) if self.show_grouped.get() else [])+(self.model.get('ignored_cells',[]) if self.show_ignored.get() else []),
            key=lambda c:(c.get('sort_ns',c['at_ns']),c.get('passing_order') or 1000,c['cell_key']))

    def toggle_grouped(self):
        if not self.show_grouped.get() and self.selected_cell and self.selected_cell.get('grouped_under'):
            parent=next((c for c in self.model['cells'] if c['cell_key']==self.selected_cell['grouped_under']),None)
            if parent:self.select_cell(parent);self.reveal_selection();return
        self.paint()

    def navigation_target(self,dx,dy):
        cells=self.displayed_cells()
        owner=getattr(self,'compact_owner',None)
        if owner and owner.visible and self.window.state()=='withdrawn' and len(self.model['columns'])>1:cells=[c for c in cells if c['column']>0]
        if not cells:return None
        columns=sorted({c['column'] for c in cells})
        current=self.selected_cell
        ordered=[c for column in columns for c in cells if c['column']==column]
        if current is None or current['cell_key'] not in {c['cell_key'] for c in cells}:
            target=ordered[-1] if self.hold_removed_selection else ordered[0]
            if self.hold_removed_selection and dy>0:return None
        elif dy:
            index=next(i for i,c in enumerate(ordered) if c['cell_key']==current['cell_key'])
            target=ordered[max(0,min(len(ordered)-1,index+dy))]
        else:
            column=current['column'];rows=[c for c in cells if c['column']==column]
            row=next(i for i,c in enumerate(rows) if c['cell_key']==current['cell_key'])
            if dx:
                column=columns[max(0,min(len(columns)-1,columns.index(column)+dx))]
                rows=[c for c in cells if c['column']==column]
            target=rows[max(0,min(len(rows)-1,row+dy))]
        return target

    def move_selection(self,event,dx,dy):
        if event.widget.winfo_class() in ('TEntry','Entry','Text','TCombobox','Spinbox','TSpinbox'):return
        target=self.navigation_target(dx,dy)
        if target is None:return 'break'
        self.select_cell(target)
        self.reveal_selection()
        return 'break'

    def reveal_selection(self):
        target=self.selected_cell
        if target is None:return
        tag=next((t for t,c in self.locations.items() if c['cell_key']==target['cell_key']),None)
        if tag:
            x0,y0,x1,y1=self.canvas.bbox(tag);_,_,total_w,total_h=map(float,self.canvas.cget('scrollregion').split())
            for axis,low,high,total,size in (('x',x0,x1,total_w,self.canvas.winfo_width()),('y',y0,y1,total_h,self.canvas.winfo_height())):
                start=getattr(self.canvas,'canvas'+axis)(0)
                if low<start:getattr(self.canvas,axis+'view_moveto')(max(0,low)/max(1,total))
                elif high>start+size:getattr(self.canvas,axis+'view_moveto')(max(0,high-size)/max(1,total))

    def request(self,operation):
        if self.stop.is_set():return
        try:
            day=date.fromisoformat(self.day.get().strip()).isoformat()
            tolerance=float(self.tolerance.get());offset=float(self.offset.get())
            config=Configuration(**vars(self.config));config.root=self.root_path.get().strip()
            job=(operation,day,config,self.event_id,tolerance,offset,self.category.get(),self.competition_id,self.app.selected)
            if self.busy:
                self.pending_job=job;return
            self.dispatch(job)
        except (ValueError,queue.Full) as exc:self.status.set(str(exc))

    def dispatch(self,job):
        self.jobs.put_nowait(job)
        self.busy=True;self.import_button.configure(state='disabled')
        if job[0]=='import':self.status.set('Importing trusted saved CMNs through CrossMgr MCP; capture and review continue…')

    def work(self):
        while not self.stop.is_set():
            try:job=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            operation,day,config,event_id,tolerance,offset,category,competition_id,current_clip=job
            try:
                if operation=='import':passings.import_day(self.app.path,config,day)
                analysis_message=None
                if operation in ('index_bikes','stop_bikes'):
                    if event_id is None:raise ValueError('Select an event first')
                    from .service import start_bikes,stop_event_bikes
                    if operation=='index_bikes':
                        runs=start_bikes(self.app.path,event_id=event_id,offset=offset)
                        analysis_message=f'Queued {len(runs)} captures for bike indexing: category finishers first, otherwise newest first. OCR and original footage are unchanged.'
                    else:
                        stopped=stop_event_bikes(self.app.path,event_id,offset)
                        analysis_message=f'Cancelled {stopped} queued captures. Any active capture analysis finishes before stopping.'
                query_started=time.perf_counter()
                c=storage.connect(self.app.path,readonly=True)
                try:
                    c.execute('BEGIN')
                    events=passings.list_events(c,day)
                    if event_id is None and competition_id is None and current_clip:
                        clip=c.execute('SELECT started_ns FROM clips WHERE id=?',(current_clip,)).fetchone()
                        near=next((e for e in events if clip and e['start_ns']<=clip['started_ns']<=e['end_ns']),None)
                        if near:event_id=near['id'];competition_id=near['competition_id']
                    if competition_id not in {e['competition_id'] for e in events}:competition_id=events[0]['competition_id'] if events else None
                    options=[e for e in events if e['competition_id']==competition_id]
                    if event_id not in {e['id'] for e in options}:event_id=options[0]['id'] if options else None
                    if operation in ('events','import'):category='All categories'
                    model=passings.compare_event(c,event_id,tolerance,offset,category) if event_id else None
                    self.results.put(('loaded',dict(events=events,model=model,category=category,competition_id=competition_id,
                        query_ms=(time.perf_counter()-query_started)*1000,analysis_message=analysis_message)))
                finally:c.close()
            except Exception as exc:self.results.put(('error',str(exc)))

    def poll(self):
        if self.stop.is_set():return
        while not self.results.empty():
            kind,value=self.results.get();self.busy=False;self.import_button.configure(state='normal')
            if self.pending_job is not None:
                job,self.pending_job=self.pending_job,None;self.dispatch(job);continue
            if kind=='error':
                self.pending_error=value;self.status.set(value);self.next_refresh=time.monotonic()+10
            else:
                self.app.performance.observe('passings_query_ms',value['query_ms'])
                if value.get('analysis_message'):self.review_message.set(value['analysis_message'])
                previous_selection=self.selected_cell
                self.pending_error='';self.events=value['events'];self.model=value['model']
                self.competition_id=value['competition_id']
                self.competitions=list({e['competition_id']:e['competition'] for e in self.events}.items())
                self.competition_picker.configure(values=[f'{name} · #{cid}' for cid,name in self.competitions])
                self.competition_name.set(next((f'{name} · #{cid}' for cid,name in self.competitions if cid==self.competition_id),''))
                self.event_options=[e for e in self.events if e['competition_id']==self.competition_id]
                self.event_picker.configure(values=[f"{e['name']} · #{e['id']}" for e in self.event_options])
                if self.model:
                    self.last_review_history=self.model.get('undo_review_id');self.last_redo_history=self.model.get('redo_review_id');self.update_review_buttons()
                    self.event_id=self.model['event']['id']
                    self.event_name.set(next(f"{e['name']} · #{e['id']}" for e in self.events if e['id']==self.event_id))
                    self.category_picker.configure(values=['All categories']+self.model['categories'])
                    self.category.set(value['category'])
                    cells=self.model['cells'];counts={s:sum(c['state']==s for c in cells) for s in COLOURS}
                    cached=datetime.fromtimestamp(self.model['source_imported_ns']/1e9).strftime('%Y-%m-%d %H:%M')
                    self.status.set(f"{counts['matched']} matched · {counts['missing']} without visual match · {counts['video_only']} visual-only in roster · {counts['extra']} outside roster. CMN cache: {cached}. Live video evidence refreshes every 5 s.\n"+self.model['warning'])
                    coverage=self.model.get('bike_coverage',{})
                    self.status.set(self.status.get()+f"\nBike index: {coverage.get('indexed',0)}/{coverage.get('total',0)} captures. {len(self.model.get('ignored_cells',[]))} ignored (Show ignored to inspect/restore). Unindexed captures may contain additional bikes; use Find bikes.")
                    jobs=self.model.get('bike_jobs',{})
                    if jobs:self.status.set(self.status.get()+f" Indexing: {jobs.get('running',0)} running, {jobs.get('queued',0)} queued.")
                    reconciled=self.model.get('review_reconciliations',[])
                    if reconciled:self.status.set(self.status.get()+f" {len(reconciled)} review associations reconciled automatically; saved manual evidence retained.")
                    if self.model.get('grouped_cells'):self.status.set(self.status.get()+f" {len(self.model['grouped_cells'])} possible duplicate reads grouped; Show grouped to inspect.")
                else:
                    self.event_id=None;self.event_name.set('');self.status.set('No cached events for this date. Use Import / refresh CMNs to load the date from the configured base.')
                time_signature=(self.event_id,self.model['event']['start_ns'],self.model['offset']) if self.model else None
                if time_signature!=getattr(self,'time_context_signature',None):
                    self.time_context_signature=time_signature;self.app.refresh_time_displays()
                signature=repr(self.model)
                # A refresh replaces cell dictionaries even when their values
                # are unchanged. Keep selection attached to the passing key,
                # rather than the lifetime of a particular result object.
                old_key=self.selected_cell.get('cell_key') if self.selected_cell else None
                self.selected_cell=next((c for c in self.displayed_cells() if c['cell_key']==old_key),None)
                if signature!=self.last_signature:
                    self.last_signature=signature
                    open_next=False
                    if self.selected_cell is None and previous_selection and self.displayed_cells() and previous_selection['cell_key']!=self.hold_removed_selection:
                        candidates=[c for c in self.displayed_cells() if c['column']==previous_selection['column']] or self.displayed_cells()
                        self.selected_cell=min(candidates,key=lambda c:(c['at_ns']<previous_selection['at_ns'],abs(c['at_ns']-previous_selection['at_ns'])))
                        self.review_number.set(self.selected_cell['bib'] if self.selected_cell['bib'].isdigit() else '')
                        self.review_note.set('');open_next=True
                    if self.selected_cell:self.describe_cell(open_first=open_next)
                    else:
                        self.capture_rows=[];self.capture_picker.configure(values=());self.capture_picker.set('')
                    self.paint()
                if self.restore_state and self.model:
                    saved=self.restore_state;self.restore_state=None
                    cell=next((c for c in self.displayed_cells() if c['cell_key']==saved.get('selected')),None)
                    if cell is None and not self.show_grouped.get():
                        grouped=next((c for c in self.model.get('grouped_cells',[]) if c['cell_key']==saved.get('selected')),None)
                        if grouped:cell=next((c for c in self.model['cells'] if c['cell_key']==grouped['grouped_under']),None)
                    if cell:
                        self.selected_cell=cell;self.review_number.set(cell['bib'] if cell['bib'].isdigit() else '')
                        self.describe_cell(open_first=False)
                        index=next((i for i,r in enumerate(self.capture_rows) if r['clip_id']==saved.get('capture')),0)
                        if self.capture_rows:self.capture_picker.current(index)
                        self.paint()
                    self.canvas.xview_moveto(saved.get('scroll_x',0));self.canvas.yview_moveto(saved.get('scroll_y',0))
                self.update_review_buttons()
                self.next_refresh=time.monotonic()+5
        if not self.busy and self.event_id and time.monotonic()>=self.next_refresh:self.request('compare')
        self.poll_timer=self.window.after(100,self.poll)

    def choose_event(self,event=None):
        index=self.event_picker.current()
        if index>=0:
            self.event_id=self.event_options[index]['id'];self.category.set('All categories');self.request('compare')

    def choose_competition(self,event=None):
        index=self.competition_picker.current()
        if index>=0:
            self.competition_id=self.competitions[index][0];self.event_id=None
            self.category.set('All categories');self.request('events')

    def paint(self):
        owner=getattr(self,'compact_owner',None)
        if owner and owner.visible and self.window.state()=='withdrawn':return
        drawing_started=time.perf_counter()
        self.canvas.delete('all');self.header_canvas.delete('all');self.locations={}
        if not self.model:
            self.canvas.configure(scrollregion=(0,0,1,1));self.header_canvas.configure(scrollregion=(0,0,1,44));return
        width=242;height=75;header=44
        columns=self.model['columns'];rows=[[] for _ in columns]
        for cell in self.displayed_cells():rows[cell['column']].append(cell)
        # Only repaint on model/size changes; scrolling moves existing canvas
        # items without redrawing every cell on each GUI timer tick.
        for col,info in enumerate(columns):
            x=col*width
            self.header_canvas.create_rectangle(x,0,x+width,header,fill='#dce3eb',outline='#aab6c4')
            from .race_clock import display
            stamp=display(info['start_ns'],self.model['event'],milliseconds=False,prefix=False)
            self.header_canvas.create_text(x+8,5,text=info['label']+' · '+stamp,anchor='nw',font=('TkDefaultFont',10,'bold'))
            if info.get('leader_bib'):self.header_canvas.create_text(x+8,24,text='Leader '+info['leader_bib'],anchor='nw')
            for row,cell in enumerate(rows[col]):
                y=row*height;tag=f'cell-{col}-{row}';self.locations[tag]=cell
                fill=COLOURS[cell['state']]
                selected=self.selected_cell is not None and self.selected_cell['cell_key']==cell['cell_key']
                self.canvas.create_rectangle(x+3,y+3,x+width-3,y+height-3,fill=fill,outline='#0057c2' if selected else '#bbb',width=5 if selected else 1,tags=(tag,'selected-passing') if selected else (tag,))
                marker='✓' if cell['confirmed'] else '?' if cell['visual_count'] else '—'
                if cell.get('grouped_candidates'):marker+=f" [+{len(cell['grouped_candidates'])} grouped]"
                title=f"{row+1}.  {cell['bib']} {marker}  {cell['name']}"
                if cell.get('passing_order'):title=f"{row+1}.  {cell['bib']} {marker} [bike {cell['passing_order']}] {cell['name']}"
                if cell.get('grouped_under'):title='↳ '+title
                if selected:title='▶ '+title
                stamp=display(cell['at_ns'],self.model['event'],prefix=False)
                detail=f"{stamp} · "+('CM + visual' if cell['state']=='matched' else 'CM · no visual' if cell['state']=='missing' else cell['origin'])
                cats=', '.join(cell['categories']) or 'Not in this event'
                if cell.get('ambiguous'):detail+=' · ambiguous'
                for dy,text,bold in ((8,title,True),(29,detail,False),(49,cats,False)):
                    font=self.fonts[bold]
                    while text and font.measure(text)>width-16:text=text[:-2]+'…'
                    self.canvas.create_text(x+8,y+dy,text=text,anchor='nw',font=font,tags=tag)
        self.canvas.configure(scrollregion=(0,0,max(width*len(columns),1),max([len(r) for r in rows]+[1])*height))
        self.header_canvas.configure(scrollregion=(0,0,max(width*len(columns),1),header))
        self.header_canvas.xview_moveto(self.canvas.xview()[0])
        self.app.performance.observe('passings_draw_ms',(time.perf_counter()-drawing_started)*1000)

    def click(self,event):
        self.canvas.focus_set()
        tags=self.canvas.gettags('current')
        cell=next((self.locations[t] for t in tags if t in self.locations),None)
        if cell is None:return 'break'
        self.select_cell(cell);return 'break'

    def select_cell(self,cell):
        self.submitted_advance=None;self.hold_removed_selection=None
        self.canvas.focus_set()
        if self.selected_cell is not None and self.selected_cell['cell_key']==cell['cell_key']:
            # Re-selecting the same passing must not restart video loading or
            # discard an operator's review entry and chosen capture/frame.
            self.selected_cell=cell
            index=self.capture_picker.current()
            if 0<=index<len(self.capture_rows):
                row=self.capture_rows[index]
                if self.app.mode!='replay' or self.app.selected!=row['clip_id'] or row.get('ordinal') is None and (cell['cell_key'],row['clip_id']) not in self.positioned_candidates:
                    self.open_capture(index)
            self.paint();return 'break'
        self.selected_cell=cell
        if self.add_target and not self.add_pending:self.cancel_add_bib()
        self.review_number.set(cell['bib'] if cell['bib'].isdigit() else '')
        self.review_note.set('')
        self.describe_cell(open_first=True)
        self.update_review_buttons()
        self.paint();return 'break'

    def describe_cell(self,open_first=False):
        cell=self.selected_cell
        old_clip=self.capture_rows[self.capture_picker.current()]['clip_id'] if 0<=self.capture_picker.current()<len(self.capture_rows) else None
        self.capture_rows=cell['captures']
        provenance=cell.get('provenance','')
        self.detail.set(f"Bib {cell['bib']} · {cell['name']} · {cell['origin']} · {provenance}. "
            f"{cell['visual_count']} matching visual observations; {len(self.capture_rows)} matching/nearby capture choices. "+
            ('Other OCR alternatives on this track: '+', '.join(cell['alternative_bibs'])+'. ' if cell.get('alternative_bibs') else '')+
            'Times are uncalibrated; an OCR candidate or stored CM passing is not proof of RFID detection.')
        if cell.get('grouped_candidates'):self.detail.set(self.detail.get()+f" {len(cell['grouped_candidates'])} nearby possible duplicates grouped; enable Show grouped to inspect them.")
        if cell.get('grouped_under'):self.detail.set(self.detail.get()+f" Possible duplicate: {cell['group_reason']} ({cell['group_delta_seconds']:+.1f}s). Original CrossMgr data is retained.")
        self.capture_picker.configure(values=[f"Clip {r['clip_id']} · "+('nearby bike · '+r.get('number','?') if r.get('candidate') else 'matching bib'+(' ✓' if r.get('confirmed') else ' ?') if r.get('ordinal') is not None and r.get('number') not in (None,'?') else 'unidentified bike' if r.get('ordinal') is not None else 'nearby time candidate') for r in self.capture_rows])
        if self.capture_rows:
            index=next((i for i,r in enumerate(self.capture_rows) if r['clip_id']==old_clip),0) if not open_first else 0
            self.capture_picker.current(index)
            if open_first:self.open_capture(index)
        else:self.capture_picker.set('No capture in the selected time window')

    def open_capture(self,index):
        if not 0<=index<len(self.capture_rows):return
        row=self.capture_rows[index]
        hint=None
        if row.get('ordinal') is None and row.get('target_ns') is not None:
            self.positioned_candidates.add((self.selected_cell['cell_key'],row['clip_id']))
            excluded=[v['key'] for cell in self.model['cells'] if cell['cell_key']!=self.selected_cell['cell_key']
                for v in cell['captures'][:cell['visual_count']] if v['clip_id']==row['clip_id'] and v.get('key')]
            ignored=[key for cell in self.model.get('ignored_cells',[]) if cell['captures'][0]['clip_id']==row['clip_id'] for key in cell.get('source_keys',[])]
            protected=[v['key'] for cell in self.model['cells'] for v in cell['captures'][:cell['visual_count']]
                if v['clip_id']==row['clip_id'] and v.get('confirmed') and v.get('key')]
            hint=dict(target_ns=row['target_ns'],bib=self.selected_cell['bib'],exclude_keys=excluded,ignore_keys=ignored,protected_keys=protected)
        self.app.pending_seek=(row['clip_id'],row['ordinal']) if row.get('ordinal') is not None else None
        self.app.select(row['clip_id'],focus_view=False,target_ns=hint,align_wheel=True)
        if row.get('bike_box') and row.get('ordinal') is not None:
            box=row['bike_box'];w,h=row['width'],row['height']
            self.app.plate_evidence=(row['clip_id'],row['ordinal'],[[box[0]*w,box[1]*h],[box[2]*w,box[1]*h],[box[2]*w,box[3]*h],[box[0]*w,box[3]*h]])

    def review_action(self,action,advance=False):
        if self.review_pending:return
        if self.selected_cell and self.selected_cell['state']=='ignored':
            self.review_message.set('Restore this ignored candidate before confirming or correcting it.');return
        if not self.model or self.model['event']['id']!=self.event_id:
            self.review_message.set('Wait for the selected event to load before saving.');return
        index=self.capture_picker.current()
        if self.selected_cell is None or not 0<=index<len(self.capture_rows):
            self.review_message.set('Select a passing and a capture first.');return
        row=self.capture_rows[index]
        ordinal=getattr(self.app,'displayed_ordinal',None)
        if self.app.mode!='replay' or self.app.selected!=row['clip_id'] or ordinal is None:
            self.review_message.set('Wait for the selected capture to display before saving a decision.');return
        number=self.review_number.get().strip()
        if action!='ignored':
            from .bib_review import validate_number
            try:validate_number(number)
            except ValueError as exc:self.review_message.set(str(exc));return
        request=dict(event_id=self.event_id,clip_id=row['clip_id'],ordinal=ordinal,action=action,
            number=number if action!='ignored' else None,visual_key=row.get('key'),note=self.review_note.get().strip())
        if action!='ignored':
            try:request.update(self.app.bike_annotation())
            except ValueError as exc:self.review_message.set(str(exc));return
        self.submitted_bike=(self.app.bike_mark,self.app.bike_order.get())
        if advance:
            target=self.navigation_target(0,1)
            self.submitted_advance=(self.event_id,self.selected_cell['cell_key'],
                target['cell_key'] if target and target['cell_key']!=self.selected_cell['cell_key'] else None)
        self.review_pending=True;self.update_review_buttons()
        self.review_message.set(f'Saving review for clip {row["clip_id"]}, displayed frame {ordinal+1}…')
        self.app.reader.jobs.put(('passing_review',request))

    def position_candidate(self,clip,position,index):
        selected=self.capture_picker.current()
        row=self.capture_rows[selected] if 0<=selected<len(self.capture_rows) else None
        if not row or row['clip_id']!=clip or row.get('ordinal') is not None or not position.get('physical_key'):return
        ordinal=position['ordinal'];stamp=next(r['received_ns'] for r in index if r['ordinal']==ordinal)
        row.update(ordinal=ordinal,key=position['physical_key'],physical_key=position['physical_key'],first_ns=stamp,last_ns=stamp,candidate=True)

    def begin_add_bib(self):
        if self.review_pending:return
        ordinal=getattr(self.app,'displayed_ordinal',None)
        if not self.model or self.model['event']['id']!=self.event_id or self.app.mode!='replay' or ordinal is None or not self.app.index:
            self.review_message.set('Select a race and display a saved frame before adding a bib.');return
        self.app.playing=False
        self.app.play_button.configure(text='▶  Play')
        self.add_target=(self.event_id,self.app.selected,ordinal)
        self.add_number.set('');self.add_entry.configure(state='normal')
        self.add_bar.pack(fill='x',before=self.action_bar)
        self.review_message.set(f'Adding a separate rider at clip {self.app.selected}, frame {ordinal+1}. Type bib, Enter to save, Esc to cancel.')
        owner=getattr(self,'compact_owner',None)
        if owner and owner.visible and self.window.state()=='withdrawn':owner.show_add()
        else:self.window.lift();self.window.focus_force();self.add_entry.focus_set()

    def cancel_add_bib(self,event=None):
        if self.add_pending:return 'break'
        self.add_target=None;self.add_bar.pack_forget();self.canvas.focus_set()
        owner=getattr(self,'compact_owner',None)
        if owner and owner.visible:owner.hide_add()
        return 'break'

    def submit_add_bib(self,event=None):
        if self.review_pending or self.add_target is None:return 'break'
        if self.add_target!=(self.event_id,self.app.selected,getattr(self.app,'displayed_ordinal',None)) or self.app.mode!='replay':
            self.review_message.set('The displayed frame or event changed. Cancel and press + on the intended frame.');return 'break'
        number=self.add_number.get().strip()
        try:
            from .bib_review import validate_number
            validate_number(number)
            annotation=self.app.bike_annotation()
        except ValueError as exc:self.review_message.set(str(exc));return 'break'
        event_id,clip,ordinal=self.add_target
        request=dict(event_id=event_id,clip_id=clip,ordinal=ordinal,number=number,action='confirmed',add=True,
            note=self.review_note.get().strip(),**annotation)
        self.submitted_bike=(self.app.bike_mark,self.app.bike_order.get())
        self.review_pending=True;self.add_pending=True;self.add_entry.configure(state='disabled');self.update_review_buttons()
        self.review_message.set(f'Adding bib {number} at clip {clip}, displayed frame {ordinal+1}…')
        self.app.reader.jobs.put(('passing_review',request));return 'break'

    def update_review_buttons(self):
        ignored=self.selected_cell is not None and self.selected_cell['state']=='ignored'
        for button in (self.confirm_button,self.correct_button,self.ignore_button):
            button.configure(state='disabled' if self.review_pending or ignored else 'normal')
        self.undo_button.configure(state='normal' if self.last_review_history and not self.review_pending else 'disabled')
        self.redo_button.configure(state='normal' if self.last_redo_history and not self.review_pending else 'disabled')
        self.restore_button.configure(state='normal' if ignored and self.selected_cell.get('restore_history_id') and not self.review_pending else 'disabled')

    def restore_ignored(self):
        if self.review_pending or not self.selected_cell or not self.selected_cell.get('restore_history_id'):return
        self.review_pending=True;self.update_review_buttons()
        self.app.reader.jobs.put(('passing_review',dict(history_id=self.selected_cell['restore_history_id'])))

    def review_result(self,result,error=False):
        self.review_pending=False
        advance=self.submitted_advance;self.submitted_advance=None
        if self.add_pending:
            self.add_pending=False;self.add_entry.configure(state='normal')
            if not error:self.cancel_add_bib()
        if error:self.review_message.set(str(result))
        else:
            if self.submitted_bike:
                mark,order=self.submitted_bike;self.submitted_bike=None
                if self.app.bike_mark==mark:self.app.clear_bike_mark()
                if self.app.bike_order.get()==order:self.app.bike_order.set('')
            self.last_review_history=None;self.last_redo_history=None
            action=result.get('action') or result['review']['action'] if result else 'undone'
            self.review_message.set('Saved: '+action+'. CrossMgr passings are unchanged.'+
                (' The expected CrossMgr passing still needs visual confirmation.' if action=='ignored' else ''))
            if advance and self.event_id==advance[0] and self.selected_cell and self.selected_cell['cell_key']==advance[1]:
                target=next((c for c in self.displayed_cells() if c['cell_key']==advance[2]),None)
                if target:
                    self.select_cell(target);self.reveal_selection()
                elif action=='ignored':self.hold_removed_selection=advance[1]
            self.request('compare')
        self.update_review_buttons()

    def undo_review(self):
        if self.review_pending or not self.last_review_history:return
        self.review_pending=True;self.update_review_buttons()
        self.app.reader.jobs.put(('passing_review',dict(history_id=self.last_review_history)))

    def redo_review(self):
        if self.review_pending or not self.last_redo_history:return
        self.review_pending=True;self.update_review_buttons()
        self.app.reader.jobs.put(('passing_review',dict(history_id=self.last_redo_history,redo=True)))

    def close(self):
        self.app.last_passings_state=self.session_snapshot()
        owner=getattr(self,'compact_owner',None)
        if owner and owner.visible and not getattr(self.app,'closing',False):
            self.window.withdraw();return
        self.window.after_cancel(self.poll_timer)
        self.stop.set();self.window.destroy()
        if not getattr(self.app,'closing',False):self.app.set_passings_layout(False)

    def session_snapshot(self):
        index=self.capture_picker.current()
        return dict(geometry=self.window.geometry(),day=self.day.get(),root=self.root_path.get(),
            competition_id=self.competition_id,event_id=self.event_id,category=self.category.get(),
            tolerance=self.tolerance.get(),offset=self.offset.get(),show_ignored=self.show_ignored.get(),show_grouped=self.show_grouped.get(),
            selected=self.selected_cell['cell_key'] if self.selected_cell else None,
            capture=self.capture_rows[index]['clip_id'] if 0<=index<len(self.capture_rows) else None,
            scroll_x=self.canvas.xview()[0],scroll_y=self.canvas.yview()[0])
