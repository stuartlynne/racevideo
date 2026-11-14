"""Synthetic full-HD camera + deliberately slow motion analysis + actual Tk.

No physical camera required. Verify latest preview survives analysis backlog and
an intentionally blocked event loop, while the compressed ring stays bounded.
"""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch
from fractions import Fraction
from types import SimpleNamespace

from PIL import Image, ImageDraw
from racevideo import storage
from racevideo.__main__ import parser
from racevideo.pipeline import capture_worker, context
from racevideo.recorder import record
from racevideo.motion import MotionDetector
from racevideo.gui import ReviewWindow


class Camera:
    streams=SimpleNamespace(video=[SimpleNamespace(codec_context=SimpleNamespace(name='mjpeg',width=1920,height=1080))])
    def demux(self, stream):
        pictures=[]
        for shade in (80,190):
            image=Image.new('RGB',(1920,1080),(70,80,90))
            ImageDraw.Draw(image).rectangle((820,200,1100,900),fill=(shade,shade,shade))
            out=io.BytesIO();image.save(out,'JPEG',quality=85);pictures.append(out.getvalue())
        start=time.monotonic()
        for tick in range(270):
            time.sleep(max(0,start+tick/30-time.monotonic()))
            jpeg=pictures[tick%2]
            class Packet:
                size=len(jpeg);pts=tick;time_base=Fraction(1,30)
                def __bytes__(self):return jpeg
            yield Packet()
    def close(self):pass


def fixture_capture(*args):
    with patch('av.open',return_value=Camera()):capture_worker(*args)


def fixture_record(path, buffer_mb=8):
    args=parser().parse_args(['record','--db',path,'--buffer-mb',str(buffer_mb),'--run-seconds','9'])
    original=MotionDetector.analyze
    def slow(self,jpeg):
        time.sleep(.18)
        return original(self,jpeg)
    with patch.object(MotionDetector,'analyze',slow):
        raise SystemExit(record(args,capture_target=fixture_capture))


def main():
    if '--trace-hangs' in sys.argv:
        import faulthandler
        faulthandler.dump_traceback_later(45,repeat=True)
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'stress.sqlite3'
        c=storage.connect(path);storage.initialize(c);c.close()
        overrun = '--overrun' in sys.argv
        budget = 1 if overrun else 8
        recorder=context().Process(target=fixture_record,args=(str(path),budget))
        recorder.start()
        root=tk.Tk();app=ReviewWindow(root,path)
        def pump(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                root.update();time.sleep(.003)
        try:
            pump(3)
            assert app.shown_image is not None
            # A half-second application stall must not become a video backlog.
            time.sleep(.6)
            pump(.5)
            assert app.performance.snapshot()['preview_age_ms']['last']<500
            # Keep operator interactions active while analysis falls seconds behind.
            for i in range(12):
                root.geometry(f'{1000+i%3*30}x750')
                app.go_live();pump(.3)
            stats=app.performance.snapshot();status=app.last_status
            assert status['capture_frames']>=170,status
            if overrun:
                assert status['analysis_overrun_frames']>0,status
                assert 'ANALYSIS GAP' in app.status_label.cget('text')
            else:
                assert status['analysis_lag_ms']>1000,status['analysis_lag_ms']
                assert status['analysis_overrun_frames']==0,status
            assert status['ring_bytes']<=budget*1024**2
            assert stats['preview_age_ms']['p95']<500,stats
            assert stats['callback_delay_ms']['p95']<150,stats
            assert stats['counters']['preview_presented']>=50,stats
            assert len({recorder.pid,status['capture_pid'],stats['counters']['preview_pid']})==3
            # Persist only measurements, not the temporary paths/source images.
            evidence=dict(gui=stats,recorder={key:status[key] for key in (
                'capture_frames','frames','analysis_lag_ms','analysis_overrun_frames','ring_bytes','ring_capacity_bytes','motion_analysis_ms')},
                source='Synthetic 1920x1080 JPEG at 30fps; 180ms added per motion analysis; one 600ms GUI stall')
            Path('docs/evidence/pipeline-overrun.json' if overrun else 'docs/evidence/pipeline-stress.json').write_text(json.dumps(evidence,indent=2)+'\n')
            print(json.dumps(evidence,indent=2))
            app.preview.process.terminate(); app.preview.process.join(2)
            pump(2)
            assert 'PREVIEW STALE' in app.viewer.itemcget(app.warning,'text')
            assert not app.performance_snapshot['counters']['preview_worker_alive']
            root.geometry('1100x780');pump(.2)  # Dead-worker locks cannot block resize.

        finally:
            app.close()
            # Finish analysis of retained frames; do not silently discard its backlog.
            recorder.join(40)
            if recorder.is_alive():recorder.kill();recorder.join();raise AssertionError('Recorder did not drain')
            assert recorder.exitcode==0,recorder.exitcode
        c=storage.connect(path,readonly=True)
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert storage.list_clips(c),'Delayed analysis did not save motion'
        if overrun:
            metadata=[json.loads(row[0]) for row in c.execute('SELECT metadata FROM clip_details')]
            assert any(m['end_reason']=='analysis_overrun' for m in metadata),metadata
        c.close()
        print('Pipeline stress passed: capture, motion, preview in distinct processes; bounded ring and responsive latest preview')


if __name__=='__main__':main()
