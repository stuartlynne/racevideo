#!/usr/bin/env python3
"""Install user launchers and an optional MCP service after pip installation.

No root actions and no camera opening. Recordings live outside the source tree.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=Path.home()/'.local/share/racevideo/racevideo.sqlite3')
    p.add_argument('--service',action='store_true',help='Enable/start the user MCP service')
    p.add_argument('--desktop',action='store_true',help='Also place the launcher on the desktop')
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    python=root/'.venv/bin/python'
    if not python.exists():p.error('Create .venv and install .[ocr,mcp] first')
    db=args.db.expanduser().resolve();db.parent.mkdir(parents=True,exist_ok=True)
    # Initialize using the selected environment, never a global Python package.
    subprocess.run([str(python),'-c','from racevideo import storage; import sys; c=storage.connect(sys.argv[1]); storage.initialize(c); c.close()',str(db)],check=True)
    bin_dir=Path.home()/'.local/bin';bin_dir.mkdir(parents=True,exist_ok=True)
    launcher=bin_dir/'racevideo'
    launcher.write_text('#!/bin/sh\n# Managed by RaceVideo tools/install_user.py\n'
                        'export OMP_THREAD_LIMIT=1\nexport OPENBLAS_NUM_THREADS=1\n'
                        'cd '+shlex.quote(str(root))+'\n'
                        'exec '+shlex.quote(str(python))+' -m racevideo --db '+shlex.quote(str(db))+' --no-start "$@"\n')
    launcher.chmod(0o755)
    tool_launcher=bin_dir/'racevideo-tool'
    tool_launcher.write_text('#!/bin/sh\nexec '+shlex.quote(str(root/'.venv/bin/racevideo-tool'))+' "$@"\n')
    tool_launcher.chmod(0o755)
    text=f'''[Desktop Entry]
Type=Application
Name=RaceVideo
Comment=Race finish video capture and review
Exec="{launcher}"
Icon=camera-video
Terminal=false
Categories=AudioVideo;Video;
StartupNotify=true
'''
    apps=Path.home()/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    app=apps/'racevideo.desktop';app.write_text(text);app.chmod(0o755)
    if args.desktop:
        try:desktop=Path(subprocess.check_output(['xdg-user-dir','DESKTOP'],text=True).strip())
        except (OSError,subprocess.CalledProcessError):desktop=Path.home()/'Desktop'
        desktop.mkdir(parents=True,exist_ok=True)
        icon=desktop/'RaceVideo.desktop';icon.write_text(text);icon.chmod(0o755)
        environment=os.environ.copy()
        environment.setdefault('DBUS_SESSION_BUS_ADDRESS',f'unix:path=/run/user/{os.getuid()}/bus')
        try:
            result=subprocess.run(['gio','set',str(icon),'metadata::trusted','true'],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if result.returncode:print('Desktop may require right-click > Allow Launching; application-menu launcher is also installed.')
        except FileNotFoundError:pass
    if args.service:
        subprocess.run([str(python),'-m','racevideo_mcp.install_service','--db',str(db),'--enable','--start'],check=True)
    print(f'Application launcher: {launcher}')
    print(f'Recording store: {db}')
    print('The launcher opens Live/review without starting capture. Use Start recorder or MCP when the camera is configured.')


if __name__=='__main__':main()
