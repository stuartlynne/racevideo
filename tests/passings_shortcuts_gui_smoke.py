"""Real key events across both windows, enlarged video and independent bib adds."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import bib_review
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        first=f.clip(60,'24');second=f.clip(65)
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);root.geometry('1400x1000');root.update()
        normal_height=app.viewer.winfo_height()
        app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError(panel.review_message.get())
        def key(widget,keysym):
            widget.focus_force();root.update()
            widget.event_generate('<KeyPress>',keysym=keysym)
            widget.event_generate('<KeyRelease>',keysym=keysym)
            root.update()
        wait(lambda:panel.model is not None and not panel.busy)
        assert not app.browser_area.winfo_ismapped()
        assert app.viewer.winfo_height()>normal_height+100
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60))
        wait(lambda:app.displayed_ordinal==1 and app.selected==first)
        # Space on the Ignore button must confirm, not activate that button.
        key(panel.ignore_button,'space')
        wait(lambda:not panel.review_pending and not panel.busy and any(c['confirmed'] and c.get('seconds')==60 and c['bib']=='24' for c in panel.model['cells']))
        assert not panel.model['ignored_cells'] and not app.playing
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='7' and c.get('seconds')==65))
        wait(lambda:app.selected==second and app.displayed_ordinal is not None and app.index)
        key(app.viewer,'space')
        wait(lambda:not panel.review_pending and not panel.busy and any(c['confirmed'] and c.get('seconds')==65 and c['bib']=='7' for c in panel.model['cells']))
        panel.select_cell(next(c for c in panel.model['cells'] if c.get('seconds')==65 and c['bib']=='7'))
        wait(lambda:app.selected==second and app.displayed_ordinal is not None and app.index)
        assert not app.playing
        for number in ('4','25'):
            key(app.viewer,'plus')
            wait(lambda:panel.add_target is not None and panel.add_entry.winfo_ismapped())
            # Type actual keys, preserving the selected rider rather than correcting it.
            for digit in number:key(panel.add_entry,digit)
            assert panel.add_number.get()==number
            key(panel.add_entry,'Return')
            wait(lambda:not panel.review_pending and not panel.busy and panel.add_target is None)
        assert {r['number'] for r in bib_review.list_rows(f.c,second)}=={'7','4','25'}
        key(panel.canvas,'KP_Add');wait(lambda:panel.add_target is not None)
        panel.add_number.set('1234');key(panel.add_entry,'Return')
        assert panel.add_target is not None and not panel.review_pending
        key(panel.add_entry,'Escape');assert panel.add_target is None
        # A literal minus in a note remains text, rather than hiding a rider.
        panel.number_entry.focus_force();panel.review_number.set('7');key(panel.number_entry,'minus')
        assert '-' in panel.review_number.get() and not panel.model['ignored_cells']
        cell=next(c for c in panel.model['cells'] if c['bib']=='4' and c['origin']=='Visual only')
        panel.select_cell(cell);wait(lambda:app.selected==second and app.displayed_ordinal is not None)
        key(app.viewer,'minus')
        wait(lambda:not panel.review_pending and not panel.busy and len(panel.model['ignored_cells'])==1)
        assert not any(c['bib']=='4' and c['origin']=='Visual only' for c in panel.model['cells'])
        assert any(c['bib']=='25' for c in panel.model['cells'])
        panel.close();root.update()
        assert app.browser_area.winfo_ismapped()
        assert app.viewer.winfo_height()==normal_height
        wait(lambda:app.mode=='replay' and app.index and app.displayed_ordinal is not None)
        app.ordinal=0;app.playing=False;played=[];toggle=app.toggle_play
        def track_play():
            result=toggle();played.append(app.playing);return result
        app.toggle_play=track_play
        key(app.viewer,'space');assert played==[True],played
        assert f.c.execute('SELECT count(*) FROM frames').fetchone()[0]==8
        print('Passings shortcuts GUI passed: larger video/restored browser, Space confirms from either window without button activation, +digits/Enter adds independent riders, Escape cancels, minus ignores, text-entry protection, normal playback restored')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
