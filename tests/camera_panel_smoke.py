"""Test unavailable controls and changing control flags, without hardware."""
import copy
import queue
from types import SimpleNamespace
import time
import tkinter as tk
from unittest.mock import patch

from racevideo.camera import CameraControls
from racevideo.camera_panel import CameraPanel
from test_camera import Driver


root=tk.Tk()
try:
    backend=CameraControls.__new__(CameraControls)
    backend.fd=-1
    with patch('racevideo.camera.fcntl.ioctl',Driver().ioctl):
        controls=backend.enumerate()
    status=dict(state='recording', heartbeat=time.time(), session='test', device='test-camera', camera_controls=controls)
    app=SimpleNamespace(root=root,last_status=status,reader=SimpleNamespace(jobs=queue.SimpleQueue()),
                        camera_panel=None,start_recorder=lambda:None)
    panel=CameraPanel(app)
    assert app.reader.jobs.get_nowait()==('capture_modes','test-camera')
    panel.receive_modes(dict(device='test-camera',modes=[dict(width=3840,height=2160,fps=60,format='MJPEG'),dict(width=3840,height=2160,fps=30,format='MJPEG')],devices=[],error=None))
    root.update()
    assert panel.mode_apply.instate(['disabled'])  # Cannot change a recording camera.
    assert len(panel.rows)==3
    assert panel.rows[30]['editor'].instate(['disabled'])
    labels=[w.cget('text') for w in panel.body.winfo_children() if w.winfo_class()=='TLabel']
    assert any('Not exposed' in label for label in labels)
    # Real Tcl dropdown focus previously crashed focus_get(), killing GUI polls.
    menu=panel.rows[20]['editor']
    menu.focus_force()
    root.tk.call('ttk::combobox::Post',str(menu))
    root.update()
    popup=str(root.tk.call('ttk::combobox::PopdownWindow',str(menu)))
    root.tk.call('focus',popup+'.f.l')
    for _ in range(5):
        panel.update(status)
        root.update()
    root.tk.call('ttk::combobox::Unpost',str(menu))
    menu.current(0)
    menu.event_generate('<<ComboboxSelected>>')
    root.update()
    panel.update(status)  # A status refresh must not overwrite an unapplied choice.
    assert menu.current()==0
    assert app.reader.jobs.empty()
    assert 'click Apply' in panel.message.get()
    panel.rows[20]['widgets'][-1].invoke()
    assert app.reader.jobs.get_nowait()==('camera',('test',20,1))
    panel.result(dict(control_id=20,actual=1,value=1,error=None))
    panel.rows[10]['variable'].set(40)
    panel.apply(10)
    assert app.reader.jobs.get_nowait()==('camera',('test',10,40))
    panel.result(dict(control_id=10,actual=40,value=40,error=None))
    assert 'camera reports 40' in panel.message.get()
    changed=copy.deepcopy(status)
    changed['camera_controls'][2].update(writable=True,disabled_reason='')
    panel.update(changed)
    assert panel.rows[30]['editor'].instate(['!disabled'])
    panel.slide(30,'67')
    assert panel.rows[30]['variable'].get()=='68'  # Valid 17-step focus position.
    # Draft numeric entry must survive focus moving to Apply before its release.
    row=panel.rows[10]
    row['variable'].set(45)
    row['widgets'][-1].focus_force()
    panel.update(status)
    assert row['variable'].get()=='45'
    changed['camera_controls_error']='Device disconnected'
    panel.update(changed)
    assert panel.rows[10]['editor'].instate(['disabled'])
    assert 'Device disconnected' in panel.message.get()
    stopped=dict(status,state='stopped');app.last_status=stopped
    panel.drafts.clear();panel.pending.clear();panel.update(stopped)
    panel.mode_picker.current(0);panel.note_mode_draft();assert panel.mode_draft
    panel.apply_mode()
    name,profile=app.reader.jobs.get_nowait()
    assert name=='capture_profile' and profile['fps']==60 and profile['width']==3840
    panel.profile_saved(dict(profile={k:profile[k] for k in ('device','width','height','fps')},error=None))
    panel.update(app.last_status)
    assert not panel.mode_draft and not panel.mode_pending
    assert '3840×2160 @ 60 fps' in panel.mode_status.cget('text')
    assert 'Capture mode saved' in panel.message.get()
    print('Camera panel passed: open Tcl dropdown focus, unapplied menu survives refresh, explicit Apply, '
          'missing controls, inactive/active flags, readback, step rounding, disconnect')
finally:
    root.destroy()
