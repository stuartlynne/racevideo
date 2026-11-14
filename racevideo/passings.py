"""Cached CrossMgr evidence and event-scoped visual passing comparisons.

CMN evidence is versioned by input hashes; matching never writes race results.
All functions here run off the Tk thread.
"""
import bisect
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from . import storage


SCHEMA = '''
CREATE TABLE IF NOT EXISTS race_competitions (
 id INTEGER PRIMARY KEY, day TEXT NOT NULL, source_directory TEXT NOT NULL,
 name TEXT NOT NULL, UNIQUE(day,source_directory)
);
CREATE TABLE IF NOT EXISTS race_events (
 id INTEGER PRIMARY KEY, competition_id INTEGER NOT NULL REFERENCES race_competitions(id),
 source_key TEXT NOT NULL UNIQUE, source_path TEXT NOT NULL, name TEXT NOT NULL,
 current_source_id INTEGER, start_ns INTEGER NOT NULL, end_ns INTEGER NOT NULL,
 timezone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS race_sources (
 id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES race_events(id),
 fingerprint TEXT NOT NULL, imported_ns INTEGER NOT NULL, payload TEXT NOT NULL,
 UNIQUE(event_id,fingerprint)
);
CREATE TABLE IF NOT EXISTS race_categories (
 source_id INTEGER NOT NULL REFERENCES race_sources(id), name TEXT NOT NULL,
 wave INTEGER NOT NULL, metadata TEXT NOT NULL, PRIMARY KEY(source_id,name)
);
CREATE TABLE IF NOT EXISTS race_participants (
 source_id INTEGER NOT NULL REFERENCES race_sources(id), bib TEXT NOT NULL,
 name TEXT NOT NULL, team TEXT NOT NULL, status TEXT NOT NULL, tags TEXT NOT NULL,
 PRIMARY KEY(source_id,bib)
);
CREATE TABLE IF NOT EXISTS race_participant_categories (
 source_id INTEGER NOT NULL, bib TEXT NOT NULL, category TEXT NOT NULL,
 PRIMARY KEY(source_id,bib,category),
 FOREIGN KEY(source_id,bib) REFERENCES race_participants(source_id,bib),
 FOREIGN KEY(source_id,category) REFERENCES race_categories(source_id,name)
);
CREATE TABLE IF NOT EXISTS race_passings (
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL, bib TEXT NOT NULL,
 seconds REAL NOT NULL, at_ns INTEGER NOT NULL, rider_lap INTEGER,
 provenance TEXT NOT NULL, metadata TEXT NOT NULL,
 FOREIGN KEY(source_id,bib) REFERENCES race_participants(source_id,bib),
 UNIQUE(source_id,bib,seconds)
);
CREATE INDEX IF NOT EXISTS race_passings_time ON race_passings(source_id,at_ns);
'''


def zone(config):
    if config.timezone_file:
        with Path(config.timezone_file).expanduser().open('rb') as stream:
            return ZoneInfo.from_file(stream, key=config.timezone)
    return ZoneInfo(config.timezone)


def absolute_ns(value, tz):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        # Refuse ambiguous/nonexistent local starts instead of silently selecting
        # a DST fold. UTC offsets in the source can resolve such cases.
        a, b = dt.replace(tzinfo=tz, fold=0), dt.replace(tzinfo=tz, fold=1)
        if a.utcoffset() != b.utcoffset(): raise ValueError('Ambiguous/nonexistent local race start; explicit UTC offset required')
        dt = a
    delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days*86400 + delta.seconds)*1_000_000_000 + delta.microseconds*1000


