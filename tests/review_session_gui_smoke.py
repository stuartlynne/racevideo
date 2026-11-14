"""Session restart, keyboard focus, reversible review and actual pointer panning."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(60,'24')
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);root.geometry('1100x900+100+50')
        app.review_day.set('2026-11-08');app.bib_filter.set('24');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        panel.window.geometry('1000x750+220+80')
        def wait(predicate):
            until=time.monotonic()+12
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError(panel.status.get()+'; '+panel.review_message.get())
        def key(widget,keysym,state=0):
            widget.focus_force();root.update();kwargs={'state':state} if state else {}
            widget.event_generate('<KeyPress>',keysym=keysym,**kwargs)
            widget.event_generate('<KeyRelease>',keysym=keysym,**kwargs);root.update()
        wait(lambda:panel.model is not None and not panel.busy)
        panel.category.set('Women');panel.request('compare');wait(lambda:not panel.busy and panel.model and panel.category.get()=='Women')
        panel.select_cell(next(c for c in panel.model['cells'] if c.get('seconds')==60))
        wait(lambda:app.selected==clip and app.displayed_ordinal==1)
        column=panel.selected_cell['column']
        key(app.viewer,'Right');wait(lambda:panel.selected_cell['column']>column)
        key(app.viewer,'Left');wait(lambda:panel.selected_cell['column']==column and app.displayed_ordinal==1)
        key(app.viewer,'space');wait(lambda:not panel.review_pending and not panel.busy and any(c['confirmed'] and c.get('seconds')==60 for c in panel.model['cells']))
        panel.select_cell(next(c for c in panel.model['cells'] if c.get('seconds')==60))
        wait(lambda:app.selected==clip and app.displayed_ordinal==1)
        for widget,keysym,confirmed in ((app.viewer,'z',False),(panel.canvas,'r',True),(panel.canvas,'z',False),(app.viewer,'r',True)):
            wait(lambda:not panel.busy)
            key(widget,keysym,4)
            wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell['confirmed']==confirmed)
        # '+' must actually transfer input focus from main to the add entry.
        key(app.viewer,'plus');wait(lambda:root.focus_get()==panel.add_entry)
        panel.add_entry.event_generate('<KeyPress>',keysym='5');root.update()
        assert panel.add_number.get()=='5'
        panel.add_entry.event_generate('<KeyPress>',keysym='Escape');root.update()
        app.zoom_review(3);wait(lambda:app.last_render_token==app.token)
        cx,cy=app.view.cx,app.view.cy
        x,y=app.viewer.winfo_width()//2,app.viewer.winfo_height()//2
        app.viewer.event_generate('<ButtonPress-1>',x=x,y=y)
        app.viewer.event_generate('<B1-Motion>',x=x+75,y=y+40)
        app.viewer.event_generate('<ButtonRelease-1>',x=x+75,y=y+40)
        wait(lambda:app.last_render_token==app.token)
        assert app.view.cx<cx and app.view.cy<cy
        expected=app.view.bounds(app.source_size(),app.reader.size)
        assert all(abs(a-b)<1 for a,b in zip(app.review_bounds,expected))
        main_geometry=root.geometry();panel_geometry=panel.window.geometry();view=vars(app.view).copy();selected=panel.selected_cell['cell_key']
        app.close();app=None
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path)
        until=time.monotonic()+12
        while time.monotonic()<until:
            root.update();time.sleep(.01);assert not errors,errors
            panel=app.passings_panel
            if panel and panel.model and not panel.busy and app.displayed_ordinal==1 and app.restore_view is None:break
        else:raise AssertionError('Session was not restored')
        assert root.geometry()==main_geometry,(root.geometry(),main_geometry)
        assert panel.window.geometry()==panel_geometry
        assert app.review_day.get()=='2026-11-08' and app.bib_filter.get()=='24'
        assert panel.category.get()=='Women' and panel.selected_cell['cell_key']==selected
        assert app.selected==clip and vars(app.view)==view,(vars(app.view),view)
        assert not app.browser_area.winfo_ismapped()
        print('Review session GUI passed: both window geometries, date/filter, event/category/selection/frame/zoom restored; arrows, confirm, undo/redo from both windows; real focus transfer and zoomed pointer drag')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
