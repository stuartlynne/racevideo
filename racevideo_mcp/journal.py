import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time


class Journal:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS commands(
              id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, target TEXT NOT NULL,
              operation TEXT NOT NULL, state TEXT NOT NULL, result TEXT, error TEXT,
              created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
              store TEXT NOT NULL,state TEXT NOT NULL,result TEXT,error TEXT,created REAL NOT NULL,updated REAL NOT NULL);
            UPDATE commands SET state='unknown',error='Service restarted before outcome reconciliation'
              WHERE state IN ('queued','sent');
            UPDATE jobs SET state='error',error='Service restarted during job' WHERE state IN ('queued','running');''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=3);c.row_factory=sqlite3.Row
        try:
            c.execute('PRAGMA journal_mode=WAL')
            with c:yield c
        finally:c.close()

    def command(self,cid,target,operation,arguments):
        fingerprint=hashlib.sha256(json.dumps([target,operation,arguments],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.connect() as c:
            row=c.execute('SELECT * FROM commands WHERE id=?',(cid,)).fetchone()
            if row:
                if row['fingerprint']!=fingerprint:raise ValueError('Command ID already belongs to different arguments')
                return self.get_command(cid),False
            now=time.time()
            c.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?)',
                      (cid,fingerprint,target,operation,'queued',None,None,now,now))
        return self.get_command(cid),True

    def command_result(self,cid,state,result=None,error=None):
        with self.connect() as c:c.execute('UPDATE commands SET state=?,result=?,error=?,updated=? WHERE id=?',
            (state,json.dumps(result) if result is not None else None,error,time.time(),cid))

    def get_command(self,cid):
        with self.connect() as c:row=c.execute('SELECT * FROM commands WHERE id=?',(cid,)).fetchone()
        if not row:raise ValueError('Unknown command ID')
        result=dict(row);result.pop('fingerprint');result['result']=json.loads(result['result']) if result['result'] else None
        return result

    def create_job(self,jid,kind,store):
        with self.connect() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
            (jid,kind,store,'queued',None,None,time.time(),time.time()))

    def update_job(self,jid,state,result=None,error=None):
        with self.connect() as c:c.execute('UPDATE jobs SET state=?,result=?,error=?,updated=? WHERE id=?',
            (state,json.dumps(result) if result is not None else None,error,time.time(),jid))

    def get_job(self,jid):
        with self.connect() as c:row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row:raise ValueError('Unknown job ID')
        result=dict(row);result['result']=json.loads(result['result']) if result['result'] else None
        return result
