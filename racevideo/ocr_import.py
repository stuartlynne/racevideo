"""Import complete, atomic GPU clip reports into a writable review database.

Idempotent by batch/clip; original JPEGs and human reviews are preserved. Can run
repeatedly while the remote batch is still processing the remaining clips.
"""
import argparse
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from . import storage


def prepare(connection,manifest):
    created=0
    with connection:
        connection.execute("INSERT OR IGNORE INTO ocr_batches VALUES(?,?,?,?,?,?,?)",(manifest['batch_id'],time.time_ns(),time.time_ns(),'active',len(manifest['clips']),0,json.dumps(manifest['parameters'])))
        for clip in manifest['clips']:
            key=f'{manifest["batch_id"]}:{clip}'
            if connection.execute('SELECT 1 FROM ocr_imports WHERE import_key=?',(key,)).fetchone():continue
            row=connection.execute('SELECT frame_count FROM clips WHERE id=?',(clip,)).fetchone()
            if row is None:raise ValueError(f'Clip {clip} absent from review store')
            params=dict(manifest['parameters'],engine=manifest['engine'],batch_id=manifest['batch_id'],source='offline neural batch',device=manifest.get('device'))
            summary=dict(engine=manifest['engine'],batch_id=manifest['batch_id'],sampled_frames=0,total_samples=row[0])
            run=connection.execute('INSERT INTO ocr_runs(clip_id,created,state,parameters,summary) VALUES(?,?,?,?,?)',
                                   (clip,time.time(),'queued',json.dumps(params),json.dumps(summary))).lastrowid
            connection.execute('INSERT INTO ocr_imports VALUES(?,?,?,0)',(key,clip,run));created+=1
    return created


