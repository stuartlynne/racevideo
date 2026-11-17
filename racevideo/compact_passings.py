"""Single-screen bib grid sharing the detailed passing controller and its reviews."""
from datetime import date
import queue,threading,time
import tkinter as tk
from tkinter import ttk
from .passings_panel import COLOURS
from .race_clock import elapsed


def header_clock(ns):
    return elapsed(((ns+500_000_000)//1_000_000_000)*1_000_000_000,False,True)


class CompactPassings:
    def __init__(self,app,parent):
        self.app=app;self.visible=True;self.panel=None;self.signature=None
        self.restore_scroll=app.saved_session.get('compact_view',{});self.follow=tk.BooleanVar(value=app.mode=='live')
        self.jobs=queue.Queue(maxsize=1);self.results=queue.SimpleQueue();self.stop=threading.Event();self.force_live=True;self.live_state='';self.live_busy=False;self.live_error='';self.live_ready=False;self.next_live=0
        self.prestart_categories=[];self.prestart_name='';self.prestart_total=0
        self.frame=ttk.Frame(parent,width=440);self.frame.pack_propagate(False)
        bar=ttk.Frame(self.frame);bar.pack(fill='x')
        ttk.Checkbutton(bar,text='Current CrossMgr race',variable=self.follow,command=self.follow_changed).pack(side='left')
        ttk.Button(bar,text='Pop out',style='Compact.TButton',command=app.show_event_passings).pack(side='right')
        from .crossmgr_client import Configuration
        target_row=ttk.Frame(self.frame);target_row.pack(fill='x',padx=4)
        ttk.Label(target_row,text='MCP target:').pack(side='left')
        self.target=tk.StringVar(value=Configuration.load().target)
        self.target_picker=ttk.Combobox(target_row,textvariable=self.target,values=Configuration.targets(),state='readonly')
        self.target_picker.pack(side='left',fill='x',expand=True)
        self.target_picker.bind('<<ComboboxSelected>>',self.choose_target)
        self.race_name=tk.StringVar()
        self.generation=0
        self.selector=ttk.Frame(self.frame);self.selector.pack(fill='x',padx=4,pady=3)
        self.status=ttk.Label(self.frame,text='Loading passings…',wraplength=425);self.status.pack(fill='x',padx=6)
        area=ttk.Frame(self.frame);self.area=area;area.pack(fill='both',expand=True)
        self.header=tk.Canvas(area,height=58,highlightthickness=0,bg='#dce3eb');self.header.grid(row=0,column=0,sticky='ew')
        self.canvas=tk.Canvas(area,highlightthickness=0,bg='#f5f5f5',takefocus=True);self.canvas.grid(row=1,column=0,sticky='nsew')
        xbar=ttk.Scrollbar(area,orient='horizontal',command=self.canvas.xview);xbar.grid(row=2,column=0,sticky='ew')
        ybar=ttk.Scrollbar(area,command=self.canvas.yview);ybar.grid(row=1,column=1,sticky='ns')
        def sync_x(a,b):xbar.set(a,b);self.header.xview_moveto(float(a))
        self.canvas.configure(xscrollcommand=sync_x,yscrollcommand=ybar.set)
        area.rowconfigure(1,weight=1);area.columnconfigure(0,weight=1)
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<Motion>',self.hover)
        for widget in (self.canvas,self.header):
            widget.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
            widget.bind('<Button-4>',lambda e:self.canvas.yview_scroll(-1,'units'))
            widget.bind('<Button-5>',lambda e:self.canvas.yview_scroll(1,'units'))
        self.detail=ttk.Label(self.frame,text='Click a bib to review its capture.',wraplength=425);self.detail.pack(side='bottom',fill='x',padx=6,pady=3,before=area)
        self.actions=ttk.Frame(self.frame);self.actions.pack(side='bottom',fill='x',padx=4,before=area)
        for text,cmd in [('Confirm',lambda:self.action('confirmed')),('Ignore',lambda:self.action('ignored')),('Undo',lambda:self.panel.undo_review() if self.panel else None)]:
            ttk.Button(self.actions,text=text,style='Compact.TButton',command=cmd).pack(side='left',padx=2)
        self.add_bar=ttk.Frame(self.frame);self.locations={};self.last_selected=None
        threading.Thread(target=self.work,name='compact-crossmgr-read',daemon=True).start()
        self.app.root.after(100,self.tick)

    def ensure_panel(self):
        if self.app.passings_panel is None or not self.app.passings_panel.window.winfo_exists():
            self.app.show_event_passings(embedded=True)
        panel=self.app.passings_panel
        if panel is self.panel:return
        self.panel=panel;panel.compact_owner=self;self.controls_signature=None
        for child in self.actions.winfo_children()[3:]:child.destroy()
        for child in self.add_bar.winfo_children():child.destroy()
        for child in self.selector.winfo_children():child.destroy()
        self.race_name_entry=ttk.Entry(self.selector,textvariable=self.race_name,state='readonly')
        self.race_name_entry.pack(fill='x',pady=(0,2))
        self.archive_controls=ttk.Frame(self.selector);self.archive_controls.pack(fill='x')
        row=ttk.Frame(self.archive_controls);row.pack(fill='x')
        self.day_picker=ttk.Combobox(row,textvariable=panel.day,width=12,values=(),state='normal');self.day_picker.pack(side='left')
        self.day_picker.bind('<Return>',lambda e:self.choose_day());self.day_picker.bind('<<ComboboxSelected>>',lambda e:self.choose_day())
        self.load_button=ttk.Button(row,text='Load',style='Compact.TButton',command=self.choose_day);self.load_button.pack(side='left',padx=2)
        self.import_button=ttk.Button(row,text='Import date',style='Compact.TButton',command=lambda:self.archive('import'));self.import_button.pack(side='left')
        self.event_picker=ttk.Combobox(self.archive_controls,state='readonly');self.event_picker.pack(fill='x',pady=2);self.event_picker.bind('<<ComboboxSelected>>',self.choose_event)
        self.category_picker=ttk.Combobox(self.selector,textvariable=panel.category,state='readonly');self.category_picker.pack(fill='x');self.category_picker.bind('<<ComboboxSelected>>',self.choose_category)
        ttk.Checkbutton(self.selector,text='Show grouped candidates',variable=panel.show_grouped,command=panel.toggle_grouped).pack(anchor='w')
        self.update_mode_controls()
        self.correct_number=ttk.Entry(self.actions,textvariable=panel.review_number,width=5);self.correct_number.pack(side='left',padx=3)
        self.correct_number.bind('<Return>',lambda e:self.action('corrected'))
        ttk.Button(self.actions,text='Correct',style='Compact.TButton',command=lambda:self.action('corrected')).pack(side='left')
        ttk.Label(self.add_bar,text='Add bib:').pack(side='left')
        self.add_entry=ttk.Entry(self.add_bar,textvariable=panel.add_number,width=6);self.add_entry.pack(side='left')
        self.add_entry.bind('<Return>',panel.submit_add_bib);self.add_entry.bind('<Escape>',panel.cancel_add_bib)
        ttk.Button(self.add_bar,text='Add',style='Compact.TButton',command=panel.submit_add_bib).pack(side='left')
        ttk.Button(self.add_bar,text='Cancel',style='Compact.TButton',command=panel.cancel_add_bib).pack(side='left')
        self.app.install_review_shortcuts(self.frame)

    def choose_target(self,event=None):
        from .crossmgr_client import Configuration
        from tkinter import messagebox
        if self.live_busy or (self.panel and self.panel.busy):
            self.target.set(Configuration.load().target)
            messagebox.showinfo('CrossMgr target','Wait for the current CrossMgr request to finish.')
            return
        try:config=Configuration.select(self.target.get())
        except Exception as exc:
            self.target.set(Configuration.load().target)
            messagebox.showerror('CrossMgr target',str(exc));return
        self.ensure_panel()
        self.panel.config=config;self.panel.root_path.set(config.root)
        self.panel.model=None;self.panel.event_id=None;self.panel.competition_id=None
        self.panel.selected_cell=None;self.panel.events=[]
        self.race_name.set('')
        self.generation+=1
        self.follow_current()

    def action(self,action):
        if self.panel:self.panel.review_action(action,advance=action in ('confirmed','ignored'))

    def show_add(self):
        self.add_bar.pack(side='bottom',fill='x',padx=6,before=self.area);self.add_entry.configure(state='normal');self.app.root.after_idle(self.add_entry.focus_set)

    def hide_add(self):self.add_bar.pack_forget();self.canvas.focus_set()

    def follow_current(self):
        self.force_live=True;self.follow.set(True);self.live_error='';self.live_ready=False;self.next_live=0;self.signature=None
        if hasattr(self,'archive_controls'):self.update_mode_controls()

    def follow_changed(self):
        self.force_live=True;self.live_error='';self.live_ready=False;self.signature=None
        if hasattr(self,'archive_controls'):self.update_mode_controls()
        if self.follow.get():self.app.go_live();self.next_live=0

    def update_mode_controls(self):
        """Live selection is only target plus server-provided category."""
        if self.follow.get():
            self.archive_controls.pack_forget()
        elif not self.archive_controls.winfo_manager():
            self.archive_controls.pack(fill='x',before=self.category_picker)

    def archive(self,operation='events'):
        self.follow.set(False);self.live_error='';self.signature=None
        self.panel.event_id=None;self.panel.competition_id=None;self.panel.request(operation)

    def choose_day(self):
        try:date.fromisoformat(self.panel.day.get())
        except ValueError:self.status.configure(text='Date must be YYYY-MM-DD');return
        self.archive()

    def choose_event(self,event=None):
        index=self.event_picker.current()
        if not 0<=index<len(self.event_options):return
        chosen=self.event_options[index];self.follow.set(False)
        self.panel.event_id=chosen['id'];self.panel.competition_id=chosen['competition_id'];self.panel.category.set('All categories');self.panel.request('compare')

    def choose_category(self,event=None):
        self.signature=None
        if not (self.follow.get() and self.live_state=='unstarted'):self.panel.request('compare')

    def work(self):
        from .crossmgr_client import Client,Configuration
        from . import storage,passings
        client=None
        while not self.stop.is_set():
            try:generation,config=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            try:
                if client is None or client.config!=config:client=Client(config)
                if self.force_live:client.live_signature=None;self.force_live=False
                result=client.fetch_live()
                if self.stop.is_set():return
                live=result['payload'].get('live',{})
                if live.get('state')=='unstarted':
                    race=result['payload']['roster']['race']
                    categories=[c['name'] for c in race.get('categories',[])]
                    self.results.put(('prestart',(result['day'],live.get('state','unstarted'),race.get('name','Current race'),race.get('total',0),categories),generation))
                    continue
                c=storage.connect(self.app.path)
                try:
                    event=passings.cache_event(c,client.config,result['path'],result['day'],result['payload'])
                    competition=c.execute('SELECT competition_id FROM race_events WHERE id=?',(event,)).fetchone()[0]
                finally:c.close()
                self.results.put(('live',(event,competition,result['day'],result['payload'].get('live',{}).get('state',''),result['payload']['review']['race'].get('name','')),generation))
            except Exception as exc:self.results.put(('error',str(exc),generation))

    def tick(self):
        if self.stop.is_set() or self.app.closing:return
        if self.visible:
            self.ensure_panel();panel=self.panel
            # Video review and race following are independent. Keyboard,
            # pop-out and asynchronous capture opens all enter replay; none
            # should silently disable polling or reset an in-flight refresh.
            while not self.results.empty():
                kind,value,generation=self.results.get();self.live_busy=False
                if generation!=self.generation:continue
                if not self.follow.get():continue
                if kind=='error':self.live_error=value;self.live_ready=False;self.signature=None
                elif kind=='prestart':
                    day,state,name,total,categories=value
                    self.live_error='';self.live_ready=True;self.live_state=state
                    self.prestart_name=name;self.prestart_total=total;self.prestart_categories=categories
                    self.race_name.set(name)
                    panel.day.set(day);panel.event_id=None;panel.competition_id=None;panel.model=None;panel.selected_cell=None
                    if panel.category.get() not in ['All categories']+categories:panel.category.set('All categories')
                    self.signature=None
                else:
                    event,competition,day,state,name=value;self.live_state=state;changed=panel.event_id!=event
                    self.live_error='';self.live_ready=True;panel.day.set(day);panel.event_id=event;panel.competition_id=competition
                    self.race_name.set(name)
                    if changed and not self.prestart_categories:panel.category.set('All categories')
                    self.prestart_categories=[];self.prestart_name='';self.prestart_total=0
                    panel.request('compare');self.signature=None
            if self.follow.get() and not self.live_busy and time.monotonic()>=self.next_live:
                self.live_busy=True;self.next_live=time.monotonic()+5;self.jobs.put_nowait((self.generation,panel.config))
            self.event_options=panel.events
            values=[f"{e['name']} · {e['competition']}" for e in self.event_options]
            if not self.follow.get():
                name=panel.model['event']['name'] if panel.model and panel.model['event']['id']==panel.event_id else ''
                if self.race_name.get()!=name:self.race_name.set(name)
            elif not self.live_ready and self.race_name.get():self.race_name.set('')
            categories=['All categories']+(self.prestart_categories if self.follow.get() and self.live_state=='unstarted' else panel.model['categories'] if panel.model else [])
            dates=[v for v in self.app.date_picker.cget('values') if v not in ('Today','All dates')]
            self.update_mode_controls()
            controls=(self.follow.get(),values,panel.event_id,categories,dates)
            if controls!=getattr(self,'controls_signature',None):
                self.controls_signature=controls
                self.event_picker.configure(values=values,state='disabled' if self.follow.get() else 'readonly')
                current=next((i for i,e in enumerate(self.event_options) if e['id']==panel.event_id),None)
                if current is not None:self.event_picker.current(current)
                self.day_picker.configure(values=dates,state='disabled' if self.follow.get() else 'normal')
                self.category_picker.configure(values=categories)
                self.load_button.configure(state='disabled' if self.follow.get() else 'normal');self.import_button.configure(state='disabled' if self.follow.get() else 'normal')
            self.render()
            message=panel.review_message.get()
            if message!=getattr(self,'review_message',None):
                self.review_message=message;self.detail.configure(text=message[:180])
        self.app.root.after(200,self.tick)

    def render(self):
        panel=self.panel;model=panel.model
        if self.follow.get() and (self.live_error or not self.live_ready):
            self.status.configure(text=(self.live_error+' · Uncheck Current race to browse saved events.') if self.live_error else 'Connecting to current CrossMgr race…')
            if self.signature!='unavailable':self.canvas.delete('all');self.header.delete('all');self.locations={};self.signature='unavailable'
            return
        if self.follow.get() and self.live_state=='unstarted':
            self.status.configure(text=f'Current race (not started) · {self.prestart_name} · {self.prestart_total} registered')
            if self.signature!='unstarted':self.canvas.delete('all');self.header.delete('all');self.locations={};self.signature='unstarted'
            return
        if model and model['event']['id']!=panel.event_id:model=None
        cells=panel.displayed_cells() if model else []
        selected=panel.selected_cell['cell_key'] if panel.selected_cell else None
        signature=(self.follow.get(),self.live_state,panel.event_id,panel.category.get(),[(x['label'],x['start_ns']) for x in model['columns']] if model else [],[(c['cell_key'],c['bib'],c['state'],c['confirmed'],c['column']) for c in cells],selected)
        if signature==self.signature:
            # Keep click targets current even when visual fields need no redraw.
            by_key={c['cell_key']:c for c in cells}
            self.locations={tag:by_key[old['cell_key']] for tag,old in self.locations.items() if old['cell_key'] in by_key}
            return
        drawing_started=time.perf_counter()
        self.signature=signature;self.canvas.delete('all');self.header.delete('all');self.locations={}
        if not model:self.status.configure(text=panel.status.get());self.detail.configure(text='Select a date and event, or follow the current race.');return
        self.status.configure(text=('Current race'+(' (finished)' if self.live_state=='finished' else '')+' · ' if self.follow.get() else 'Archive · ')+model['event']['name'])
        columns=[(i,c) for i,c in enumerate(model['columns']) if i or len(model['columns'])==1]
        from .passings_layout import layout
        table=layout(cells,[i for i,_ in columns])
        width=44;height=25;gutter=27
        for j,(column,info) in enumerate(columns):
            x=gutter+j*width
            self.header.create_rectangle(x,0,x+width,58,fill='#dce3eb',outline='#bbc4ce')
            stamp=header_clock(info['start_ns']-model['event']['start_ns'])
            duration=header_clock(info['start_ns']-model['columns'][max(0,column-1)]['start_ns'])
            self.header.create_text(x+width/2,6,text=str(column) if column else 'Start',anchor='n',font=('Sans',10,'bold'))
            self.header.create_text(x+width/2,24,text=duration+'\n'+stamp,anchor='n',font=('Sans',8,'bold'))
            for row,entry in enumerate(table):
                cell=entry['cells'].get(column)
                if cell is None:continue
                y=row*height;tag='compact:'+cell['cell_key'];self.locations[tag]=cell
                self.canvas.create_rectangle(x,y,x+width,y+height,fill=COLOURS[cell['state']],outline='#0057c2' if cell['cell_key']==selected else '#d3d9df',width=3 if cell['cell_key']==selected else 1,tags=(tag,))
                self.canvas.create_text(x+width/2,y+height/2,text=cell['bib'],font=('Sans',10,'bold' if cell['confirmed'] else 'normal'),fill='#14233a',tags=(tag,))
        count=max(len(table),1)
        for row,entry in enumerate(table):
            if entry['position'] is not None:self.canvas.create_text(13,row*height+height/2,text=str(entry['position']),font=('Sans',9,'bold'),fill='#35465d')
        self.canvas.configure(scrollregion=(0,0,gutter+len(columns)*width,count*height));self.header.configure(scrollregion=(0,0,gutter+len(columns)*width,58));self.header.xview_moveto(self.canvas.xview()[0])
        if selected!=self.last_selected:
            tag='compact:'+str(selected);bounds=self.canvas.bbox(tag)
            if bounds:
                x0,y0,x1,y1=bounds;totalw=gutter+len(columns)*width;totalh=count*height
                for axis,lo,hi,total,size in [('x',x0,x1,totalw,self.canvas.winfo_width()),('y',y0,y1,totalh,self.canvas.winfo_height())]:
                    start=getattr(self.canvas,'canvas'+axis)(0)
                    if lo<start:getattr(self.canvas,axis+'view_moveto')(max(0,lo)/total)
                    elif hi>start+size:getattr(self.canvas,axis+'view_moveto')(max(0,hi-size)/total)
            self.last_selected=selected
        if self.restore_scroll:
            self.canvas.xview_moveto(self.restore_scroll.get('x',0));self.canvas.yview_moveto(self.restore_scroll.get('y',0));self.restore_scroll=None
        if panel.selected_cell:self.detail.configure(text=panel.selected_cell['bib']+' · '+panel.selected_cell['name']+(' · visual candidate; identity unconfirmed' if panel.selected_cell.get('suggested_visual') else ' · no nearby saved capture' if not panel.selected_cell['captures'] else ''))
        else:self.detail.configure(text='Click a bib to review its capture.')
        self.app.performance.observe('compact_passings_draw_ms',(time.perf_counter()-drawing_started)*1000)

    def cell_at(self):return next((self.locations[t] for t in self.canvas.gettags('current') if t in self.locations),None)
    def click(self,event):
        cell=self.cell_at()
        if cell:
            self.panel.select_cell(cell);self.canvas.focus_set();self.signature=None;self.render()
        return 'break'
    def hover(self,event):
        cell=self.cell_at()
        if cell:self.detail.configure(text=f"{cell['bib']} · {cell['name']} · {cell['state']}")
    def close(self):self.stop.set()
