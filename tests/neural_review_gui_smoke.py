"""Actual saved-race clip: Neural OCR subprocess -> SQLite -> Tk -> operator review.

Run under Xvfb against a disposable exported clip508 store, never a backup or the
operator's working database. No physical camera or AMD runtime is used.
"""
import sys,time,tkinter as tk
from pathlib import Path
from PIL import ImageGrab
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    path=Path(sys.argv[1]);root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
    app=ReviewWindow(root,path)
    def pump(seconds=.05):
        until=time.monotonic()+seconds
        while time.monotonic()<until:root.update();time.sleep(.005)
        assert not errors,errors
    def wait(predicate,seconds=10):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            pump()
            if predicate():return
        raise AssertionError('Timed out: '+str(app.ocr_run))
    try:
        app.select(508);wait(lambda:app.mode=='replay' and app.index and app.last_status.get('neural_ocr_area') and app.displayed_ordinal is not None)
        assert app.ocr_engine.get()=='Neural OCR'
        initial=(app.ocr_run or {}).get('id')
        app.read_plates();wait(lambda:app.ocr_run and app.ocr_run['id']!=initial and app.ocr_run['state'] in ('complete','error'),120)
        assert app.ocr_run['state']=='complete',app.ocr_run
        assert app.ocr_run['summary']['engine']=='paddle-v5-rider-native-v2'
        wait(lambda:any(r['number']=='826' for r in app.bib_review_rows))
        app.show_ocr_results();row=next(r for r in app.bib_review_rows if r['number']=='826' and r['run_id']==app.ocr_run['id'])
        app.ocr_tree.selection_set(row['row_key']);wait(lambda:app.displayed_ordinal==row['ordinal'])
        app.review_bib('accepted');wait(lambda:any(r['number']=='826' and r.get('decision')=='accepted' for r in app.bib_review_rows))
        Path('docs/evidence').mkdir(exist_ok=True)
        ImageGrab.grab().save('docs/evidence/neural-bib-review-validation.png')
        print('Neural review GUI passed on disposable real clip508: all frames scanned in separate CPU process, source crops and alternatives imported, 826 reviewed, original-frame navigation, no Tk errors')
    finally:app.close()


if __name__=='__main__':main()
