"""Read-only audit of automatic review reconciliation across cached events."""
import argparse,json
from pathlib import Path
from racevideo import storage,passings
from racevideo.bike_evidence import collect
from racevideo.review_resolution import resolve


def audit(database,day=None):
    c=storage.connect(database,readonly=True)
    try:
        c.execute('BEGIN')
        events=c.execute('''SELECT e.* FROM race_events e JOIN race_competitions c ON c.id=e.competition_id
            WHERE (? IS NULL OR c.day=?) ORDER BY e.start_ns,e.id''',(day,day)).fetchall()
        rows=[]
        for event in events:
            model=passings.compare_event(c,event['id'])
            raw,_=collect(c,event['start_ns'],event['end_ns'],event_id=event['id'])
            reviews=[dict(r) for r in c.execute('SELECT * FROM race_visual_reviews WHERE event_id=?',(event['id'],))]
            visible=resolve(raw,reviews)['evidence']
            represented={v['key'] for cell in model['cells'] for v in cell['captures'][:cell['visual_count']] if v.get('confirmed')}
            missing=[dict(review_key=v['key'],bib=v['number'],clip_id=v['clip_id'],ordinal=v['ordinal'])
                for v in visible if v['confirmed'] and v['key'] not in represented]
            rows.append(dict(event_id=event['id'],event=event['name'],visible_manual=sum(bool(v['confirmed']) for v in visible),
                reconciliations=model['review_reconciliations'],unrepresented_manual=missing))
        return dict(events=rows,summary=dict(events=len(rows),manual=sum(r['visible_manual'] for r in rows),
            automatic_reconciliations=sum(len(r['reconciliations']) for r in rows),
            unrepresented_manual=sum(len(r['unrepresented_manual']) for r in rows)))
    finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--day');p.add_argument('--output');a=p.parse_args()
    report=audit(a.db,a.day)
    if a.output:Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['summary']))
    return int(bool(report['summary']['unrepresented_manual']))


if __name__=='__main__':raise SystemExit(main())
