"""Install the persistent MCP server as the current user's systemd unit."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .config import config_home,state_home,private_write


def quote(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8766)
    p.add_argument('--public-url')
    p.add_argument('--enable',action='store_true');p.add_argument('--start',action='store_true')
    args=p.parse_args(argv)
    root=Path(__file__).resolve().parent.parent
    config_dir=config_home();state_dir=state_home()
    config=dict(host=args.host,port=args.port,stores={'default':str(args.db.expanduser().resolve())},
                config_dir=str(config_dir),state_dir=str(state_dir),public_url=args.public_url)
    config_file=config_dir/'service.json';private_write(config_file,json.dumps(config,indent=2)+'\n')
    unit_dir=Path.home()/'.config/systemd/user';unit_dir.mkdir(parents=True,exist_ok=True)
    unit=unit_dir/'racevideo-mcp.service'
    contents=f'''[Unit]
Description=RaceVideo MCP and reverse app bridge
After=network.target

[Service]
Type=simple
WorkingDirectory={str(root).replace('%','%%')}
ExecStart={quote(sys.executable)} -m racevideo_mcp.server --config {quote(config_file)}
Restart=on-failure
RestartSec=2
TimeoutStopSec=15
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
Environment=PYTHONUNBUFFERED=1
Environment=OMP_THREAD_LIMIT=1
Environment=OPENBLAS_NUM_THREADS=1
Environment=RACEVIDEO_SYSTEMD_CHILDREN=1

[Install]
WantedBy=default.target
'''
    unit.write_text(contents)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    if args.enable:subprocess.run(['systemctl','--user','enable','racevideo-mcp.service'],check=True)
    if args.start:subprocess.run(['systemctl','--user','restart','racevideo-mcp.service'],check=True)
    print(f'Installed {unit}')
    print(f'MCP URL: http://{args.host}:{args.port}/mcp')
    print(f'Bearer token file: {config_dir/"token"} (private; do not put its contents in logs)')
    print(f'App bootstrap: {config_dir/"bridge.json"}')


if __name__=='__main__':main()
