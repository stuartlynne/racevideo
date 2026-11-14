"""A missing rider in one multi-bike clip must not reopen its first rider."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import storage,bike_index
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        start=f.start+60*10**9
        frames=[storage.Frame(start+i*33_333_333,100*10**9+i*33_333_333,i,'1/30',f.jpeg) for i in range(143)]
        clip=storage.save_clip(f.c,frames,start,'test',64,32,'test')
        run=storage.create_ocr_run(f.path,clip,{})
        with f.c:
            f.c.execute('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(run,'24',frames[11].received_ns,frames[29].received_ns,19,95,17,'[]',f.jpeg,'repeated','first-bike'))
            f.c.execute("UPDATE ocr_runs SET state='complete' WHERE id=?",(run,))
            # The expected next rider's timestamp is closer to the earlier bike;
            # already-associated evidence must not outrank an unassigned bike.
            f.c.execute("UPDATE race_passings SET seconds=61,at_ns=? WHERE bib='7' AND seconds=65",(f.start+61*10**9,))
        def track(key,a,b,ordinal,weak=False):
            return dict(key=key,first_ordinal=a,last_ordinal=b,ordinal=ordinal,box=[10,0,54,32],
                points=[dict(ordinal=i,box=[10,0,54,32]) for i in range(a,b+1)],numbers=[],confirmed=False,uncertain=weak)
        bike_index.save(f.c,clip,dict(source='detector',passages=[track('first',4,32,19),track('fragment',26,32,32,True),track('second',63,85,74)]))
        unindexed=f.clip(69.8)
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01);assert not errors,errors
                if predicate():return
            raise AssertionError(panel.review_message.get())
        wait(lambda:panel.model is not None and not panel.busy)
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60))
        wait(lambda:app.selected==clip and app.displayed_ordinal==17 and app.next_bike_button.instate(['!disabled']))
        assert len(app.navigation_stops())==2 and len(app.bike_navigation['passages'])==3
        app.next_bike_button.invoke();wait(lambda:app.displayed_ordinal==74)
        app.previous_bike_button.invoke();wait(lambda:app.displayed_ordinal==19)
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='7' and c.get('seconds')==61))
        wait(lambda:app.displayed_ordinal==74 and app.previous_bike_button.instate(['!disabled']))
        assert app.next_bike_button.instate(['disabled'])
        app.previous_bike_button.invoke();wait(lambda:app.displayed_ordinal==19)
        app.next_bike_button.invoke();wait(lambda:app.displayed_ordinal==74)
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='4' and c.get('seconds')==70))
        wait(lambda:app.selected==unindexed and app.displayed_ordinal==2)
        assert f.c.execute('SELECT count(*) FROM frames WHERE clip_id=?',(clip,)).fetchone()[0]==143
        print('Passing bike target GUI passed: missing second rider centers at frame 75; primary Previous/Next skip fragments; explicit targets align navigation; unindexed fallback seeks expected time; footage unchanged')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
