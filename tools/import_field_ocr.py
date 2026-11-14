"""CLI for atomic GPU-result import into the writable review store."""
import argparse,json
from pathlib import Path
from racevideo.ocr_import import prepare,import_clip,import_directory

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('database',type=Path);p.add_argument('results',type=Path);a=p.parse_args()
    print(json.dumps(import_directory(a.database,a.results)),flush=True)


if __name__=='__main__':main()
