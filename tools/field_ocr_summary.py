"""Read-only coverage/candidate report for an imported field batch, not accuracy."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def summarize(database, manifest):
    batch=json.loads(manifest.read_text());ids=batch['clips']
    c=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    try:
        rows=c.execute('''SELECT c.id,c.started_ns,c.frame_count,r.id AS run_id,
          r.state,r.summary,r.parameters,i.imported_ns
          FROM ocr_imports i JOIN clips c ON c.id=i.clip_id JOIN ocr_runs r ON r.id=i.run_id
          WHERE i.import_key LIKE ? ORDER BY c.started_ns,c.id''',(batch['batch_id']+':%',)).fetchall()
        states=Counter();devices=Counter();hourly={};completed=[];frames=0;raw=0;observations=0
        for row in rows:
            states[row['state']]+=1
            if row['state']!='complete' or not row['imported_ns']:continue
            summary=json.loads(row['summary']);parameters=json.loads(row['parameters'])
            if summary['sampled_frames']!=row['frame_count']:raise ValueError('Incomplete frame coverage')
            frames+=row['frame_count'];raw+=summary['raw_reads'];observations+=summary['observations'];completed.append(row['id'])
            devices[summary.get('device') or parameters.get('device') or 'unrecorded']+=1
            hour=datetime.fromtimestamp(row['started_ns']/1e9).astimezone().isoformat(timespec='hours')
            group=hourly.setdefault(hour,dict(clips=0,frames=0,clips_with_candidates=0))
            group['clips']+=1;group['frames']+=row['frame_count'];group['clips_with_candidates']+=summary['observations']>0
        candidates=c.execute('''SELECT o.number,COUNT(*) AS observation_count,
          COUNT(DISTINCT i.clip_id) AS clips
          FROM ocr_imports i JOIN ocr_runs r ON r.id=i.run_id
          JOIN ocr_observations o ON o.run_id=r.id
          WHERE i.import_key LIKE ? AND r.state='complete' AND i.imported_ns>0
          GROUP BY o.number ORDER BY clips DESC,o.number''',(batch['batch_id']+':%',)).fetchall()
        reviews=c.execute('''SELECT b.decision,COUNT(*) FROM bib_reviews b
          WHERE EXISTS(SELECT 1 FROM ocr_imports i WHERE i.clip_id=b.clip_id AND i.import_key LIKE ?)
          GROUP BY b.decision''',(batch['batch_id']+':%',)).fetchall()
        encounters=c.execute('''SELECT COUNT(DISTINCT o.encounter_key),COUNT(DISTINCT i.clip_id)
          FROM ocr_imports i JOIN ocr_runs r ON r.id=i.run_id JOIN ocr_observations o ON o.run_id=r.id
          WHERE i.import_key LIKE ? AND r.state='complete' AND i.imported_ns>0''',(batch['batch_id']+':%',)).fetchone()
        return dict(generated_utc=datetime.now(timezone.utc).isoformat(),database=str(database.resolve()),
          batch_id=batch['batch_id'],total_clips=len(ids),completed_clips=len(completed),
          missing_clips=sorted(set(ids)-set(completed)),run_states=dict(states),
          covered_original_frames=frames,raw_numeric_reads=raw,observations=observations,
          qualified_encounters=encounters[0],clips_with_candidates=encounters[1],
          device_clip_counts=dict(devices),operator_decisions=dict(reviews),
          hourly_local=hourly,candidates=[dict(r) for r in candidates],
          interpretation='Coverage and unreviewed candidate counts, not recognition accuracy, rider totals or official passings.')
    finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('database',type=Path);p.add_argument('manifest',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=summarize(a.database,a.manifest)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('hourly_local','candidates','missing_clips')}))


if __name__=='__main__':main()
