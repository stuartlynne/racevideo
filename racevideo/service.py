"""Start/reattach to the independent recorder from CLI or review UI."""
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys


OPTIONS = ('device', 'width', 'height', 'fps', 'trigger', 'interval', 'seconds',
           'buffer_mb', 'pre_roll', 'post_roll', 'motion_gap', 'motion_fps',
           'motion_delta', 'motion_fraction', 'event_mb', 'event_seconds','quiet_close')


def launch_worker(command,path,kind,log_path,cwd=None):
    """User-systemd children get their own unit; GUI/CLI retain detached processes."""
    if os.environ.get('RACEVIDEO_SYSTEMD_CHILDREN')=='1':
        identity=hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]
        unit=f'racevideo-{kind}-{identity}'
        subprocess.run(['systemd-run','--user','--quiet','--collect','--unit',unit,
            *(['--property=WorkingDirectory='+str(cwd)] if cwd else []),
            '--property=UMask=0077','--property=NoNewPrivileges=true',
            '--property=StandardOutput=append:'+str(log_path),
            '--property=StandardError=append:'+str(log_path),
            '--setenv=OMP_THREAD_LIMIT=1','--setenv=OPENBLAS_NUM_THREADS=1',
            '--',*command],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    else:
        with Path(log_path).open('a') as log:
            subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,cwd=cwd)


