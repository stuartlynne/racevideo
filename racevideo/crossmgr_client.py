"""Read-only saved-race MCP client. Never unpickle CMNs in RaceVideo."""
import asyncio
from dataclasses import dataclass, field
from datetime import date
import json
import os
import time
from pathlib import Path


@dataclass
class Configuration:
    target: str = ''
    tool_names: dict = field(default_factory=dict)
    root: str = '~/wimsey_crossmgr/sl/2026/LMCX'
    url: str = 'http://127.0.0.1:8050/mcp'
    token_file: str = '~/.config/crossmgr-mcp/token'
    timezone: str = 'America/Vancouver'
    timezone_file: str = ''
    instance: str = ''
    live_race_path: str = ''

    @staticmethod
    def config_path():
        return Path(os.environ.get('RACEVIDEO_CROSSMGR_CONFIG', '~/.config/racevideo/crossmgr.json')).expanduser()

    @classmethod
    def targets(cls):
        path = cls.config_path()
        data = json.loads(path.read_text()) if path.exists() else {}
        return list(data.get('targets', {}))

    @classmethod
    def select(cls, target):
        path = cls.config_path()
        data = json.loads(path.read_text())
        if target not in data.get('targets', {}):
            raise ValueError('Unknown CrossMgr target: ' + target)
        if any(k in os.environ for k in ('CROSSMGR_MCP_URL', 'CROSSMGR_MCP_TOKEN_FILE', 'CROSSMGR_TARGET')):
            raise ValueError('Remove CrossMgr target/URL/token environment overrides before selecting a target')
        data['selected_target'] = target
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(path)
        return cls.load()

    @classmethod
    def load(cls):
        path = cls.config_path()
        values = json.loads(path.read_text()) if path.exists() else {}
        targets = values.pop('targets', {})
        selected = os.environ.get('CROSSMGR_TARGET', values.pop('selected_target', ''))
        if targets:
            selected = selected or next(iter(targets))
            if selected not in targets:
                raise ValueError('Unknown CrossMgr target: ' + selected)
            values.update(targets[selected])
            values['target'] = selected
        for field, env in dict(root='RACEVIDEO_CROSSMGR_ROOT', url='CROSSMGR_MCP_URL',
                              token_file='CROSSMGR_MCP_TOKEN_FILE', timezone='RACEVIDEO_RACE_TIMEZONE',
                              timezone_file='RACEVIDEO_RACE_TZFILE',instance='CROSSMGR_INSTANCE',live_race_path='CROSSMGR_LIVE_RACE_PATH').items():
            if env in os.environ: values[field] = os.environ[env]
        return cls(**values)


def discover(root, day):
    """Date-prefixed event directories, immediate CMNs only; no executable reads."""
    prefix = date.fromisoformat(day).strftime('%Y%m%d') + '-'
    base = Path(root).expanduser().resolve(strict=True)
    paths = []
    for directory in sorted(base.iterdir()):
        if directory.name.startswith(prefix) and directory.is_dir():
            for path in sorted(directory.iterdir()):
                if path.suffix.lower() == '.cmn' and path.is_file():
                    resolved = path.resolve(strict=True)
                    if not resolved.is_relative_to(base):
                        raise ValueError('CMN symlink leaves configured competition root')
                    paths.append(str(resolved))
    return paths