def cache_event(connection, config, path, day, payload):
    inspected, reviewed = payload['inspect'], payload['review']
    if inspected['inputs'] != reviewed['inputs']: raise ValueError('Inconsistent CMN input snapshots')
    race = reviewed['race']; info = inspected['race']
    if race.get('is_time_trial'): raise ValueError('Time-trial coordinate conversion is not implemented')
    if not race.get('start_time'): raise ValueError('Event has no recorded start time')
    tz = zone(config); start = absolute_ns(race['start_time'], tz)
    inputs=reviewed['inputs']
    if payload.get('live'):
        origin=payload['live'];inputs=[dict(item,path=origin['race_path']) if item.get('path')==origin['snapshot_path'] else item for item in inputs]
    fingerprint = hashlib.sha256(json.dumps(dict(inputs=inputs, timezone=config.timezone,
        # Include the observed interpretation, so a timezone-data update can be reimported.
        start_ns=start, format=2), sort_keys=True).encode()).hexdigest()
    directory = str(Path(path).parent); key = config.url.rstrip('/') + '|' + path
    categories = {c['name']: c for c in info['categories']}
    grouped = {}
    for row in race['rows']: grouped.setdefault(str(row['bib']), []).append(row)
    # Wave results use race-elapsed coordinates. Component results may instead
    # subtract the wave start. Never derive lap boundaries from those duplicates.
    selected = {}
    for bib, rows in grouped.items():
        waves = [r for r in rows if categories.get(r['category'], {}).get('wave')]
        if not waves: raise ValueError(f'No wave result for bib {bib}; cannot establish lap coordinates')
        selected[bib] = waves[0]
    # A registered tag owner may never have generated a model passing. Keep that
    # entrant in the event identity set without inventing a passing or category.
    for assignments in race.get('tag_assignments',{}).values():
        for assignment in assignments:
            selected.setdefault(str(assignment['bib']),dict(first_name='Workbook entrant',last_name='',team='',
                status='Workbook tag assignment only',passings=[],calculated_times=[],calculated_interpolation=[]))
    passing_rows = []
    for bib, row in selected.items():
        calculated = row.get('calculated_times', [])
        interpolation = row.get('calculated_interpolation', [])
        for p in row['passings']:
            seconds = float(p['seconds'])
            if not math.isfinite(seconds): raise ValueError('Non-finite passing time')
            lap = next((i for i, t in enumerate(calculated) if i > 0 and
                i < len(interpolation) and not interpolation[i] and abs(float(t)-seconds) < 0.00001), None)
            passing_rows.append((bib, seconds, start+round(seconds*1e9), lap,
                                 p.get('provenance', 'Unknown'), json.dumps(p)))
    finish = absolute_ns(info['finish_time'], tz) if info.get('finish_time') else start
    end = max([finish, start] + [p[2] for p in passing_rows])
    with connection:
        connection.execute('INSERT OR IGNORE INTO race_competitions(day,source_directory,name) VALUES(?,?,?)',
                           (day, directory, Path(directory).name[9:]))
        competition = connection.execute('SELECT id FROM race_competitions WHERE day=? AND source_directory=?', (day,directory)).fetchone()[0]
        connection.execute('INSERT OR IGNORE INTO race_events(competition_id,source_key,source_path,name,start_ns,end_ns,timezone) VALUES(?,?,?,?,?,?,?)',
                           (competition,key,path,race['name'],start,end,config.timezone))
        event = connection.execute('SELECT id FROM race_events WHERE source_key=?', (key,)).fetchone()[0]
        existing = connection.execute('SELECT id FROM race_sources WHERE event_id=? AND fingerprint=?', (event,fingerprint)).fetchone()
        if existing:
            source = existing[0]
        else:
            source = connection.execute('INSERT INTO race_sources(event_id,fingerprint,imported_ns,payload) VALUES(?,?,?,?)',
                (event,fingerprint,time.time_ns(),json.dumps(payload))).lastrowid
            connection.executemany('INSERT INTO race_categories VALUES(?,?,?,?)',
                ((source,name,int(c.get('wave',False)),json.dumps(c)) for name,c in categories.items()))
            for bib, row in selected.items():
                tags = {tag: assignments for tag,assignments in race.get('tag_assignments',{}).items()
                        if any(str(a['bib']) == bib for a in assignments)}
                connection.execute('INSERT INTO race_participants VALUES(?,?,?,?,?,?)',
                    (source,bib,' '.join(str(row.get(k) or '') for k in ('first_name','last_name')).strip(),
                     row.get('team') or '',row.get('status') or '',json.dumps(tags)))
                connection.executemany('INSERT OR IGNORE INTO race_participant_categories VALUES(?,?,?)',
                    ((source,bib,r['category']) for r in grouped.get(bib,[])))
            connection.executemany('INSERT OR IGNORE INTO race_passings(source_id,bib,seconds,at_ns,rider_lap,provenance,metadata) VALUES(?,?,?,?,?,?,?)',
                                   ((source,*p) for p in passing_rows))
        connection.execute('UPDATE race_events SET current_source_id=?,name=?,start_ns=?,end_ns=?,timezone=? WHERE id=?',
                           (source,race['name'],start,end,config.timezone,event))
    return event


def import_day(database, config, day):
    from .crossmgr_client import discover, Client
    paths = discover(config.root, day)
    if not paths: raise ValueError(f'No CMNs found for {day} under {config.root}')
    c = storage.connect(database)
    try:
        storage.initialize(c)
        imported = []
        Client(config).fetch(paths, lambda path,payload: imported.append(cache_event(c, config, path, day, payload)))
        return imported
    finally: c.close()


