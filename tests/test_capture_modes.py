import ctypes as C
import errno
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from racevideo import capture_modes as modes,storage
from racevideo.service import configuration

class ModeTests(unittest.TestCase):
    def driver(self,fd,operation,data,mutate):
        if operation==modes.request(2,modes.Format):
            q=modes.Format.from_buffer(data)
            if q.index>1:raise OSError(errno.EINVAL,'end')
            q.pixel_format=int.from_bytes(b'MJPG' if q.index==0 else b'YUYV','little')
        elif operation==modes.request(74,modes.Size):
            q=modes.Size.from_buffer(data)
            if q.index:raise OSError(errno.EINVAL,'end')
            q.type=1;q.values[0]=3840;q.values[1]=2160
        else:
            self.assertEqual(operation,modes.request(75,modes.Interval))
            q=modes.Interval.from_buffer(data)
            if q.index>1:raise OSError(errno.EINVAL,'end')
            q.type=1;q.values[0]=1;q.values[1]=60 if q.index==0 else 30
    def test_linux_discovery_lists_only_real_mjpeg_modes(self):
        self.assertEqual((C.sizeof(modes.Format),C.sizeof(modes.Size),C.sizeof(modes.Interval)),(64,44,52))
        with patch('racevideo.camera.fcntl.ioctl',self.driver):found=modes.enumerate_modes('/dev/null')
        self.assertEqual([(m['width'],m['height'],m['fps']) for m in found],[(3840,2160,60),(3840,2160,30)])
    def test_mode_selection_persists_without_starting_and_refuses_active_recorder(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.sqlite3';c=storage.connect(p);storage.initialize(c);c.close()
            profile=dict(device='/dev/test-camera',width=3840,height=2160,fps=60)
            with patch('racevideo.capture_modes.enumerate_modes',return_value=[profile]):modes.save_profile(p,profile)
            c=storage.connect(p);saved=storage.read_setting(c,'capture_configuration');c.close()
            self.assertEqual(saved,profile)
            self.assertEqual(configuration(dict(configuration={'fps':30,'trigger':'motion'},capture_configuration=saved))['fps'],60)
            with patch('racevideo.service.recorder_running',return_value=True),patch('racevideo.capture_modes.enumerate_modes') as query:
                with self.assertRaisesRegex(ValueError,'Stop the recorder'):modes.save_profile(p,profile)
                query.assert_not_called()
            with patch('racevideo.capture_modes.enumerate_modes',return_value=[]):
                with self.assertRaisesRegex(ValueError,'not advertised'):modes.save_profile(p,dict(profile,fps=120))
    def test_driver_claiming_60_with_actual_30_is_not_a_pass(self):
        state=dict(state='recording',width=3840,height=2160,configuration=dict(width=3840,height=2160,fps=60),capture_fps=30,capture_window_seconds=3,capture_metrics_ns=time.time_ns())
        self.assertIn('WARNING',modes.assessment(state))
        state['capture_fps']=59.9;self.assertIn('Currently meeting',modes.assessment(state))
        state['negotiated_fps']=30;self.assertIn('driver reports',modes.assessment(state));state['negotiated_fps']=60
        state['width']=1920;self.assertIn('dimensions',modes.assessment(state))
        state['width']=3840;state['capture_metrics_ns']=0;self.assertIn('stale',modes.assessment(state))
    def test_saved_frame_metrics_preserve_a_gap(self):
        ns=1_000_000_000
        frames=[storage.Frame(ns+i,ns+i,None,None,b'jpeg') for i in (0,16_666_667,50_000_000)]
        result=modes.frame_metrics(frames)
        self.assertAlmostEqual(result['stored_fps'],40)
        self.assertAlmostEqual(result['max_frame_gap_ms'],33.333333)
    def test_agent_cannot_start_or_restart_over_operator_mode_draft(self):
        import asyncio
        from types import SimpleNamespace
        from racevideo_mcp.operations import Operations
        from racevideo_mcp.journal import Journal
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'recording.sqlite3';c=storage.connect(p);storage.initialize(c);c.close()
            hub=SimpleNamespace(instances={'gui':{'snapshot':{'capture_mode_editing':True}}},for_store=lambda store:['gui'])
            ops=Operations({'default':p},root,hub,Journal(root/'journal.sqlite3'))
            with patch('racevideo_mcp.operations.start_recorder') as launch:
                result=asyncio.run(ops.recorder('default','start'))
                self.assertEqual(result['state'],'failed');self.assertIn('capture-mode edits',result['error'])
                with self.assertRaisesRegex(ValueError,'edits must finish'):
                    asyncio.run(ops.set_settings('default',{'fps':60},restart=True))
                launch.assert_not_called()

if __name__=='__main__':unittest.main()
