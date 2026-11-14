"""Audited event-specific visual decisions alongside existing global bib reviews."""
import json
import time
from . import bib_review, storage


SCHEMA='''
CREATE TABLE IF NOT EXISTS race_visual_reviews (
 id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES race_events(id),
 clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
 subject_key TEXT NOT NULL, action TEXT NOT NULL CHECK(action IN ('confirmed','corrected','ignored')),
 number TEXT, ordinal INTEGER NOT NULL, received_ns INTEGER NOT NULL,
 source_keys TEXT NOT NULL, bib_review_id INTEGER, note TEXT NOT NULL,
 updated_ns INTEGER NOT NULL, UNIQUE(event_id,clip_id,subject_key)
);
CREATE TABLE IF NOT EXISTS race_visual_review_history (
 id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES race_events(id),
 review_id INTEGER NOT NULL, changed_ns INTEGER NOT NULL, action TEXT NOT NULL,
 previous TEXT, current TEXT, previous_bib TEXT, current_bib TEXT, actor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS race_visual_reviews_event ON race_visual_reviews(event_id,clip_id);
CREATE TABLE IF NOT EXISTS race_visual_history_links (
 history_id INTEGER PRIMARY KEY REFERENCES race_visual_review_history(id),
 inverse_of INTEGER NOT NULL REFERENCES race_visual_review_history(id)
);
'''


