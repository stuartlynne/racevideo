"""Thin authenticated MCP client. Never starts a second standalone service."""
import argparse
import asyncio
import base64
import json
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import config_home


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('list','call'))
    p.add_argument('tool',nargs='?')
    p.add_argument('--arguments',default='{}')
    p.add_argument('--url')
    p.add_argument('--token-file',type=Path,default=config_home()/'token')
    p.add_argument('--output-dir',type=Path,help='Save returned images here instead of printing their base64')
    args=p.parse_args(argv)
    settings_path=config_home()/'service.json'
    settings=json.loads(settings_path.read_text()) if settings_path.exists() else {}
    url=args.url or settings.get('public_url') or f"http://127.0.0.1:{settings.get('port',8766)}/mcp"
    if not url.rstrip('/').endswith('/mcp'):url=url.rstrip('/')+'/mcp'
    async def run():
        token=args.token_file.read_text().strip()
        async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=45) as http:
            # Wait only for connection readiness. Never retry a tool mutation.
            origin=url.split('/mcp',1)[0]
            deadline=time.monotonic()+4
            while True:
                try:
                    response=await http.get(origin+'/health',timeout=1)
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                if time.monotonic()>=deadline:raise ConnectionError('Service HTTP endpoint is unavailable')
                await asyncio.sleep(.1)
            async with streamable_http_client(url,http_client=http) as (reader,writer,_):
                async with ClientSession(reader,writer) as session:
                    await session.initialize()
                    if args.action=='list':
                        tools=await session.list_tools()
                        print(json.dumps([dict(name=t.name,description=t.description) for t in tools.tools],indent=2));return 0
                    if not args.tool:p.error('call requires a tool name')
                    result=await session.call_tool(args.tool,json.loads(args.arguments))
                    images=[]
                    for i,block in enumerate(result.content):
                        if block.type=='image':
                            if args.output_dir:
                                args.output_dir.mkdir(parents=True,exist_ok=True)
                                path=args.output_dir/f'{args.tool.replace(".","-")}-{i}.jpg'
                                path.write_bytes(base64.b64decode(block.data));images.append(str(path.resolve()))
                            else:images.append('Image returned; use --output-dir to save it')
                    data=result.structuredContent
                    if data is None:
                        texts=[c.text for c in result.content if c.type=='text']
                        try:data=json.loads(texts[0]) if len(texts)==1 else texts
                        except (ValueError,IndexError):data=texts
                    print(json.dumps(dict(is_error=result.isError,result=data,images=images),indent=2))
                    return int(bool(result.isError))
    try:return asyncio.run(run())
    except Exception as exc:
        while isinstance(exc,BaseExceptionGroup) and exc.exceptions:exc=exc.exceptions[0]
        raise SystemExit(f'Cannot use RaceVideo MCP service: {exc}') from None


if __name__=='__main__':raise SystemExit(main())