def recorder_running(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.recorder.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def start_recorder(path, options):
    path = Path(path).resolve()
    if recorder_running(path):
        return False
    from . import storage
    with storage.connect(path) as c:
        storage.initialize(c)
        saved=storage.read_setting(c,'capture_configuration',{})
    options={**saved,**options}
    command = [sys.executable, '-m', 'racevideo', 'record', '--db', str(path)]
    for name in OPTIONS:
        if name in options:
            command.extend(['--' + name.replace('_', '-'), str(options[name])])
    launch_worker(command,path,'recorder',path.with_suffix('.recorder.log'))
    profile={k:options[k] for k in ('device','width','height','fps') if k in options}
    if profile:storage.write_setting(path,'capture_configuration',profile)
    return True


def configuration(status):
    if status.get('configuration'):
        result={**status['configuration'],**status.get('capture_configuration',{})}
        if 'configured_quiet_close' in status:result['quiet_close']=status['configured_quiet_close']
        return result
    # Compatibility with an already-running recorder from before config storage.
    result = {key: status[key] for key in OPTIONS if key in status}
    if 'requested_fps' in status:
        result['fps'] = status['requested_fps']
    result.update(status.get('capture_configuration',{}))
    if 'configured_quiet_close' in status:result['quiet_close']=status['configured_quiet_close']
    return result


def neural_runtime():
    root=Path(__file__).resolve().parents[1]
    for name,device in (('.venv-ocr-paddle','gpu:0'),('.venv-ocr-cpu','cpu')):
        python=root/name/'bin/python'
        if python.exists():return str(python),device
    return None


def start_ocr(path,clip_id,parameters):
    from . import storage
    parameters=dict(parameters)
    c=storage.connect(path)
    try:
        engine=parameters.get('engine',storage.read_setting(c,'ocr_engine','tesseract'))
        if engine not in ('tesseract','paddle-rider-v1'):raise ValueError('Unknown OCR engine')
        parameters['number_lengths']=[1,2,3]
        if c.execute("SELECT 1 FROM bike_analyses WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('Wait for bike detection to finish before starting OCR')
        from .retention import settings
        parameters['retention']=settings(parameters.get('retention',storage.read_setting(c,'retention_settings',{})))
        if engine=='tesseract' and parameters['retention']['mode'] in ('bicycle','person_bicycle'):
            raise ValueError('Bike-based trim proposals require Neural OCR; choose road-motion proposals for Tesseract')
        if engine=='paddle-rider-v1':
            runtime=neural_runtime()
            if runtime is None:raise ValueError('Neural OCR runtime is not installed')
            models=Path(storage.read_setting(c,'neural_models_dir',str(Path.home()/'.paddlex/official_models')))
            if not (models/'PP-OCRv5_mobile_det').exists():raise ValueError('Neural model directory is not configured')
            parameters.setdefault('roi',storage.read_setting(c,'neural_ocr_area',[.05,.4,.98,.9]))
            parameters.pop('fps',None)
            parameters['all_frames']=True
            parameters.update(engine=engine,models_dir=str(models),device=runtime[1],detector_rotations=[0,90],recognizer_rotations=[0,90,180,270])
    finally:c.close()
    run_id=storage.create_ocr_run(path,clip_id,parameters)
    path=Path(path).resolve()
    try:
        command=([runtime[0],'-m','racevideo.neural_job','--db',str(path),'--run',str(run_id)] if engine=='paddle-rider-v1' else
                 [sys.executable,'-m','racevideo','ocr','--db',str(path),'--ocr-run',str(run_id)])
        launch_worker(command,path,f'ocr-{run_id}',path.with_suffix('.ocr.log'),cwd=Path(__file__).resolve().parents[1] if engine=='paddle-rider-v1' else None)
    except Exception as exc:
        c=storage.connect(path)
        with c:c.execute("UPDATE ocr_runs SET state='error',error=? WHERE id=?",(str(exc),run_id))
        c.close()
        raise
    return run_id


def start_retention(path,clip_id):
    import json,time
    from . import storage
    from .retention import settings
    c=storage.connect(path)
    try:
        p=settings(storage.read_setting(c,'retention_settings',{}))
        if p['mode']!='motion':raise ValueError('Choose road-motion proposals, or use Read plates to reuse neural bike detections')
        if c.execute("SELECT 1 FROM retention_proposals WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('A trim analysis is already queued/running')
        with c:
            run=c.execute("INSERT INTO retention_proposals(clip_id,created_ns,state,parameters) VALUES(?,?,'queued',?)",(clip_id,time.time_ns(),json.dumps(p))).lastrowid
        try:launch_worker([sys.executable,'-m','racevideo.retention','--db',str(Path(path).resolve()),'--proposal',str(run)],
            path,'retention',Path(path).with_suffix('.retention.log'),cwd=Path(__file__).resolve().parents[1])
        except Exception as exc:
            with c:c.execute("UPDATE retention_proposals SET state='error',error=? WHERE id=?",(str(exc),run))
            raise
        return run
    finally:c.close()


def start_bikes(path,clip_id=None,*,event_id=None,offset=0):
    import time
    from . import storage
    runtime=neural_runtime()
    if runtime is None:raise ValueError('Install the neural analysis runtime to detect bike passages')
    c=storage.connect(path)
    try:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM bike_analyses WHERE state IN ('queued','running') LIMIT 1").fetchone() or c.execute("SELECT 1 FROM ocr_runs WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('Wait for the current OCR/bike analysis to finish')
        models=Path(storage.read_setting(c,'neural_models_dir',str(Path.home()/'.paddlex/official_models')))
        if event_id is not None:
            import math,json
            if not math.isfinite(offset) or abs(offset)>86400:raise ValueError('Invalid clock offset')
            event=c.execute('SELECT start_ns,end_ns FROM race_events WHERE id=?',(event_id,)).fetchone()
            if event is None:raise ValueError('Event no longer exists')
            shift=round(offset*1e9)
            clips=[]
            from .bike_index import completed_analysis
            for row in c.execute('SELECT id FROM clips WHERE started_ns<=? AND ended_ns>=? ORDER BY started_ns,id',(event['end_ns']+shift,event['start_ns']+shift)):
                last=completed_analysis(c,row['id'])
                if last is None or json.loads(last['report']).get('policy')!='passage-v3':clips.append(row['id'])
        else:
            if not c.execute('SELECT 1 FROM clips WHERE id=?',(clip_id,)).fetchone():raise ValueError('Capture no longer exists')
            clips=[clip_id]
        if event_id is not None and clips:
            from .analysis_priority import plan
            rows=[dict(c.execute('SELECT id,started_ns,ended_ns FROM clips WHERE id=?',(ident,)).fetchone()) for ident in clips]
            clips=[r['clip_id'] for r in plan(c,event_id,rows,offset=offset)['tasks']]
        if not clips:c.commit();return [] if event_id is not None else None
        with c:runs=[c.execute("INSERT INTO bike_analyses(clip_id,created_ns,state) VALUES(?,?,'queued')",(clip,time.time_ns())).lastrowid for clip in clips]
        try:launch_worker([runtime[0],'-m','racevideo.bike_index','--db',str(Path(path).resolve()),'--analysis',*[str(run) for run in runs],'--models',str(models),'--device',runtime[1],*(['--event',str(event_id),'--offset',str(offset)] if event_id is not None else [])],
            path,'bikes',Path(path).with_suffix('.bikes.log'),cwd=Path(__file__).resolve().parents[1])
        except Exception as exc:
            with c:
                for run in runs:c.execute("UPDATE bike_analyses SET state='error',error=? WHERE id=?",(str(exc),run))
            raise
        return runs if event_id is not None else runs[0]
    finally:c.close()


def stop_event_bikes(path,event_id,offset=0):
    import math
    if not math.isfinite(offset) or abs(offset)>86400:raise ValueError('Invalid clock offset')
    from . import storage
    c=storage.connect(path)
    try:
        event=c.execute('SELECT start_ns,end_ns FROM race_events WHERE id=?',(event_id,)).fetchone()
        if event is None:raise ValueError('Event no longer exists')
        shift=round(offset*1e9)
        with c:
            return c.execute("""UPDATE bike_analyses SET state='cancelled' WHERE state='queued' AND clip_id IN
                (SELECT id FROM clips WHERE started_ns<=? AND ended_ns>=?)""",(event['end_ns']+shift,event['start_ns']+shift)).rowcount
    finally:c.close()
