"""Physical camera + actual Tk controls + recorder queue/readback integration.

Uses its own temporary store, restores touched settings, and needs /dev/video0.
Run with xvfb-run -a .venv/bin/python tests/camera_live_smoke.py [screenshot.png]
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk

from racevideo import storage
from racevideo.camera import CameraControls
from racevideo.gui import ReviewWindow


with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / "controls.sqlite3"
    connection = storage.connect(path)
    storage.initialize(connection)
    connection.close()
    backend = CameraControls('/dev/video0')
    initial = {c['id']: c for c in backend.enumerate()}
    recorder = subprocess.Popen([sys.executable, '-m', 'racevideo', 'record', '--db', str(path),
                                 '--trigger', 'timer', '--interval', '1000', '--run-seconds', '60'])
    root = tk.Tk()
    app = ReviewWindow(root, path)

    def pump(seconds=.3):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            root.update()
            time.sleep(.01)

    def apply(cid, value):
        row = app.camera_panel.rows[cid]
        if row['control']['type'] == 3:
            index = next(i for i,c in enumerate(row['control']['choices']) if c['value']==value)
            row['editor'].current(index)
        else:
            row['variable'].set(value)
        app.camera_panel.apply(cid)
        deadline = time.monotonic() + 4
        while cid in app.camera_panel.pending and time.monotonic() < deadline:
            pump(.1)
        assert cid not in app.camera_panel.pending
        assert 'camera reports' in app.camera_panel.message.get(), app.camera_panel.message.get()
        assert backend.describe(cid)['value'] == value
        pump(.5)

    try:
        pump(2)
        app.open_camera()
        pump(.3)
        assert app.camera_panel.rows
        contrast = 0x980901
        focus_auto, focus = 0x9A090C, 0x9A090A
        exposure_auto, exposure = 0x9A0901, 0x9A0902
        old = initial[contrast]['value']
        apply(contrast, old+1 if old<initial[contrast]['maximum'] else old-1)
        apply(contrast, old)
        apply(focus_auto, 0)
        assert app.camera_panel.rows[focus]['control']['writable']
        apply(focus, initial[focus]['value'])
        apply(focus_auto, initial[focus_auto]['value'])
        apply(exposure_auto, 1)
        assert app.camera_panel.rows[exposure]['control']['writable']
        apply(exposure, 5)  # 0.5ms / 1/2000s; briefly exercised, then restored.
        apply(exposure, initial[exposure]['value'])
        apply(exposure_auto, initial[exposure_auto]['value'])
        assert not app.camera_panel.rows[exposure]['control']['writable']
        # Invalid requests must report an error without stopping capture.
        row = app.camera_panel.rows[contrast]
        row['variable'].set(initial[contrast]['maximum']+1)
        app.camera_panel.apply(contrast)
        pump(1)
        assert 'outside' in app.camera_panel.message.get(), app.camera_panel.message.get()
        assert app.last_status['state'] == 'recording'
        if len(sys.argv)>1:
            from PIL import ImageGrab
            ImageGrab.grab().save(sys.argv[1])
        print('Camera UI passed: discovery, contrast write/readback, autofocus/manual focus, '
              'manual 1/2000s exposure, automatic-mode dependencies, rejected invalid value, '
              'capture continues; settings restored')
    finally:
        # Restore in dependency order even if an assertion fails.
        backend.set(0x9A090C, 0)
        backend.set(0x9A090A, initial[0x9A090A]['value'])
        backend.set(0x9A090C, initial[0x9A090C]['value'])
        backend.set(0x9A0901, 1)
        backend.set(0x9A0902, initial[0x9A0902]['value'])
        backend.set(0x9A0901, initial[0x9A0901]['value'])
        backend.set(0x980901, initial[0x980901]['value'])
        backend.close()
        app.close()
        if recorder.poll() is None:
            storage.command(path, 'stop')
            try: recorder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.terminate()
                recorder.wait(timeout=5)
