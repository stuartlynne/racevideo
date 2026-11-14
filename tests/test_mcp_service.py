import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from PIL import Image
from racevideo import storage
from racevideo_mcp import media
from racevideo_mcp.hub import Hub
from racevideo_mcp.journal import Journal
from racevideo_mcp.operations import Operations
from racevideo.mcp_bridge import AppBridge
from types import SimpleNamespace


class JournalTests(unittest.TestCase):
    def test_revoked_control_lease_cannot_be_renewed_or_submit_another_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'recording.sqlite3';c=storage.connect(path);storage.initialize(c);c.close()
            storage.renew_control_lease(path,'lease')
            ids=storage.request_camera_batch(path,'session',[{'id':1,'value':10},{'id':2,'value':20}],time.time()+4,'lease')
            self.assertEqual(len(ids),2)
            storage.revoke_control_leases(path,['lease'])
            with self.assertRaises(ValueError):storage.renew_control_lease(path,'lease')
            with self.assertRaises(ValueError):storage.request_camera_batch(path,'session',[{'id':1,'value':30}],time.time()+4,'lease')
            c=storage.connect(path,readonly=True)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM camera_requests').fetchone()[0],2);c.close()

    def test_dedup_rejects_changed_arguments_and_restart_marks_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'journal.sqlite3';j=Journal(path)
            _,new=j.command('one','gui','view.frame',{'frame':2});self.assertTrue(new)
            _,new=j.command('one','gui','view.frame',{'frame':2});self.assertFalse(new)
            with self.assertRaises(ValueError):j.command('one','gui','view.frame',{'frame':3})
            j.command_result('one','sent')
            again=Journal(path)
            self.assertEqual(again.get_command('one')['state'],'unknown')
            again.command_result('one','succeeded',{'frame':2})
            self.assertEqual(again.get_command('one')['result'],{'frame':2})
            again.create_job('job','export','default')
            self.assertEqual(again.get_job('job')['state'],'queued')


class BridgeGuardTests(unittest.TestCase):
    def test_operator_drafts_and_takeover(self):
        bridge=AppBridge.__new__(AppBridge)
        bridge.app=SimpleNamespace(camera_panel=SimpleNamespace(drafts={1},pending=set()),
                                   reader=SimpleNamespace(camera_pending=set()))
        bridge.leases={};bridge.revoked=set()
        command=dict(id='a',operation='camera.reserve',arguments=dict(lease_id='lease',control_ids=[1]))
        with self.assertRaisesRegex(ValueError,'editing'):bridge.dispatch(command)
        bridge.app.camera_panel.drafts.clear()
        bridge.dispatch(command);self.assertTrue(bridge.reserved(1))
        bridge.revoke();self.assertFalse(bridge.reserved(1))
        with self.assertRaisesRegex(ValueError,'released'):bridge.dispatch(command)


class MediaTests(unittest.TestCase):
    def test_metrics_reject_invalid_area_and_export_preserves_variable_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'recording.sqlite3';c=storage.connect(path);storage.initialize(c)
            frames=[];times=(0,.1,.33,.6)
            for i,t in enumerate(times):
                image=Image.new('RGB',(320,180),(80+i*30,80,80));out=io.BytesIO();image.save(out,'JPEG')
                frames.append(storage.Frame(int(1e12+t*1e9),int(t*1e9),i,'1/10',out.getvalue()))
            clip=storage.save_clip(c,frames,frames[0].received_ns,'timer',320,180,'test');c.close()
            with self.assertRaises(ValueError):media.metrics(frames[0].jpeg,[-1,0,1,1])
            self.assertGreater(media.metrics(frames[0].jpeg)['median'],30)
            sheet,index=media.contact_sheet(path,clip,4)
            self.assertEqual(len(index),4);Image.open(io.BytesIO(sheet)).verify()
            output=Path(temp)/'export.mp4';media.export_mp4(path,clip,output,320)
            import av
            with av.open(output) as video:decoded=[float(f.pts*f.time_base) for f in video.decode(video=0)]
            self.assertEqual(len(decoded),4)
            for expected,actual in zip(times,decoded):self.assertAlmostEqual(expected,actual,places=3)
            c=storage.connect(path,readonly=True)
            self.assertEqual(storage.read_frame(c,clip,0),frames[0].jpeg);c.close()


class HubTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_reply_is_unknown_and_same_command_is_not_resent(self):
        with tempfile.TemporaryDirectory() as temp:
            class Socket:
                count=0
                async def send_json(self,message):self.count+=1
            ws=Socket();hub=Hub(Journal(Path(temp)/'service.sqlite3'),{})
            hub.instances['gui']=dict(ws=ws,store='default',pid=os.getpid(),connected=True,closed=False,
                last_net=time.monotonic(),last_progress=time.monotonic(),snapshot={})
            first=await hub.call('gui','view.live',{},'same',timeout=.01)
            second=await hub.call('gui','view.live',{},'same',timeout=.01)
            self.assertEqual(first['state'],'unknown');self.assertEqual(second['state'],'unknown')
            self.assertEqual(ws.count,1)

    async def test_stalled_gui_is_not_treated_as_responsive(self):
        with tempfile.TemporaryDirectory() as temp:
            hub=Hub(Journal(Path(temp)/'service.sqlite3'),{})
            hub.instances['gui']=dict(store='default',pid=1,connected=True,closed=False,
                last_net=time.monotonic(),last_progress=time.monotonic()-4,snapshot={})
            result=await hub.call('gui','view.live',{},'cmd')
            self.assertEqual(result['state'],'failed')
            with self.assertRaises(ValueError):hub.for_store('default')


if __name__=='__main__':unittest.main()
