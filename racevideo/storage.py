"""One SQLite writer, short lived reader transactions, and original JPEG frames."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import json
import sqlite3
import time
from datetime import date, datetime, time as day_time, timedelta
import re

from PIL import Image


SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
 id INTEGER PRIMARY KEY, started_ns INTEGER NOT NULL, ended_ns INTEGER NOT NULL,
 trigger_ns INTEGER NOT NULL, reason TEXT NOT NULL, frame_count INTEGER NOT NULL,
 width INTEGER NOT NULL, height INTEGER NOT NULL, thumbnail BLOB NOT NULL,
 session TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frames (
 clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 ordinal INTEGER NOT NULL, received_ns INTEGER NOT NULL,
 monotonic_ns INTEGER NOT NULL, source_pts INTEGER, time_base TEXT,
 jpeg BLOB NOT NULL, PRIMARY KEY (clip_id, ordinal)
);
CREATE TABLE IF NOT EXISTS runtime (
 id INTEGER PRIMARY KEY CHECK (id=1), heartbeat REAL NOT NULL,
 status TEXT NOT NULL, preview BLOB
);
CREATE TABLE IF NOT EXISTS commands (
 id INTEGER PRIMARY KEY, created REAL NOT NULL,
 name TEXT NOT NULL CHECK (name IN ('capture','stop')),
 handled REAL
);
CREATE TABLE IF NOT EXISTS settings (
 name TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clip_details (
 clip_id INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
 metadata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS camera_requests (
 id INTEGER PRIMARY KEY, created REAL NOT NULL, session TEXT NOT NULL,
 control_id INTEGER NOT NULL, value INTEGER NOT NULL,
 processed REAL, actual INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS control_leases (
 id TEXT PRIMARY KEY, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ocr_runs (
 id INTEGER PRIMARY KEY, clip_id INTEGER NOT NULL REFERENCES clips(id),
 created REAL NOT NULL, state TEXT NOT NULL, parameters TEXT NOT NULL,
 summary TEXT NOT NULL DEFAULT '{}', error TEXT
);
CREATE TABLE IF NOT EXISTS ocr_reads (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES ocr_runs(id),
 ordinal INTEGER NOT NULL, received_ns INTEGER NOT NULL, monotonic_ns INTEGER NOT NULL,
 number TEXT NOT NULL, confidence INTEGER NOT NULL, quad TEXT NOT NULL,
 rotation INTEGER NOT NULL, variant TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ocr_reads_run ON ocr_reads(run_id);
CREATE TABLE IF NOT EXISTS ocr_observations (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES ocr_runs(id),
 number TEXT NOT NULL, first_ns INTEGER NOT NULL, last_ns INTEGER NOT NULL,
 frame_count INTEGER NOT NULL, confidence INTEGER NOT NULL, ordinal INTEGER NOT NULL,
 quad TEXT NOT NULL, evidence BLOB NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clip_annotations (
 clip_id INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
 starred INTEGER NOT NULL DEFAULT 0 CHECK(starred IN (0,1))
);
CREATE INDEX IF NOT EXISTS clips_started ON clips(started_ns);
CREATE INDEX IF NOT EXISTS ocr_runs_clip_state ON ocr_runs(clip_id,state,id);
CREATE INDEX IF NOT EXISTS ocr_observations_number ON ocr_observations(number,run_id);

"""

def _insert_video_matches(clip_expression=None):
    scope=f' AND r.clip_id={clip_expression}' if clip_expression else ''
    return f'''INSERT INTO video_tag_matches(tag_id,video_set_id,ocr_run_id,first_seen_ns,last_seen_ns,encounter_count,max_confidence)
      SELECT o.number,r.clip_id,r.id,MIN(o.first_ns),MAX(o.last_ns),COUNT(*),MAX(o.confidence)
      FROM ocr_runs r JOIN ocr_observations o ON o.run_id=r.id
      WHERE r.id=(SELECT MAX(r2.id) FROM ocr_runs r2 WHERE r2.clip_id=r.clip_id AND r2.state='complete'){scope}
      GROUP BY o.number,r.clip_id,r.id;'''