def import_clip(connection,report):
    import cv2
    import numpy as np
    from .plate_selection import crop_quad
    if report['state']!='complete':raise ValueError('Incomplete GPU report')
    clip=report['clip'];key=f'{report["batch_id"]}:{clip}'
    imported=connection.execute('SELECT i.*,r.state FROM ocr_imports i JOIN ocr_runs r ON r.id=i.run_id WHERE import_key=?',(key,)).fetchone()
    if imported is None:raise ValueError('Prepare the batch before importing clips')
    if imported['state']=='complete' and imported['imported_ns']:return False
    source=report['source_clip'];actual=connection.execute('SELECT id,started_ns,ended_ns,frame_count,width,height FROM clips WHERE id=?',(clip,)).fetchone()
    if actual is None or any(actual[k]!=source[k] for k in ('id','started_ns','ended_ns','frame_count','width','height')):raise ValueError(f'Clip {clip} belongs to different video data')
    frames=storage.frame_index(connection,clip)
    rows=report['results']
    if len(rows)!=len(frames) or len(rows)!=report['frames']:raise ValueError('Incomplete frame coverage')
    by_frame={}
    for row,frame in zip(rows,frames):
        if any(row[k]!=frame[k] for k in ('ordinal','received_ns','monotonic_ns')):raise ValueError('Frame identity/timestamp mismatch')
        by_frame[row['ordinal']]=row
    run=imported['run_id'];raw=[];observations=[]
    for row in rows:
        for reading in row['readings']:
            if not re.fullmatch('[0-9]{1,3}',reading['text']):raise ValueError('Invalid numeric OCR output')
            score=float(reading['score'])
            if not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid OCR score')
            raw.append((run,row['ordinal'],row['received_ns'],row['monotonic_ns'],reading['text'],round(score*100),
                        json.dumps(reading['quad']),reading['rotation'],'paddle-rider'))
    for encounter in report['encounters']:
        encounter_key=f'{key}:track:{encounter["track"]}'
        for alternative in encounter['consensus']['alternatives']:
            number=alternative['number'];supported={}
            for view in encounter['views']:
                for reading in view['readings']:
                    if reading['text']==number and reading['score']>=.85:
                        old=supported.get(view['ordinal'])
                        if old is None or old['score']<reading['score']:supported[view['ordinal']]=dict(reading,ordinal=view['ordinal'])
            if not supported:continue
            best=max(supported.values(),key=lambda r:r['score']);ordinal=best['ordinal']
            if ordinal not in by_frame:raise ValueError('Evidence frame outside clip report')
            image=cv2.imdecode(np.frombuffer(storage.read_frame(connection,clip,ordinal),np.uint8),cv2.IMREAD_COLOR)
            patch=crop_quad(image,best['quad'])
            if patch is None:raise ValueError('Invalid evidence crop')
            patch=np.ascontiguousarray(np.rot90(patch,best['rotation']//90))
            ok,evidence=cv2.imencode('.jpg',patch)
            if not ok:raise ValueError('Cannot encode evidence')
            first=min(by_frame[n]['received_ns'] for n in supported);last=max(by_frame[n]['received_ns'] for n in supported)
            status='ambiguous' if encounter['consensus']['status']=='ambiguous' else 'repeated' if len(supported)>=2 else 'candidate'
            observations.append((run,number,first,last,len(supported),round(best['score']*100),ordinal,json.dumps(best['quad']),evidence.tobytes(),status,encounter_key))
    parameters=json.loads(connection.execute('SELECT parameters FROM ocr_runs WHERE id=?',(run,)).fetchone()[0])
    device=report.get('device') or report.get('parameters',{}).get('device') or parameters.get('device')
    if device is None and parameters.get('source')=='zbook9 NVIDIA batch':device='gpu:0'
    parameters.update(source='all-frame neural scan',device=device)
    summary=dict(engine=report['engine'],batch_id=report['batch_id'],sampled_frames=report['frames'],total_samples=report['frames'],
                 raw_reads=len(raw),observations=len(observations),encounters=len(report['encounters']),wall_seconds=report['wall_seconds'],
                 cpu_seconds=report['cpu_seconds'],regions=report['regions'],device=device,provenance='All-frame neural scan; operator review required')
    with connection:
        connection.execute("UPDATE ocr_runs SET state='running',error=NULL WHERE id=?",(run,))
        connection.execute('DELETE FROM ocr_reads WHERE run_id=?',(run,))
        # A failed transaction never exposes incomplete evidence or replaces human decisions.
        if connection.execute('SELECT 1 FROM ocr_observations WHERE run_id=?',(run,)).fetchone():raise ValueError('Unexpected observations in unfinished import')
        connection.executemany('''INSERT INTO ocr_reads(run_id,ordinal,received_ns,monotonic_ns,number,confidence,quad,rotation,variant) VALUES(?,?,?,?,?,?,?,?,?)''',raw)
        connection.executemany('''INSERT INTO ocr_observations(run_id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,evidence,status,encounter_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',observations)
        connection.execute("UPDATE ocr_runs SET state='complete',summary=?,parameters=? WHERE id=?",(json.dumps(summary),json.dumps(parameters),run))
        connection.execute('UPDATE ocr_imports SET imported_ns=? WHERE import_key=?',(time.time_ns(),key))
        if report.get('retention_proposal'):
            from .retention import save
            save(connection,clip,report['retention_proposal'],source_run_id=run,commit=False)
        if report.get('bike_index'):
            from .bike_index import save
            save(connection,clip,report['bike_index'],source_run_id=run,commit=False)
    return True


def import_directory(path,directory):
    manifest=json.loads((directory/'batch.json').read_text());c=storage.connect(path)
    try:
        storage.initialize(c);prepared=prepare(c,manifest);count=0
        completed_keys={r[0] for r in c.execute("SELECT i.import_key FROM ocr_imports i JOIN ocr_runs r ON r.id=i.run_id WHERE i.imported_ns>0 AND r.state='complete'")}
        for clip in manifest['clips']:
            if f'{manifest["batch_id"]}:{clip}' in completed_keys:continue
            source=directory/f'clip-{clip}.json'
            if source.exists():count+=import_clip(c,json.loads(source.read_text()))
        # Publish remote progress without changing a previously completed result.
        for worker in directory.glob('worker-*.json'):
            state=json.loads(worker.read_text());clip=state.get('clip')
            if clip is not None:
                key=f'{manifest["batch_id"]}:{clip}'
                row=c.execute('SELECT run_id FROM ocr_imports WHERE import_key=?',(key,)).fetchone()
                if row:
                    summary=dict(engine=manifest['engine'],batch_id=manifest['batch_id'],sampled_frames=state.get('ordinal',0),total_samples=state.get('frames','?'))
                    with c:c.execute("UPDATE ocr_runs SET state='running',summary=? WHERE id=? AND state IN ('queued','running')",(json.dumps(summary),row[0]))
            for error in state.get('errors',[]):
                with c:c.execute("UPDATE ocr_runs SET state='error',error=? WHERE id=(SELECT run_id FROM ocr_imports WHERE import_key=?) AND state!='complete'",(error['error'],f'{manifest["batch_id"]}:{error["clip"]}'))
        total=c.execute("SELECT count(*) FROM ocr_imports WHERE import_key LIKE ? AND imported_ns>0",(manifest['batch_id']+':%',)).fetchone()[0]
        with c:c.execute("UPDATE ocr_batches SET updated_ns=?,state=?,completed_clips=? WHERE id=?",(time.time_ns(),'complete' if total==len(manifest['clips']) else 'active',total,manifest['batch_id']))
        return dict(batch_id=manifest['batch_id'],prepared=prepared,newly_imported=count,completed=total,total=len(manifest['clips']))
    finally:c.close()
