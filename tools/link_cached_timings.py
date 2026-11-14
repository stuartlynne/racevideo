"""Link existing measured tracks using current evidence keys; no timing approval."""
import argparse,json
from pathlib import Path
from racevideo import storage,wheel_timing,bike_index,passings


def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True,type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
    c=storage.connect(a.db);models={};navigation={};matches=[];skipped=0
    for row in c.execute("SELECT id,clip_id,parameters,report FROM wheel_analyses WHERE state='complete' ORDER BY id").fetchall():
        if not json.loads(row['report']).get('samples'):continue
        entry=json.loads(row['parameters'])['entry'];clip=row['clip_id']
        if clip not in navigation:navigation[clip]=bike_index.navigation(c,clip)
        candidates=[e for e in navigation[clip]['stops'] if (e.get('visual_key')==entry['visual_key'] if entry.get('visual_key') else
            e['key']==entry['key'] and e['first_ordinal']==entry['first_ordinal'] and e['last_ordinal']==entry['last_ordinal'])]
        if len(candidates)!=1:skipped+=1;continue
        entry=candidates[0];meta=c.execute('SELECT started_ns,ended_ns FROM clips WHERE id=?',(clip,)).fetchone()
        found=[]
        for event in c.execute('SELECT id FROM race_events WHERE start_ns<=? AND end_ns>=?',(meta['ended_ns'],meta['started_ns'])).fetchall():
            if event['id'] not in models:models[event['id']]=passings.compare_event(c,event['id'])
            context=wheel_timing.passing_context(models[event['id']],clip,entry)
            if context:found.append(context)
        # Never choose between overlapping event interpretations.
        if len(found)!=1:skipped+=1;continue
        context=found[0]
        item=dict(analysis_id=row['id'],clip_id=clip,context=context)
        if a.apply:
            with c:item['link_id']=wheel_timing.link_passing(c,row['id'],context)
        matches.append(item)
    print(json.dumps(dict(applied=a.apply,matched=matches,skipped=skipped),indent=2));c.close()


if __name__=='__main__':main()
