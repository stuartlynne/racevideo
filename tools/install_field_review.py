"""Install a review-only launcher for an existing writable test database."""
import argparse
import json
import os
from pathlib import Path
import shlex
import time
from racevideo import storage
from racevideo.service import recorder_running


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--clip',type=int,default=212)
    p.add_argument('--timezone-file',type=Path);p.add_argument('--models',type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];db=a.db.resolve()
    if not db.exists() or not os.access(db,os.W_OK):raise ValueError('Choose the writable review copy, not a backup')
    c=storage.connect(db)
    try:
        storage.initialize(c)
        if not c.execute('SELECT 1 FROM clips WHERE id=?',(a.clip,)).fetchone():raise ValueError('Initial review clip is absent')
        if not recorder_running(db):
            with c:c.execute('UPDATE runtime SET heartbeat=?,status=?,preview=NULL WHERE id=1',(time.time(),json.dumps(dict(state='stopped',frames=0))))
    finally:c.close()
    if a.models:storage.write_setting(db,'neural_models_dir',str(a.models.resolve()))
    storage.write_setting(db,'ocr_engine','paddle-rider-v1')
    bin_dir=Path.home()/'.local/bin';bin_dir.mkdir(parents=True,exist_ok=True)
    launcher=bin_dir/'racevideo-field-review'
    text='#!/bin/sh\n# Review-only: no camera capture starts automatically.\n'
    if a.timezone_file:
        if not a.timezone_file.exists():raise ValueError('Timezone file is absent')
        text+='export TZ='+shlex.quote(':'+str(a.timezone_file.resolve()))+'\n'
    text+='cd '+shlex.quote(str(root))+'\nexec '+shlex.quote(str(root/'.venv/bin/python'))+' -m racevideo --db '+shlex.quote(str(db))+' --no-start --review-clip '+str(a.clip)+' "$@"\n'
    launcher.write_text(text);launcher.chmod(0o755)
    apps=Path.home()/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    desktop=apps/'racevideo-field-review.desktop';desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=RaceVideo — 2026-11-08 review
Comment=Review OCR and operator bib evidence from the writable race-day test copy
Exec={launcher}
Icon=camera-video
Terminal=false
Categories=AudioVideo;Video;
''');desktop.chmod(0o755)
    print('Review launcher:',launcher)
    print('Review database:',db)


if __name__=='__main__':main()
