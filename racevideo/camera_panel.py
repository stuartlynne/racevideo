"""A capability-driven control panel; all writes go to the recorder queue."""
import tkinter as tk
import time
from tkinter import ttk

from .camera import format_value


# Known settings worth calling out even when the camera does not expose them.
COMMON = {0x9A090C: "Autofocus", 0x9A090A: "Manual focus", 0x9A0901: "Exposure mode",
          0x9A0902: "Exposure time", 0x980900: "Brightness", 0x980901: "Contrast",
          0x98091B: "Sharpness", 0x980913: "Gain", 0x980902: "Saturation",
          0x98090C: "Automatic white balance", 0x98091A: "White balance temperature"}
ORDER = {control_id: i for i, control_id in enumerate(COMMON)}


class CameraPanel:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("RaceVideo — Camera controls")
        self.window.geometry("760x720")
        self.window.minsize(660, 400)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.rows = {}
        self.pending = set()
        self.drafts = set()
        self.signature = None
        self.capture_modes=[]
        self.mode_pending=False
        self.mode_draft=False
        self.was_online = None
        self.last_control_error=None
        self.message = tk.StringVar(value="Reading available controls…")
        header = ttk.Frame(self.window, padding=12)
        header.pack(fill="x")
        ttk.Label(header, text="Camera controls", font=("Sans", 14, "bold")).pack(anchor="w")
        ttk.Label(header, text="Switch autofocus off for manual focus; select Manual Mode for shutter control.\n"
                              "Menus/numbers use Apply; sliders apply on release. Actual values appear below.").pack(anchor="w", pady=6)
        self.device = ttk.Label(header, text="")
        self.device.pack(anchor="w")
        self.exposure_status = ttk.Label(header, text="", font=("Sans", 11, "bold"))
        self.exposure_status.pack(anchor="w", pady=(6, 0))
        actions = ttk.Frame(header)
        actions.pack(fill='x', pady=(6, 0))
        self.manual_button = ttk.Button(actions, text='Enable manual exposure', command=self.enable_manual)
        self.manual_button.pack(side='left')
        self.start_button = ttk.Button(actions, text='Start recorder', command=app.start_recorder)
        self.start_button.pack(side='left', padx=8)
        self.release_agent_button=ttk.Button(actions,text='Release agent control',
            command=lambda:getattr(app,'remote').revoke())
        self.release_agent_button.pack(side='left')
        from .service import configuration
        config=configuration(app.last_status)
        mode_frame=ttk.LabelFrame(header,text='Capture mode · change while recorder is stopped',padding=6)
        mode_frame.pack(fill='x',pady=(8,0))
        self.mode_device=tk.StringVar(value=config.get('device','/dev/video0'))
        self.device_picker=ttk.Combobox(mode_frame,textvariable=self.mode_device,width=45)
        self.device_picker.grid(row=0,column=0,sticky='ew')
        self.device_picker.bind('<<ComboboxSelected>>',lambda e:(self.note_mode_draft(),self.refresh_modes()))
        self.device_picker.bind('<KeyRelease>',lambda e:self.note_mode_draft())
        ttk.Button(mode_frame,text='Refresh modes',command=self.refresh_modes).grid(row=0,column=1,padx=5)
        self.mode_choice=tk.StringVar()
        self.mode_picker=ttk.Combobox(mode_frame,textvariable=self.mode_choice,state='readonly')
        self.mode_picker.grid(row=1,column=0,sticky='ew',pady=5)
        self.mode_picker.bind('<<ComboboxSelected>>',lambda e:self.note_mode_draft())
        self.mode_apply=ttk.Button(mode_frame,text='Use mode',command=self.apply_mode)
        self.mode_apply.grid(row=1,column=1,padx=5)
        mode_frame.columnconfigure(0,weight=1)
        self.mode_status=ttk.Label(mode_frame,text='',wraplength=690)
        self.mode_status.grid(row=2,column=0,columnspan=2,sticky='w')
        self.mode_hint=ttk.Label(mode_frame,text='Only advertised MJPEG modes are listed. Stop recorder → Use mode → Start recorder.\nCheck manual exposure/gain after restarting; a mode change may reset camera controls.',wraplength=690)
        self.mode_hint.grid(row=3,column=0,columnspan=2,sticky='w',pady=(4,0))
        canvas = tk.Canvas(self.window, background="#202630", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.window, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        self.body = ttk.Frame(canvas, padding=12)
        item = canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        canvas.bind("<Button-4>", lambda _: canvas.yview_scroll(-2, "units"))
        canvas.bind("<Button-5>", lambda _: canvas.yview_scroll(2, "units"))
        def wheel(event):
            amount = -2 if getattr(event, "num", None) == 4 else 2
            if getattr(event, "delta", 0):
                amount = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            canvas.yview_scroll(amount, "units")
            return "break"
        for event in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.window.bind(event, wheel)
        footer = ttk.Frame(self.window, padding=10)
        footer.pack(fill="x", side="bottom")
        ttk.Label(footer, textvariable=self.message, wraplength=700).pack(anchor="w")
        ttk.Label(footer, text="These change future camera images. Saved clips remain original.",
                  foreground="#9aabbf").pack(anchor="w", pady=(6, 0))
        self.update(app.last_status)
        self.refresh_modes()

    def refresh_modes(self):
        self.capture_modes=[];self.mode_choice.set('Reading camera modes…')
        self.mode_picker.configure(values=())
        self.app.reader.jobs.put(('capture_modes',self.mode_device.get().strip()))

    def note_mode_draft(self):
        self.mode_draft=True
        self.message.set('Capture selection changed — stop recorder and click Use mode to save it.')

    def receive_modes(self,result):
        if result['device']!=self.mode_device.get().strip():return
        from .capture_modes import mode_label
        from .service import configuration
        self.loaded_mode_device=result['device'];self.capture_modes=result['modes']
        devices=[alias for d in result['devices'] if d.get('capture') for alias in (d.get('aliases') or [d['device']])]
        self.device_picker.configure(values=devices)
        labels=[mode_label(m) for m in self.capture_modes];self.mode_picker.configure(values=labels)
        config=configuration(self.app.last_status)
        selected=next((i for i,m in enumerate(self.capture_modes) if m['width']==config.get('width',1280) and m['height']==config.get('height',720) and abs(m['fps']-config.get('fps',30))<.1),0)
        if labels:self.mode_picker.current(selected)
        else:self.mode_choice.set('No discrete MJPEG modes found')
        if result.get('error'):self.message.set('Cannot read camera modes: '+result['error'])

    def apply_mode(self):
        if self.mode_pending:return
        remote=getattr(self.app,'remote',None)
        if remote and remote.leases:
            self.message.set('Release agent control before changing capture mode.');return
        index=self.mode_picker.current()
        if index<0 or index>=len(self.capture_modes) or self.mode_device.get().strip()!=getattr(self,'loaded_mode_device',None):
            self.message.set('Refresh modes for this device and select an advertised mode.');return
        if self.drafts or self.pending:
            self.message.set('Apply camera-control edits while recording, or close/reopen Camera to discard them. Then stop and select the capture mode.');return
        self.mode_pending=True
        profile=dict(self.capture_modes[index],device=self.loaded_mode_device)
        self.app.reader.jobs.put(('capture_profile',profile))
        self.message.set('Saving mode for next recorder start…')

    def profile_saved(self,result):
        self.mode_pending=False
        if result['error']:self.message.set(result['error']);return
        self.mode_draft=False
        self.app.last_status['capture_configuration']=result['profile']
        self.message.set('Capture mode saved. Start recorder, then check the delivered dimensions and frame rate.')

    def close(self):
        self.app.camera_panel = None
        self.window.destroy()

    def build(self, controls):
        for widget in self.body.winfo_children():
            widget.destroy()
        self.rows = {}
        available = {c["id"]: c for c in controls}
        for control in sorted(controls, key=lambda c: (ORDER.get(c["id"], 100), c["name"])):
            cid = control["id"]
            row = ttk.Frame(self.body, padding=(0, 5))
            row.pack(fill="x")
            ttk.Label(row, text=control["name"], width=29).grid(row=0, column=0, sticky="w")
            row.columnconfigure(1, weight=1)
            variable = tk.StringVar()
            widgets = []
            choices = [f"{c['label']} ({c['value']})" for c in control["choices"]]
            if control["type"] == 2:
                variable = tk.IntVar()
                editor = ttk.Checkbutton(row, variable=variable, text="Enabled",
                                         command=lambda c=cid: self.apply(c))
                editor.grid(row=0, column=1, sticky="w")
                widgets.append(editor)
            elif control["type"] in (3, 9):
                editor = ttk.Combobox(row, textvariable=variable, values=choices, state="readonly", width=30)
                editor.grid(row=0, column=1, sticky="ew")
                editor.bind("<<ComboboxSelected>>", lambda e, c=cid: self.menu_changed(c))
                button = ttk.Button(row, text="Apply", command=lambda c=cid: self.apply(c))
                button.grid(row=0, column=3, padx=(6, 0))
                widgets.extend((editor, button))
            elif control["type"] == 1:
                slider = ttk.Scale(row, from_=control["minimum"], to=control["maximum"])
                slider.grid(row=0, column=1, sticky="ew", padx=(0, 8))
                editor = ttk.Spinbox(row, from_=control["minimum"], to=control["maximum"],
                                     increment=control["step"], textvariable=variable, width=7)
                editor.grid(row=0, column=2)
                editor.bind("<Return>", lambda e, c=cid: self.apply(c))
                slider.configure(command=lambda value, c=cid: self.slide(c, value))
                slider.bind("<ButtonRelease-1>", lambda e, c=cid: self.apply(c))
                slider.bind("<KeyRelease>", lambda e, c=cid: self.apply(c))
                button = ttk.Button(row, text="Apply", command=lambda c=cid: self.apply(c))
                button.grid(row=0, column=3, padx=(6, 0))
                widgets.extend((slider, editor, button))
            elif control["type"] == 4:
                editor = ttk.Button(row, text="Run", command=lambda c=cid: self.apply(c))
                editor.grid(row=0, column=1, sticky="w")
                widgets.append(editor)
            else:
                editor = ttk.Label(row, text="Unsupported control type")
                editor.grid(row=0, column=1, sticky="w")
            detail = ttk.Label(row, text="", foreground="#9aabbf")
            detail.grid(row=1, column=1, columnspan=3, sticky="w")
            self.rows[cid] = dict(control=control, variable=variable, editor=editor,
                                  widgets=widgets, detail=detail,
                                  slider=slider if control["type"] == 1 else None, syncing=False)
            if control['type'] == 1:
                variable.trace_add('write', lambda *_, c=cid: self.number_changed(c))
        missing = [name for cid, name in COMMON.items() if cid not in available]
        if missing:
            ttk.Label(self.body, text="Not exposed by this camera: " + ", ".join(missing),
                      foreground="#9aabbf", wraplength=650).pack(anchor="w", pady=12)

    def slide(self, cid, value):
        row = self.rows.get(cid)
        if row:
            c = row["control"]
            value = c["minimum"] + round((float(value) - c["minimum"]) / c["step"]) * c["step"]
            value = min(c["maximum"], max(c["minimum"], value))
            row["variable"].set(str(value))

    def menu_changed(self, cid):
        self.drafts.add(cid)
        self.message.set(f"{self.rows[cid]['control']['name']}: selection changed — click Apply.")

    def number_changed(self, cid):
        row = self.rows.get(cid)
        if row and not row['syncing']:
            self.drafts.add(cid)

    def enable_manual(self):
        row = self.rows.get(0x9A0901)
        if row:
            index = next((i for i, c in enumerate(row['control']['choices']) if c['value'] == 1), None)
            if index is not None:
                row['editor'].current(index)
                self.menu_changed(0x9A0901)
                self.apply(0x9A0901)

    def apply(self, cid):
        row = self.rows[cid]
        c = row["control"]
        try:
            if c["type"] in (3, 9):
                value = c["choices"][row["editor"].current()]["value"]
            elif c["type"] == 4:
                value = 0
            else:
                value = int(row["variable"].get())
        except (ValueError, tk.TclError, IndexError):
            self.message.set("Enter a valid camera value before applying.")
            return
        if c["type"] in (1, 2):
            if not c["minimum"] <= value <= c["maximum"]:
                self.message.set(f"{c['name']}: value outside camera's supported range.")
                return
            if (value - c["minimum"]) % c["step"]:
                self.message.set(f"{c['name']}: choose a value in steps of {c['step']} from {c['minimum']}.")
                return
        status = self.app.last_status
        remote=getattr(self.app,'remote',None)
        if remote and remote.reserved(cid):
            self.message.set('Agent is adjusting this control; use Release agent control to take over.')
            return
        if (status.get("state") != "recording" or time.time() - status.get("heartbeat", 0) > 3
                or status.get("camera_controls_error") or not c["writable"]):
            self.message.set("This control is currently unavailable.")
            return
        self.pending.add(cid)
        self.message.set(f"Applying {c['name']}…")
        self.app.reader.jobs.put(("camera", (status["session"], cid, value)))

    def result(self, result):
        self.pending.discard(result["control_id"])
        row = self.rows.get(result["control_id"])
        name = row["control"]["name"] if row else "Camera control"
        if result["error"]:
            self.message.set(f"{name}: {result['error']}")
        else:
            self.drafts.discard(result["control_id"])
            actual = format_value(result["control_id"], result["actual"])
            self.message.set(f"{name}: camera reports {actual} (requested {result['value']}).")

    def update(self, status):
        from .capture_modes import assessment
        config=status.get('configuration',{})
        requested=f"{config.get('width','?')}×{config.get('height','?')} @ {config.get('fps',status.get('requested_fps','?'))} fps"
        measured=status.get('capture_fps');negotiated=status.get('negotiated_fps')
        actual=f"{status.get('width','?')}×{status.get('height','?')} @ {negotiated:g} fps" if negotiated is not None else 'waiting'
        self.mode_status.configure(text=f"Requested: {requested} · Driver: {actual}\nMeasured: {measured:.1f} fps · {assessment(status)}" if measured is not None else f"Requested: {requested} · Driver: {actual}\n{assessment(status)}")
        running=status.get('state') in ('recording','starting') and time.time()-status.get('heartbeat',0)<3
        if not running:
            from .service import configuration
            next_config=configuration(status)
            self.mode_status.configure(text=f"Next start: {next_config.get('width',1280)}×{next_config.get('height',720)} @ {next_config.get('fps',30):g} fps\nRecorder stopped. Use mode saves your selection; Start recorder begins capture.")
        self.mode_apply.state(['disabled'] if running or self.mode_pending or not self.capture_modes else ['!disabled'])
        self.device_picker.state(['disabled'] if running else ['!disabled'])
        self.mode_picker.state(['disabled'] if running else ['!disabled'])
        controls = status.get("camera_controls", [])
        signature = [(c["id"], c["type"], c["minimum"], c["maximum"], c["step"],
                      tuple((v["value"], v["label"]) for v in c["choices"])) for c in controls]
        if signature != self.signature:
            self.build(controls)
            self.signature = signature
        self.device.configure(text=f"{status.get('device', '')} · {len(controls)} controls discovered · {status.get('state', 'waiting')}")
        online = (status.get("state") == "recording" and not status.get("camera_controls_error")
                  and time.time() - status.get("heartbeat", 0) < 3)
        modes = next((c for c in controls if c['id'] == 0x9A0901), None)
        exposure = next((c for c in controls if c['id'] == 0x9A0902), None)
        manual = modes is not None and modes['value'] in (1, 2)
        self.exposure_status.configure(
            text=('Recorder stopped/offline — start it to adjust settings.' if not online else
                  'Camera reports MANUAL exposure — time control available.' if manual and exposure and exposure['writable'] else
                  'Camera reports MANUAL exposure, but driver marks time unavailable.' if manual else
                  'Camera reports AUTOMATIC exposure — enable manual exposure below.' if modes else
                  'Exposure mode is not reported by this camera.'),
            foreground='#6be4ab' if online and manual and exposure and exposure['writable'] else '#ffcd70')
        can_manual = bool(online and modes and modes['writable'] and
                          any(c['value'] == 1 for c in modes['choices']))
        self.manual_button.state(['!disabled'] if can_manual else ['disabled'])
        self.start_button.state(['disabled'] if online else ['!disabled'])
        remote=getattr(self.app,'remote',None)
        self.release_agent_button.state(['!disabled'] if remote and remote.leases else ['disabled'])
        if status.get("camera_controls_error") and status['camera_controls_error']!=self.last_control_error:
            self.message.set("Camera controls unavailable: " + status["camera_controls_error"])
        elif not online and online != self.was_online:
            self.message.set("Recorder is stopped or offline; start capture to adjust camera settings.")
        elif online != self.was_online:
            self.message.set("Ready — changes apply to the live camera." if controls else "No adjustable controls reported by this camera.")
        self.was_online = online
        self.last_control_error=status.get('camera_controls_error')
        # Tk's combobox popup is created in Tcl, not in tkinter's widget tree.
        # focus_get() tries to wrap it as a Python widget and raises KeyError
        # while the menu is open. Compare raw Tcl widget paths instead.
        focused = str(self.window.tk.call("focus"))
        for c in controls:
            row = self.rows[c["id"]]
            row["control"] = c
            reserved=bool(remote and remote.reserved(c['id']))
            for widget in row["widgets"]:
                widget.state(["!disabled"] if online and c["writable"] and not reserved else ["disabled"])
            detail = (c["disabled_reason"] if not c["writable"] else
                      f"{c['minimum']}…{c['maximum']} · step {c['step']} · default {c['default']}")
            if c["type"] != 4:
                detail += " · actual " + c["display_value"]
            if not online:
                detail = 'Recorder stopped/offline · ' + detail
            elif remote and remote.reserved(c['id']):
                detail='Agent adjusting settings · '+detail
            row["detail"].configure(text=detail)
            editing_number = not reserved and c["type"] == 1 and focused in (str(row["editor"]), str(row["slider"]))
            editing_menu = not reserved and c["type"] in (3, 9) and (
                focused == str(row["editor"]) or focused.startswith(str(row["editor"]) + "."))
            if c["id"] in self.pending or c["id"] in self.drafts or editing_number or editing_menu:
                continue
            if c["type"] in (3, 9):
                match = next((i for i, item in enumerate(c["choices"]) if item["value"] == c["value"]), -1)
                if match >= 0:
                    row["editor"].current(match)
            elif c["type"] in (1, 2) and c["value"] is not None:
                row['syncing'] = True
                try:
                    row["variable"].set(c["value"])
                    if row["slider"]:
                        row["slider"].set(c["value"])
                finally:
                    row['syncing'] = False
