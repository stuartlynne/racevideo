"""One optional neural analysis subprocess; never imported by the GUI/capture path."""
import os
os.environ.pop('OMP_THREAD_LIMIT',None)
os.environ['OMP_NUM_THREADS']='2'
os.environ.setdefault('DISABLE_MODEL_SOURCE_CHECK','True')
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
import argparse
import fcntl
import json
from pathlib import Path
import time
from . import storage


def run(path,run_id):
    # Pick distinct physical cores, rather than two SMT siblings.
    selected=[];seen=set()
    for cpu in sorted(os.sched_getaffinity(0)):
        folder=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        try:key=(folder.joinpath('physical_package_id').read_text(),folder.joinpath('core_id').read_text())
        except OSError:key=(cpu,)
        if key not in seen:selected.append(cpu);seen.add(key)
        if len(selected)==2:break
    os.sched_setaffinity(0,set(selected))
    from .neural_ocr import Scanner
    from .ocr_import import import_clip
    writer=storage.connect(path);reader=storage.connect(path,readonly=True)
    lock=open(str(Path(path).resolve())+'.ocr.lock','a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        row=writer.execute('SELECT * FROM ocr_runs WHERE id=?',(run_id,)).fetchone()
        if row is None:raise ValueError('Unknown OCR job')
        parameters=json.loads(row['parameters']);clip=row['clip_id'];batch_id=f'neural-job-{run_id}-{int(row["created"]*1000000)}'
        key=f'{batch_id}:{clip}'
        count=writer.execute('SELECT frame_count FROM clips WHERE id=?',(clip,)).fetchone()[0]
        def progress(ordinal,total):
            with writer:writer.execute("UPDATE ocr_runs SET state='running',summary=? WHERE id=?",(json.dumps(dict(engine='paddle-v5-rider-native-v2',sampled_frames=ordinal,total_samples=total)),run_id))
        progress(0,count)
        scanner=Scanner(Path(parameters['models_dir']),parameters['device'],parameters,cpu_threads=2)
        report=scanner.scan(reader,clip,progress)
        report.update(batch_id=batch_id,engine='paddle-v5-rider-native-v2',parameters=parameters)
        with writer:writer.execute('INSERT INTO ocr_imports VALUES(?,?,?,0)',(key,clip,run_id))
        import_clip(writer,report)
    except Exception as error:
        with writer:writer.execute("UPDATE ocr_runs SET state='error',error=? WHERE id=?",(str(error),run_id))
        raise
    finally:lock.close();reader.close();writer.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--run',type=int,required=True);a=p.parse_args();run(a.db,a.run)


if __name__=='__main__':main()