def list_events(connection, day):
    return [dict(r) for r in connection.execute('''SELECT e.*,c.name AS competition,s.imported_ns
      FROM race_events e JOIN race_competitions c ON c.id=e.competition_id
      JOIN race_sources s ON s.id=e.current_source_id WHERE c.day=? ORDER BY e.start_ns,e.name''',(day,))]


def visual_evidence(connection, start, end,clip_id=None):
    """Effective operator-reviewed / latest OCR observations, with no image blobs."""
    query='''SELECT * FROM (
      SELECT o.number,o.first_ns,o.last_ns,o.ordinal,NULL AS decision,o.confidence,
        o.status,o.encounter_key,o.run_id,r.clip_id,'ocr:'||o.id AS key,0 AS confirmed,NULL AS provenance,NULL AS reviewed_ns
      FROM ocr_observations o JOIN ocr_runs r ON r.id=o.run_id
      LEFT JOIN bib_reviews b ON b.observation_id=o.id
      WHERE b.id IS NULL AND r.id=(SELECT MAX(id) FROM ocr_runs latest WHERE latest.clip_id=r.clip_id AND latest.state='complete')
      AND NOT EXISTS(SELECT 1 FROM bib_reviews h WHERE h.clip_id=r.clip_id AND h.number=o.number
        AND h.decision!='rejected' AND h.first_ns<=o.last_ns AND h.last_ns>=o.first_ns)
      UNION ALL
      SELECT b.number,b.first_ns,b.last_ns,b.ordinal,b.decision,o.confidence,
        COALESCE(o.status,'manual'),b.encounter_key,o.run_id,b.clip_id,'review:'||b.id,1,b.provenance,b.updated_ns
      FROM bib_reviews b LEFT JOIN ocr_observations o ON o.id=b.observation_id
      WHERE b.decision!='rejected'
    ) WHERE first_ns<=? AND last_ns>=? ORDER BY first_ns,key'''
    params=[end,start]
    if clip_id is not None:
        query=query.replace(' ORDER BY first_ns,key',' AND clip_id=? ORDER BY first_ns,key');params.append(clip_id)
    rows=[dict(row) for row in connection.execute(query,params)]
    for row in rows:
        provenance=json.loads(row.pop('provenance') or '{}')
        row['passing_order']=provenance.get('passing_order');row['bike_box']=provenance.get('bike_box')
    return rows


