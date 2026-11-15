"""Date/bib/star/cleanup and original-pixel zoom through an actual isolated Tk UI."""
import io
from datetime import date,timedelta
from pathlib import Path
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

from PIL import Image,ImageDraw
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'review.sqlite3';c=storage.connect(path);storage.initialize(c)
        today=date.today().isoformat();yesterday=(date.today()-timedelta(days=1)).isoformat()
        def clip(day,number,offset=0):
            image=Image.new('RGB',(1280,720),'#314251');draw=ImageDraw.Draw(image)
            for x in range(0,1280,80):draw.line((x,0,x,720),fill='#506779')
            draw.rectangle((520,250,760,430),fill='white');draw.text((560,290),number,fill='black',font_size=70)
            out=io.BytesIO();image.save(out,'JPEG',quality=95);jpeg=out.getvalue()
            ns=storage.local_day_bounds(day)[0]+(12*3600+offset)*1_000_000_000
            frames=[storage.Frame(ns+i*100_000_000,ns+i*100_000_000,i,'1/10',jpeg) for i in range(4)]
            clip_id=storage.save_clip(c,frames,ns,'motion',1280,720,'fixture')
            run=storage.create_ocr_run(path,clip_id,{})
            with c:
                c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
                c.execute('INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (run,number,ns,ns+300_000_000,3,85,1,'[]',jpeg,'repeated'))
            return clip_id
        old=clip(yesterday,'333');a=clip(today,'333');b=clip(today,'042',120)
        root=tk.Tk();app=ReviewWindow(root,path)
        def pump(seconds=.4):
            end=time.monotonic()+seconds
            while time.monotonic()<end:root.update();time.sleep(.005)
        def wait(predicate,seconds=4):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                pump(.05)
                if predicate():return
            raise AssertionError('Timed out waiting for UI state')
        try:
            wait(lambda:len(app.clips)==2)
            assert app.review_day.get()=='Today' and [r['id'] for r in app.clips]==[a,b]
            app.select(a);wait(lambda:bool(app.index) and app.shown_image is not None)
            app.display_button.invoke();pump(.1)
            assert app.display_adjustment_window.winfo_exists()
            app.set_display_adjustment('brightness',1.6);wait(lambda:'adjusted' in app.display_button.cget('text'))
            assert app.display_adjustments['brightness']==1.6
            app.reset_display_adjustments();wait(lambda:'normal' in app.display_button.cget('text'))
            assert app.display_adjustments==dict(brightness=1.0,contrast=1.0,sharpness=1.0)
            app.display_adjustment_window.destroy()
            caption=app.frame_label.cget('text');app.ordinal=3;app.request_frame()
            assert app.frame_label.cget('text')==caption
            wait(lambda:app.displayed_ordinal==3)
            assert app.frame_label.cget('text')=='Frame 4 / 4'
            app.viewer.event_generate('<Button-4>',x=600,y=180);wait(lambda:app.view.zoom>1)
            app.zoom_review(3);pump(.4)
            original=app.view.cx
            app.viewer.event_generate('<ButtonPress-1>',x=500,y=200)
            app.viewer.event_generate('<B1-Motion>',x=560,y=225)
            app.viewer.event_generate('<ButtonRelease-1>',x=560,y=225);pump(.4)
            assert app.view.cx<original
            assert app.display_size[0]<=app.viewer.winfo_width()
            app.escape_review();assert app.mode=='replay' and app.view.zoom==1
            app.escape_review();assert app.mode=='live'
            app.select(b);wait(lambda:app.index and app.selected==b and app.displayed_ordinal is not None)
            assert 'disabled' not in app.star_button.state()
            app.star_button.invoke();wait(lambda:any(r['id']==b and r.get('starred') for r in app.clips))
            wait(lambda:app.star_button.cget('text')=='★ Starred')
            app.review_day.set(yesterday);app.apply_browser();wait(lambda:[r['id'] for r in app.clips]==[old])
            app.browse_today();wait(lambda:len(app.clips)==2)
            app.bib_filter.set('333');app.apply_browser();wait(lambda:[r['id'] for r in app.clips]==[a])
            app.show_passages();wait(lambda:len(app.passages_tree.get_children())==1)
            row=app.passages_tree.get_children()[0];app.passages_tree.selection_set(row);app.jump_passage()
            wait(lambda:app.mode=='replay' and app.selected==a and app.ordinal==1)
            app.passages_window.destroy()
            # Navigate to a clip outside the current day/filter, as MCP does.
            app.select(old);wait(lambda:app.selected==old and app.mode=='replay' and app.review_day.get()==yesterday)
            assert app.bib_filter.get()==''
            app.browse_today();wait(lambda:len(app.clips)==2)
            app.bib_filter.set('333, 042');app.apply_browser();wait(lambda:len(app.clips)==2)
            app.stars_only.set(True);app.apply_browser();wait(lambda:[r['id'] for r in app.clips]==[b])
            app.select(b);wait(lambda:app.index and app.selected==b and app.displayed_ordinal is not None)
            if Path('data').exists():
                from PIL import ImageGrab
                ImageGrab.grab().save('data/review-ui.png')
            # Cancellation must not remove anything. Confirmed cleanup includes
            # unstarred clips hidden by current bib/star filters, and keeps stars.
            app.preview_cleanup();wait(lambda:app.cleanup_panel is not None)
            assert app.cleanup_panel.delete_button.instate(['disabled'])
            app.cleanup_panel.cancel();wait(lambda:not app.cleanup_pending)
            assert len(storage.browse_clips(c,today))==2
            app.preview_cleanup();wait(lambda:app.cleanup_panel is not None)
            panel=app.cleanup_panel
            panel.text.set('DELETE '+yesterday+' 1');pump(.05)
            assert panel.delete_button.instate(['disabled'])
            panel.text.set(panel.phrase);pump(.05)
            assert not panel.delete_button.instate(['disabled'])
            panel.entry.event_generate('<Return>');pump(.05)
            assert app.cleanup_panel is panel and len(storage.browse_clips(c,today))==2
            panel.delete_button.invoke();wait(lambda:not app.cleanup_pending)
            assert [r['id'] for r in storage.browse_clips(c,today)]==[b]
            assert [r['id'] for r in storage.browse_clips(c,yesterday)]==[old]
            app.stars_only.set(False);app.bib_filter.set('');app.apply_browser()
            wait(lambda:[r['id'] for r in app.clips]==[b])
            app.select(b);wait(lambda:app.index and app.selected==b and app.displayed_ordinal is not None)
            app.toggle_star();wait(lambda:storage.browse_clips(c,today)[0]['starred']==0)
            assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
            print('Review GUI passed: display adjustments, Today/date selection, ANY bib filter, candidate sightings/source jump, anchored zoom/pan/Fit, persistent stars, safe cleanup/cancel, hidden clips and older dates retained correctly')
        finally:app.close();c.close()


if __name__=='__main__':main()
