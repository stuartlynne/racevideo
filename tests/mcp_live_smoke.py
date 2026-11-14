"""Physical camera through MCP: headless capture, GUI guard, tuning/restore/takeover.

Run with camera free: xvfb-run -a .venv/bin/python tests/mcp_live_smoke.py
Restores touched hardware settings and stops its temporary recorder.
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
import uvicorn

from racevideo import storage
from racevideo.camera import CameraControls
from racevideo.service import recorder_running
from racevideo_mcp.config import bootstrap
from racevideo_mcp.server import build
from mcp_integration import GUI_SCRIPT


async def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);path=root/'live.sqlite3'
        c=storage.connect(path);storage.initialize(c);c.close()
        backend=CameraControls('/dev/video0');original={c['id']:c['value'] for c in backend.enumerate()}
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        app=build({'default':path},root/'state','admin-test','bridge-test',port=port)
        bootstrap(root/'bridge.json',f'ws://127.0.0.1:{port}/bridge','bridge-test','test-service')
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',access_log=False))
        task=asyncio.create_task(server.serve())
        while not server.started:await asyncio.sleep(.05)
        gui=None;log=(root/'gui.log').open('w+')
        try:
            async with httpx.AsyncClient(headers={'Authorization':'Bearer admin-test'}) as http:
                async with streamable_http_client(f'http://127.0.0.1:{port}/mcp',http_client=http) as (r,w,_):
                    async with ClientSession(r,w) as client:
                        async def call(name,args=None):
                            result=await client.call_tool(name,args or {})
                            assert not result.isError,(name,result.content)
                            if result.structuredContent is not None:return result.structuredContent
                            return json.loads(next(c.text for c in result.content if c.type=='text'))
                        async def fresh():
                            for _ in range(80):
                                status=await call('racevideo.status')
                                if status.get('fresh'):return status
                                await asyncio.sleep(.1)
                            raise AssertionError('Camera did not become live')
                        started=await call('recorder.start',{'configuration':{'width':1280,'height':720}})
                        assert started['state']=='succeeded',started
                        state=await fresh();session=state['session']
                        sample=await client.call_tool('camera.sample')
                        Image.open(io.BytesIO(base64.b64decode(next(c.data for c in sample.content if c.type=='image')))).verify()
                        # No GUI: direct service-owned requests get real driver readback.
                        changed=await call('camera.set',{'changes':[{'id':0x9A0901,'value':1},
                            {'id':0x9A0902,'value':original[0x9A0902]}],'command_id':'manual-readback'})
                        assert changed['state']=='succeeded',changed
                        duplicate=await call('camera.set',{'changes':[{'id':0x9A0901,'value':1},
                            {'id':0x9A0902,'value':original[0x9A0902]}],'command_id':'manual-readback'})
                        assert duplicate['id']==changed['id']
                        c=storage.connect(path,readonly=True)
                        assert c.execute("SELECT COUNT(*) FROM camera_requests WHERE command_id='manual-readback'").fetchone()[0]==2
                        c.close()
                        expired=storage.request_camera_control(path,session,0x980901,original[0x980901]+1,
                                                               expires=time.time()-1,command_id='expired-test')
                        for _ in range(30):
                            c=storage.connect(path,readonly=True);rows=storage.camera_results(c,{expired});c.close()
                            if rows:break
                            await asyncio.sleep(.1)
                        assert 'expired' in rows[0]['error']
                        assert backend.describe(0x980901)['value']==original[0x980901]
                        # Queue and revoke atomically so the recorder cannot execute
                        # the request before the test marks its reservation revoked.
                        c=storage.connect(path)
                        with c:
                            c.execute('INSERT INTO control_leases VALUES(?,?,0)',('queued-takeover',time.time()+20))
                            row=c.execute('INSERT INTO camera_requests(created,session,control_id,value,expires,command_id) VALUES(?,?,?,?,?,?)',
                                (time.time(),session,0x980901,original[0x980901]+1,time.time()+4,'queued-takeover'))
                            revoked_request=row.lastrowid
                            c.execute("UPDATE control_leases SET revoked=1 WHERE id='queued-takeover'")
                        c.close()
                        for _ in range(30):
                            c=storage.connect(path,readonly=True);cancelled=storage.camera_results(c,{revoked_request});c.close()
                            if cancelled:break
                            await asyncio.sleep(.1)
                        assert 'released' in cancelled[0]['error']
                        assert backend.describe(0x980901)['value']==original[0x980901]
                        env=os.environ.copy();env['RACEVIDEO_MCP_BRIDGE_FILE']=str(root/'bridge.json')
                        control=root/'control.json'
                        gui=subprocess.Popen([sys.executable,'-c',GUI_SCRIPT,str(path),str(control)],env=env,stdout=log,stderr=log)
                        for _ in range(60):
                            instances=app.hub.list()
                            if instances and instances[0]['responsive']:break
                            await asyncio.sleep(.1)
                        assert instances[0]['responsive']
                        control.write_text(json.dumps({'op':'dirty'}));await asyncio.sleep(.4)
                        refused=await call('camera.set',{'changes':[{'id':0x9A0901,'value':1}]})
                        assert refused['state']=='failed' and 'editing' in refused['error'],refused
                        control.write_text(json.dumps({'op':'clear'}));await asyncio.sleep(.4)
                        exposure=original[0x9A0902];gain=original.get(0x980913,128)
                        trials=[exposure,max(3,exposure//2)]
                        job=await call('camera.tune',{'exposures':trials,'max_gain':gain,'min_median':1,'apply_best':False})
                        for _ in range(150):
                            result=await call('jobs.get',{'job_id':job['id']})
                            if result['state'] in ('complete','error'):break
                            await asyncio.sleep(.1)
                        assert result['state']=='complete' and result['result']['restored'],result
                        assert backend.describe(0x9A0902)['value']==exposure
                        evidence=await client.call_tool('jobs.frame',{'job_id':job['id']})
                        assert any(c.type=='image' for c in evidence.content)
                        # Operator takeover must stop subsequent agent writes/restoration.
                        second=await call('camera.tune',{'exposures':trials,'max_gain':gain,'min_median':1})
                        for _ in range(80):
                            snapshot=app.hub.list()[0]['snapshot']
                            if second['id'] in snapshot.get('camera_leases',[]):break
                            await asyncio.sleep(.05)
                        assert second['id'] in snapshot.get('camera_leases',[])
                        operator_value=max(3,exposure-1)
                        control.write_text(json.dumps({'op':'takeover','value':operator_value}))
                        for _ in range(150):
                            taken=await call('jobs.get',{'job_id':second['id']})
                            if taken['state'] in ('complete','error'):break
                            await asyncio.sleep(.1)
                        assert taken['state']=='error' and 'released' in str(taken),taken
                        for _ in range(40):
                            if backend.describe(0x9A0902)['value']==operator_value:break
                            await asyncio.sleep(.1)
                        assert backend.describe(0x9A0902)['value']==operator_value,taken
                        await call('recorder.capture',{'command_id':'save-once'})
                        for _ in range(40):
                            clips=await call('clips.list')
                            if clips['clips']:break
                            await asyncio.sleep(.1)
                        assert clips['clips']
                        print('MCP live passed: headless camera/stream sampling, verified ordered writes, '
                              'deduplication, request expiry, GUI draft guard, measured trials/restore, '
                              'trial images, operator takeover prevents restore, buffered capture')
                        await call('recorder.stop')
                        for _ in range(50):
                            if not recorder_running(path):break
                            await asyncio.sleep(.1)
        except Exception:
            log.flush();print((root/'gui.log').read_text()[-5000:])
            recording_log=path.with_suffix('.recorder.log')
            if recording_log.exists():print(recording_log.read_text()[-5000:])
            raise
        finally:
            if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
            if recorder_running(path):
                storage.command(path,'stop')
                for _ in range(50):
                    if not recorder_running(path):break
                    await asyncio.sleep(.1)
            backend.set(0x9A0901,1);backend.set(0x9A0902,original[0x9A0902])
            for cid in (0x980913,0x9A0903):
                if cid in original:backend.set(cid,original[cid])
            backend.set(0x9A0901,original[0x9A0901]);backend.close()
            server.should_exit=True;await asyncio.wait_for(task,15);log.close()


if __name__=='__main__':asyncio.run(main())
