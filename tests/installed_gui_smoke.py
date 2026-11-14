"""Exercise the installed store/production bridge on an isolated X display.

Usage: xvfb-run -a .venv/bin/python tests/installed_gui_smoke.py /path/to/store
Does not open a camera or start recording.
"""
import sys
import time
import tkinter as tk
from racevideo.gui import ReviewWindow


def main():
    root=tk.Tk();errors=[]
    root.report_callback_exception=lambda *args:errors.append(args)
    app=ReviewWindow(root,sys.argv[1])
    try:
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            root.update();time.sleep(.01)
            if app.remote.connected and app.performance_snapshot.get('uptime_seconds',0)>1.5:break
        assert not errors,errors
        assert app.remote.connected and app.preview.process.is_alive()
        assert app.performance_snapshot['counters']['preview_worker_alive']
        assert app.review_day.get()=='Today'
        print('Installed GUI/store, healthy preview worker and production MCP bridge passed; no camera opened')
    finally:app.close()


if __name__=='__main__':main()
