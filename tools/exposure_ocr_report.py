"""Read-only exposure/OCR association report. Candidate yield is not accuracy."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3


def analyze(database,batch):
    c=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('BEGIN')
    groups=defaultdict(list);hourly=defaultdict(lambda:[0,0]);examples=[]
    try:
        rows=c.execute('''SELECT c.id,c.started_ns,c.frame_count,d.metadata,r.id AS run_id,r.summary
          ,r.parameters FROM ocr_imports i JOIN ocr_runs r ON r.id=i.run_id JOIN clips c ON c.id=r.clip_id
          LEFT JOIN clip_details d ON d.clip_id=c.id
          WHERE i.import_key LIKE ? AND r.state='complete' ORDER BY c.started_ns,c.id''',(batch+':%',)).fetchall()
        for row in rows:
            settings=json.loads(row['metadata'] or '{}').get('camera_settings_at_trigger',{})
            exposure=settings.get(str(0x9a0902));summary=json.loads(row['summary'])
            observations=[dict(o) for o in c.execute('SELECT number,status,frame_count,encounter_key FROM ocr_observations WHERE run_id=?',(row['run_id'],))]
            local=datetime.fromtimestamp(row['started_ns']/1e9).astimezone()
            item=dict(clip_id=row['id'],time=local.isoformat(),frames=row['frame_count'],raw_reads=summary['raw_reads'],observations=observations,exposure=exposure,mode=settings.get(str(0x9a0901)),gain=settings.get(str(0x980913)))
            groups[exposure].append(item);hourly[exposure,local.hour][0]+=1;hourly[exposure,local.hour][1]+=bool(observations)
            if row['id'] in (212,508,670,800):examples.append(item)
        result=[]
        for exposure,items in sorted(groups.items(),key=lambda item:(item[0] is None,item[0] or 0)):
            positive=sum(bool(i['observations']) for i in items)
            result.append(dict(setting=exposure,exposure_ms=exposure/10 if exposure is not None else None,
              reciprocal_seconds=10000/exposure if exposure else None,clips=len(items),candidate_clips=positive,
              candidate_yield_percent=100*positive/len(items),
              repeated_candidate_clips=sum(any(o['status']=='repeated' for o in i['observations']) for i in items),
              frames=sum(i['frames'] for i in items),raw_reads=sum(i['raw_reads'] for i in items),
              observation_alternatives=sum(len(i['observations']) for i in items),
              exposure_modes=dict(Counter(i['mode'] for i in items)),gains=dict(Counter(i['gain'] for i in items)),
              first_local=items[0]['time'],last_local=items[-1]['time'],clips_detail=items))
        policies=sorted({tuple(json.loads(row['parameters']).get('number_lengths',[3])) for row in rows})
        batch_state=c.execute('SELECT state,total_clips FROM ocr_batches WHERE id=?',(batch,)).fetchone()
        return dict(generated_utc=datetime.now(timezone.utc).isoformat(),batch_id=batch,
          number_length_policies=[list(p) for p in policies],
          import_state=batch_state['state'] if batch_state else None,
          planned_clips=batch_state['total_clips'] if batch_state else None,
          clips=len(rows),candidate_clips=sum(r['candidate_clips'] for r in result),
          operator_review_count=c.execute('SELECT COUNT(*) FROM bib_reviews').fetchone()[0],
          groups=result,hourly=[dict(setting=k[0],hour=k[1],clips=v[0],candidate_clips=v[1]) for k,v in sorted(hourly.items(),key=lambda item:(item[0][0] is None,item[0][0] or 0,item[0][1]))],
          selected_previously_verified_examples=examples,
          interpretation='Exposure values are trigger-time driver metadata in 100-microsecond units. Candidates include wrong and ambiguous hypotheses. No ground-truth accuracy rate or causal shutter effect is established.')
    finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('database',type=Path);p.add_argument('--batch',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.database,a.batch);a.output.write_text(json.dumps(result,indent=2)+'\n')
    for row in result['groups']:print(json.dumps({k:v for k,v in row.items() if k!='clips_detail'}))


if __name__=='__main__':main()
