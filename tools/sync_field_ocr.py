"""Durable, incremental GPU-results sync. Never transfers or writes the protected source."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from tools.import_field_ocr import import_directory
from tools.field_ocr_batch import atomic_json


def main():
    p=argparse.ArgumentParser();p.add_argument('database',type=Path);p.add_argument('directory',type=Path)
    p.add_argument('--remote',required=True);p.add_argument('--interval',type=float,default=20)
    p.add_argument('--supplement',type=Path,help='Additional atomic reports from an isolated CPU batch')
    a=p.parse_args()
    a.directory.mkdir(parents=True,exist_ok=True)
    while True:
        result=subprocess.run(['rsync','-a','--ignore-existing','-e','ssh -x -o BatchMode=yes -o ConnectTimeout=10',
            '--include=batch.json','--include=clip-*.json','--include=complete.json',
            '--exclude=*',a.remote.rstrip('/')+'/',str(a.directory)+'/'])
        progress_result=subprocess.run(['rsync','-a','-e','ssh -x -o BatchMode=yes -o ConnectTimeout=10',
            '--include=worker-*.json','--exclude=*',a.remote.rstrip('/')+'/',str(a.directory)+'/'])
        if a.supplement:
            for report in a.supplement.glob('clip-*.json'):
                try:os.link(report,a.directory/report.name)
                except FileExistsError:pass
        if result.returncode:
            print('Results sync temporarily unavailable; completed imports are retained.',flush=True)
        if (a.directory/'batch.json').exists():
            progress=import_directory(a.database,a.directory);progress['updated']=time.time()
            atomic_json(a.directory/'import-progress.json',progress);print(json.dumps(progress),flush=True)
            if progress['completed']==progress['total']:return
            workers=[json.loads(p.read_text()) for p in a.directory.glob('worker-*.json')]
            if not a.supplement and not progress_result.returncode and workers and all(w['state']=='complete' for w in workers) and any(w['errors'] for w in workers):
                raise SystemExit('GPU batch finished with failed clips; resume the GPU batch to retry')
        time.sleep(a.interval)


if __name__=='__main__':main()
