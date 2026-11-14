import asyncio
import json
import os
import time
import uuid

from starlette.websockets import WebSocketDisconnect


class Hub:
    def __init__(self,journal,stores):
        self.journal=journal;self.stores=stores
        self.instances={};self.pending={}

    def ready(self,instance):
        return (instance.get('connected') and time.monotonic()-instance.get('last_net',0)<1.5
                and time.monotonic()-instance.get('last_progress',0)<1.5)

    def list(self):
        result=[]
        for iid,item in self.instances.items():
            result.append(dict(instance=iid,store=item['store'],pid=item['pid'],connected=item['connected'],
                               responsive=self.ready(item),closed=item.get('closed',False),snapshot=item.get('snapshot',{})))
        return result

    def for_store(self,store):
        result=[]
        for iid,item in self.instances.items():
            if item['store']!=store or item.get('closed'):continue
            try:os.kill(item['pid'],0)
            except ProcessLookupError:continue
            except PermissionError:pass
            if not self.ready(item):raise ValueError('A registered GUI is disconnected or unresponsive; reconcile it first')
            result.append(iid)
        return result

    async def call(self,iid,operation,arguments=None,command_id=None,timeout=6):
        arguments=arguments or {};cid=command_id or uuid.uuid4().hex
        record,new=self.journal.command(cid,iid,operation,arguments)
        if not new:return record
        instance=self.instances.get(iid)
        if not instance or not self.ready(instance):
            self.journal.command_result(cid,'failed',error='GUI is not connected and responsive')
            return self.journal.get_command(cid)
        future=asyncio.get_running_loop().create_future();self.pending[cid]=(iid,future)
        try:
            self.journal.command_result(cid,'sent')
            await instance['ws'].send_json(dict(type='command',id=cid,operation=operation,arguments=arguments,
                                                expires_at=time.time()+2))
            await asyncio.wait_for(asyncio.shield(future),timeout)
        except asyncio.CancelledError:
            self.journal.command_result(cid,'unknown',error='Caller cancelled before outcome reconciliation')
            raise
        except Exception:
            self.journal.command_result(cid,'unknown',error='Reply unavailable; do not replay; inspect command status')
        finally:self.pending.pop(cid,None)
        return self.journal.get_command(cid)

    async def websocket(self,ws):
        await ws.accept();item=None;iid=None
        try:
            hello=await asyncio.wait_for(ws.receive_json(),3)
            if hello.get('type')!='hello' or hello.get('protocol')!=1:raise ValueError('Unsupported bridge handshake')
            iid=str(hello['instance'])
            if len(iid)!=32 or any(c not in '0123456789abcdef' for c in iid):raise ValueError('Invalid instance ID')
            store=next((name for name,path in self.stores.items() if str(path)==hello['database']),None)
            if store is None:raise ValueError('Database is not configured in this service')
            old=self.instances.get(iid)
            if old and old.get('connected'):await old['ws'].close(code=1000)
            item=dict(ws=ws,store=store,pid=int(hello['pid']),connected=True,closed=False,
                      last_net=time.monotonic(),last_progress=0,snapshot={})
            self.instances[iid]=item
            while True:
                message=await ws.receive_json();item['last_net']=time.monotonic()
                if message.get('type')=='heartbeat':
                    snapshot=message.get('snapshot',{})
                    if snapshot.get('gui_tick')!=item['snapshot'].get('gui_tick'):
                        item['last_progress']=time.monotonic()
                    item['snapshot']=snapshot
                elif message.get('type')=='result':
                    cid=message['id']
                    try:record=self.journal.get_command(cid)
                    except ValueError:continue
                    if record['target']!=iid:continue
                    self.journal.command_result(cid,'failed' if message.get('error') else 'succeeded',
                                                message.get('result'),message.get('error'))
                    if cid in self.pending and not self.pending[cid][1].done():self.pending[cid][1].set_result(True)
                elif message.get('type')=='goodbye':
                    item['closed']=True;break
        except (WebSocketDisconnect,asyncio.TimeoutError):pass
        except Exception:
            await ws.close(code=1008)
        finally:
            if item is not None:item['connected']=False
