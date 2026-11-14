"""A portable snapshot must include committed rows still in the source WAL."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class SnapshotTests(unittest.TestCase):
    def test_committed_wal_is_copied_and_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.sqlite3'
            destination = Path(folder) / 'snapshot.sqlite3'
            connection = sqlite3.connect(source)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA wal_autocheckpoint=0')
            connection.execute('CREATE TABLE clips(started_ns INTEGER, frame_count INTEGER)')
            connection.execute('CREATE TABLE frames(ordinal INTEGER)')
            connection.executemany('INSERT INTO frames VALUES(?)', [(0,), (1,), (2,)])
            connection.execute('INSERT INTO clips VALUES(1000000000, 3)')
            connection.commit()
            self.assertGreater(Path(str(source) + '-wal').stat().st_size, 0)
            command = [sys.executable, '-m', 'tools.snapshot_recording_store', str(source), str(destination)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            report = json.loads(Path(str(destination) + '.json').read_text())
            self.assertEqual(report['sha256'], hashlib.sha256(destination.read_bytes()).hexdigest())
            self.assertEqual(report['quick_check'], 'ok')
            copied = sqlite3.connect(destination)
            try:
                self.assertEqual(copied.execute('SELECT * FROM clips').fetchall(), [(1000000000, 3)])
            finally:
                copied.close()
            verified = Path(folder) / 'verified.json'
            subprocess.run([sys.executable, '-m', 'tools.verify_recording_snapshot',
                            str(destination), '--output', str(verified)],
                           check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(verified.read_text())['stored_frames'], 3)
            self.assertEqual(connection.execute('SELECT * FROM clips').fetchall(), [(1000000000, 3)])
            # Refuse to overwrite an existing verified archive.
            retry = subprocess.run(command, capture_output=True)
            self.assertNotEqual(retry.returncode, 0)
            connection.close()
