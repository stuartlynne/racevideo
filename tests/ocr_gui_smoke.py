"""Real clip GUI test: mouse-select search area, subprocess OCR, source review.

Run under Xvfb; argument is a store containing clip 109. Requires OCR extras.
"""
import sys
import time
import tkinter as tk

from racevideo import storage
from racevideo.gui import ReviewWindow
from racevideo.service import recorder_running


def main():
    c=storage.connect(sys.argv[1]);storage.initialize(c);c.close()
    root=tk.Tk();errors=[]
    root.report_callback_exception=lambda *args:errors.append(args)
    app=ReviewWindow(root,sys.argv[1])
    started_capture=False


    def pump(seconds=.3):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            root.update();time.sleep(.01)
        assert not errors,errors


    try:
        pump(1)
        if '--live' in sys.argv and not recorder_running(sys.argv[1]):
            app.start_recorder();started_capture=True
            deadline=time.monotonic()+8
            while app.last_status.get('state')!='recording' and time.monotonic()<deadline:pump(.1)
            assert app.last_status['state']=='recording'
        capture_before=app.last_status.get('frames',0)
        app.select(109)
        deadline=time.monotonic()+5
        while (app.mode!='replay' or app.selected!=109 or getattr(app,'displayed_ordinal',None) is None) and time.monotonic()<deadline:pump(.1)
        app.ocr_engine.set('Tesseract');app.update_ocr_engine(True)
        app.select_ocr_area()
        left,top,w,h=app.image_bounds()
        for event,x,y in (('<ButtonPress-1>',.15,.4),('<B1-Motion>',.53,.99),('<ButtonRelease-1>',.53,.99)):
            app.viewer.event_generate(event,x=round(left+x*w),y=round(top+y*h))
        pump(.5)
        assert not app.ocr_selecting
        assert abs(app.ocr_area[0]-.15)<.002
        app.ocr_engine.set('Tesseract');app.update_ocr_engine()
        app.read_plates()
        initial_id=(app.ocr_run or {}).get('id')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            pump(.1)
            if app.ocr_run and app.ocr_run['id']!=initial_id and app.ocr_run['state'] in ('complete','error'):break
        assert app.ocr_run and app.ocr_run['state']=='complete',app.ocr_run
        assert any(r['number']=='469' for r in app.ocr_run['observations']),app.ocr_run
        app.show_ocr_results();pump(.2)
        reading=next(r for r in app.ocr_run['observations'] if r['number']=='469')
        app.ocr_tree.selection_set(str(reading['id']))
        app.jump_ocr();pump(.4)
        assert app.ordinal==reading['ordinal']
        if '--live' in sys.argv:
            assert app.last_status['frames']>capture_before
            assert app.last_status['state']=='recording'
        if len(sys.argv)>2:
            from PIL import ImageGrab
            ImageGrab.grab().save(sys.argv[2])
        print('OCR GUI passed: mouse area selection, background worker, progress/results, 469 read, source-frame jump; no Tk errors')
    finally:
        if started_capture:
            storage.command(sys.argv[1],'stop')
            deadline=time.monotonic()+5
            while app.last_status.get('state')!='stopped' and time.monotonic()<deadline:pump(.1)
        app.close()


if __name__ == "__main__":
    main()
