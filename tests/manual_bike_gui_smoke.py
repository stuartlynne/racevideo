"""Two manual identities on one frame retain distinct bike boxes and order."""
from pathlib import Path
import json
import sys
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).parent))
import test_bib_review as fixtures
from racevideo.gui import ReviewWindow


def main():
    f=fixtures.BibReviewTests();f.setUp();app=None
    try:
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
        app=ReviewWindow(root,f.path);app.review_day.set('All dates');app.apply_browser()
        def wait(predicate):
            until=time.monotonic()+6
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError('Timed out: '+app.review_message.get())
        wait(lambda:bool(app.clips));app.select(f.clip)
        wait(lambda:getattr(app,'displayed_ordinal',None) is not None)
        app.show_ocr_results()
        def mark(box):
            app.begin_bike_mark();left,top,w,h=app.image_bounds();x0,y0,x1,y1=box
            app.viewer.event_generate('<ButtonPress-1>',x=int(left+x0*w),y=int(top+y0*h))
            app.viewer.event_generate('<B1-Motion>',x=int(left+x1*w),y=int(top+y1*h))
            app.viewer.event_generate('<ButtonRelease-1>',x=int(left+x1*w),y=int(top+y1*h))
            assert app.bike_mark and not app.bike_marking
        mark((.1,.2,.4,.8));assert app.bike_order.get()=='1'
        app.review_number.set('4');app.add_manual_bib();wait(lambda:len(app.bib_review_rows)==1 and app.pending_bike_mark_save is None)
        mark((.55,.2,.9,.8));assert app.bike_order.get()=='2'
        app.review_number.set('1');app.add_manual_bib();wait(lambda:len(app.bib_review_rows)==2 and app.pending_bike_mark_save is None)
        rows=app.bib_review_rows
        assert [(r['number'],r['passing_order']) for r in rows]==[('4',1),('1',2)]
        assert rows[0]['ordinal']==rows[1]['ordinal']
        assert rows[0]['bike_box']!=rows[1]['bike_box']
        app.ocr_tree.selection_set(rows[0]['row_key']);wait(lambda:app.plate_evidence is not None)
        assert app.viewer.itemcget(app.plate_evidence_outline,'state')=='normal'
        assert app.ocr_tree.item(rows[0]['row_key'],'values')[1]=='Bike 1'
        wait(lambda:len(app.bike_navigation.get('passages',[]))==2)
        app.active_bike_key=app.bike_navigation['passages'][0]['key'];app.next_bike_button.invoke()
        wait(lambda:'Bike 2/2' in app.bike_count_label.cget('text'))
        assert app.active_bike_key==app.bike_navigation['passages'][1]['key']
        app.previous_bike_button.invoke();wait(lambda:'Bike 1/2' in app.bike_count_label.cget('text'))
        mark((.2,.2,.5,.8));old=app.displayed_ordinal
        app.ordinal=old+1;app.request_frame();wait(lambda:app.displayed_ordinal==old+1)
        app.review_number.set('589');app.add_manual_bib()
        assert 'another frame' in app.review_message.get()
        assert len(app.bib_review_rows)==2
        assert f.c.execute('PRAGMA foreign_key_check').fetchall()==[]
        print('Manual bike GUI passed: two boxes/numbers on one source frame, explicit order, saved source highlight, stale-frame guard')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
