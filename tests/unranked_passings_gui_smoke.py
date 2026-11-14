"""Extra candidates have no CM position; Delete ignores and advances, undo restores."""
import copy,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_passings as fixtures
from racevideo.gui import ReviewWindow
from racevideo.crossmgr_client import Client,Configuration
from racevideo.passings_layout import layout

def main():
    f=fixtures.PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(80);f.index_bikes(clip,2)
        live=dict(path='/events/20261108-Test/test.cmn',day='2026-11-08',payload=copy.deepcopy(f.source))
        with patch.object(Configuration,'load',return_value=f.config),patch.object(Client,'fetch_live',return_value=live):
            root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
            app=ReviewWindow(root,f.path);root.geometry('1250x900')
            def wait(predicate):
                end=time.monotonic()+15
                while time.monotonic()<end:
                    root.update();time.sleep(.02);assert not errors,errors
                    if predicate():return
                raise AssertionError('GUI did not settle')
            wait(lambda:app.compact_passings and app.compact_passings.panel and app.compact_passings.panel.model)
            compact=app.compact_passings;panel=compact.panel
            unknown=lambda:[c for c in panel.model['cells'] if c['bib']=='?']
            wait(lambda:len(unknown())==2)
            table=layout(panel.displayed_cells(),list(range(len(panel.model['columns']))))
            assert all(r['position'] is None for r in table if any(c['bib']=='?' for c in r['cells'].values()))
            first=unknown()[0];second=unknown()[1];panel.select_cell(first)
            wait(lambda:app.mode=='replay' and app.selected==clip and app.displayed_ordinal==first['captures'][0]['ordinal'])
            app.viewer.focus_force();root.update();app.viewer.event_generate('<KeyPress>',keysym='Delete')
            wait(lambda:not panel.review_pending and not panel.busy and len(unknown())==1)
            assert panel.selected_cell['cell_key']==second['cell_key']
            assert len(panel.model['ignored_cells'])==1
            wait(lambda:app.displayed_ordinal==second['captures'][0]['ordinal'])
            app.viewer.event_generate('<KeyPress>',keysym='z',state=4)
            wait(lambda:not panel.review_pending and not panel.busy and len(unknown())==2)
            assert f.c.execute('SELECT count(*) FROM frames WHERE clip_id=?',(clip,)).fetchone()[0]==4
            app.show_event_passings();wait(lambda:panel.window.state()=='normal')
            panel.paint();assert panel.locations
            print('Unranked review GUI passed: extra rows, Delete from main ignores/advances, undo, video retained, detailed view')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
