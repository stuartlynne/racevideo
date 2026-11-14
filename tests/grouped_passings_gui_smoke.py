"""Possible duplicate grouping follows confirmation and is fully inspectable."""
import sys,time,json,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import storage
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(60,'24')
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
        cell=next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60)
        parent_key=cell['cell_key'];panel.select_cell(cell)
        wait(lambda:app.selected==clip and app.displayed_ordinal==1)
        panel.confirm_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and len(panel.model['grouped_cells'])==1)
        parent=next(c for c in panel.model['cells'] if c['cell_key']==parent_key)
        assert parent['confirmed'] and len(parent['grouped_candidates'])==1
        assert not any(c['cell_key']=='cm:'+str(extra) for c in panel.displayed_cells())
        assert any('+1 grouped' in panel.canvas.itemcget(item,'text') for item in panel.canvas.find_all() if panel.canvas.type(item)=='text')
        panel.restore_state=dict(selected='cm:'+str(extra),capture=clip)
        panel.selected_cell=None;panel.request('compare')
        wait(lambda:not panel.busy and panel.selected_cell and panel.selected_cell['cell_key']==parent_key)
        panel.show_grouped.set(True);panel.toggle_grouped()
        grouped=next(c for c in panel.displayed_cells() if c['cell_key']=='cm:'+str(extra))
        panel.select_cell(grouped)
        assert 'Possible duplicate' in panel.detail.get()
        assert panel.session_snapshot()['show_grouped']
        panel.show_grouped.set(False);panel.toggle_grouped()
        assert panel.selected_cell['cell_key']==parent_key
        wait(lambda:app.displayed_ordinal==1)
        panel.undo_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and not panel.model['grouped_cells'])
        assert any(c['cell_key']=='cm:'+str(extra) for c in panel.displayed_cells())
        assert f.c.execute('SELECT count(*) FROM race_passings').fetchone()[0]==raw_count
        assert f.c.execute('SELECT count(*) FROM frames').fetchone()[0]==4
        print('Grouped passings GUI passed: confirm folds possible duplicate, badge and Show grouped expose it, hide returns to parent, undo restores row, source reads/footage unchanged')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
