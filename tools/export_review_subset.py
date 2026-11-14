"""Read-only source export of complete clips into an explicitly derived test store."""
import argparse,sqlite3,json,time
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('--clips',type=int,nargs='+',required=True);a=p.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 a.output.parent.mkdir(parents=True,exist_ok=True);source=sqlite3.connect(a.source.resolve().as_uri()+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
 dest=sqlite3.connect(a.output);dest.execute('PRAGMA journal_mode=DELETE')
 tables=['clips','frames','clip_details']
 for table in tables:
  sql=source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0];dest.execute(sql)
 counts=[]
 for clip in a.clips:
  with dest:
   for table,key in [('clips','id'),('frames','clip_id'),('clip_details','clip_id')]:
    query=f'SELECT * FROM {table} WHERE {key}=?';cursor=source.execute(query,(clip,));names=[d[0] for d in cursor.description];placeholders=','.join('?' for _ in names)
    for row in cursor:dest.execute(f'INSERT INTO {table} VALUES ({placeholders})',tuple(row))
  count=dest.execute('SELECT count(*) FROM frames WHERE clip_id=?',(clip,)).fetchone()[0];counts.append([clip,count]);print('copied',clip,count,flush=True)
 dest.close();source.close();Path(str(a.output)+'.json').write_text(json.dumps(dict(source=str(a.source),derived_subset=True,clips=counts),indent=2)+'\n')
if __name__=='__main__':main()
