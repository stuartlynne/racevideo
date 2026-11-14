"""Import a day's trusted CMNs into RaceVideo through the saved-race MCP API."""
import argparse
import json
from pathlib import Path
from racevideo.crossmgr_client import Configuration
from racevideo import passings, storage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--day',required=True)
    parser.add_argument('--root')
    args=parser.parse_args()
    config=Configuration.load()
    if args.root:config.root=args.root
    events=passings.import_day(args.db,config,args.day)
    c=storage.connect(args.db,readonly=True)
    try:
        reports=[]
        for event in events:
            model=passings.compare_event(c,event)
            reports.append(dict(event=model['event']['name'],event_id=event,
                columns=len(model['columns']),counts={state:sum(x['state']==state for x in model['cells'])
                    for state in ('matched','missing','extra','video_only')}))
        print(json.dumps(reports,indent=2))
    finally:c.close()


if __name__=='__main__':main()
