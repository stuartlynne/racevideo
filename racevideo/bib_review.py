"""Operator bib decisions alongside immutable OCR evidence. No race-result writes."""
import json
import re
import math
import time

REVIEW_TABLE = '''
CREATE TABLE IF NOT EXISTS bib_reviews (
 id INTEGER PRIMARY KEY,
 clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 observation_id INTEGER UNIQUE REFERENCES ocr_observations(id) ON DELETE SET NULL,
 original_number TEXT NOT NULL,
 number TEXT,
 decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected','corrected','manual')),
 ordinal INTEGER NOT NULL, received_ns INTEGER NOT NULL,
 first_ns INTEGER NOT NULL, last_ns INTEGER NOT NULL,
 encounter_key TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL DEFAULT 'operator',
 provenance TEXT NOT NULL,
 created_ns INTEGER NOT NULL, updated_ns INTEGER NOT NULL,
 CHECK((decision='rejected' AND number IS NULL) OR
       (decision!='rejected' AND length(number) BETWEEN 1 AND 3 AND number NOT GLOB '*[^0-9]*'))
);
'''

SCHEMA = REVIEW_TABLE + '''
CREATE INDEX IF NOT EXISTS bib_reviews_clip ON bib_reviews(clip_id,updated_ns);
CREATE INDEX IF NOT EXISTS bib_reviews_number ON bib_reviews(number,clip_id);
CREATE TABLE IF NOT EXISTS bib_review_history (
 id INTEGER PRIMARY KEY, clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 review_id INTEGER, observation_id INTEGER, changed_ns INTEGER NOT NULL,
 actor TEXT NOT NULL, action TEXT NOT NULL, previous TEXT, current TEXT
);
CREATE INDEX IF NOT EXISTS bib_review_history_review ON bib_review_history(review_id);
CREATE TABLE IF NOT EXISTS reviewed_video_tag_matches (
 tag_id TEXT NOT NULL, video_set_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 ocr_run_id INTEGER REFERENCES ocr_runs(id) ON DELETE SET NULL,
 first_seen_ns INTEGER NOT NULL, last_seen_ns INTEGER NOT NULL,
 encounter_count INTEGER NOT NULL, max_confidence INTEGER NOT NULL,
 confirmed_count INTEGER NOT NULL,
 PRIMARY KEY(tag_id,video_set_id)
);
CREATE VIEW IF NOT EXISTS today_reviewed_video_tag_matches AS
 SELECT m.* FROM reviewed_video_tag_matches m JOIN clips c ON c.id=m.video_set_id
 WHERE c.started_ns>=CAST(strftime('%s','now','localtime','start of day','utc') AS INTEGER)*1000000000
 AND c.started_ns<CAST(strftime('%s','now','localtime','start of day','+1 day','utc') AS INTEGER)*1000000000;
CREATE INDEX IF NOT EXISTS reviewed_matches_video ON reviewed_video_tag_matches(video_set_id,tag_id);
CREATE INDEX IF NOT EXISTS ocr_observations_run ON ocr_observations(run_id);
CREATE TABLE IF NOT EXISTS ocr_batches (
 id TEXT PRIMARY KEY, created_ns INTEGER NOT NULL, updated_ns INTEGER NOT NULL,
 state TEXT NOT NULL, total_clips INTEGER NOT NULL, completed_clips INTEGER NOT NULL, parameters TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ocr_imports (
 import_key TEXT PRIMARY KEY, clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 run_id INTEGER NOT NULL REFERENCES ocr_runs(id) ON DELETE CASCADE,
 imported_ns INTEGER NOT NULL
);
'''


def effective_evidence(clip_expression=None):
    raw_scope = ' AND r.clip_id=' + clip_expression if clip_expression else ''
    human_scope = ' AND b.clip_id=' + clip_expression if clip_expression else ''
    return f'''
      SELECT o.number AS tag_id,r.clip_id AS video_set_id,r.id AS ocr_run_id,
             o.first_ns,o.last_ns,COALESCE(o.encounter_key,'ocr:'||o.id) AS encounter_key,
             o.confidence,0 AS confirmed
      FROM ocr_runs r JOIN ocr_observations o ON o.run_id=r.id
      LEFT JOIN bib_reviews b ON b.observation_id=o.id
      WHERE r.id=(SELECT MAX(id) FROM ocr_runs WHERE clip_id=r.clip_id AND state='complete')
        AND b.id IS NULL
        AND NOT EXISTS(SELECT 1 FROM bib_reviews h WHERE h.clip_id=r.clip_id AND h.number=o.number AND h.decision!='rejected' AND h.first_ns<=o.last_ns AND h.last_ns>=o.first_ns) {raw_scope}
      UNION ALL
      SELECT b.number,b.clip_id,o.run_id,b.first_ns,b.last_ns,b.encounter_key,
             COALESCE(o.confidence,0),1
      FROM bib_reviews b LEFT JOIN ocr_observations o ON o.id=b.observation_id
      WHERE b.decision!='rejected' {human_scope}
    '''