def compare_event(connection, event_id, tolerance=3.0, offset=0.0, category='All categories',duplicate_seconds=30):
    """offset = camera receipt clock minus CMN UTC clock, seconds.

    Comparison is temporal evidence, not a calibrated finish-time measurement.
    A visual track is assigned to at most one stored passing; all alternative
    bibs from a shared encounter are flagged as ambiguous.
    """
    if not math.isfinite(tolerance) or not 0<=tolerance<=60: raise ValueError('Match window must be 0–60 seconds')
    if not math.isfinite(offset) or abs(offset)>86400: raise ValueError('Clock offset must be within one day')
    event = dict(connection.execute('SELECT * FROM race_events WHERE id=?',(event_id,)).fetchone())
    source = event['current_source_id']; shift = round(offset*1e9); margin = round(tolerance*1e9)
    riders = {r['bib']:dict(r) for r in connection.execute('SELECT * FROM race_participants WHERE source_id=?',(source,))}
    memberships = {}
    for row in connection.execute('SELECT bib,category FROM race_participant_categories WHERE source_id=?',(source,)):
        memberships.setdefault(row['bib'], []).append(row['category'])
    passings = [dict(r) for r in connection.execute('SELECT * FROM race_passings WHERE source_id=? ORDER BY at_ns,bib',(source,))]
    leaders = {}
    for p in passings:
        if p['rider_lap'] is not None:
            leaders.setdefault(p['rider_lap'], p)
    boundaries = sorted(leaders.values(), key=lambda p:p['at_ns'])
    times = [p['at_ns'] for p in boundaries]
    columns = [dict(label='Start / pre-lap', start_ns=event['start_ns'])] + [dict(label=f"Lap {p['rider_lap']}", start_ns=p['at_ns'], leader_bib=p['bib']) for p in boundaries]
    clips = [dict(r) for r in connection.execute('SELECT id,started_ns,ended_ns FROM clips WHERE started_ns<=? AND ended_ns>=? ORDER BY started_ns',
                (event['end_ns']+shift+margin,event['start_ns']+shift-margin))]
    from .bike_evidence import collect
    evidence,coverage = collect(connection,event['start_ns']+shift,event['end_ns']+shift,event_id=event_id)
    reviews=[dict(r) for r in connection.execute('SELECT * FROM race_visual_reviews WHERE event_id=?',(event_id,))]
    from .review_resolution import resolve
    resolution=resolve(evidence,reviews);evidence=resolution['evidence']
    def group_key(v):
        return v.get('physical_key') or ((v['clip_id'],v['run_id'],v['encounter_key']) if v['encounter_key'] else v['key'])
    alternatives = {}
    for v in evidence:
        if not v['confirmed'] and v['encounter_key']:
            alternatives.setdefault((v['clip_id'],v['encounter_key']), set()).add(v['number'])
    edges = []
    for i,p in enumerate(passings):
        target=p['at_ns']+shift
        for j,v in enumerate(evidence):
            if p['bib']!=v['number']: continue
            distance = max(v['first_ns']-target, target-v['last_ns'], 0)
            if distance<=margin: edges.append((not v['confirmed'],distance,i,j))
    assignments = {}; used = set();owners={}
    for _,distance,i,j in sorted(edges):
        if j in used:continue
        group=group_key(evidence[j])
        if group in owners and owners[group]!=i and not evidence[j]['confirmed']:continue
        owners.setdefault(group,i)
        assignments.setdefault(i,[]).append(j);used.add(j)
    cells=[]
    for i,p in enumerate(passings):
        if category!='All categories' and category not in memberships.get(p['bib'],[]): continue
        target=p['at_ns']+shift
        matched=[evidence[j] for j in assignments.get(i,[])]
        candidates=[dict(clip_id=c['id'],first_ns=c['started_ns'],last_ns=c['ended_ns'],ordinal=None,
                         target_ns=target,confirmed=False) for c in clips if c['started_ns']<=target+margin and c['ended_ns']>=target-margin]
        candidates.sort(key=lambda c:(max(c['first_ns']-target,target-c['last_ns'],0),abs((c['first_ns']+c['last_ns'])//2-target)))
        nearby=[];seen_bikes=set()
        def nearby_rank(v):
            owner=owners.get(group_key(v))
            return (owner is not None and owner!=i,not v.get('navigation_primary',False),v.get('uncertain',False),abs(v.get('passage_ns',(v['first_ns']+v['last_ns'])//2)-target))
        for v in sorted(evidence,key=nearby_rank):
            physical=v.get('physical_key')
            if not physical or physical in seen_bikes or abs(v['passage_ns']-target)>margin:continue
            seen_bikes.add(physical)
            nearby.append(dict(v,ordinal=v.get('passage_ordinal',v['ordinal']),candidate=True,target_ns=target))
        if not matched:candidates=nearby+[c for c in candidates if c['clip_id'] not in {v['clip_id'] for v in nearby}]
        for v in matched:
            v['ambiguous']=len(alternatives.get((v['clip_id'],v['encounter_key']),()))>1
        cell=dict(p, cell_key=f"cm:{p['id']}", column=bisect.bisect_right(times,p['at_ns']), name=riders[p['bib']]['name'],
            categories=memberships.get(p['bib'],[]), state='matched' if matched else 'missing',
            confirmed=any(v['confirmed'] for v in matched), ambiguous=any(v.get('ambiguous') for v in matched),
            captures=matched+[c for c in candidates if c['clip_id'] not in {v['clip_id'] for v in matched}],
            visual_count=len(matched), origin='CrossMgr')
        cells.append(cell)
        cell['sort_ns']=min((v.get('passage_ns',(v['first_ns']+v['last_ns'])//2)-shift for v in matched),default=p['at_ns'])
        cell['passing_order']=next((v['passing_order'] for v in matched if v.get('passing_order')),None)
    associated = {}
    for cell in cells:
        for v in cell['captures'][:cell['visual_count']]:
            associated.setdefault(group_key(v),[]).append(cell)
    orphan_groups = {}
    for j,v in enumerate(evidence):
        if j in used:continue
        bib=v['number']; outside=bib not in riders and bib!='?'
        group=group_key(v)
        if group in associated and not v['confirmed']:
            # Competing OCR strings on one track are alternatives, not evidence
            # of additional riders. Keep them inspectable on the matched cell.
            for cell in associated[group]:
                cell['alternative_bibs']=sorted(set(cell.get('alternative_bibs',[])+[bib]))
                cell['ambiguous']=True
            continue
        if category!='All categories' and bib!='?' and not outside and category not in memberships.get(bib,[]):continue
        if v['confirmed']:group=('confirmed',v['key'])
        if group in orphan_groups:
            cell=orphan_groups[group]
            cell['alternative_bibs']=sorted(set(cell['alternative_bibs']+[bib]))
            cell['bib']=' / '.join(cell['alternative_bibs'])
            cell['ambiguous']=True
            cell['captures'].append(v);cell['visual_count']+=1
            continue
        stamp=v.get('passage_ns',(v['first_ns']+v['last_ns'])//2)-shift
        cell=dict(bib=bib,passing_order=v.get('passing_order'),cell_key='visual:'+v['key'],at_ns=stamp,column=bisect.bisect_right(times,stamp),
            name=riders.get(bib,{}).get('name','Unidentified bike' if bib=='?' else 'Not in this event'), categories=memberships.get(bib,[]),
            state='extra' if outside else 'video_only',confirmed=v['confirmed'],
            ambiguous=len(alternatives.get((v['clip_id'],v['encounter_key']),()))>1,
            captures=[v],visual_count=1,origin='Visual only',provenance='Human review' if v['confirmed'] else 'Uncertain bike candidate' if v.get('uncertain') else 'Bike candidate' if bib=='?' else 'OCR candidate',rider_lap=None)
        cells.append(cell)
        cell['alternative_bibs']=[bib];orphan_groups[group]=cell
    cells.sort(key=lambda c:(c.get('sort_ns',c['at_ns']),c.get('passing_order') or 1000,c['bib'],c['origin']))
    from .review_duplicates import group
    cells,grouped_cells=group(cells,duplicate_seconds)
    ignored_cells=[]
    for review in reviews:
        if review['action']!='ignored':continue
        stamp=review['received_ns']-shift
        if not event['start_ns']<=stamp<=event['end_ns']:continue
        history=connection.execute('SELECT id,current FROM race_visual_review_history WHERE review_id=? ORDER BY id DESC LIMIT 1',(review['id'],)).fetchone()
        ignored_cells.append(dict(cell_key='ignored:'+str(review['id']),bib='Hidden',name='Ignored bike / bystander',
            at_ns=stamp,column=bisect.bisect_right(times,stamp),categories=[],state='ignored',confirmed=False,
            captures=[dict(clip_id=review['clip_id'],ordinal=review['ordinal'],first_ns=review['received_ns'],last_ns=review['received_ns'],confirmed=False)],
            visual_count=0,origin='Ignored by operator',provenance=review['note'],source_keys=json.loads(review['source_keys']),
            restore_history_id=history['id'] if history and json.loads(history['current'])==review else None))
    from .passing_review import history_state
    history=history_state(connection,event_id)
    bike_jobs={r['state']:r['n'] for r in connection.execute('''SELECT a.state,count(*) AS n FROM bike_analyses a
        JOIN clips c ON c.id=a.clip_id WHERE c.started_ns<=? AND c.ended_ns>=?
        AND a.state IN ('queued','running') GROUP BY a.state''',(event['end_ns']+shift,event['start_ns']+shift))}
    # Explicit candidate timing associations, separate from CM and identity reads.
    from .wheel_timing import linked_results
    timings={}
    for result in linked_results(connection,event_id):
        if result['stale_race_start'] or result['camera_minus_cm_ns']!=shift:continue
        key=(result['cell_key'],result['visual_key'])
        if key not in timings:timings[key]=result
    for cell in cells+grouped_cells:
        clips={r['clip_id'] for r in cell['captures']}
        cell['video_timings']=[r for (key,visual),r in timings.items() if key==cell['cell_key'] and r['bib']==cell['bib'] and r['clip_id'] in clips]
    return dict(event=event,columns=columns,cells=cells,grouped_cells=grouped_cells,duplicate_seconds=duplicate_seconds,ignored_cells=ignored_cells,review_reconciliations=resolution['reconciliations'],bike_coverage=coverage,categories=sorted(set(c for cs in memberships.values() for c in cs)),
                tolerance=tolerance,offset=offset,bike_jobs=bike_jobs,**history,source_imported_ns=connection.execute('SELECT imported_ns FROM race_sources WHERE id=?',(source,)).fetchone()[0],
                warning='Bike candidates include uncertain detections; ? is not proof of a rider or identity. Missing CrossMgr entries remain for review, never automatic DNF. Category filter retains unidentified bikes and overall race lap boundaries.')
