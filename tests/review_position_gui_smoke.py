"""Test default centering and exact source-frame overrides with real Tk."""
from pathlib import Path
import sys
import time
import tkinter as tk
sys.path.insert(0,str(Path(__file__).parent))
import test_review_position as fixtures
from racevideo.gui import ReviewWindow


def main():
    f=fixtures.ReviewPositionTests();f.setUp();app=None
    try:
        clip=f.clip();root=tk.Tk();errors=[];root.report_callback_exception=lambda *a:errors.append(a)
        app=ReviewWindow(root,f.path);app.review_day.set('All dates');app.apply_browser()
        def wait(predicate):
            until=time.monotonic()+6
            while time.monotonic()<until:
                root.update();time.sleep(.01)
                assert not errors,errors
                if predicate():return
            raise AssertionError('Review position timed out')
        wait(lambda:bool(app.clips));app.select(clip)
        wait(lambda:getattr(app,'displayed_ordinal',None) is not None)
        centered=app.displayed_ordinal;assert abs(centered-10)<=2,centered
        app.pending_seek=(clip,2);app.select(clip)
        wait(lambda:app.displayed_ordinal==2)
        app.select(clip);wait(lambda:app.displayed_ordinal==centered)
        assert app.performance.counters['review_position_cached']
        app.select(clip,auto_position=False);wait(lambda:app.displayed_ordinal==0)
        print('Review position GUI passed: first subject centred; exact evidence seeks preserved; repeated selection cached; explicit frame zero preserved')
    finally:
        if app:app.close()
        f.tearDown()


if __name__=='__main__':main()