def refresh_sql(clip_expression=None):
    scope=' WHERE video_set_id='+clip_expression if clip_expression else ''
    return 'DELETE FROM reviewed_video_tag_matches'+scope+';\n'+f'''
      INSERT INTO reviewed_video_tag_matches
      SELECT tag_id,video_set_id,MAX(ocr_run_id),MIN(first_ns),MAX(last_ns),
             COUNT(DISTINCT encounter_key),MAX(confidence),COUNT(DISTINCT CASE WHEN confirmed=1 THEN encounter_key END)
      FROM ({effective_evidence(clip_expression)}) GROUP BY tag_id,video_set_id;
    '''


def install(connection, previous_version):
    columns={row[1] for row in connection.execute('PRAGMA table_info(ocr_observations)')}
    if 'encounter_key' not in columns:
        connection.execute('ALTER TABLE ocr_observations ADD COLUMN encounter_key TEXT')
        connection.commit()
    migrations=[]
    if previous_version<11:
        migrations.extend('DROP TRIGGER '+row[0]+';' for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'reviewed_%'"))
    if previous_version<11 and connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bib_reviews'").fetchone():
        migrations.extend((REVIEW_TABLE.replace('IF NOT EXISTS bib_reviews','bib_reviews_v11'),
                           'INSERT INTO bib_reviews_v11 SELECT * FROM bib_reviews;',
                           'DROP TABLE bib_reviews;', 'ALTER TABLE bib_reviews_v11 RENAME TO bib_reviews;'))
    migrations.append(SCHEMA)
    for name,event,clips in (
        ('reviewed_run_insert','AFTER INSERT ON ocr_runs',('NEW.clip_id',)),
        ('reviewed_run_update','AFTER UPDATE OF state,clip_id ON ocr_runs',('OLD.clip_id','NEW.clip_id')),
        ('reviewed_run_delete','AFTER DELETE ON ocr_runs',('OLD.clip_id',)),
        ('reviewed_obs_insert','AFTER INSERT ON ocr_observations',('(SELECT clip_id FROM ocr_runs WHERE id=NEW.run_id)',)),
        ('reviewed_obs_update','AFTER UPDATE ON ocr_observations',('(SELECT clip_id FROM ocr_runs WHERE id=OLD.run_id)','(SELECT clip_id FROM ocr_runs WHERE id=NEW.run_id)')),
        ('reviewed_obs_delete','AFTER DELETE ON ocr_observations',('(SELECT clip_id FROM ocr_runs WHERE id=OLD.run_id)',)),
        ('reviewed_human_insert','AFTER INSERT ON bib_reviews',('NEW.clip_id',)),
        ('reviewed_human_update','AFTER UPDATE ON bib_reviews',('OLD.clip_id','NEW.clip_id')),
        ('reviewed_human_delete','AFTER DELETE ON bib_reviews',('OLD.clip_id',)),
    ):
        migrations.append(f'CREATE TRIGGER IF NOT EXISTS {name} {event} BEGIN\n'+''.join(refresh_sql(clip) for clip in clips)+'\nEND;')
    if previous_version<11:migrations.append(refresh_sql())
    connection.executescript('BEGIN IMMEDIATE;\n'+'\n'.join(migrations)+'\nCOMMIT;')


def validate_number(number):
    if not isinstance(number,str) or not re.fullmatch('[0-9]{1,3}',number):
        raise ValueError('Enter 1–3 digits, retaining leading zeroes, e.g. 7, 24, 042')
    return number


def validate_bike(box=None,order=None):
    if box is not None:
        if not isinstance(box,(tuple,list)) or len(box)!=4:raise ValueError('Mark a rectangle around one bike')
        box=list(map(float,box))
        if not all(math.isfinite(v) for v in box) or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):
            raise ValueError('Bike rectangle must lie inside the source image')
    if order is not None and (type(order) is not int or not 1<=order<=999):raise ValueError('Bike order must be 1–999 within this capture')
    return box,order


