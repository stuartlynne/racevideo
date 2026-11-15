"""Unassigned CrossMgr reads stay cached but never become review rows."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        original=dict(f.c.execute("SELECT * FROM race_passings WHERE bib='24' AND seconds=60").fetchone())
        original.pop('id');original.update(seconds=88.6,at_ns=f.start+88_600_000_000,rider_lap=None)
        with f.c:extra=f.c.execute('INSERT INTO race_passings('+','.join(original)+') VALUES('+','.join('?' for _ in original)+')',tuple(original.values())).lastrowid
        raw_count=f.c.execute('SELECT count(*) FROM race_passings').fetchone()[0]
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01);assert not errors,errors
                if predicate():return
            raise AssertionError(panel.status.get()+'; '+panel.review_message.get())
        wait(lambda:panel.model is not None and not panel.busy)
        assert not panel.model['grouped_cells']
        assert not any(c.get('rider_lap') is None and c['origin']=='CrossMgr' for c in panel.model['cells'])
        assert not any(c['cell_key']=='cm:'+str(extra) for c in panel.displayed_cells())
        assert f.c.execute('SELECT count(*) FROM race_passings').fetchone()[0]==raw_count
        print('Unassigned passings GUI passed: raw CrossMgr read retained in source cache and omitted from compact/detailed review')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
