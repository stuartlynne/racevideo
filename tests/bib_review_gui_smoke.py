"""Exercise real Tk review controls under Xvfb, without any display GPU/camera."""
import io
from datetime import date
from pathlib import Path
import tempfile
import time
import tkinter as tk
from PIL import Image,ImageDraw,ImageGrab
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'review.sqlite3';c=storage.connect(path);storage.initialize(c)
        ns=storage.local_day_bounds(date.today().isoformat())[0]+12*3600*10**9
        image=Image.new('RGB',(640,360),'#314251');draw=ImageDraw.Draw(image);draw.rectangle((200,150,400,260),fill='white');draw.text((225,165),'155',fill='black',font_size=65)
        data=io.BytesIO();image.save(data,'JPEG');jpeg=data.getvalue()
        frames=[storage.Frame(ns+i*100_000_000,ns+i*100_000_000,i,'1/10',jpeg) for i in range(4)]
        clip=storage.save_clip(c,frames,ns,'fixture',640,360,'fixture');empty=storage.save_clip(c,frames,ns,'fixture',640,360,'fixture')
        run=storage.create_ocr_run(path,clip,{})
        with c:
            ids=[]
            for number in ('755','978'):
                ids.append(c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(run,number,ns,ns+200_000_000,3,95,1,'[[200,150],[400,150],[400,260],[200,260]]',jpeg,'ambiguous','fixture:track:1')).lastrowid)
            c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,path)
        def pump(seconds=.05):
            until=time.monotonic()+seconds
            while time.monotonic()<until:root.update();time.sleep(.005)
            assert not errors,errors
        def wait(predicate):
            until=time.monotonic()+5
            while time.monotonic()<until:
                pump()
                if predicate():return
            raise AssertionError('Timed out waiting for review UI')
        try:
            wait(lambda:len(app.clips)==2);app.select(clip)
            wait(lambda:app.index and len(app.bib_review_rows)==2 and getattr(app,'displayed_ordinal',None) is not None)
            app.show_ocr_results();app.ocr_tree.selection_set(str(ids[0]));wait(lambda:app.ordinal==1)
            # Polling unchanged evidence must not replace rows, reset a correction
            # being typed, or bounce the operator back to the source frame.
            app.review_number.set('042');app.ocr_tree.yview_moveto(.5)
            app.refresh_ocr_tree();pump(.1)
            assert app.review_number.get()=='042'
            assert app.ocr_tree.selection()==(str(ids[0]),)
            app.review_number.set('155');app.review_bib('corrected')
            wait(lambda:any(r.get('decision')=='corrected' and r['number']=='155' for r in app.bib_review_rows))
            assert c.execute('SELECT number FROM ocr_observations WHERE id=?',(ids[0],)).fetchone()[0]=='755'
            app.review_number.set('24');app.review_bib('corrected')
            wait(lambda:any(r.get('decision')=='corrected' and r['number']=='24' for r in app.bib_review_rows))
            app.review_number.set('155');app.review_bib('corrected')
            wait(lambda:any(r.get('decision')=='corrected' and r['number']=='155' for r in app.bib_review_rows))
            app.ocr_tree.selection_set(str(ids[1]));pump(.1);app.review_bib('rejected')
            wait(lambda:any(r.get('decision')=='rejected' for r in app.bib_review_rows))
            app.ordinal=3;app.request_frame();wait(lambda:app.displayed_ordinal==3)
            app.review_number.set('042');app.add_manual_bib()
            wait(lambda:any(r.get('manual') and r['number']=='042' for r in app.bib_review_rows))
            row=next(r for r in app.bib_review_rows if r.get('manual'))
            assert row['ordinal']==3 and row['received_ns']==ns+300_000_000
            assert [r[0] for r in c.execute('SELECT tag_id FROM reviewed_video_tag_matches ORDER BY tag_id')]==['042','155']
            screenshot=Path('data/bib-review-ui.png');ImageGrab.grab().save(screenshot)
            app.ocr_tree.selection_set(row['row_key']);pump(.1);app.review_bib('reset')
            wait(lambda:not any(r.get('manual') for r in app.bib_review_rows))
            app.select(empty);wait(lambda:app.index and not app.bib_review_rows and app.displayed_ordinal is not None)
            app.review_number.set('24');app.add_manual_bib()
            wait(lambda:any(r['number']=='24' for r in app.bib_review_rows))
            app.review_number.set('7');app.add_manual_bib()
            wait(lambda:any(r['number']=='7' for r in app.bib_review_rows))
            assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
            print('Bib review GUI passed: source-frame selection/highlight, correction, rejection, manual bib anchored to displayed frame, reset, manual-only clip, immutable OCR, no Tk errors')
        finally:app.close();c.close()


if __name__=='__main__':main()
