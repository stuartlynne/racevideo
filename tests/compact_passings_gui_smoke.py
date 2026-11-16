"""One-screen live/archive grid shares selection, capture and audited reviews."""
import copy,os,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_passings as fixtures
from racevideo.gui import ReviewWindow
from racevideo.crossmgr_client import Client,Configuration


def main():
    f=fixtures.PassingsTests();f.setUp();app=None
    payload=copy.deepcopy(f.source);payload['inspect']['race']['date']='2026-11-08'
    live=dict(path='/events/20261108-Test/test.cmn',day='2026-11-08',payload=payload)
    try:
        clip=f.clip(60,'24');f.clip(65,'7')
        with patch.object(Configuration,'load',return_value=f.config),patch.object(Client,'fetch_live',return_value=live):
            root=tk.Tk();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
            app=ReviewWindow(root,f.path);root.geometry('1250x900')
            def wait(p):
                until=time.monotonic()+15
                while time.monotonic()<until:
                    root.update();time.sleep(.02);assert not errors,errors
                    if p():return
                raise AssertionError('GUI did not settle: '+(app.compact_passings.status.cget('text') if app.compact_passings else 'no sidebar')+'; '+(app.passings_panel.review_message.get() if app.passings_panel else '')+'; focus '+str(root.focus_get()))
            wait(lambda:app.compact_passings and app.compact_passings.panel and app.compact_passings.panel.model and app.compact_passings.locations)
            compact=app.compact_passings;panel=compact.panel
            assert compact.visible and compact.live_ready and compact.follow.get()
            assert not compact.archive_controls.winfo_ismapped() and compact.category_picker.winfo_ismapped()
            assert compact.race_name.get()==payload['review']['race']['name']
            assert compact.target_picker.winfo_rooty()<compact.race_name_entry.winfo_rooty()<compact.category_picker.winfo_rooty()
            assert panel.window.state()=='withdrawn'
            # Reviewing through the shared controller (keyboard/pop-out/advance)
            # must not silently stop polling the current race.
            panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60))
            wait(lambda:app.mode=='replay' and app.displayed_ordinal is not None)
            until=time.monotonic()+.5
            while time.monotonic()<until:root.update();time.sleep(.02)
            assert compact.follow.get(),'Video review disabled current-race refresh'
            # A new source arrives while staying in review, without a Live click.
            payload['inspect']['inputs'][0]['sha256']='live-update'
            rider=next(r for r in payload['review']['race']['rows'] if r['bib']==7)
            rider['passings'].append(dict(seconds=170,provenance='Unattributed',metadata=None))
            rider['calculated_times'].append(170);rider['calculated_interpolation'].append(False)
            wait(lambda:any(c['bib']=='7' and c.get('seconds')==170 for c in panel.model['cells']))
            assert app.mode=='replay' and compact.follow.get()
            # Idle follow waits for display and real input, then opens the
            # newest passing with a capture without requiring another click.
            newest_clip=f.clip(170)
            panel.request('compare')
            wait(lambda:not panel.busy and any(c.get('seconds')==170 and c['captures'] for c in panel.model['cells']))
            idle=app.idle_passings;clock=idle.clock;now=[0.0]
            idle.clock=lambda:now[0];idle.last_activity=0;idle.arm(panel.event_id,clip)
            idle.tick(panel)
            now[0]=14
            app.viewer.event_generate('<Motion>',x=100,y=100);root.update()
            assert idle.last_activity==14
            now[0]=15;idle.tick(panel);assert app.selected==clip
            now[0]=29;idle.tick(panel)
            wait(lambda:app.selected==newest_clip and app.displayed_ordinal is not None)
            wait(lambda:not panel.busy)
            panel.review_action('confirmed',advance=True)
            wait(lambda:not panel.review_pending and idle.confirmed_last)
            # A committed confirmation of the last entry bypasses the delay.
            arrival_clip=f.clip(175)
            payload['inspect']['inputs'][0]['sha256']='confirmed-last-arrival'
            arrival_rider=next(r for r in payload['review']['race']['rows'] if r['bib']==24)
            arrival_rider['passings'].append(dict(seconds=175,provenance='Unattributed',metadata=None))
            arrival_rider['calculated_times'].append(175);arrival_rider['calculated_interpolation'].append(False)
            compact.next_live=0
            wait(lambda:app.selected==arrival_clip and app.displayed_ordinal is not None)
            assert now[0]==29 and not idle.confirmed_last
            idle.clock=clock;idle.activity()
            app.go_live(follow_race=True)
            wait(lambda:compact.live_ready and not panel.busy)
            assert app.viewer.winfo_rootx()>compact.frame.winfo_rootx()+250
            assert app.frame_label.winfo_viewable() and app.frame_label.winfo_rooty()+app.frame_label.winfo_height()<=root.winfo_rooty()+root.winfo_height()
            cell=next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60)
            tag='compact:'+cell['cell_key']
            original_cells=panel.model['cells']
            replacement=dict(cell,captures=[dict(cell['captures'][0],ordinal=2)])
            panel.model['cells']=[replacement if c['cell_key']==cell['cell_key'] else c for c in original_cells];compact.render()
            assert compact.locations[tag]['captures'][0]['ordinal']==2
            panel.model['cells']=original_cells;compact.render()
            x0,y0,x1,y1=compact.canvas.bbox(tag);x,y=(x0+x1)//2,(y0+y1)//2
            compact.canvas.event_generate('<Motion>',x=x,y=y);compact.canvas.event_generate('<Button-1>',x=x,y=y)
            wait(lambda:app.selected==clip and app.displayed_ordinal==1 and app.viewer.itemcget(app.bib_overlay_text,'text')=='1-1 00:01:00 24 24, Rider')
            assert panel.navigation_target(0,-1)['cell_key']==cell['cell_key']
            assert compact.follow.get()
            assert app.viewer.itemcget(app.bib_overlay_text,'state')=='normal'
            assert app.viewer.itemcget(app.race_time_overlay,'state')=='hidden'
            subject,basename=app.annotated_frame_identity()
            assert subject=='Test - Test - 1-1-00:01:00-24-24, Rider'
            assert basename=='Test-Test-1-1-00:01:00-24-24,Rider.jpg'
            exported=f.path.with_name(basename);app.write_annotated_frame(exported)
            from PIL import Image
            with Image.open(exported) as result:assert result.size==app.displayed_frame.size and result.format=='JPEG'
            with patch.dict(os.environ,{'XDG_CACHE_HOME':str(f.path.parent)}),patch('tkinter.simpledialog.askstring',return_value='rider@example.com'),patch('racevideo.email_jpg.send_jpg') as send:
                app.email_annotated_frame()
                wait(lambda:send.called and not app.email_sending)
                recipient,attachment,sent_subject=send.call_args.args
                assert recipient=='rider@example.com' and sent_subject==subject
                assert str(attachment).endswith('/'+basename) and os.path.exists(attachment)
            def key(widget,keysym,state=0):
                widget.focus_force();root.update();widget.event_generate('<KeyPress>',keysym=keysym,**({'state':state} if state else {}));widget.event_generate('<KeyRelease>',keysym=keysym,**({'state':state} if state else {}))
            key(compact.canvas,'space')
            wait(lambda:not panel.review_pending and not panel.busy and any(c['bib']=='24' and c.get('seconds')==60 and c['confirmed'] for c in panel.model['cells']))
            key(app.viewer,'z',4)
            wait(lambda:not panel.review_pending and not panel.busy and not next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60)['confirmed'])
            wait(lambda:app.mode=='replay' and app.displayed_ordinal is not None and app.index)
            key(app.viewer,'plus');wait(lambda:root.focus_get()==compact.add_entry)
            assert panel.window.state()=='withdrawn'
            key(compact.add_entry,'Escape');wait(lambda:not compact.add_bar.winfo_ismapped())
            app.show_event_passings();wait(lambda:panel.window.state()=='normal')
            panel.close();wait(lambda:panel.window.state()=='withdrawn')
            compact.panel.category.set('Women');compact.category_picker.event_generate('<<ComboboxSelected>>')
            wait(lambda:not panel.busy and panel.category.get()=='Women' and all(c['bib']=='24' for c in panel.model['cells']))
            other=copy.deepcopy(f.source);other['review']['race']['name']='Other event';other['review']['race']['start_time']='2026-11-09T10:00:00+00:00';other['inspect']['race']['finish_time']='2026-11-09T10:03:00+00:00'
            from racevideo import passings
            other_id=passings.cache_event(f.c,f.config,'/events/20261109-Other/other.cmn','2026-11-09',other)
            panel.day.set('2026-11-09');compact.choose_day()
            wait(lambda:panel.model and panel.model['event']['id']==other_id and not panel.busy)
            wait(lambda:compact.event_options and any(e['id']==other_id for e in compact.event_options))
            compact.event_picker.current(next(i for i,e in enumerate(compact.event_options) if e['id']==other_id));compact.event_picker.event_generate('<<ComboboxSelected>>')
            wait(lambda:not panel.busy and panel.event_id==other_id)
            panel.day.set('2026-11-08');compact.choose_day()
            wait(lambda:panel.model and panel.model['event']['id']==f.event and not panel.busy)
            compact.follow_current();app.go_live();compact.results.put(('error','Live CrossMgr unavailable: test offline',compact.generation))
            wait(lambda:'test offline' in compact.status.cget('text'))
            assert not compact.archive_controls.winfo_ismapped() and compact.category_picker.winfo_ismapped()
            assert not compact.locations
            compact.follow.set(False);compact.follow_changed();compact.signature=None;compact.render()
            wait(lambda:compact.archive_controls.winfo_ismapped())
            assert compact.locations
            app.live_button.invoke()
            wait(lambda:compact.follow.get() and compact.live_ready and compact.locations)
            assert app.mode=='live' and not compact.archive_controls.winfo_ismapped()
            state=app.session_snapshot();assert state['compact_passings'] and not state['passings_window_open']
            app.compact_enabled.set(False);app.toggle_compact_passings();root.update()
            assert not compact.visible and not panel.window.winfo_exists()
            app.compact_enabled.set(True);app.toggle_compact_passings()
            wait(lambda:compact.panel is not panel and compact.panel.model is not None)
            panel=compact.panel
            panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60))
            wait(lambda:app.selected==clip and app.displayed_ordinal==1)
            panel.category.set('Women');panel.request('compare');wait(lambda:not panel.busy)
            app.video_area.sashpos(0,390);root.update()
            app.close();app=None
            root=tk.Tk();root.report_callback_exception=lambda *a:errors.append(a)
            app=ReviewWindow(root,f.path)
            wait(lambda:app.compact_passings and app.compact_passings.panel and app.compact_passings.panel.model and app.displayed_ordinal==1)
            compact=app.compact_passings;panel=compact.panel
            assert panel.window.state()=='withdrawn' and panel.category.get()=='Women'
            assert abs(app.video_area.sashpos(0)-390)<=2
            print('Compact passings GUI passed: current-race snapshot, bib grid click opens capture with video passing overlay, confirm/undo/add from main, pop-out retention, date/event/category selection, offline hides stale live grid, hide/reopen, session and pane-width restoration')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
