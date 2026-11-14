"""Real Tk exercise of matched/missing/extra cells and main-view navigation."""
import copy
from pathlib import Path
import sys
import time
import tkinter as tk
from PIL import ImageGrab

sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo.gui import ReviewWindow


def main():
    fixture=PassingsTests();fixture.setUp()
    app=None
    try:
        matched=fixture.clip(60,'24');unread=fixture.clip(64.9);fixture.clip(80,'999')
        from racevideo import passings
        alternate=copy.deepcopy(fixture.source);alternate['review']['race']['name']='Test alternate'
        alternate_id=passings.cache_event(fixture.c,fixture.config,'/events/20261108-Alternate/alternate.cmn','2026-11-08',alternate)
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,fixture.path)
        app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings()
        panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+8
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                if errors:raise AssertionError(errors)
                if predicate():return
            raise AssertionError('GUI timed out: '+panel.status.get()+'; review: '+panel.review_message.get())
        wait(lambda:panel.model is not None and not panel.busy)
        def click_cell(predicate):
            tag=next(tag for tag,c in panel.locations.items() if predicate(c))
            shape=panel.canvas.find_withtag(tag)[0]
            x1,y1,x2,y2=panel.canvas.coords(shape)
            x=int((x1+x2)/2-panel.canvas.canvasx(0));y=int((y1+y2)/2-panel.canvas.canvasy(0))
            panel.canvas.event_generate('<Motion>',x=x,y=y)
            panel.canvas.event_generate('<Button-1>',x=x,y=y)
            panel.canvas.event_generate('<ButtonRelease-1>',x=x,y=y)
        click_cell(lambda c:c['state']=='matched')
        wait(lambda:app.selected==matched and getattr(app,'displayed_ordinal',None)==1)
        # The five-second refresh returns new dictionaries even if the model
        # has not changed. Repeated clicks must keep a strong selection border.
        selected_key=panel.selected_cell['cell_key']
        panel.review_note.set('Review draft survives another click')
        for _ in range(3):
            old_model=panel.model
            panel.request('compare')
            wait(lambda:not panel.busy and panel.model is not old_model)
            click_cell(lambda c:c['cell_key']==selected_key)
            root.update()
            assert panel.selected_cell['cell_key']==selected_key
            assert panel.review_note.get()=='Review draft survives another click'
            borders=panel.canvas.find_withtag('selected-passing')
            assert len(borders)==1
            assert panel.canvas.itemcget(borders[0],'outline')=='#0057c2'
            assert float(panel.canvas.itemcget(borders[0],'width'))==5
        # A repaint between clicks must also retain selection after refresh.
        old_model=panel.model;panel.request('compare')
        wait(lambda:not panel.busy and panel.model is not old_model)
        panel.paint()
        assert len(panel.canvas.find_withtag('selected-passing'))==1
        panel.review_note.set('')
        wait(lambda:app.quick_confirm_button.instate(['!disabled']) and '24' in app.quick_confirm_button.cget('text'))
        app.quick_confirm_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell and panel.selected_cell['confirmed'])
        panel.review_number.set('4');panel.correct_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and any(c['bib']=='4' and c['confirmed'] and c['origin']=='Visual only' for c in panel.model['cells']))
        panel.undo_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and any(c['bib']=='24' and c['confirmed'] for c in panel.model['cells']))
        click_cell(lambda c:c['bib']=='7' and c.get('seconds')==65)
        # Unindexed captures seek the expected passing time, not frame zero.
        wait(lambda:app.selected==unread and getattr(app,'displayed_ordinal',None)==1)
        assert panel.capture_rows[0]['clip_id']==unread
        key=panel.selected_cell['cell_key'];panel.request('compare')
        wait(lambda:not panel.busy)
        assert panel.selected_cell['cell_key']==key and panel.capture_rows[0]['clip_id']==unread
        wait(lambda:app.quick_confirm_button.instate(['!disabled']) and '7' in app.quick_confirm_button.cget('text'))
        app.quick_confirm_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and panel.selected_cell and panel.selected_cell['confirmed'])
        assert any(c['bib']=='7' and c['state']=='matched' for c in panel.model['cells'])
        click_cell(lambda c:c['state']=='extra')
        wait(lambda:app.selected not in (matched,unread) and getattr(app,'displayed_ordinal',None)==1)
        # Ignore must hide just the selected visual encounter; undo restores it.
        panel.ignore_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and not any(c['state']=='extra' for c in panel.model['cells']))
        panel.undo_button.invoke()
        wait(lambda:not panel.review_pending and not panel.busy and any(c['state']=='extra' for c in panel.model['cells']))
        panel.category.set('Women');panel.request('compare')
        wait(lambda:not panel.busy and panel.model and all(c['bib'] in ('24','999') for c in panel.model['cells']))
        second=next(i for i,(cid,name) in enumerate(panel.competitions) if name=='Alternate')
        panel.competition_picker.current(second);panel.choose_competition()
        wait(lambda:not panel.busy and panel.event_id==alternate_id)
        assert len(panel.event_options)==1 and panel.model['event']['name']=='Test alternate'
        Path('data/validation').mkdir(parents=True,exist_ok=True)
        panel.window.lift();root.update()
        ImageGrab.grab().save('data/validation/passings-fixture-ui.png')
        print('Passings GUI passed: per-cell colours, matched source frame, unread time candidate, extra capture, category filter, no Tk errors')
    finally:
        if app:app.close()
        fixture.tearDown()


if __name__=='__main__':main()
