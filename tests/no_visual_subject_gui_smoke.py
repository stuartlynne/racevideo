"""CM-no-visual automatically scans images, without OCR or a prior bike index."""
import sys,time,io,tkinter as tk
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        frames=[];start=f.start+69_500_000_000
        for i in range(150):
            image=Image.new('RGB',(320,180),'#aaaaaa')
            if 30<=i<=65 or 90<=i<=125:
                begin=30 if i<90 else 90;x=350-(i-begin)*12
                ImageDraw.Draw(image).rectangle((x-25,60,x+25,165),fill='#111111')
            buf=io.BytesIO();image.save(buf,'JPEG')
            frames.append(storage.Frame(start+i*33_333_333,i*33_333_333,i,'1/30',buf.getvalue()))
        clip=storage.save_clip(f.c,frames,start,'test',320,180,'test')
        with f.c:f.c.execute("UPDATE race_passings SET seconds=72.4,at_ns=? WHERE bib='7' AND seconds=65",(f.start+72_400_000_000,))
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+12
            while time.monotonic()<until:
                root.update();time.sleep(.01);assert not errors,errors
                if predicate():return
            raise AssertionError(panel.review_message.get())
        wait(lambda:panel.model is not None and not panel.busy)
        assert not f.c.execute('SELECT 1 FROM ocr_runs').fetchone()
        assert not f.c.execute('SELECT 1 FROM bike_analyses').fetchone()
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='4' and c.get('seconds')==70))
        wait(lambda:app.selected==clip and app.displayed_ordinal is not None and app.bike_navigation.get('source')=='motion')
        first=app.displayed_ordinal
        assert abs(first-46)<=3,first
        assert f.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0]==0
        # Confirm immediately, before the periodic comparison refresh. The new
        # motion target must already be linked, rather than creating a duplicate.
        panel.confirm_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell['confirmed'])
        assert len([c for c in panel.model['cells'] if c['bib']=='?'])==1
        assert len(app.navigation_stops())==2
        assert app.next_bike_button.instate(['!disabled'])
        app.next_bike_button.invoke();wait(lambda:app.displayed_ordinal!=first)
        second=app.displayed_ordinal;assert abs(second-106)<=3,second
        app.previous_bike_button.invoke();wait(lambda:app.displayed_ordinal==first)
        # The second missing CM entry also starts in empty ground if seeking
        # its timestamp literally; it must use the later cached motion stop.
        panel.request('compare');wait(lambda:not panel.busy)
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='7' and c.get('seconds')==72.4))
        wait(lambda:app.displayed_ordinal==second and ' 7 ' in app.viewer.itemcget(app.bib_overlay_text,'text'))
        assert f.c.execute('SELECT count(*) FROM frames').fetchone()[0]==150
        assert f.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0]==1
        assert not f.c.execute('SELECT 1 FROM ocr_runs').fetchone()
        print('CM no visual GUI passed: empty predicted-time frames replaced by centered moving subjects; both riders found without OCR/neural index; cached Previous/Next works; no automatic confirmations; explicit confirmation links the target; footage unchanged')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
