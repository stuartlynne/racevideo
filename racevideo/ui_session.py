"""Small, host-local review state alongside each recording database."""
import json
import os
from pathlib import Path


def filename(database):return Path(str(Path(database).resolve())+'.ui.json')

def load(database):
    try:
        data=json.loads(filename(database).read_text())
        return data if isinstance(data,dict) and data.get('version')==1 else {}
    except (OSError,ValueError):return {}


def save(database,state):
    target=filename(database);temporary=target.with_name(target.name+'.'+str(os.getpid())+'.tmp')
    try:
        temporary.write_text(json.dumps(state));temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)