def _refresh_video_matches(clip_expression):
    return f'DELETE FROM video_tag_matches WHERE video_set_id={clip_expression};\n'+_insert_video_matches(clip_expression)


# A compact many-to-many lookup; detailed frame/encounter evidence stays in
# ocr_observations. Triggers keep it correct for both workers and SQL imports.
SCHEMA += '''
CREATE TABLE IF NOT EXISTS video_tag_matches (
 tag_id TEXT NOT NULL,
 video_set_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 ocr_run_id INTEGER NOT NULL REFERENCES ocr_runs(id) ON DELETE CASCADE,
 first_seen_ns INTEGER NOT NULL, last_seen_ns INTEGER NOT NULL,
 encounter_count INTEGER NOT NULL, max_confidence INTEGER NOT NULL,
 PRIMARY KEY(tag_id,video_set_id)
);
CREATE INDEX IF NOT EXISTS video_tag_matches_video ON video_tag_matches(video_set_id,tag_id);
CREATE VIEW IF NOT EXISTS today_video_tag_matches AS
 SELECT m.* FROM video_tag_matches m JOIN clips c ON c.id=m.video_set_id
 WHERE c.started_ns>=CAST(strftime('%s','now','localtime','start of day','utc') AS INTEGER)*1000000000
   AND c.started_ns<CAST(strftime('%s','now','localtime','start of day','+1 day','utc') AS INTEGER)*1000000000;

'''
for _name,_event,_condition,_clips in (
    ('ocr_run_match_insert','AFTER INSERT ON ocr_runs',"NEW.state='complete'",('NEW.clip_id',)),
    ('ocr_run_match_update','AFTER UPDATE OF state,clip_id ON ocr_runs','1',('OLD.clip_id','NEW.clip_id')),
    ('ocr_run_match_delete','AFTER DELETE ON ocr_runs','1',('OLD.clip_id',)),
    ('ocr_observation_match_insert','AFTER INSERT ON ocr_observations',
     "NEW.run_id=(SELECT MAX(id) FROM ocr_runs WHERE clip_id=(SELECT clip_id FROM ocr_runs WHERE id=NEW.run_id) AND state='complete')",
     ('(SELECT clip_id FROM ocr_runs WHERE id=NEW.run_id)',)),
    ('ocr_observation_match_update','AFTER UPDATE ON ocr_observations','1',
     ('(SELECT clip_id FROM ocr_runs WHERE id=OLD.run_id)','(SELECT clip_id FROM ocr_runs WHERE id=NEW.run_id)')),
    ('ocr_observation_match_delete','AFTER DELETE ON ocr_observations',
     "OLD.run_id=(SELECT MAX(id) FROM ocr_runs WHERE clip_id=(SELECT clip_id FROM ocr_runs WHERE id=OLD.run_id) AND state='complete')",
     ('(SELECT clip_id FROM ocr_runs WHERE id=OLD.run_id)',)),
):
    SCHEMA+=f'CREATE TRIGGER IF NOT EXISTS {_name} {_event} WHEN {_condition} BEGIN\n'+''.join(_refresh_video_matches(c) for c in _clips)+'\nEND;\n'



@dataclass(frozen=True)
class Frame:
    received_ns: int
    monotonic_ns: int
    source_pts: int | None
    time_base: str | None
    jpeg: bytes
    capture_bad_packets: int = 0  # Cumulative session counter at receipt; summarized per saved clip.


def connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path).expanduser().resolve()
    if readonly:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        raise RuntimeError(f"Unsupported database schema {version}")
    connection.executescript(SCHEMA)
    from . import passings
    connection.executescript(passings.SCHEMA)
    from . import passing_review
    connection.executescript(passing_review.SCHEMA)
    from . import retention
    connection.executescript(retention.SCHEMA)
    from . import bike_index
    connection.executescript(bike_index.SCHEMA)
    from . import wheel_timing
    connection.executescript(wheel_timing.SCHEMA)
    from . import bib_review
    bib_review.install(connection,version)
    with connection:
        connection.execute("INSERT OR IGNORE INTO settings(name,value) SELECT 'clip_id_high_water',CAST(COALESCE(MAX(id),0) AS TEXT) FROM clips")
    columns={r['name'] for r in connection.execute('PRAGMA table_info(camera_requests)')}
    with connection:
        for name,kind in (('expires','REAL'),('command_id','TEXT')):
            if name not in columns:connection.execute(f'ALTER TABLE camera_requests ADD COLUMN {name} {kind}')
        if version<8:
            connection.execute('DELETE FROM video_tag_matches')
            connection.execute(_insert_video_matches())
        connection.execute('PRAGMA user_version=11')


