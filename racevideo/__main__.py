"""Run `python -m racevideo` to launch capture and review."""
import argparse
import logging
from pathlib import Path

from . import storage
from .service import recorder_running, start_recorder


def parser():
    p = argparse.ArgumentParser(description="RaceVideo MJPEG recorder and concurrent review")
    p.add_argument("action", nargs="?", choices=("gui", "record", "status", "stop", "capture", "ocr"), default="gui")
    p.add_argument("--db", default="data/racevideo.sqlite3", help="SQLite recording store")
    p.add_argument("--device", default="/dev/video0")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--trigger", choices=("motion", "timer"), default="motion")
    p.add_argument("--interval", type=float, default=10, help="Seconds between timer-mode captures")
    p.add_argument("--seconds", type=float, default=2, help="Seconds in manual/timer recent-buffer captures")
    p.add_argument("--pre-roll", type=float, default=0.5)
    p.add_argument("--post-roll", type=float, default=2.0)
    p.add_argument('--quiet-close',type=float,default=1.0,help='Close a motion clip after this many quiet seconds; 0 uses full post-roll')
    p.add_argument("--motion-gap", type=float, default=0.2, help="Quiet gap held as one motion indication")
    p.add_argument("--motion-fps", type=float, default=15, help="Maximum motion analysis rate")
    p.add_argument("--motion-delta", type=int, default=18, help="Changed-pixel brightness threshold (1–255)")
    p.add_argument("--motion-fraction", type=float, default=0.025, help="Changed fraction of ROI needed to trigger")
    p.add_argument("--event-mb", type=int, default=128, help="Split long motion events at this compressed size")
    p.add_argument("--event-seconds", type=float, default=30, help="Split long motion events at this duration")
    p.add_argument("--buffer-mb", type=int, default=64, help="Compressed rolling buffer RAM cap")
    p.add_argument("--run-seconds", type=float, default=0, help="Recorder test duration; zero runs until stopped")
    p.add_argument("--no-start", action="store_true", help="Review existing store without starting a recorder")
    p.add_argument("--camera-controls", action="store_true", help="Open camera settings with the review window")
    p.add_argument('--review-clip',type=int,help='Open a saved clip for review')
    p.add_argument('--passings',action='store_true',help='Open the event passings review window')
    p.add_argument('--clip',type=int,help='Saved clip ID to scan')
    p.add_argument('--ocr-area',default='0,0,1,1',help='Normalized left,top,right,bottom OCR search area')
    p.add_argument('--ocr-fps',type=float,default=8)
    p.add_argument('--ocr-run',type=int,help=argparse.SUPPRESS)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    import math
    if not math.isfinite(args.fps) or args.fps<=0:p.error('Frame rate must be finite and positive')
    if not math.isfinite(args.quiet_close) or args.quiet_close<0:p.error('Quiet close must be finite and nonnegative')
    if min(args.width, args.height, args.fps, args.interval, args.seconds, args.buffer_mb) <= 0:
        p.error("Capture dimensions, rate, durations and buffer size must be positive")
    if (min(args.post_roll, args.motion_gap, args.motion_fps, args.event_mb, args.event_seconds) <= 0 or
            args.pre_roll < 0 or not 1 <= args.motion_delta <= 255 or
            not 0 < args.motion_fraction <= 1):
        p.error("Motion timings/limits must be positive, pre-roll nonnegative, delta 1–255, fraction (0,1]")
    path = Path(args.db).expanduser().resolve()
    args.db = str(path)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action=='ocr':
        import json
        connection=storage.connect(path)
        storage.initialize(connection)
        connection.close()
        run_id=args.ocr_run
        if not run_id:
            if not args.clip:p.error('OCR requires --clip')
            try:area=[float(v) for v in args.ocr_area.split(',')]
            except ValueError:p.error('OCR area requires four comma-separated numbers')
            run_id=storage.create_ocr_run(path,args.clip,dict(roi=area,fps=args.ocr_fps))
        try:
            from .ocr import run_job
            result=run_job(path,run_id)
            print(json.dumps(result,indent=2))
            return 0
        except Exception as exc:
            connection=storage.connect(path)
            with connection:connection.execute("UPDATE ocr_runs SET state='error',error=? WHERE id=?",(str(exc),run_id))
            connection.close()
            logging.exception("OCR failed; install optional OCR dependencies with pip install -e '.[ocr]'")
            return 1
    if args.action == "record":
        from .recorder import record
        return record(args)
    if args.action in ("capture", "stop"):
        if not recorder_running(path):
            p.error("No recorder is running for this database")
        storage.command(path, args.action)
        return 0
    if args.action == "status":
        import json
        with storage.connect(path, readonly=True) as connection:
            status = storage.read_runtime(connection)
            status.pop("preview", None)
            status["recorder_running"] = recorder_running(path)
            status["total_clips"] = connection.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
            print(json.dumps(status, indent=2))
        return 0
    with storage.connect(path) as connection:
        storage.initialize(connection)
        saved=storage.read_setting(connection,'capture_configuration',{})
    import sys
    arguments=sys.argv[1:] if argv is None else argv
    for key in ('device','width','height','fps'):
        if key in saved and not any(a=='--'+key or a.startswith('--'+key+'=') for a in arguments):
            setattr(args,key,saved[key])
    if not args.no_start and not recorder_running(path):
        start_recorder(path, vars(args))
        print(f"Recorder log: {path.with_suffix('.recorder.log')}", flush=True)
        print("Closing the review window leaves the recorder running. Use Stop recorder to finish.", flush=True)
    from .gui import run
    run(path, open_camera=args.camera_controls, review_clip=args.review_clip, open_passings=args.passings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
