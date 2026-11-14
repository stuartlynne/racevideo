"""Resumable all-frame NVIDIA/CPU field scan. Read-only video input, atomic per-clip results.

Two independent workers can share the A1000; no AMD runtime is used. The files
are imported separately into the writable review store. Models stay warm.
"""
import os
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
import argparse
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import sqlite3
import time
import traceback


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, separators=(',', ':')) + '\n')
    os.replace(temporary, path)


from racevideo.neural_ocr import Scanner


def worker(worker_id, args, clips, manifest):
    allowed=set(map(int,args.cpu_sets[worker_id].split(',')))
    os.sched_setaffinity(0,allowed)
    connection=sqlite3.connect(args.store.resolve().as_uri()+'?mode=ro',uri=True)
    scanner=None;done=0;errors=[];started=time.time()
    def status(**extra):
        atomic_json(args.output/f'worker-{worker_id}.json',dict(worker=worker_id,pid=os.getpid(),completed=done,total=len(clips),errors=errors,started=started,updated=time.time(),**extra))
    try:
        for clip in clips:
            destination=args.output/f'clip-{clip}.json'
            if args.completed_directory:
                published=args.completed_directory/f'clip-{clip}.json'
                if published.exists():
                    prior=json.loads(published.read_text())
                    if prior.get('state')=='complete' and prior.get('batch_id')==manifest['batch_id']:
                        done+=1;status(state='running',clip=clip,skipped=True);continue
            if destination.exists():
                prior=json.loads(destination.read_text())
                if prior.get('state')=='complete' and prior.get('batch_id')==manifest['batch_id']:
                    done+=1;status(state='running',clip=clip,skipped=True);continue
            try:
                if scanner is None:scanner=Scanner(args.models,args.device)
                status(state='running',clip=clip,ordinal=0)
                result=scanner.scan(connection,clip,lambda ordinal,total:status(state='running',clip=clip,ordinal=ordinal,frames=total))
                result.update(batch_id=manifest['batch_id'],engine=manifest['engine'],parameters=manifest['parameters'])
                atomic_json(destination,result);done+=1;status(state='running',clip=clip)
                print(f'worker {worker_id}: clip {clip}, {result["frames"]} frames, {len(result["encounters"])} tracks, {result["wall_seconds"]:.1f}s',flush=True)
            except Exception as error:
                errors.append(dict(clip=clip,error=str(error)));status(state='running',clip=clip)
                traceback.print_exc()
        status(state='complete')
    finally:connection.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('store',type=Path);p.add_argument('--models',type=Path,required=True)
    p.add_argument('--day',default='2026-11-08');p.add_argument('--device',default='gpu:0');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cpu-sets',nargs='+',default=['0','2']);p.add_argument('--clips',type=int,nargs='+')
    p.add_argument('--reverse',action='store_true',help='Process newest clips first; does not change batch identity')
    p.add_argument('--completed-directory',type=Path,help='Skip matching reports already published by another host')
    a=p.parse_args()
    import fcntl
    a.output.mkdir(parents=True,exist_ok=True);lock=(a.output/'batch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    c=sqlite3.connect(a.store.resolve().as_uri()+'?mode=ro',uri=True)
    clips=a.clips or [r[0] for r in c.execute("SELECT id FROM clips WHERE date(started_ns/1000000000,'unixepoch','localtime')=? ORDER BY id",(a.day,))];c.close()
    parameters=dict(profile='rider-native-v2',number_lengths=[1,2,3],roi=[.05,.4,.98,.9],detector_rotations=[0,90],recognizer_rotations=[0,90,180,270],detector_limit=960,min_score=.85,minimum_frames=3,maximum_gap=8)
    identity=dict(source_bytes=a.store.stat().st_size,clips=clips,parameters=parameters,engine='paddle-v5-rider-native-v2')
    manifest_path=a.output/'batch.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if any(manifest[k]!=v for k,v in identity.items()):raise ValueError('Existing batch uses different source or parameters')
    else:
        manifest=dict(identity,device=a.device,batch_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:24],source=str(a.store.resolve()),created_utc=datetime.now(timezone.utc).isoformat())
        atomic_json(manifest_path,manifest)
    ctx=mp.get_context('spawn');processes=[]
    scheduled=list(reversed(clips)) if a.reverse else clips
    for i in range(len(a.cpu_sets)):
        child=ctx.Process(target=worker,args=(i,a,scheduled[i::len(a.cpu_sets)],manifest));child.start();processes.append(child)
    for child in processes:child.join()
    if any(child.exitcode for child in processes):raise SystemExit('A GPU worker exited; completed clips are retained for resume')
    summaries=[json.loads((a.output/f'worker-{i}.json').read_text()) for i in range(len(a.cpu_sets))]
    if any(row['errors'] for row in summaries):raise SystemExit('Some clips failed; rerun the same command to retry')
    atomic_json(a.output/'complete.json',dict(batch_id=manifest['batch_id'],clips=len(clips),completed_utc=datetime.now(timezone.utc).isoformat()))


if __name__=='__main__':main()