def thumbnail(jpeg: bytes) -> bytes:
    with Image.open(io.BytesIO(jpeg)) as image:
        image.thumbnail((180, 102))
        out = io.BytesIO()
        image.convert("RGB").save(out, "JPEG", quality=75)
        return out.getvalue()


def save_clip(connection, frames: list[Frame], trigger_ns: int, reason: str,
              width: int, height: int, session: str, metadata: dict | None = None) -> int:
    if not frames:
        raise ValueError("Cannot save an empty clip")
    thumb_frame = frames[len(frames) // 2]
    if metadata and metadata.get("first_motion_monotonic_ns") is not None:
        # A short passing followed by a 2s quiet tail often has an empty clip
        # midpoint. Choose the midpoint of the motion interval for its thumbnail.
        start = max(frames[0].monotonic_ns, metadata["first_motion_monotonic_ns"])
        end = min(frames[-1].monotonic_ns, metadata["last_motion_monotonic_ns"])
        target = (start + max(start, end)) // 2
        thumb_frame = min(frames, key=lambda f: abs(f.monotonic_ns - target))
    thumb = thumbnail(thumb_frame.jpeg)
    with connection:
        # Durable high water mark: deleting the newest clip must never reuse its
        # ID for different footage (including external MCP/export references).
        connection.execute("UPDATE settings SET value=CAST(MAX(CAST(value AS INTEGER),(SELECT COALESCE(MAX(id),0) FROM clips))+1 AS TEXT) WHERE name='clip_id_high_water'")
        clip_id=int(connection.execute("SELECT value FROM settings WHERE name='clip_id_high_water'").fetchone()[0])
        cursor = connection.execute(
            "INSERT INTO clips(id,started_ns,ended_ns,trigger_ns,reason,frame_count,"
            "width,height,thumbnail,session) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (clip_id, frames[0].received_ns, frames[-1].received_ns, trigger_ns, reason,
             len(frames), width, height, thumb, session))
        clip_id = cursor.lastrowid
        connection.executemany("INSERT INTO frames VALUES(?,?,?,?,?,?,?)", (
            (clip_id, i, f.received_ns, f.monotonic_ns, f.source_pts, f.time_base, f.jpeg)
            for i, f in enumerate(frames)))
        if metadata is not None:
            connection.execute("INSERT INTO clip_details VALUES(?,?)", (clip_id, json.dumps(metadata)))
    return clip_id


def publish(connection, status: dict, preview: bytes | None) -> None:
    with connection:
        connection.execute("INSERT INTO runtime VALUES(1,?,?,?) "
                           "ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,"
                           "status=excluded.status,preview=excluded.preview",
                           (time.time(), json.dumps(status), preview))


def read_runtime(connection) -> dict:
    row = connection.execute("SELECT * FROM runtime WHERE id=1").fetchone()
    if row is None:
        return {"state": "waiting", "heartbeat": 0, "preview": None}
    result = json.loads(row["status"])
    result.update(heartbeat=row["heartbeat"], preview=row["preview"])
    return result


def list_clips(connection, after: int = 0, limit: int | None = None) -> list[dict]:
    return [dict(row) for row in connection.execute(
        "SELECT * FROM clips WHERE id>? ORDER BY id LIMIT ?", (after, limit if limit is not None else -1))]


def frame_index(connection, clip_id: int) -> list[dict]:
    return [dict(row) for row in connection.execute(
        "SELECT ordinal,received_ns,monotonic_ns,source_pts,time_base FROM frames "
        "WHERE clip_id=? ORDER BY ordinal", (clip_id,))]


