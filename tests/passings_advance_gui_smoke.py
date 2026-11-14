"""Column-major keys, committed keyboard auto-advance and video bib overlay."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo import passings
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        for cell in passings.compare_event(f.c,f.event)['cells']:
            f.clip(cell['seconds'],None if cell['bib']=='7' and cell['seconds']==65 else cell['bib'])
        f.clip(80,'999');last_clip=f.clip(140,'888')
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01);assert not errors,errors
                if predicate():return
            raise AssertionError(panel.review_message.get())
        def key(widget,keysym):
            widget.focus_force();root.update();widget.event_generate('<KeyPress>',keysym=keysym)
            widget.event_generate('<KeyRelease>',keysym=keysym);root.update()
        def choose(predicate):
            cell=next(c for c in panel.displayed_cells() if predicate(c));panel.select_cell(cell)
            wait(lambda:app.displayed_ordinal is not None and app.selected==panel.capture_rows[panel.capture_picker.current()]['clip_id'])
            return cell
        def overlay(number,colour):
            wait(lambda:app.viewer.itemcget(app.bib_overlay_text,'state')=='normal' and app.viewer.itemcget(app.bib_overlay_text,'text')==number)
            assert app.viewer.itemcget(app.bib_overlay_text,'fill')==colour
            assert app.viewer.coords(app.bib_overlay_text)==[24.0,18.0]
            assert '48' in app.viewer.itemcget(app.bib_overlay_text,'font')
        wait(lambda:panel.model is not None and not panel.busy)
        cells=panel.displayed_cells();columns=sorted({c['column'] for c in cells})
        ordered=[c for col in columns for c in cells if c['column']==col]
        panel.select_cell(ordered[0]);key(app.viewer,'Up');assert panel.selected_cell['cell_key']==ordered[0]['cell_key']
        # Down visits all rows, wrapping at every column boundary.
        for cell in ordered[1:]:
            key(app.viewer,'Down');assert panel.selected_cell['cell_key']==cell['cell_key']
        key(panel.canvas,'Down');assert panel.selected_cell['cell_key']==ordered[-1]['cell_key']
        for cell in reversed(ordered[:-1]):
            key(panel.canvas,'Up');assert panel.selected_cell['cell_key']==cell['cell_key']
        choose(lambda c:c['bib']=='24' and c.get('seconds')==60);overlay('24','#65e894')
        key(app.viewer,'space')
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell and panel.selected_cell['bib']=='7' and panel.selected_cell.get('seconds')==65 and app.displayed_ordinal is not None)
        overlay('7','#ffe14a')
        # Validation failures never advance.
        held=panel.selected_cell['cell_key'];panel.review_number.set('invalid');key(app.viewer,'space')
        assert not panel.review_pending and panel.selected_cell['cell_key']==held
        choose(lambda c:c['bib']=='999');overlay('999','#ff6b6b')
        key(panel.canvas,'minus')
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell and panel.selected_cell['column']==2 and panel.selected_cell['bib']=='24')
        assert len(panel.model['ignored_cells'])==1
        choose(lambda c:c['bib']=='888');overlay('888','#ff6b6b')
        key(app.viewer,'space')
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell and panel.selected_cell['bib']=='888' and panel.selected_cell['confirmed'] and app.displayed_ordinal is not None)
        # Last-row ignore hides it, holds the video, and never wraps to the start.
        key(app.viewer,'minus')
        wait(lambda:not panel.review_pending and not panel.busy and not any(c['bib']=='888' for c in panel.model['cells']))
        assert panel.selected_cell is None and app.selected==last_clip
        key(app.viewer,'Down');assert panel.selected_cell is None and app.selected==last_clip
        key(panel.canvas,'Up');assert panel.selected_cell['bib']=='7' and panel.selected_cell.get('seconds')==130
        panel.close();app.update_bib_overlay()
        assert app.viewer.itemcget(app.bib_overlay_text,'state')=='hidden'
        print('Passings advance GUI passed: full column-major Up/Down and boundaries from both windows; confirm/ignore advance after commit; invalid input holds; end ignore holds video; large green/yellow/red overlay')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
