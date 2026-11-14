"""Physical 1080p exposure workflow from start, edit, close/reopen, stop/start.

Uses a temporary store and restores the original hardware settings. Camera free
required. Run under Xvfb; this exercises actual widgets/driver, not mocked writes.
"""
from pathlib import Path
import tempfile
import time
import tkinter as tk

from racevideo import storage
from racevideo.camera import CameraControls
from racevideo.gui import ReviewWindow
from racevideo.service import recorder_running


with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'workflow.sqlite3'
    connection=storage.connect(path)
    storage.initialize(connection)
    config=dict(device='/dev/video0',width=1920,height=1080,fps=30,trigger='timer',interval=1000)
    storage.publish(connection,dict(state='stopped',configuration=config),None)
    connection.close()
    backend=CameraControls('/dev/video0')
    original_mode=backend.describe(0x9A0901)['value']
    original_time=backend.describe(0x9A0902)['value']
    root=tk.Tk()
    errors=[]
    root.report_callback_exception=lambda *exc:errors.append(exc)
    app=ReviewWindow(root,path)

    def pump(seconds=.3):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            root.update()
            time.sleep(.01)
        assert not errors,errors

    def until(predicate,timeout=8):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:pump(.1)
        assert predicate(),app.last_status.get('state')

    def manual():
        app.camera_panel.manual_button.invoke()
        until(lambda:0x9A0901 not in app.camera_panel.pending)
        until(lambda:app.camera_panel.rows[0x9A0902]['control']['writable'])
        assert backend.describe(0x9A0901)['value']==1

    def number(value):
        row=app.camera_panel.rows[0x9A0902]
        editor,button=row['editor'],row['widgets'][-1]
        editor.focus_force();editor.delete(0,'end');editor.insert(0,str(value))
        pump(.4)
        button.focus_force();pump(.6)  # Old refresh could replace the draft here.
        assert editor.get()==str(value),(editor.get(),value)
        button.invoke()
        until(lambda:0x9A0902 not in app.camera_panel.pending)
        assert backend.describe(0x9A0902)['value']==value,app.camera_panel.message.get()
        pump(.4)

    try:
        pump(.5)
        app.recorder_button.invoke()
        until(lambda:app.last_status.get('state')=='recording' and bool(app.last_status.get('camera_controls')))
        assert app.last_status['width']==1920
        app.open_camera();pump(.4)
        manual()
        number(5)
        app.camera_panel.close();app.open_camera();pump(1)
        assert app.camera_panel.rows[0x9A0902]['control']['writable']
        assert app.camera_panel.rows[0x9A0902]['variable'].get()=='5'
        assert 'MANUAL' in app.camera_panel.exposure_status.cget('text')
        app.recorder_button.invoke()
        until(lambda:app.last_status.get('state')=='stopped')
        assert app.camera_panel.start_button.instate(['!disabled'])
        app.camera_panel.close();app.open_camera();pump(.3)
        app.camera_panel.start_button.invoke()
        until(lambda:app.last_status.get('state')=='recording')
        until(lambda:bool(app.last_status.get('camera_controls')))
        assert app.last_status['width']==1920
        manual();number(original_time)
        print('1080p physical workflow passed: start, manual exposure, type/apply 5 with intervening refresh, '
              'close/reopen retains editable value, stop/start from panel preserves resolution; no Tk errors')
    finally:
        backend.set(0x9A0901,1)
        backend.set(0x9A0902,original_time)
        backend.set(0x9A0901,original_mode)
        backend.close()
        if recorder_running(path):
            storage.command(path,'stop')
            end=time.monotonic()+5
            while recorder_running(path) and time.monotonic()<end:time.sleep(.1)
        app.close()