def read_frame(connection, clip_id: int, ordinal: int) -> bytes:
    row = connection.execute("SELECT jpeg FROM frames WHERE clip_id=? AND ordinal=?",
                             (clip_id, ordinal)).fetchone()
    if row is None:
        raise LookupError(f"No frame {ordinal} in clip {clip_id}")
    return row[0]


def command(path, name: str) -> None:
    connection = connect(path)
    try:
        with connection:
            connection.execute("INSERT INTO commands(created,name) VALUES(?,?)",
                               (time.time(), name))
    finally:
        connection.close()


def read_setting(connection, name, default=None):
    row = connection.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
    return json.loads(row[0]) if row else default


def write_setting(path, name, value):
    connection = connect(path)
    try:
        with connection:
            connection.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(name) "
                               "DO UPDATE SET value=excluded.value", (name, json.dumps(value)))
    finally:
        connection.close()


def request_camera_control(path, session, control_id, value, expires=None, command_id=None):
    connection = connect(path)
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO camera_requests(created,session,control_id,value,expires,command_id) VALUES(?,?,?,?,?,?)",
                (time.time(), session, control_id, value, expires, command_id))
        return cursor.lastrowid
    finally:
        connection.close()


def camera_results(connection, ids):
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return [dict(row) for row in connection.execute(
        f"SELECT * FROM camera_requests WHERE id IN ({placeholders}) AND processed IS NOT NULL ORDER BY id",
        list(ids))]


def renew_control_lease(path,lease_id):
    c=connect(path)
    try:
        with c:
            c.execute('INSERT INTO control_leases(id,expires,revoked) VALUES(?,?,0) '
                      'ON CONFLICT(id) DO UPDATE SET expires=excluded.expires WHERE revoked=0',(lease_id,time.time()+25))
            if c.execute('SELECT revoked FROM control_leases WHERE id=?',(lease_id,)).fetchone()[0]:
                raise ValueError('Operator released this agent control lease')
    finally:c.close()


def revoke_control_leases(path,lease_ids):
    c=connect(path)
    try:
        with c:
            c.executemany('INSERT INTO control_leases(id,expires,revoked) VALUES(?,?,1) '
                          'ON CONFLICT(id) DO UPDATE SET revoked=1,expires=excluded.expires',
                          ((lease_id,time.time()) for lease_id in lease_ids))
    finally:c.close()


def request_camera_batch(path,session,changes,expires,command_id):
    c=connect(path)
    try:
        with c:
            lease=c.execute('SELECT * FROM control_leases WHERE id=?',(command_id,)).fetchone()
            if not lease or lease['revoked'] or lease['expires']<time.time():raise ValueError('Agent camera lease is not active')
            ids=[]
            for change in changes:
                cursor=c.execute('INSERT INTO camera_requests(created,session,control_id,value,expires,command_id) '
                                 'VALUES(?,?,?,?,?,?)',(time.time(),session,change['id'],change['value'],expires,command_id))
                ids.append(cursor.lastrowid)
        return ids
    finally:c.close()


def validate_ocr_rotations(values):
    if not isinstance(values,(tuple,list)) or not values or any(type(v) is not int or v not in (0,180) for v in values):
        raise ValueError('OCR rotations must be [0], [180], or [0, 180]')
    return list(dict.fromkeys(values))


def create_ocr_run(path, clip_id, parameters):
    connection=connect(path)
    try:
        from .motion import validate_roi
        parameters=dict(parameters)
        # Freeze current choices into the job; later operator changes must not
        # silently alter what a queued scan processes.
        parameters['roi']=list(validate_roi(parameters.get('roi',read_setting(connection,'ocr_area',(0,0,1,1)))))
        parameters['rotations']=validate_ocr_rotations(parameters.get('rotations',read_setting(connection,'ocr_rotations',[0,180])))
        with connection:
            result=connection.execute('INSERT INTO ocr_runs(clip_id,created,state,parameters) VALUES(?,?,?,?)',
                                      (clip_id,time.time(),'queued',json.dumps(parameters)))
        return result.lastrowid
    finally:
        connection.close()


