"""A review suggestion appears once; raw candidates remain inspectable."""
import copy,json,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_passings as fixtures
from racevideo.gui import ReviewWindow
from racevideo.crossmgr_client import Client,Configuration


def main():
    f=fixtures.PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(65);analysis=f.index_bikes(clip,2)
        report=json.loads(f.c.execute('SELECT report FROM bike_analyses WHERE id=?',(analysis,)).fetchone()[0])
        for candidate in report['passages']:candidate['uncertain']=False
        with f.c:f.c.execute('UPDATE bike_analyses SET report=? WHERE id=?',(json.dumps(report),analysis))
        live=dict(path='/events/20261108-Test/test.cmn',day='2026-11-08',payload=copy.deepcopy(f.source))
        with patch.object(Configuration,'load',return_value=f.config),patch.object(Client,'fetch_live',return_value=live):
            root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
            app=ReviewWindow(root,f.path)
            def wait(predicate):
                end=time.monotonic()+15
                while time.monotonic()<end:
                    root.update();time.sleep(.02);assert not errors,errors
                    if predicate():return
                raise AssertionError('GUI did not settle')
            wait(lambda:app.compact_passings and app.compact_passings.panel and app.compact_passings.panel.model)
            view=app.compact_passings;panel=view.panel
            expected=next(c for c in panel.model['cells'] if c['bib']=='7' and c.get('seconds')==65)
            assert expected['suggested_visual'] and not expected['confirmed'] and expected['state']=='missing'
            assert len(panel.model['grouped_cells'])==1
            wait(lambda:len([c for c in view.locations.values() if c['bib']=='?'])==1)
            check=next(child for child in view.selector.winfo_children() if child.winfo_class()=='TCheckbutton')
            check.invoke();wait(lambda:len([c for c in view.locations.values() if c['bib']=='?'])==2)
            assert any(c.get('grouped_under')==expected['cell_key'] for c in view.locations.values())
            check.invoke();wait(lambda:len([c for c in view.locations.values() if c['bib']=='?'])==1)
            panel.select_cell(expected);wait(lambda:app.mode=='replay' and app.selected==clip and app.displayed_ordinal is not None)
            assert 'identity is still unconfirmed' in panel.detail.get()
            assert f.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0]==0
            print('Suggested grouping GUI passed: one proposed row, distinct extra retained, Show grouped toggles raw candidate, no identity confirmation')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
