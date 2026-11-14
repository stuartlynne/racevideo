"""Verify every transferred byte against an independently checked SQLite snapshot."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(str(args.snapshot) + '.json').read_text())
    if manifest['quick_check'] != 'ok':
        raise ValueError('Source snapshot did not pass SQLite quick_check')
    size = args.snapshot.stat().st_size
    if size != manifest['bytes']:
        raise ValueError(f'File size mismatch: {size} != {manifest["bytes"]}')
    started = time.monotonic()
    digest = hashlib.sha256()
    total = 0
    last = -1
    with args.snapshot.open('rb') as stream:
        while chunk := stream.read(16 * 1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
            percent = int(total * 100 / max(1, size))
            if percent // 10 != last:
                last = percent // 10
                print(f'Verify hash {percent}%', flush=True)
    if digest.hexdigest() != manifest['sha256']:
        raise ValueError('SHA256 mismatch; transferred snapshot is not verified')
    connection = sqlite3.connect(args.snapshot.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        daily = connection.execute("SELECT date(started_ns/1000000000,'unixepoch','localtime'), count(*), sum(frame_count) FROM clips GROUP BY 1").fetchall()
        frames = connection.execute('SELECT count(*) FROM frames').fetchone()[0]
    finally:
        connection.close()
    if [list(row) for row in daily] != manifest['daily_counts']:
        raise ValueError('Daily clip counts differ from source; check local timezone')
    if frames != sum(row[2] for row in daily):
        raise ValueError('Stored frame count differs from clip totals')
    report = dict(snapshot=str(args.snapshot.resolve()), bytes=size,
                  sha256=digest.hexdigest(), hash_matches=True,
                  source_quick_check='ok', daily_counts=daily,
                  stored_frames=frames,
                  completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  wall_seconds=time.monotonic() - started)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