def decide(database, *,event_id,clip_id,ordinal,action,number=None,visual_key=None,note='',actor='operator',bike_box=None,passing_order=None,add=False):
    """Anchor the human decision to the frame actually displayed, never a guess.

    Source keys scope competing OCR alternatives to this encounter and event.
    A changed OCR run must be reviewed again rather than hiding new tracks on
    interval overlap alone. No clip-wide rejection or CMN mutation occurs.
    """
    if action not in ('confirmed','corrected','ignored'):raise ValueError('Invalid visual review action')
    if add and (action=='ignored' or visual_key is not None):raise ValueError('An added bib must be independent of existing visual evidence')
    if action!='ignored':bib_review.validate_number(number)
    bike_box,passing_order=bib_review.validate_bike(bike_box,passing_order)
    if not actor or len(actor)>100 or len(note)>1800:raise ValueError('Invalid reviewer/note')
    c=storage.connect(database)
    try:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM race_events WHERE id=?',(event_id,)).fetchone():raise ValueError('Event no longer exists')
        frame=c.execute('SELECT received_ns FROM frames WHERE clip_id=? AND ordinal=?',(clip_id,ordinal)).fetchone()
        if frame is None:raise ValueError('Displayed source frame no longer exists')
        from .bike_evidence import collect
        evidence,_=collect(c,-2**63,2**63-1,clip_id=clip_id,event_id=event_id)
        source=next((r for r in evidence if r['key']==visual_key),None)
        if source is None and visual_key and visual_key.startswith('bike:'):
            source=next((r for r in evidence if r.get('physical_key')==visual_key),None)
        if visual_key and source is None:raise ValueError('Visual evidence changed; update matches and select the encounter again')
        sources=[r['key'] for r in evidence if source and r['clip_id']==clip_id and
                 (r['key']==visual_key or source['encounter_key'] and r['encounter_key']==source['encounter_key'] and r['run_id']==source['run_id'])]
        if source and source.get('physical_key'):
            sources=list(set(source.get('source_keys',[])+[r['key'] for r in evidence if r.get('physical_key')==source['physical_key']]))
        previous=None
        if visual_key:
            previous=next((dict(r) for r in c.execute('SELECT * FROM race_visual_reviews WHERE event_id=? AND clip_id=?',(event_id,clip_id))
                if visual_key in json.loads(r['source_keys'])),None)
        subject=previous['subject_key'] if previous else (source.get('physical_key') if source and source.get('physical_key') else 'track:'+str(source['run_id'])+':'+source['encounter_key'] if source and source['encounter_key'] else visual_key or 'frame:'+str(ordinal))
        if add:subject='added:'+str(ordinal)+':'+number
        if previous is None:
            row=c.execute('SELECT * FROM race_visual_reviews WHERE event_id=? AND clip_id=? AND subject_key=?',(event_id,clip_id,subject)).fetchone()
            previous=dict(row) if row else None
        if previous:sources=list(set(sources+json.loads(previous['source_keys'])))
        before_bib=None;current_bib=None
        if action!='ignored':
            if source and source.get('physical_key') and bike_box is None:
                point=next((p for p in source.get('points',[]) if p['ordinal']==ordinal),None)
                if point:
                    x0,y0,x1,y1=point['box'];w,h=source['width'],source['height']
                    bike_box=[max(0,x0/w),max(0,y0/h),min(1,x1/w),min(1,y1/h)]
                    bike_box,passing_order=bib_review.validate_bike(bike_box,passing_order)
            args=dict(decision='accepted',number=number,note=f'Event {event_id}; displayed frame {ordinal}; '+note,actor=actor,_connection=c)
            if source and not source.get('physical_key') and bike_box is not None and source['ordinal']!=ordinal:
                raise ValueError('A marked bike on a different frame must be added as separate manual evidence in Review bibs')
            args.update(bike_box=bike_box,passing_order=passing_order)
            if source and not source.get('physical_key') and source['key'].startswith('ocr:'):
                args['observation_id']=int(source['key'].split(':')[1])
                old=c.execute('SELECT * FROM bib_reviews WHERE observation_id=?',(args['observation_id'],)).fetchone()
            elif source and source['key'].startswith('review:'):
                old=c.execute('SELECT * FROM bib_reviews WHERE id=?',(int(source['key'].split(':')[1]),)).fetchone()
                if old['observation_id'] is not None:args['observation_id']=old['observation_id']
                else:args['review_id']=old['id']
            else:
                old=c.execute("SELECT * FROM bib_reviews WHERE clip_id=? AND ordinal=? AND observation_id IS NULL AND decision!='rejected' AND number=?",(clip_id,ordinal,number)).fetchone()
                if old:args['review_id']=old['id']
                else:args.update(decision='manual',ordinal=ordinal)
            before_bib=dict(old) if old else None
            current_bib=bib_review.decide(database,clip_id,**args)
            sources.append('review:'+str(current_bib['id']))
        now=time.time_ns();number=None if action=='ignored' else number
        values=(event_id,clip_id,subject,action,number,ordinal,frame[0],json.dumps(sorted(set(sources))),
                current_bib['id'] if current_bib else None,note,now)
        if previous:
            c.execute('''UPDATE race_visual_reviews SET event_id=?,clip_id=?,subject_key=?,action=?,number=?,ordinal=?,received_ns=?,source_keys=?,bib_review_id=?,note=?,updated_ns=? WHERE id=?''',(*values,previous['id']))
            rid=previous['id']
        else:
            rid=c.execute('SELECT MAX(COALESCE((SELECT MAX(id) FROM race_visual_reviews),0),COALESCE((SELECT MAX(review_id) FROM race_visual_review_history),0))+1').fetchone()[0]
            c.execute('INSERT INTO race_visual_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(rid,*values))
        current=dict(c.execute('SELECT * FROM race_visual_reviews WHERE id=?',(rid,)).fetchone())
        history=c.execute('''INSERT INTO race_visual_review_history(event_id,review_id,changed_ns,action,previous,current,previous_bib,current_bib,actor) VALUES(?,?,?,?,?,?,?,?,?)''',
            (event_id,rid,now,action,json.dumps(previous),json.dumps(current),json.dumps(before_bib),json.dumps(current_bib),actor)).lastrowid
        c.commit();return dict(history_id=history,review=current)
    except Exception:c.rollback();raise
    finally:c.close()


def undo(database,history_id):
    return _invert(database,history_id,'undo')


def redo(database,history_id):
    return _invert(database,history_id,'redo')


def history_state(c,event_id):
    undo_stack=[];redo_stack=[]
    for h in c.execute('''SELECT h.id,h.action,l.inverse_of FROM race_visual_review_history h
        LEFT JOIN race_visual_history_links l ON l.history_id=h.id WHERE h.event_id=? ORDER BY h.id''',(event_id,)):
        if h['action']=='undo':
            if h['inverse_of'] in undo_stack:undo_stack.remove(h['inverse_of'])
            else:undo_stack=[]
            redo_stack.append(h['id']) if h['inverse_of'] else redo_stack.clear()
        elif h['action']=='redo':
            if h['inverse_of'] in redo_stack:redo_stack.remove(h['inverse_of'])
            undo_stack.append(h['id'])
        else:undo_stack.append(h['id']);redo_stack=[]
    return dict(undo_review_id=undo_stack[-1] if undo_stack else None,redo_review_id=redo_stack[-1] if redo_stack else None)


def _invert(database,history_id,action):
    c=storage.connect(database)
    try:
        c.execute('BEGIN IMMEDIATE')
        h=c.execute('SELECT * FROM race_visual_review_history WHERE id=?',(history_id,)).fetchone()
        if h is None or (h['action']=='undo')!=(action=='redo'):raise ValueError('Nothing to '+action)
        if action=='redo' and history_state(c,h['event_id'])['redo_review_id']!=history_id:raise ValueError('Nothing to redo; the review history changed')
        expected=json.loads(h['current']);old=json.loads(h['previous'])
        current=c.execute('SELECT * FROM race_visual_reviews WHERE id=?',(h['review_id'],)).fetchone()
        if (dict(current) if current else None)!=expected:raise ValueError('Decision changed since this action; refresh before '+action)
        after_bib=json.loads(h['current_bib']);before_bib=json.loads(h['previous_bib'])
        if after_bib or before_bib:
            subject=after_bib or before_bib
            actual=c.execute('SELECT * FROM bib_reviews WHERE id=?',(subject['id'],)).fetchone()
            if (dict(actual) if actual else None)!=after_bib:raise ValueError('Bib review changed elsewhere; '+action+' would overwrite it')
            if before_bib:
                provenance=json.loads(before_bib['provenance']);order=provenance.get('passing_order')
                if order and c.execute("SELECT 1 FROM bib_reviews WHERE clip_id=? AND id!=? AND decision!='rejected' AND json_extract(provenance,'$.passing_order')=?",(before_bib['clip_id'],before_bib['id'],order)).fetchone():
                    raise ValueError('Bike order was assigned elsewhere; refresh before '+action)
                columns=list(before_bib)
                c.execute('INSERT INTO bib_reviews('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in columns if k!='id'),tuple(before_bib.values()))
            else:c.execute('DELETE FROM bib_reviews WHERE id=?',(after_bib['id'],))
            c.execute('''INSERT INTO bib_review_history(clip_id,review_id,observation_id,changed_ns,actor,action,previous,current)
                VALUES(?,?,?,?,?,?,?,?)''',(subject['clip_id'],subject['id'],subject['observation_id'],time.time_ns(),'operator',action,json.dumps(after_bib),json.dumps(before_bib)))
        if old:
            columns=list(old)
            c.execute('INSERT INTO race_visual_reviews('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+') ON CONFLICT(id) DO UPDATE SET '+','.join(k+'=excluded.'+k for k in columns if k!='id'),tuple(old.values()))
        else:c.execute('DELETE FROM race_visual_reviews WHERE id=?',(h['review_id'],))
        inverse=c.execute('''INSERT INTO race_visual_review_history(event_id,review_id,changed_ns,action,previous,current,previous_bib,current_bib,actor) VALUES(?,?,?,?,?,?,?,?,?)''',
            (h['event_id'],h['review_id'],time.time_ns(),action,h['current'],h['previous'],h['current_bib'],h['previous_bib'],'operator')).lastrowid
        c.execute('INSERT INTO race_visual_history_links VALUES(?,?)',(inverse,history_id))
        c.commit();return dict(history_id=inverse,review=old,action=action)
    except Exception:c.rollback();raise
    finally:c.close()
