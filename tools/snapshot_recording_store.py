"""Create a consistent standalone SQLite backup without changing the source store."""
import argparse,sqlite3,time,json,hashlib,shutil,datetime,os
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
 if a.destination.exists():raise FileExistsError(a.destination)
 partial=Path(str(a.destination)+'.partial')
 if partial.exists():raise FileExistsError(partial)
 a.destination.parent.mkdir(parents=True,exist_ok=True)
 if shutil.disk_usage(a.destination.parent).free<a.source.stat().st_size*1.05:raise RuntimeError('Insufficient snapshot space')
 source=sqlite3.connect(a.source.resolve().as_uri()+'?mode=ro',uri=True,timeout=30);dest=sqlite3.connect(partial)
 started=time.monotonic();last=[-1]
 def progress(status,remaining,total):
  pct=int(100*(total-remaining)/max(1,total))
  if pct//5!=last[0]:last[0]=pct//5;print(f'backup {pct}% ({total-remaining}/{total} pages)',flush=True)
 try:source.backup(dest,pages=1024,progress=progress,sleep=.02)
 finally:source.close();dest.close()
 os.replace(partial,a.destination)
 print('backup complete; validating',flush=True)
 c=sqlite3.connect(a.destination.resolve().as_uri()+'?mode=ro',uri=True)
 check=c.execute('PRAGMA quick_check').fetchall()
 if check!=[('ok',)]:raise RuntimeError(check)
 print('quick_check ok; hashing snapshot',flush=True)
 days=c.execute("SELECT date(started_ns/1000000000,'unixepoch','localtime'),count(*),sum(frame_count) FROM clips GROUP BY 1").fetchall();c.close()
 h=hashlib.sha256()
 done=0;last_hash=-1;size=a.destination.stat().st_size
 with a.destination.open('rb') as f:
  while block:=f.read(16*1024*1024):
   h.update(block);done+=len(block);pct=int(done*100/max(1,size))
   if pct//10!=last_hash:last_hash=pct//10;print(f'hash {pct}%',flush=True)
 report=dict(source=str(a.source),snapshot=str(a.destination),bytes=a.destination.stat().st_size,sha256=h.hexdigest(),quick_check='ok',daily_counts=days,completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),wall_seconds=time.monotonic()-started)
 manifest=Path(str(a.destination)+'.json');temporary=Path(str(manifest)+'.tmp')
 temporary.write_text(json.dumps(report,indent=2)+'\n');os.replace(temporary,manifest);print(json.dumps(report),flush=True)
if __name__=='__main__':main()
