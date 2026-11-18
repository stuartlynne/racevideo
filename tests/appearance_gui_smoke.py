"""Suggestions/report navigation are advisory and do not alter the lap table."""
import copy,json,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_passings as fixtures
from racevideo.gui import ReviewWindow
from racevideo.appearance import result_path,review_fingerprint
from racevideo.crossmgr_client import Client,Configuration


def main():
    f=fixtures.PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(60);analysis=f.index_bikes(clip)
        report=Path(f.tmp.name)/'appearance.html';report.write_text('<h1>Appearance evidence</h1>')
        result_path(f.path,f.event).write_text(json.dumps(dict(policy='fixture',fingerprint=review_fingerprint(f.c,f.event),report=str(report),subjects=[
            dict(id='test-subject',physical_key=f'bike:{analysis}:detected:1',clip_id=clip,ordinal=1,
                rankings={'hybrid':[dict(bib='7',score=.91)]})])))
        live=dict(path='/events/20261108-Test/test.cmn',day='2026-11-08',payload=copy.deepcopy(f.source))
        with patch.object(Configuration,'load',return_value=f.config),patch.object(Client,'fetch_live',return_value=live),patch('webbrowser.open') as browser:
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
            cell=next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60)
            panel.select_cell(cell);view.signature=None;view.render()
            wait(lambda:app.mode=='replay' and app.selected==clip)
            assert cell['state']=='missing' and not cell['confirmed'] and cell['bib']=='24'
            assert '7 (0.91)' in panel.detail.get()
            assert 'Appearance suggests: 7' in view.detail.cget('text')
            bar=view.frame.winfo_children()[0]
            next(child for child in bar.winfo_children() if child.winfo_class()=='TButton' and child.cget('text')=='Appearance').invoke()
            browser.assert_called_once_with(report.as_uri()+'#test-subject')
            assert f.c.execute('SELECT count(*) FROM race_visual_reviews').fetchone()[0]==0
            assert f.c.execute('SELECT count(*) FROM bib_reviews').fetchone()[0]==0
            print('Appearance GUI passed: advisory ranking, distinct bib retained, source report opens at selected subject, no review writes')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
