"""Bike-centric rows, real arrow keys, scoped ignore and individual restore."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(80);f.index_bikes(clip,2)
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings()
        panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError(panel.status.get()+'; '+panel.review_message.get())
        wait(lambda:panel.model is not None and not panel.busy)
        unknown=[c for c in panel.displayed_cells() if c['bib']=='?']
        assert len(unknown)==2
        panel.select_cell(unknown[0]);wait(lambda:app.displayed_ordinal==1)
        panel.window.focus_force();panel.canvas.focus_force();root.update()
        panel.canvas.event_generate('<KeyPress-Down>')
        wait(lambda:panel.selected_cell['cell_key']==unknown[1]['cell_key'] and app.displayed_ordinal==2)
        panel.canvas.event_generate('<KeyPress-Up>')
        wait(lambda:panel.selected_cell['cell_key']==unknown[0]['cell_key'] and app.displayed_ordinal==1)
        # Rapid same-clip selections must not let an old index reply consume
        # the newest target seek, or display an obsolete frame.
        for cell in (unknown[1],unknown[0],unknown[1],unknown[0]):panel.select_cell(cell)
        wait(lambda:app.displayed_ordinal==1 and app.index)
        column=panel.selected_cell['column'];panel.canvas.event_generate('<KeyPress-Left>')
        wait(lambda:panel.selected_cell['column']<column)
        panel.canvas.event_generate('<KeyPress-Right>')
        wait(lambda:panel.selected_cell['column']==column)
        # Text editing keeps the normal arrow behavior.
        panel.number_entry.focus_force();root.update();key=panel.selected_cell['cell_key']
        panel.number_entry.event_generate('<KeyPress-Down>');root.update()
        assert panel.selected_cell['cell_key']==key
        panel.select_cell(unknown[0]);wait(lambda:app.displayed_ordinal==1 and app.index)
        panel.ignore_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and len(panel.model['ignored_cells'])==1)
        assert len([c for c in panel.displayed_cells() if c['bib']=='?'])==1
        assert not any(c['state']=='ignored' for c in panel.displayed_cells())
        assert '1 ignored' in panel.status.get()
        panel.show_ignored.set(True);panel.paint()
        ignored=next(c for c in panel.displayed_cells() if c['state']=='ignored')
        panel.select_cell(ignored);wait(lambda:app.displayed_ordinal==1)
        assert panel.confirm_button.instate(['disabled'])
        assert panel.restore_button.instate(['!disabled'])
        panel.restore_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and not panel.model['ignored_cells'])
        assert len([c for c in panel.displayed_cells() if c['bib']=='?'])==2
        assert f.c.execute('SELECT count(*) FROM frames').fetchone()[0]==4
        print('Bike passings GUI passed: individual unidentified bikes, arrow-key navigation, text editing preserved, hidden count, show/restore ignored, unchanged footage')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
