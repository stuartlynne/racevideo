"""Attach to an existing recorder and exercise the real dropdown + Apply path.

Run under Xvfb with a database path. Temporarily changes exposure to Manual,
checks that time editing becomes available, and restores the original mode.
Does not stop the recorder or change the exposure-time value.
"""
import sys
import time
import tkinter as tk

from racevideo import storage
from racevideo.gui import ReviewWindow


root = tk.Tk()
errors = []
root.report_callback_exception = lambda *exc: errors.append(exc)
app = ReviewWindow(root, sys.argv[1])
mode_id, time_id = 0x9A0901, 0x9A0902
original = None


def pump(seconds=.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def choose(value):
    panel = app.camera_panel
    menu = panel.rows[mode_id]['editor']
    index = next(i for i,c in enumerate(panel.rows[mode_id]['control']['choices']) if c['value']==value)
    menu.focus_force()
    root.tk.call('ttk::combobox::Post',str(menu))
    popup = str(root.tk.call('ttk::combobox::PopdownWindow',str(menu)))
    listbox = popup+'.f.l'
    root.tk.call('focus',listbox)
    before = app.last_status['frames']
    pump(1.2)  # Several live polls while focus is inside Tcl's popup.
    assert not errors, errors
    assert app.last_status['frames'] > before
    bbox = root.tk.call(listbox,'bbox',index)
    x,y = int(bbox[0])+5, int(bbox[1])+int(bbox[3])//2
    for event in ('<Motion>','<ButtonPress-1>','<ButtonRelease-1>'):
        root.tk.call('event','generate',listbox,event,'-x',x,'-y',y)
    pump(.4)
    assert menu.current()==index, (menu.current(),index)
    assert mode_id in panel.drafts
    assert 'click Apply' in panel.message.get()
    panel.rows[mode_id]['widgets'][-1].invoke()
    until = time.monotonic()+4
    while mode_id in panel.pending and time.monotonic()<until:
        pump(.1)
    assert mode_id not in panel.pending
    assert 'camera reports' in panel.message.get(), panel.message.get()
    pump(.5)
    assert panel.rows[mode_id]['control']['value']==value


try:
    pump(1)
    app.open_camera()
    pump(.3)
    original = app.camera_panel.rows[mode_id]['control']['value']
    choose(1)
    assert app.camera_panel.rows[time_id]['widgets'][-1].instate(['!disabled'])
    app.camera_panel.close()
    app.open_camera()
    pump(.5)
    assert app.camera_panel.rows[mode_id]['control']['value']==1
    assert app.camera_panel.rows[time_id]['widgets'][-1].instate(['!disabled'])
    choose(original)
    assert not errors, errors
    print('Real dropdown passed: polling survives popup focus, Manual selection + Apply, '
          'exposure-time enabled, close/reopen retains mode, original mode restored; recorder still running')
finally:
    if original is not None:
        with storage.connect(sys.argv[1],readonly=True) as connection:
            status=storage.read_runtime(connection)
        if any(c['id']==mode_id and c['value']!=original for c in status.get('camera_controls',[])):
            storage.request_camera_control(sys.argv[1],status['session'],mode_id,original)
    app.close()
