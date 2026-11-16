"""Follow newly available passing clips only while the operator is idle."""
import time


class IdlePassings:
    delay = 15.0

    def __init__(self, app, clock=time.monotonic):
        self.app=app;self.clock=clock;self.last_activity=clock()
        self.target=None;self.displayed_since=None
        self.activity_serial=0;self.pending_confirmation=None;self.confirmed_last=False

    def activity(self, event=None):
        self.last_activity=self.clock()
        # Releasing the confirming key/button is not a new operator action.
        if str(getattr(event,'type','')) not in ('3','5'):
            self.activity_serial+=1;self.confirmed_last=False

    def arm(self, event_id, clip_id):
        self.target=(event_id,clip_id);self.displayed_since=None
        self.confirmed_last=False;self.pending_confirmation=None

    def cancel(self):
        self.target=None;self.displayed_since=None
        self.confirmed_last=False;self.pending_confirmation=None

    def prepare_confirmation(self, panel, action):
        self.pending_confirmation=None;self.confirmed_last=False
        current=panel.selected_cell
        if action!='confirmed' or not current or self.target!=(panel.event_id,self.app.selected):return
        cells=[c for c in panel.displayed_cells() if c['state']!='ignored']
        if any(c['at_ns']>current['at_ns'] for c in cells):return
        if any(c['captures'] and c['captures'][0]['clip_id']>self.app.selected for c in cells):return
        self.pending_confirmation=(self.target,current['cell_key'],self.activity_serial)

    def confirmation_result(self, panel, result, error=False):
        pending=self.pending_confirmation;self.pending_confirmation=None;self.confirmed_last=False
        if not pending or error:return
        review=(result or {}).get('review') or {}
        current=panel.selected_cell
        self.confirmed_last=bool(pending[0]==self.target and pending[2]==self.activity_serial and
            current and current['cell_key']==pending[1] and
            review.get('action')=='confirmed' and not result.get('action') and
            (review.get('event_id'),review.get('clip_id'))==self.target)

    def tick(self, panel):
        app=self.app
        if self.target is None:return
        event,clip=self.target
        owner=getattr(panel,'compact_owner',None)
        if event!=panel.event_id or (owner and not owner.follow.get()):return
        if app.mode!='replay' or app.selected!=clip or app.displayed_ordinal is None:return
        now=self.clock()
        if self.displayed_since is None:self.displayed_since=now
        if not self.confirmed_last and now-max(self.last_activity,self.displayed_since)<self.delay:return
        # A quiet keyboard does not mean an unfinished edit is safe to abandon.
        camera=app.camera_panel;motion=getattr(app,'motion_options',None)
        if (panel.busy or panel.review_pending or panel.add_target or app.playing or
                app.pending_review or app.editing_text() or app.root.grab_current() or
                app.bike_mark or app.ocr_selecting or app.roi_drag or
                (camera and (camera.drafts or camera.pending or getattr(camera,'mode_draft',False) or getattr(camera,'mode_pending',False))) or
                (motion and (motion.dirty or motion.drawing))):return
        current=panel.selected_cell
        if not current:return
        expected=current['bib'] if current['bib'].isdigit() else ''
        if panel.review_note.get().strip() or panel.review_number.get().strip()!=expected:return
        candidates=[cell for cell in panel.displayed_cells()
                    if cell['state']!='ignored' and cell['captures'] and
                    cell['at_ns']>=current['at_ns'] and cell['captures'][0]['clip_id']>clip]
        if not candidates:return
        newest=max(candidates,key=lambda c:(c['captures'][0]['clip_id'],c['at_ns']))
        panel.select_cell(newest);panel.reveal_selection()

    def install(self):
        # Run before widget shortcuts, including handlers returning "break".
        root=self.app.root;tag='RaceVideoIdleActivity'
        def attach(widget):
            if not hasattr(widget,'bindtags'):return  # Tk-owned popup internals.
            tags=widget.bindtags()
            if tag not in tags:widget.bindtags((tag,*tags))
            for child in widget.winfo_children():attach(child)
        for sequence in ('<KeyPress>','<KeyRelease>','<ButtonPress>','<ButtonRelease>','<MouseWheel>','<Motion>'):
            root.bind_class(tag,sequence,self.activity)
        root.bind_all('<Map>',lambda event:attach(event.widget),add='+')
        attach(root)
