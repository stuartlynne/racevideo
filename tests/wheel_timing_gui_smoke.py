"""Race-time wheel review, source-frame marker geometry and stale-result isolation."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_passings import PassingsTests
from racevideo.gui import ReviewWindow


def main():
    f=PassingsTests();f.setUp();app=None
    try:
        clip=f.clip(60,'24');other=f.clip(120,'24')
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        app=ReviewWindow(root,f.path);root.geometry('1200x900');app.review_day.set('2026-11-08');app.apply_browser();app.show_event_passings();panel=app.passings_panel
        def wait(predicate):
            until=time.monotonic()+12
            while time.monotonic()<until:
                root.update();time.sleep(.02);assert not errors,errors
                if predicate():return
            raise AssertionError('GUI did not settle')
        wait(lambda:panel.model is not None and not panel.busy)
        panel.select_cell(next(c for c in panel.model['cells'] if c['bib']=='24' and c.get('seconds')==60))
        wait(lambda:app.selected==clip and app.displayed_ordinal==1 and app.wheel_subject())
        subject=app.wheel_subject();key=(clip,subject.get('visual_key',subject['key']),subject['first_ordinal'],subject['last_ordinal'])
        report=dict(width=64,height=32,line_x=.5,samples=[dict(ordinal=1,leading_x=31,center=[25,24],radius=6)],
            crossing=dict(before_ordinal=0,first_observed_after_ordinal=1,estimated_received_ns=f.start+60_050_000_000,
                before_received_ns=f.start+60_000_000_000,after_received_ns=f.start+60_100_000_000,bracket_monotonic_ns=100_000_000))
        app.wheel_enabled.set(True);app.wheel_request_signature=key
        app.wheel_data=dict(clip_id=clip,state='running',report=dict(progress=dict(stage='Measuring wheels',processed=12,total=25)))
        app.draw_wheel_overlay();assert f'clip #{clip}' in app.wheel_status.cget('text') and '12/25 frames' in app.wheel_status.cget('text')
        app.wheel_data=dict(clip_id=clip,state='complete',report=report)
        app.draw_wheel_overlay();app.draw_time_overlay();root.update()
        assert app.viewer.itemcget(app.front_wheel_line,'state')=='normal'
        text=app.viewer.itemcget(app.race_time_overlay,'text')
        assert text=='1:00',text
        assert app.viewer.itemcget(app.front_wheel_line,'fill')=='#ffe14a'
        assert app.viewer.itemcget(app.finish_line,'state')=='hidden'
        original_stops=app.navigation_stops
        active=app.wheel_subject()
        peer=dict(key='peer',visual_key='peer',first_ordinal=0,last_ordinal=3,ordinal=1,numbers=['7'],points=[dict(ordinal=1,box=[30,0,60,32])])
        app.navigation_stops=lambda:[active,peer]
        peer_key=(clip,'peer',0,3)
        import copy
        peer_report=copy.deepcopy(report);peer_report['samples'][0]['leading_x']=42
        peer_report['crossing']['estimated_received_ns']=f.start+62_000_000_000
        from unittest.mock import patch
        # A manual/OCR anchor can be one frame while recovered geometry spans
        # the encounter. Keep its identity active throughout measured frames.
        report['samples'].append(dict(ordinal=100,leading_x=20,center=[25,24],radius=6))
        with patch.object(app,'displayed_ordinal',100):assert app.wheel_subject()['key']==active['key']
        report['samples'].pop()
        with patch.object(app,'source_size',return_value=(640,320)),patch.object(app.reader,'jobs') as queue:
            app.request_wheels()
            assert queue.put.call_args[0][0][0]=='wheel_peer_start'
            assert app.wheel_peer_request==peer_key and app.wheel_request_signature==key
        app.wheel_peer_request=None
        app.wheel_reports[peer_key]=dict(clip_id=clip,state='complete',report=peer_report)
        app.draw_wheel_overlay();app.draw_time_overlay()
        assert app.viewer.itemcget(app.race_time_overlay,'text')=='1:00\n7  1:02'
        peer_line,peer_caption=app.wheel_peer_items['peer']
        assert app.viewer.itemcget(peer_line,'state')=='normal'
        assert app.viewer.itemcget(peer_caption,'text')=='7'
        assert app.viewer.coords(peer_line)[0]!=app.viewer.coords(app.front_wheel_line)[0]
        before=app.viewer.coords(app.front_wheel_line)
        app.zoom_review(2);wait(lambda:app.last_render_token==app.token)
        app.draw_wheel_overlay();left,top,w,h=app.image_bounds()
        assert abs(app.viewer.coords(app.front_wheel_line)[0]-(left+31*w/64))<1
        assert before!=app.viewer.coords(app.front_wheel_line)
        app.ordinal=0;app.request_frame();wait(lambda:app.displayed_ordinal==0)
        app.draw_wheel_overlay();assert app.viewer.itemcget(app.front_wheel_line,'state')=='hidden'
        app.jump_crossing();wait(lambda:app.displayed_ordinal==1)
        assert app.viewer.itemcget(app.front_wheel_line,'state')=='normal'
        crossing=report.pop('crossing')
        app.draw_wheel_overlay()
        assert app.crossing_button.cget('text')=='Wheel frame'
        app.ordinal=0;app.request_frame();wait(lambda:app.displayed_ordinal==0)
        app.crossing_button.invoke();wait(lambda:app.displayed_ordinal==1)
        report['crossing']=crossing
        app.navigation_stops=original_stops
        app.wheel_reports.clear()
        # Poll a completed report through Reader, allowing multiple browse refreshes.
        import json
        with f.c:ident=f.c.execute("INSERT INTO wheel_analyses(clip_id,subject_key,created_ns,updated_ns,state,parameters,report) VALUES(?, 'fixture',0,0,'complete',?,?)",(clip,json.dumps(dict(entry=subject)),json.dumps(report))).lastrowid
        app.reader.wheel_watch=(key,ident);app.reader.wheel_signature=None
        wait(lambda:app.wheel_data.get('id')==ident)
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:root.update();time.sleep(.02)
        assert app.selected==clip and len(app.clips)==2
        wait(lambda:f.c.execute('SELECT count(*) FROM passing_timing_links WHERE analysis_id=?',(ident,)).fetchone()[0]==1)
        app.wheel_open_alignment=dict(clip=clip,generation=app.selection_generation,ordinal=0,view=vars(app.view).copy())
        app.ordinal=0;app.request_frame();wait(lambda:app.displayed_ordinal==0)
        app.align_open_wheel();wait(lambda:app.displayed_ordinal==1)
        assert app.wheel_open_alignment is None
        app.wheel_open_alignment=dict(clip=clip,generation=app.selection_generation,ordinal=0,view=vars(app.view).copy())
        app.ordinal=3;app.request_frame();wait(lambda:app.displayed_ordinal==3)
        app.align_open_wheel();assert app.ordinal==3 and app.wheel_open_alignment is None
        app.race_events=[];app.last_passings_state={};panel.model=None
        assert app.display_time(f.start).startswith('Clock ')
        app.select(other);wait(lambda:app.selected==other and app.displayed_ordinal is not None)
        assert not app.current_wheel_report()
        print('Wheel GUI passed: compact race times, simultaneous per-bike yellow markers and times, zoom geometry, missing sample hides marker, crossing seek, Reader watch preserves selection, no-race fallback, stale clip isolation')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
