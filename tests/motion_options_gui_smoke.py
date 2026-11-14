"""Real GUI choices/drawing, asynchronous trim analysis, source-boundary review."""
import sys,time,tkinter as tk
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_bib_review as fixtures
from racevideo import storage
from racevideo.gui import ReviewWindow
from racevideo.motion_profiles import MODES
from racevideo.retention import MODES as TRIM_MODES
from PIL import Image,ImageGrab


def main():
    f=fixtures.BibReviewTests();f.setUp();app=None
    try:
        root=tk.Tk();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
        app=ReviewWindow(root,f.path)
        def wait(predicate):
            until=time.monotonic()+10
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError('Motion options timed out: '+(panel.message.get() if 'panel' in locals() else ''))
        wait(lambda:'configured_motion_profile' in app.last_status)
        app.show_motion_options();panel=app.motion_options
        panel.mode.set(MODES['zones']);panel.trim.set(TRIM_MODES['motion']);panel.apply()
        wait(lambda:app.last_status.get('configured_motion_profile',{}).get('mode')=='zones' and not panel.dirty)
        assert storage.read_setting(f.c,'motion_profile')['mode']=='zones'
        app.live_image=Image.new('RGB',(640,360),'#526677');app.go_live();root.update()
        panel.begin_draw('entry');left,top,w,h=app.image_bounds()
        app.viewer.event_generate('<ButtonPress-1>',x=int(left+.7*w),y=int(top+.4*h))
        app.viewer.event_generate('<B1-Motion>',x=int(left+.9*w),y=int(top+.9*h))
        app.viewer.event_generate('<ButtonRelease-1>',x=int(left+.9*w),y=int(top+.9*h))
        assert panel.dirty and panel.drawing is None
        before=storage.read_setting(f.c,'motion_profile')['zones']['entry'];assert before[0]==.78
        panel.apply();wait(lambda:not panel.dirty and abs(app.last_status['configured_motion_profile']['zones']['entry'][0]-.7)<.01)
        app.review_day.set('All dates');app.apply_browser();wait(lambda:bool(app.clips));app.select(f.clip)
        wait(lambda:getattr(app,'displayed_ordinal',None) is not None)
        panel.analyze();wait(lambda:panel.proposal and panel.proposal['state']=='inconclusive')
        assert f.c.execute('SELECT count(*) FROM frames').fetchone()[0]==5
        assert len(panel.tree.get_children())==1
        panel.tree.selection_set('0');panel.jump('end');wait(lambda:app.displayed_ordinal==4)
        Path('data/validation').mkdir(parents=True,exist_ok=True);panel.window.lift();root.update()
        ImageGrab.grab().save('data/validation/motion-options-ui.png')
        print('Motion options GUI passed: selectable modes, drawn zones pending Apply, saved choices, asynchronous analysis, source-frame boundary jumps, original frames preserved')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
