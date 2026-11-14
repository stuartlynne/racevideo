"""Fixed lap headings follow horizontal scrolling, independent of body y scroll."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
        app=ReviewWindow(root,f.path);app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        panel.window.geometry('650x750')
        def wait(p):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01);assert not errors,errors
                if p():return
            raise AssertionError('GUI did not settle')
        wait(lambda:panel.model is not None and not panel.busy)
        original=panel.model
        source=panel.model['cells'][0]
        cells=[dict(source,cell_key=f'fixture:{column}:{row}',column=column) for column in range(3) for row in range(30)]
        panel.model=dict(original,cells=cells);panel.paint();root.update()
        y=panel.header_canvas.winfo_rooty()
        headings=[i for i in panel.header_canvas.find_all() if panel.header_canvas.type(i)=='text']
        positions=[panel.header_canvas.coords(i) for i in headings]
        panel.canvas.yview_moveto(.6);root.update()
        assert panel.canvas.canvasy(0)>0 and panel.header_canvas.canvasy(0)==0
        assert panel.header_canvas.winfo_rooty()==y
        assert [panel.header_canvas.coords(i) for i in headings]==positions
        assert any('Lap 1' in panel.header_canvas.itemcget(i,'text') for i in headings)
        panel.canvas.xview_moveto(.6);root.update()
        assert abs(panel.canvas.canvasx(0)-panel.header_canvas.canvasx(0))<=1
        panel.canvas.yview_moveto(0);panel.canvas.xview_moveto(0);panel.model=original;panel.paint();root.update()
        panel.select_cell(original['cells'][0]);panel.reveal_selection();root.update()
        assert panel.canvas.find_withtag('selected-passing')
        print('Frozen headings GUI passed: vertical scroll leaves headings fixed, horizontal scrolling aligns columns, selection remains visible')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