def read_ocr_run(connection, clip_id, run_id=None):
    row=(connection.execute('SELECT * FROM ocr_runs WHERE id=?',(run_id,)).fetchone() if run_id else
         connection.execute('SELECT * FROM ocr_runs WHERE clip_id=? ORDER BY id DESC LIMIT 1',(clip_id,)).fetchone())
    if not row:return None
    result=dict(row)
    result['summary']=json.loads(result['summary'])
    result['observations']=[dict(row) for row in connection.execute(
        'SELECT id,number,first_ns,last_ns,frame_count,confidence,ordinal,quad,status FROM ocr_observations '
        'WHERE run_id=? ORDER BY first_ns,id',(result['id'],))]
    return result


def local_day_bounds(day):
    """Local midnight boundaries; timestamps honor local DST, not fixed 24h days."""
    value=date.fromisoformat(day)
    return (int(datetime.combine(value,day_time()).timestamp()*1e9),
            int(datetime.combine(value+timedelta(days=1),day_time()).timestamp()*1e9))


def bib_numbers(text):
    values=tuple(dict.fromkeys(re.split(r'[\s,;]+',text.strip()))) if text.strip() else ()
    if any(not re.fullmatch(r'[0-9]{1,3}',value) for value in values):
        raise ValueError('Enter 1–3 digit bibs separated by spaces or commas, e.g. 7, 24, 333, 042')
    return values


def recording_dates(connection):
    return [r[0] for r in connection.execute("SELECT DISTINCT date(started_ns/1000000000.0,'unixepoch','localtime') FROM clips ORDER BY 1 DESC")]


def browse_clips(connection, day=None, bibs=(), starred_only=False, *, thumbnails=True, after_id=None, limit=None):
    clauses=[];params=[]
    if day:
        start,end=local_day_bounds(day);clauses+=['c.started_ns>=? AND c.started_ns<?'];params += [start,end]
    if starred_only:clauses+=['COALESCE(a.starred,0)=1']
    if bibs:
        if any(not re.fullmatch('[0-9]{1,3}',n) for n in bibs):raise ValueError('Invalid bib')
        clauses+=['EXISTS(SELECT 1 FROM reviewed_video_tag_matches m WHERE m.video_set_id=c.id AND m.tag_id IN ('+','.join('?' for n in bibs)+'))'];params+=list(bibs)
    if after_id is not None:
        clauses+=['c.id>?'];params.append(after_id)
    fields='c.*' if thumbnails else 'c.id,c.started_ns,c.ended_ns,c.trigger_ns,c.reason,c.frame_count,c.width,c.height,c.session'
    query=f'''SELECT {fields},COALESCE(a.starred,0) AS starred,
      (SELECT state FROM ocr_runs WHERE clip_id=c.id ORDER BY id DESC LIMIT 1) AS ocr_state,
      (SELECT GROUP_CONCAT(tag_id) FROM reviewed_video_tag_matches WHERE video_set_id=c.id) AS bibs,
      (SELECT GROUP_CONCAT(tag_id) FROM reviewed_video_tag_matches WHERE video_set_id=c.id AND confirmed_count>0) AS confirmed_bibs
      FROM clips c LEFT JOIN clip_annotations a ON a.clip_id=c.id'''
    if clauses:query+=' WHERE '+' AND '.join(clauses)
    query+=' ORDER BY c.id' if after_id is not None else ' ORDER BY c.started_ns,c.id'
    if limit is not None:
        query+=' LIMIT ?';params.append(limit)
    return [dict(r) for r in connection.execute(query,params)]


def set_star(path, clip_id, starred):
    c=connect(path)
    try:
        with c:c.execute('INSERT INTO clip_annotations VALUES(?,?) ON CONFLICT(clip_id) DO UPDATE SET starred=excluded.starred',(clip_id,int(bool(starred))))
    finally:c.close()