def list_rows(connection,clip_id):
    """Latest machine candidates plus durable reviewed history and manual entries."""
    latest=connection.execute("SELECT MAX(id) FROM ocr_runs WHERE clip_id=? AND state='complete'",(clip_id,)).fetchone()[0]
    rows=[]
    for row in connection.execute('''SELECT o.*,r.clip_id,b.id AS review_id,b.decision,
      b.number AS reviewed_number,b.note,b.updated_ns FROM ocr_observations o
      JOIN ocr_runs r ON r.id=o.run_id LEFT JOIN bib_reviews b ON b.observation_id=o.id
      WHERE r.clip_id=? AND (o.run_id=? OR b.id IS NOT NULL) ORDER BY o.first_ns,o.id''',(clip_id,latest)):
        item=dict(row);item.pop('evidence',None)
        item.update(row_key=str(item['id']),observation_id=item['id'],ocr_number=item['number'],
                    historical=item['run_id']!=latest,manual=False)
        if item['reviewed_number'] is not None:item['number']=item['reviewed_number']
        rows.append(item)
    for row in connection.execute('SELECT * FROM bib_reviews WHERE clip_id=? AND observation_id IS NULL ORDER BY received_ns,id',(clip_id,)):
        item=dict(row);provenance=json.loads(item['provenance'])
        item.update(row_key='manual:'+str(item['id']),review_id=item['id'],observation_id=None,
                    ocr_number=provenance.get('original_number'),number=item['number'] or item['original_number'],
                    frame_count=0,confidence=None,status='manual',quad='[]',run_id=None,
                    historical=False,manual=provenance.get('origin')=='manual')
        rows.append(item)
    dimensions=None
    for item in rows:
        provenance=json.loads(item.get('provenance') or '{}')
        if item.get('review_id') and not provenance:
            saved=connection.execute('SELECT provenance FROM bib_reviews WHERE id=?',(item['review_id'],)).fetchone()
            provenance=json.loads(saved[0]) if saved else {}
        item['passing_order']=provenance.get('passing_order')
        item['bike_box']=provenance.get('bike_box')
        if item['bike_box'] and item.get('observation_id') is None:
            if dimensions is None:dimensions=connection.execute('SELECT width,height FROM clips WHERE id=?',(clip_id,)).fetchone()
            x0,y0,x1,y1=item['bike_box'];w,h=dimensions
            item['quad']=json.dumps([[x0*w,y0*h],[x1*w,y0*h],[x1*w,y1*h],[x0*w,y1*h]])
    return sorted(rows,key=lambda r:(r['first_ns'],r.get('passing_order') or 1000,r['row_key']))


