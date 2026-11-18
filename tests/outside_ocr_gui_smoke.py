"""Wrong numeric OCR on an offered physical track is a warning, not a rider."""
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
        clip=f.clip(60,'9');analysis=f.index_bikes(clip)
        report=json.loads(f.c.execute('SELECT report FROM bike_analyses WHERE id=?',(analysis,)).fetchone()[0])
        report['passages'][0]['uncertain']=False
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
            expected=next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60)
            assert not expected['confirmed'] and expected['state']=='missing'
            wait(lambda:not any(c['bib']=='9' for c in view.locations.values()))
            panel.select_cell(expected);view.signature=None;view.render()
            wait(lambda:app.mode=='replay' and app.selected==clip)
            assert 'OCR read 9' in panel.detail.get() and 'unconfirmed' in panel.detail.get()
            assert 'OCR read 9' in view.detail.cget('text')
            check=next(child for child in view.selector.winfo_children() if child.winfo_class()=='TCheckbutton')
            check.invoke();wait(lambda:any(c['bib']=='9' for c in view.locations.values()))
            raw=next(c for c in view.locations.values() if c['bib']=='9')
            assert raw['state']=='extra' and raw['grouped_under']==expected['cell_key']
            check.invoke();wait(lambda:not any(c['bib']=='9' for c in view.locations.values()))
            assert f.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0]==0
            assert f.c.execute('SELECT number FROM ocr_observations').fetchone()[0]=='9'
            print('Outside OCR GUI passed: one unconfirmed suggestion, visible OCR warning, original 9 inspectable, no identity writes')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