def cleanup_preview(connection, day):
    start,end=local_day_bounds(day)
    rows=[dict(r) for r in connection.execute('''SELECT c.id,c.frame_count,COALESCE(a.starred,0) AS starred,
      (EXISTS(SELECT 1 FROM ocr_runs r LEFT JOIN ocr_batches b ON b.id=json_extract(r.parameters,'$.batch_id') WHERE r.clip_id=c.id AND (r.state IN ('queued','running') OR b.state='active'))
       OR EXISTS(SELECT 1 FROM bike_analyses a WHERE a.clip_id=c.id AND a.state IN ('queued','running'))
       OR EXISTS(SELECT 1 FROM retention_proposals a WHERE a.clip_id=c.id AND a.state IN ('queued','running'))
       OR EXISTS(SELECT 1 FROM wheel_analyses a WHERE a.clip_id=c.id AND a.state IN ('queued','running'))) AS busy
      FROM clips c LEFT JOIN clip_annotations a ON a.clip_id=c.id WHERE c.started_ns>=? AND c.started_ns<? ORDER BY c.id''',(start,end))]
    selected=[r for r in rows if not r['starred'] and not r['busy']]
    return dict(day=day,ids=[r['id'] for r in selected],clips=len(selected),frames=sum(r['frame_count'] for r in selected),
                starred=sum(r['starred'] for r in rows),busy=sum(bool(r['busy']) and not r['starred'] for r in rows))


def delete_previewed(path, preview):
    """Delete only previewed IDs; recheck stars/date/active OCR in one transaction."""
    from .service import recorder_running
    c=connect(path)
    try:
        c.execute('BEGIN IMMEDIATE')
        if recorder_running(path) and read_runtime(c).get('storage_protocol',0)<7:
            raise ValueError('Restart the older recorder before deleting recordings')
        eligible=set(cleanup_preview(c,preview['day'])['ids'])
        ids=sorted(eligible.intersection(preview['ids']))
        # Also protect IDs allocated by a recorder that predated this migration.
        c.execute("UPDATE settings SET value=CAST(MAX(CAST(value AS INTEGER),(SELECT COALESCE(MAX(id),0) FROM clips)) AS TEXT) WHERE name='clip_id_high_water'")
        for clip_id in ids:
            c.execute("UPDATE ocr_runs SET state='deleting' WHERE clip_id=?",(clip_id,))
            for table in ('ocr_reads','ocr_observations'):
                c.execute(f'DELETE FROM {table} WHERE run_id IN (SELECT id FROM ocr_runs WHERE clip_id=?)',(clip_id,))
            c.execute('DELETE FROM ocr_runs WHERE clip_id=?',(clip_id,))
            c.execute('DELETE FROM clips WHERE id=?',(clip_id,))
        c.commit()
        return dict(deleted=ids,skipped=len(preview['ids'])-len(ids))
    except Exception:
        c.rollback();raise
    finally:c.close()


def bib_passages(connection,day=None,bibs=(),starred_only=False):
    from . import bib_review
    clips=browse_clips(connection,day,bibs,starred_only,thumbnails=False)
    grouped={}
    for clip in clips:
        for row in bib_review.list_rows(connection,clip['id']):
            if row.get('decision')=='rejected' or bibs and row['number'] not in bibs:continue
            item=dict(row);item['clip_id']=clip['id'];item['machine_status']=item['status']
            item['status']=item.get('decision') or item['status']
            if item['observation_id'] is None:item['id']=item['row_key']
            key=(clip['id'],item['number'],item.get('encounter_key') or 'ocr:'+str(item['observation_id']))
            old=grouped.get(key)
            if old is None or item.get('decision') and not old.get('decision'):grouped[key]=item
    merged=[]
    for item in sorted(grouped.values(),key=lambda r:(r['first_ns'],str(r['id']))):
        old=next((r for r in merged if r['clip_id']==item['clip_id'] and r['number']==item['number'] and r.get('run_id')!=item.get('run_id') and (r.get('decision') or item.get('decision')) and r['first_ns']<=item['last_ns'] and item['first_ns']<=r['last_ns']),None)
        if old is None:merged.append(item)
        else:
            first,last=min(old['first_ns'],item['first_ns']),max(old['last_ns'],item['last_ns'])
            support=old.get('supporting_observation_ids',[old['id']])+[item['id']]
            if item.get('decision') and not old.get('decision'):old.update(item)
            old.update(first_ns=first,last_ns=last,supporting_observation_ids=support)
    return sorted(merged,key=lambda r:(r['first_ns'],str(r['id'])))
