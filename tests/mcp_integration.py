"""Actual HTTP MCP client, reverse GUI TCP bridge and offline media integration.

Run: xvfb-run -a .venv/bin/python tests/mcp_integration.py
No physical camera is opened. All stores and credentials are temporary.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
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

from racevideo import storage


GUI_SCRIPT='''
import json,sys,time,tkinter as tk
from pathlib import Path
from racevideo.gui import ReviewWindow
root=tk.Tk();app=ReviewWindow(root,sys.argv[1]);control=Path(sys.argv[2]);seen=None
def check():
 global seen
 if control.exists():
  command=json.loads(control.read_text())
  if command!=seen:
   seen=command
   if command['op']=='freeze':time.sleep(2.5)
   elif command['op']=='dirty':
    app.open_camera();app.camera_panel.drafts.add(0x9A0901)
   elif command['op']=='clear':
    if app.camera_panel:app.camera_panel.close()
   elif command['op']=='takeover':
    app.remote.revoke();app.open_camera()
    row=app.camera_panel.rows[0x9A0902];row['variable'].set(command['value']);app.camera_panel.apply(0x9A0902)
   elif command['op']=='close':app.close();return
 root.after(50,check)
root.after(100,check);root.mainloop()
'''


async def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary);path=root/'recording.sqlite3'
        c=storage.connect(path);storage.initialize(c)
        frames=[]
        for i,t in enumerate((0,.1,.33,.6)):
            out=io.BytesIO();Image.new('RGB',(320,180),(60+i*40,80,90)).save(out,'JPEG')
            frames.append(storage.Frame(int(1e12+t*1e9),int(t*1e9),i,'1/10',out.getvalue()))
        clip=storage.save_clip(c,frames,frames[0].received_ns,'timer',320,180,'fixture');c.close()
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        config=root/'config';state=root/'state';url=f'http://127.0.0.1:{port}'
        command=[sys.executable,'-m','racevideo_mcp.server','--db',str(path),'--port',str(port),
                 '--config-dir',str(config),'--state-dir',str(state)]
        log=(root/'server.log').open('w+')
        server=None;gui=None

        async def boot():
            nonlocal server
            server=subprocess.Popen(command,stdout=log,stderr=log)
            deadline=time.monotonic()+10
            async with httpx.AsyncClient() as client:
                while time.monotonic()<deadline:
                    try:
                        if (await client.get(url+'/health')).status_code==200:return
                    except httpx.HTTPError:pass
                    await asyncio.sleep(.1)
            raise AssertionError('Server did not start')

        @asynccontextmanager
        async def session():
            async with httpx.AsyncClient(headers={'Authorization':'Bearer '+(config/'token').read_text().strip()}) as client:
                async with streamable_http_client(url+'/mcp',http_client=client) as (reader,writer,_):
                    async with ClientSession(reader,writer) as s:
                        await s.initialize();yield s

        async def call(s,name,args=None):
            result=await s.call_tool(name,args or {})
            assert not result.isError,(name,result.content)
            if result.structuredContent is not None:return result.structuredContent
            return json.loads(next(c.text for c in result.content if c.type=='text'))

        async def wait_instance(s):
            end=time.monotonic()+8
            while time.monotonic()<end:
                data=await call(s,'app.instances')
                values=data.get('result',data) if isinstance(data,dict) else data
                ready=[i for i in values if i['responsive']]
                if ready:return ready[0]['instance']
                await asyncio.sleep(.1)
            raise AssertionError('App did not connect')

        try:
            await boot()
            async with httpx.AsyncClient() as anonymous:
                assert (await anonymous.post(url+'/mcp',json={})).status_code==401
            async with session() as s:
                tools=await s.list_tools();assert len(tools.tools)>=20
                dates=await call(s,'clips.dates',{})
                assert len(dates['dates'])==1
                selected_day=dates['dates'][0]
                dated=await call(s,'clips.list',dict(day=selected_day))
                assert [row['id'] for row in dated['clips']]==[clip]
                star=await call(s,'clips.star',dict(clip_id=clip,command_id='fixture-star'))
                assert star['state']=='succeeded'
                repeated_star=await call(s,'clips.star',dict(clip_id=clip,command_id='fixture-star'))
                assert repeated_star['id']==star['id']
                starred=await call(s,'clips.list',dict(day=selected_day,starred_only=True))
                assert [row['id'] for row in starred['clips']]==[clip]
                no_match=await call(s,'clips.list',dict(day=selected_day,bibs=['333']))
                assert no_match['clips']==[]
                sightings=await call(s,'bibs.sightings',dict(day=selected_day,bibs=['333']))
                assert sightings['sightings']==[]

                assert len((await call(s,'clips.list'))['clips'])==1
                image=await s.call_tool('frames.get',{'clip_id':clip,'ordinal':1})
                block=next(c for c in image.content if c.type=='image')
                Image.open(io.BytesIO(base64.b64decode(block.data))).verify()
                sheet=await s.call_tool('clips.contact_sheet',{'clip_id':clip,'count':4})
                assert any(c.type=='image' for c in sheet.content)
                job=await call(s,'clips.export',{'clip_id':clip,'max_width':320})
                for _ in range(100):
                    completed=await call(s,'jobs.get',{'job_id':job['id']})
                    if completed['state'] in ('complete','error'):break
                    await asyncio.sleep(.1)
                assert completed['state']=='complete',completed
                async with httpx.AsyncClient() as anonymous:
                    download=completed['result']['download_url']
                    video=await anonymous.get(download);assert video.status_code==200
                    partial=await anonymous.get(download,headers={'Range':'bytes=0-31'})
                    assert partial.status_code==206 and len(partial.content)==32
                    assert (await anonymous.get(url+completed['result']['download_path'])).status_code==401
                env=os.environ.copy();env['RACEVIDEO_MCP_BRIDGE_FILE']=str(config/'bridge.json')
                control=root/'control.json'
                gui=subprocess.Popen([sys.executable,'-c',GUI_SCRIPT,str(path),str(control)],env=env,stdout=log,stderr=log)
                iid=await wait_instance(s)
                selected=await call(s,'app.control',dict(instance=iid,operation='view.clip',arguments={'clip_id':clip,'frame':2},command_id='choose-two'))
                assert selected['state']=='succeeded' and selected['result']['displayed'],selected
                duplicate=await call(s,'app.control',dict(instance=iid,operation='view.clip',arguments={'clip_id':clip,'frame':2},command_id='choose-two'))
                assert duplicate['id']==selected['id']
                await call(s,'app.control',dict(instance=iid,operation='playback.play'))
                await call(s,'app.control',dict(instance=iid,operation='playback.pause'))
                control.write_text(json.dumps({'op':'dirty'}));await asyncio.sleep(.5)
                rejected=await call(s,'camera.set',{'changes':[{'id':0x9A0901,'value':1}]})
                assert rejected['state']=='failed' and 'editing' in rejected['error'],rejected
                control.write_text(json.dumps({'op':'clear'}));await asyncio.sleep(.3)
                control.write_text(json.dumps({'op':'freeze'}));await asyncio.sleep(1.8)
                frozen=await call(s,'app.control',dict(instance=iid,operation='view.live'))
                assert frozen['state']=='failed',frozen
                await asyncio.sleep(1)
            # Service restart does not need a GUI restart; the reverse bridge reconnects.
            server.terminate();server.wait(timeout=15)
            await boot()
            async with session() as s:
                reconnected=await wait_instance(s);assert reconnected==iid
                reconciled=await call(s,'commands.get',{'command_id':'choose-two'})
                assert reconciled['state']=='succeeded'
                control.write_text(json.dumps({'op':'close'}));gui.wait(timeout=5)
                assert len((await call(s,'clips.list'))['clips'])==1
                frame=await s.call_tool('frames.get',{'clip_id':clip,'ordinal':3})
                assert any(c.type=='image' for c in frame.content)
            c=storage.connect(path,readonly=True)
            assert storage.read_frame(c,clip,0)==frames[0].jpeg;c.close()
            print('MCP integration passed: authenticated HTTP, offline images/contact sheets/MP4/range links, '
                  'real GUI reverse bridge/view/playback, duplicate command, operator draft guard, '
                  'frozen GUI rejection, service restart/reconnect, offline access after GUI closes')
        except Exception:
            log.flush();print((root/'server.log').read_text()[-8000:]);raise
        finally:
            if gui and gui.poll() is None:gui.terminate();gui.wait(timeout=5)
            if server and server.poll() is None:server.terminate();server.wait(timeout=15)
            log.close()


if __name__=='__main__':asyncio.run(main())