def decide(path,clip_id,*,observation_id=None,review_id=None,decision,number=None,ordinal=None,note='',actor='operator',bike_box=None,passing_order=None,clear_bike=False,_connection=None):
    from . import storage
    if decision not in ('accepted','rejected','corrected','manual','reset'):raise ValueError('Invalid review action')
    if number is not None:validate_number(number)
    bike_box,passing_order=validate_bike(bike_box,passing_order)
    if len(note)>2000 or not actor or len(actor)>100:raise ValueError('Invalid review note/actor')
    c=_connection or storage.connect(path)
    try:
        if _connection is None:c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM clips WHERE id=?',(clip_id,)).fetchone() is None:raise ValueError('Unknown clip')
        old=None;observation=None
        if observation_id is not None:
            observation=c.execute('SELECT o.*,r.clip_id FROM ocr_observations o JOIN ocr_runs r ON r.id=o.run_id WHERE o.id=?',(observation_id,)).fetchone()
            if observation is None or observation['clip_id']!=clip_id:raise ValueError('Observation belongs to another clip or was removed')
            old=c.execute('SELECT * FROM bib_reviews WHERE observation_id=?',(observation_id,)).fetchone()
        elif review_id is not None:
            old=c.execute('SELECT * FROM bib_reviews WHERE id=? AND clip_id=?',(review_id,clip_id)).fetchone()
            if old is None:raise ValueError('Review no longer exists')
            if old['observation_id'] is not None:raise ValueError('Use the source observation to review this row')
        elif decision!='manual':raise ValueError('Select a candidate or add a manual bib')
        before=dict(old) if old else None;now=time.time_ns()
        if decision=='reset':
            if old:c.execute('DELETE FROM bib_reviews WHERE id=?',(old['id'],))
            current=None;rid=old['id'] if old else None
        else:
            if observation is not None:
                original=observation['number'];ordinal=observation['ordinal']
                frame=c.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip_id,ordinal)).fetchone()
                if frame is None:raise ValueError('Source frame no longer exists')
                first,last=observation['first_ns'],observation['last_ns'];key=observation['encounter_key'] or f'ocr:{observation_id}'
                provenance=json.loads(old['provenance']) if old else dict(origin='operator_review',source_run_id=observation['run_id'],source_observation_id=observation_id,original_number=original)
                if decision=='manual':raise ValueError('Manual additions must not replace OCR evidence')
                if decision=='accepted':number=number or original;decision='corrected' if number!=original else 'accepted'
                if decision=='corrected':validate_number(number)
            elif old is not None:
                original=old['original_number'];ordinal=old['ordinal'];first,last=old['first_ns'],old['last_ns'];key=old['encounter_key'];provenance=json.loads(old['provenance'])
                frame=(old['received_ns'],)
                if decision!='rejected':number=number or old['number'] or original;decision='manual'
            else:
                original=validate_number(number)
                if type(ordinal) is not int:raise ValueError('Select a displayed source frame for the manual bib')
                frame=c.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip_id,ordinal)).fetchone()
                if frame is None:raise ValueError('Source frame no longer exists')
                if c.execute("SELECT 1 FROM bib_reviews WHERE clip_id=? AND observation_id IS NULL AND number=? AND ordinal=?",(clip_id,number,ordinal)).fetchone():raise ValueError('This manual bib already exists at the displayed frame')
                first=last=frame[0];key=f'manual:{now}'
                provenance=dict(origin='manual',source_frame=ordinal)
            if clear_bike:
                provenance.pop('bike_box',None);provenance.pop('passing_order',None)
            if bike_box is not None:provenance['bike_box']=bike_box
            if passing_order is not None:
                clash=c.execute("SELECT number FROM bib_reviews WHERE clip_id=? AND decision!='rejected' AND json_extract(provenance,'$.passing_order')=? AND id!=?",(clip_id,passing_order,old['id'] if old else -1)).fetchone()
                if clash:raise ValueError(f'Bike order {passing_order} is already assigned to bib {clash[0]}; edit that review or choose another order')
                provenance['passing_order']=passing_order
            if decision=='rejected':number=None
            else:validate_number(number)
            values=(clip_id,observation_id,original,number,decision,ordinal,frame[0],first,last,key,note,actor,json.dumps(provenance),old['created_ns'] if old else now,now)
            if old:
                c.execute('''UPDATE bib_reviews SET clip_id=?,observation_id=?,original_number=?,number=?,decision=?,ordinal=?,received_ns=?,first_ns=?,last_ns=?,encounter_key=?,note=?,actor=?,provenance=?,created_ns=?,updated_ns=? WHERE id=?''',(*values,old['id']));rid=old['id']
            else:
                # Resets remove the current row but retain its audit history.
                # Do not reuse that ID for a different later decision.
                rid=c.execute('''SELECT MAX(COALESCE((SELECT MAX(id) FROM bib_reviews),0),
                  COALESCE((SELECT MAX(review_id) FROM bib_review_history),0))+1''').fetchone()[0]
                c.execute('''INSERT INTO bib_reviews(id,clip_id,observation_id,original_number,number,decision,ordinal,received_ns,first_ns,last_ns,encounter_key,note,actor,provenance,created_ns,updated_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(rid,*values))
            current=dict(c.execute('SELECT * FROM bib_reviews WHERE id=?',(rid,)).fetchone())
        c.execute('INSERT INTO bib_review_history(clip_id,review_id,observation_id,changed_ns,actor,action,previous,current) VALUES(?,?,?,?,?,?,?,?)',
                  (clip_id,rid,observation_id,now,actor,decision,json.dumps(before) if before else None,json.dumps(current) if current else None))
        if _connection is None:c.commit()
        return current
    except Exception:
        if _connection is None:c.rollback()
        raise
    finally:
        if _connection is None:c.close()
