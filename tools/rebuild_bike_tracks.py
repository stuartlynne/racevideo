"""Rebuild review stops from saved neural detections, without rerunning OCR.

Defaults to a read-only preview. --apply updates derived bike reports only,
preserving analysis/track keys and storing the old reports for rollback.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from racevideo.bike_index import clean_tracks


def human_digest(c):
    tables=['bib_reviews','bib_review_history','race_visual_reviews',
            'race_visual_review_history','race_visual_history_links']
    return {table:hashlib.sha256(repr([tuple(r) for r in c.execute(
        'SELECT * FROM '+table+' ORDER BY id' if table!='race_visual_history_links' else
        'SELECT * FROM '+table+' ORDER BY history_id')]).encode()).hexdigest() for table in tables}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path);p.add_argument('results',type=Path)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--event',type=int)
    a=p.parse_args();a.audit.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((a.results/'batch.json').read_text())
    c=sqlite3.connect(a.database.resolve().as_uri()+('' if a.apply else '?mode=ro'),uri=True,timeout=30)
    c.row_factory=sqlite3.Row;updates=[];before=human_digest(c)
    from racevideo.passings import compare_event
    def counts():
        if not a.event:return None
        model=compare_event(c,a.event)
        return dict(rows=len(model['cells']),unknown=sum(r['bib']=='?' for r in model['cells']),
            confirmed=sum(r['confirmed'] for r in model['cells']),grouped=len(model['grouped_cells']))
    initial=counts()
    for clip in manifest['clips']:
        row=c.execute('''SELECT b.id,b.report FROM bike_analyses b JOIN ocr_imports i
            ON i.run_id=b.source_run_id WHERE i.import_key=? AND b.state='complete'
            ORDER BY b.id DESC LIMIT 1''',(f'{manifest["batch_id"]}:{clip}',)).fetchone()
        if row is None:continue
        original=json.loads(row['report'])
        if original.get('policy')=='passage-v3':continue
        result=json.loads((a.results/f'clip-{clip}.json').read_text())
        actual=c.execute('SELECT id,started_ns,ended_ns,frame_count,width,height FROM clips WHERE id=?',(clip,)).fetchone()
        if dict(actual)!=result['source_clip']:raise ValueError('Source mismatch for clip '+str(clip))
        report=clean_tracks(original,result['results'],actual['width'],actual['height'])
        assert {e['key'] for e in original['passages']}=={e['key'] for e in report['passages']}
        update=dict(clip=clip,analysis_id=row['id'],previous=row['report'],report=json.dumps(report))
        (a.audit/f'clip-{clip}.json').write_text(json.dumps(update)+'\n')
        updates.append(update)
    print('Prepared',len(updates),'reports; retained all original analysis and track keys.',flush=True)
    if a.apply:
        c.execute('BEGIN IMMEDIATE')
        if human_digest(c)!=before:raise RuntimeError('Operator reviews changed during preparation; rerun to take a fresh snapshot')
        for update in updates:
            changed=c.execute('UPDATE bike_analyses SET report=? WHERE id=? AND report=?',
                (update['report'],update['analysis_id'],update['previous'])).rowcount
            if changed!=1:raise RuntimeError('Analysis changed during rebuild')
        final=counts()
        if human_digest(c)!=before:raise RuntimeError('Human reviews unexpectedly changed')
        c.commit()
    else:final=None
    summary=dict(applied=a.apply,reports=len(updates),database=str(a.database.resolve()),
        batch_id=manifest['batch_id'],before=initial,after=final,human_review_digests=before,completed=time.time())
    (a.audit/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True);c.close()


if __name__=='__main__':main()