class Client:
    def __init__(self, config): self.config = config

    async def call(self, session, tool, arguments):
        result = await session.call_tool(self.config.tool_names.get(tool, tool), arguments)
        if result.isError:
            raise ValueError(next((c.text for c in result.content if c.type == 'text'), 'CrossMgr request failed'))
        data = result.structuredContent
        if data is None: data = json.loads(next(c.text for c in result.content if c.type == 'text'))
        # FastMCP versions can wrap a primitive return under result.
        if isinstance(data, dict) and set(data) == {'result'}: data = data['result']
        return data

    async def fetch_async(self, paths, callback):
        import httpx
        from datetime import timedelta
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        token = Path(self.config.token_file).expanduser().read_text().strip()
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + token}, timeout=90) as http:
            async with streamable_http_client(self.config.url, http_client=http) as (reader, writer, _):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=90)) as session:
                    await session.initialize()
                    for path in paths:
                        args = dict(path=path, trusted_pickle=True)
                        inspect = await self.call(session, 'race.inspect', args)
                        report = await self.call(session, 'race.review', dict(args, limit=500))
                        if inspect['inputs'] != report['inputs']:
                            raise ValueError('CMN/workbook changed during import; retry')
                        rows = report['race']['rows']
                        for offset in range(500, report['race']['total'], 500):
                            page = await self.call(session, 'race.review', dict(args, limit=500, offset=offset))
                            if page['inputs'] != report['inputs']:
                                raise ValueError('CMN/workbook changed between pages; retry')
                            rows.extend(page['race']['rows'])
                        callback(path, dict(inspect=inspect, review=report))

    def fetch(self, paths, callback):
        try: asyncio.run(self.fetch_async(paths, callback))
        except Exception as exc:
            while isinstance(exc, BaseExceptionGroup) and exc.exceptions: exc = exc.exceptions[0]
            raise ValueError('CrossMgr import failed: ' + str(exc)) from None

    async def live_session(self,session):
        """Read the current GUI model through its snapshot API; never edit it."""
        selection={}
        if self.config.instance:selection['instance']=self.config.instance
        if self.config.live_race_path:selection['race_path']=self.config.live_race_path
        identity=await self.call(session,'bridge.identity',selection)
        if not identity.get('race_path'):raise ValueError('CrossMgr has no saved current race')
        if identity.get('state') in ('none','unstarted'):raise ValueError('Current CrossMgr race has not started')
        if identity.get('state')=='finished' and getattr(self,'live_state',None)=='finished' and getattr(self,'live_signature',None) and self.live_signature[:2]==(identity['instance'],identity['race_path']):return self.live_result
        snapshot=await self.call(session,'bridge.snapshot',dict(instance=identity['instance'],race_path=identity['race_path']))
        if snapshot['race_path']!=identity['race_path'] or snapshot['instance']!=identity['instance']:raise ValueError('CrossMgr changed race during snapshot; retry')
        signature=(snapshot['instance'],snapshot['race_path'],snapshot['snapshot_sha256'])
        if signature==getattr(self,'live_signature',None) and time.monotonic()-self.live_checked<60:return self.live_result
        args=dict(path=snapshot['path'],trusted_pickle=True)
        inspected=await self.call(session,'race.inspect',args)
        reviewed=await self.call(session,'race.review',dict(args,limit=500))
        if inspected['inputs']!=reviewed['inputs']:raise ValueError('Snapshot/workbook changed; retry')
        for offset in range(500,reviewed['race']['total'],500):
            page=await self.call(session,'race.review',dict(args,limit=500,offset=offset))
            if page['inputs']!=reviewed['inputs']:raise ValueError('Workbook changed while paging; retry')
            reviewed['race']['rows'].extend(page['race']['rows'])
        result=dict(path=identity['race_path'],day=inspected['race']['date'],payload=dict(inspect=inspected,review=reviewed,
            live=dict(state=identity.get('state'),instance=snapshot['instance'],race_path=identity['race_path'],snapshot_path=snapshot['path'],captured_at=snapshot.get('captured_at'),revision=snapshot.get('revision'))))
        self.live_signature,self.live_result=signature,result;self.live_state=identity.get('state');self.live_checked=time.monotonic()
        return result

    async def fetch_live_async(self):
        import httpx
        from datetime import timedelta
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        token=Path(self.config.token_file).expanduser().read_text().strip()
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=30) as http:
            async with streamable_http_client(self.config.url,http_client=http) as (reader,writer,_):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=30)) as session:
                    await session.initialize();return await self.live_session(session)

    def fetch_live(self):
        try:return asyncio.run(self.fetch_live_async())
        except Exception as exc:
            while isinstance(exc,BaseExceptionGroup) and exc.exceptions:exc=exc.exceptions[0]
            raise ValueError('Live CrossMgr unavailable: '+str(exc)) from None
