import json
import os
from pathlib import Path
import secrets


def config_home():
    return Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'racevideo-mcp'


def state_home():
    return Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'racevideo-mcp'


def private_write(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)
    os.replace(temp,path)


def token(path):
    path=Path(path)
    if not path.exists():private_write(path,secrets.token_urlsafe(32)+'\n')
    if path.stat().st_mode & 0o077:raise ValueError(f'Token file must be private: {path}')
    value=path.read_text().strip()
    if not value or any(c.isspace() for c in value):raise ValueError('Token must be a nonempty single value')
    return value


def bootstrap(path,url,bridge_token,service_id):
    private_write(path,json.dumps(dict(protocol=1,url=url,token=bridge_token,service_id=service_id))+'\n')
