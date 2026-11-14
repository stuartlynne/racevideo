"""Analysis/segment coordinator with independent camera-ingestion process.

SQLite writing is queued on a bounded writer thread. Capture and live preview
continue independently of motion analysis and storage latency.
"""
from __future__ import annotations

from collections import deque
import fcntl
import logging
import os
from pathlib import Path
import queue
import signal
import shutil
import threading
import time
import uuid


from . import storage
from .motion import DEFAULT_ROI, MotionEvents, validate_roi
from .motion_profiles import MotionBank,validate_profile
from .camera import CameraControls
from .service import OPTIONS
from .pipeline import FrameRing, PreviewSource, capture_worker, context, preview_path, ProcessFlag

LOG = logging.getLogger(__name__)


class RecentFrames:
    def __init__(self, seconds: float, max_bytes: int):
        self.duration_ns = int(seconds * 1e9)
        self.max_bytes = max_bytes
        self.frames = deque()
        self.bytes = 0
        self.evicted_for_size = 0

    def append(self, frame: storage.Frame):
        self.frames.append(frame)
        self.bytes += len(frame.jpeg)
        cutoff = frame.monotonic_ns - self.duration_ns
        while self.frames and (self.frames[0].monotonic_ns < cutoff or
                               self.bytes > self.max_bytes):
            if self.bytes > self.max_bytes:
                self.evicted_for_size += 1
            self.bytes -= len(self.frames.popleft().jpeg)

    def snapshot(self):
        return list(self.frames)


def record(args, *, capture_target=capture_worker) -> int:
    path = Path(args.db).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # The OS releases this lock even after a crash. It prevents two recorders
    # writing the same database or competing for its camera.
    lock = open(str(path) + ".recorder.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        LOG.error("A recorder already owns %s", path)
        lock.close()
        return 2
    stop = threading.Event()
    capture_done = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    clips = queue.Queue(maxsize=3)
    controls = queue.SimpleQueue()
    shared_lock = threading.Lock()
    state = dict(state="starting", pid=os.getpid(), session=uuid.uuid4().hex,
                 device=args.device, width=args.width, height=args.height,
                 requested_fps=args.fps, interval=args.interval, seconds=args.seconds,
                 frames=0, fps=0, saved_clips=0, dropped_clips=0,
                 buffer_bytes=0, buffer_seconds=0, error=None)
    state['configuration'] = {name: getattr(args, name) for name in OPTIONS}
    state['control_protocol']=3
    state['storage_protocol']=7
    latest = [None]
    ctx = context()
    ring = FrameRing(args.buffer_mb * 1024**2)
    io_stop, io_done = ProcessFlag(), ProcessFlag()
    reports = ctx.Queue(maxsize=4)
    capture = ctx.Process(target=capture_target, args=(args, ring, io_stop, io_done, reports),
                          name="racevideo-capture")
    state.update(architecture_version=2, analysis_overrun_frames=0, analysis_lag_ms=0,
                 motion_analysis_ms=0, writer_queue_clips=0)
    writer_error = []
    settings_ready = threading.Event()

    def writer():
        connection = None
        camera = None
        preview_source = None
        try:
            connection = storage.connect(path)
            storage.initialize(connection)
            last_roi = validate_roi(storage.read_setting(connection, "motion_roi", DEFAULT_ROI))
            last_profile=validate_profile(storage.read_setting(connection,'motion_profile',{}))
            with shared_lock:
                state.update(roi=last_roi,motion_profile=last_profile, trigger=args.trigger, moving=False, event_active=False,
                             motion_score=0, pre_roll=args.pre_roll, post_roll=args.post_roll,
                             motion_gap=args.motion_gap)
            settings_ready.set()
            # Do not replay commands left by a previously terminated session.
            with connection:
                connection.execute("UPDATE commands SET handled=? WHERE handled IS NULL",
                                   (time.time(),))
                connection.execute("UPDATE camera_requests SET processed=?,error=? WHERE processed IS NULL",
                                   (time.time(), "Recorder restarted; request was not applied"))
            try:
                camera = CameraControls(args.device)
                available = camera.enumerate()
                with shared_lock:
                    state.update(camera_controls=available, camera_controls_error=None,
                                 camera_controls_observed_ns=time.time_ns())
            except Exception as exc:
                LOG.warning("Camera controls unavailable: %s", exc)
                with shared_lock:
                    state.update(camera_controls=[], camera_controls_error=str(exc))
            last_publish = 0
            last_camera_poll = time.monotonic()
            while not capture_done.is_set() or not clips.empty():
                try:
                    frames, trigger, reason, metadata = clips.get(timeout=0.04)
                    if shutil.disk_usage(path.parent).free < 512 * 1024 * 1024:
                        raise RuntimeError("Less than 512 MiB free: recording stopped to protect disk space")
                    write_started = time.perf_counter()
                    from .capture_modes import frame_metrics
                    metadata=dict(metadata or {},recording_metrics=frame_metrics(frames))
                    storage.save_clip(connection, frames, trigger, reason,
                                      args.width, args.height, state["session"], metadata)
                    with shared_lock:
                        state["saved_clips"] += 1
                        state["last_clip_write_ms"] = (time.perf_counter() - write_started) * 1000
                    LOG.info("Saved %s clip, %s frames", reason, len(frames))
                except queue.Empty:
                    pass
                if time.monotonic() - last_publish >= 0.2:
                    requests = connection.execute(
                        "SELECT * FROM camera_requests WHERE processed IS NULL ORDER BY id").fetchall()
                    for requested in requests:
                        actual, error = None, None
                        try:
                            if requested["session"] != state["session"]:
                                raise ValueError("Recorder session changed; request was not applied")
                            if requested['expires'] is not None and time.time()>requested['expires']:
                                raise ValueError('Camera request expired before execution')
                            if requested['command_id']:
                                lease=connection.execute('SELECT * FROM control_leases WHERE id=?',(requested['command_id'],)).fetchone()
                                if not lease or lease['revoked'] or lease['expires']<time.time():
                                    raise ValueError('Agent camera lease expired or was released by operator')
                            if not camera:
                                raise RuntimeError("Camera controls unavailable")
                            actual = camera.set(requested["control_id"], requested["value"])
                        except Exception as exc:
                            error = str(exc)
                            LOG.warning("Camera control request failed: %s", error)
                        with connection:
                            connection.execute("UPDATE camera_requests SET processed=?,actual=?,error=? WHERE id=?",
                                               (time.time(), actual, error, requested["id"]))
                    if camera and (requests or time.monotonic() - last_camera_poll >= 2):
                        try:
                            available = camera.enumerate()
                            with shared_lock:
                                state.update(camera_controls=available, camera_controls_error=None,
                                             camera_controls_observed_ns=time.time_ns())
                        except Exception as exc:
                            with shared_lock:
                                state["camera_controls_error"] = str(exc)
                        last_camera_poll = time.monotonic()
                    # Preview sampling is independent of analysis progress and JPEG decode.
                    try:
                        if preview_source and preview_path(path).stat().st_ino != preview_source.inode:
                            preview_source.close()
                            preview_source = None
                        if preview_source is None:
                            preview_source = PreviewSource(path)
                        sample = preview_source.read(0)
                    except (OSError, ValueError):
                        sample = None
                    with shared_lock:
                        if sample:
                            latest[0] = sample[2]
                            state['last_frame_ns'] = sample[0]
                            state['analysis_lag_ms'] = max(0, sample[1] - state.get('analysis_monotonic_ns', sample[1])) / 1e6
                        _, _, _, info = ring.read(2**63 - 1, limit=0)
                        state.update(info)
                        state['analysis_backlog_frames'] = max(0, state.get('capture_frames', 0) - state.get('frames', 0) - state.get('analysis_overrun_frames', 0))
                        state['writer_queue_clips'] = clips.qsize()
                        status, preview = state.copy(), latest[0]
                    storage.publish(connection, status, preview)
                    rows = connection.execute(
                        "SELECT id,name FROM commands WHERE handled IS NULL ORDER BY id"
                    ).fetchall()
                    with connection:
                        for row in rows:
                            controls.put(row["name"])
                            if row["name"] == "stop":
                                stop.set()
                            connection.execute("UPDATE commands SET handled=? WHERE id=?",
                                               (time.time(), row["id"]))
                    roi = validate_roi(storage.read_setting(connection, "motion_roi", DEFAULT_ROI))
                    profile=validate_profile(storage.read_setting(connection,'motion_profile',{}))
                    if roi != last_roi or profile!=last_profile:
                        controls.put(('motion_profile',(roi,profile)))
                        last_roi,last_profile=roi,profile
                    last_publish = time.monotonic()
            with shared_lock:
                status = state.copy()
                status["state"] = "error" if status.get("error") else "stopped"
            storage.publish(connection, status, latest[0])
        except Exception as exc:
            LOG.exception("Recorder storage failed")
            writer_error.append(str(exc))
            with shared_lock:
                state.update(state="error", error=str(exc))
                status = state.copy()
            if connection:
                try:
                    storage.publish(connection, status, latest[0])
                except Exception:
                    LOG.exception("Could not publish recorder failure; consult recorder log")
            stop.set()
        finally:
            settings_ready.set()
            if preview_source:
                preview_source.close()
            if camera:
                camera.close()
            if connection:
                connection.close()

    thread = threading.Thread(target=writer, name="sqlite-writer")
    thread.start()
    events = None
    result = 0

    def enqueue(frames, trigger, reason, metadata=None):
        try:
            metadata=dict(metadata or {})
            if frames:
                metadata.update(capture_bad_packets_before_segment=frames[0].capture_bad_packets,
                                capture_bad_packets_through_segment=frames[-1].capture_bad_packets,
                                capture_bad_packets_in_segment=max(0,frames[-1].capture_bad_packets-frames[0].capture_bad_packets))
            clips.put_nowait((frames, trigger, reason, metadata))
        except queue.Full:
            with shared_lock:
                state["dropped_clips"] += 1
            LOG.error("Disk writer behind; skipped clip (queue full)")

    def save_event(clip):
        if clip:
            enqueue(clip.frames, clip.trigger_ns, "motion", clip.metadata)

    try:
        if not settings_ready.wait(5) or writer_error:
            raise RuntimeError("Recorder settings could not be loaded")
        detector = MotionBank(state['roi'],args.motion_delta,args.motion_fraction,state['motion_profile'])
        events = MotionEvents(args.pre_roll, args.post_roll, args.motion_gap,
                              args.event_mb * 1024**2, args.event_seconds,quiet_close=args.quiet_close)

        def motion_context():
            with shared_lock:
                settings = {str(c["id"]): c["value"] for c in state.get("camera_controls", [])}
                observed = state.get("camera_controls_observed_ns")
            return dict(roi=list(detector.roi), motion_delta=args.motion_delta,
                        motion_profile=detector.profile,
                        motion_fraction=args.motion_fraction,
                        camera_settings_at_trigger=settings,
                        camera_settings_observed_ns=observed,
                        analysis_overrun_frames=state.get("analysis_overrun_frames", 0),
                        camera_mode=dict(requested=state['configuration'].copy(),
                          delivered_width=state.get('width'),delivered_height=state.get('height'),
                          negotiated_fps=state.get('negotiated_fps'),measured_fps=state.get('capture_fps'),
                          measured_window_seconds=state.get('capture_window_seconds'),metrics_ns=state.get('capture_metrics_ns'),
                          capture_bad_packets=state.get('capture_bad_packets',0)))

        events.context = motion_context()
        capture.start()
        with shared_lock:
            state['capture_pid'] = capture.pid
            state['analysis_pid'] = os.getpid()

        def incoming():
            cursor = 0
            while True:
                while not reports.empty():
                    report = reports.get()
                    if report.get('error'):
                        raise RuntimeError(report['error'])
                    if 'width' in report:args.width,args.height=report['width'],report['height']
                    with shared_lock:state.update(report)
                cursor, batch, missed, info = ring.read(cursor)
                with shared_lock:
                    state.update(info)
                    state['analysis_overrun_frames'] += missed
                if missed:
                    LOG.error('Analysis overrun: %s compressed frames overwritten', missed)
                    save_event(events.flush('analysis_overrun'))
                    detector.reset(detector.roi)
                    recent.frames.clear()
                    recent.bytes = 0
                for frame in batch:
                    yield frame
                if stop.is_set():
                    io_stop.set()
                    break
                if not batch:
                    if io_done.is_set():
                        # Reports precede the done event, but multiprocessing Queue
                        # feeder delivery may lag it. Join, then drain reports once.
                        capture.join(1)
                        while True:
                            try:
                                report = reports.get(timeout=.1)
                            except queue.Empty:
                                break
                            if report.get('error'):
                                raise RuntimeError(report['error'])
                            if 'width' in report:args.width,args.height=report['width'],report['height']
                            with shared_lock:state.update(report)
                        if capture.exitcode not in (None, 0):
                            raise RuntimeError(f'Capture worker failed ({capture.exitcode})')
                        break
                    if not capture.is_alive():
                        raise RuntimeError(f'Capture worker exited unexpectedly ({capture.exitcode})')
                    time.sleep(.003)

        recent = RecentFrames(max(args.seconds, args.pre_roll + 0.25), args.buffer_mb * 1024 * 1024)
        next_capture = time.monotonic() + args.interval
        next_analysis = 0
        motion_score = 0
        frame_times = deque()
        for frame in incoming():
            now = frame.monotonic_ns / 1e9
            recent.append(frame)
            frame_times.append(now)
            while len(frame_times) > 1 and now - frame_times[0] > 3:
                frame_times.popleft()
            fps = ((len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
                   if len(frame_times) > 1 else 0)
            reason = None
            while not controls.empty():
                control = controls.get()
                if control == "stop":
                    stop.set()
                elif control == "capture":
                    reason = "manual"
                elif isinstance(control, tuple) and control[0] == 'motion_profile':
                    save_event(events.flush('motion_profile_changed'))
                    events.last_motion_ns = None
                    detector.reset(*control[1])
                    events.context = motion_context()
                    motion_score = 0
                    next_analysis = 0
            if stop.is_set():
                break
            detected = None
            if args.trigger == "motion":
                if not events.active:
                    events.context = motion_context()
                if now >= next_analysis:
                    analysis_started = time.perf_counter()
                    detected, motion_score = detector.analyze(frame.jpeg,event_active=events.active)
                    with shared_lock:
                        state["motion_analysis_ms"] = (time.perf_counter() - analysis_started) * 1000
                        state.update(motion_decode_ms=detector.decode_ms,motion_compare_ms=detector.compare_ms,
                                     motion_zones=detector.zone_states,motion_profile=detector.profile)
                    next_analysis = max(next_analysis + 1 / args.motion_fps, now)
                for clip in events.update(frame, detected, recent.frames):
                    save_event(clip)
            with shared_lock:
                state.update(state="recording", frames=state["frames"] + 1, fps=fps,
                             analysis_last_frame_ns=frame.received_ns,
                             analysis_monotonic_ns=frame.monotonic_ns,
                             analysis_lag_ms=max(0, state.get("newest_monotonic_ns", frame.monotonic_ns) - frame.monotonic_ns) / 1e6,
                             width=args.width, height=args.height,
                             roi=detector.roi, moving=events.moving(frame.monotonic_ns),
                             event_active=events.active, motion_score=motion_score,
                             buffer_bytes=recent.bytes,
                             buffer_seconds=(recent.frames[-1].monotonic_ns -
                                             recent.frames[0].monotonic_ns) / 1e9
                             if recent.frames else 0,
                             buffer_size_evictions=recent.evicted_for_size)
            if args.trigger == "timer" and now >= next_capture:
                reason = reason or "timer"
                next_capture = now + args.interval
            if reason and recent.frames and not stop.is_set():
                cutoff = frame.monotonic_ns - int(args.seconds * 1e9)
                enqueue([f for f in recent.frames if f.monotonic_ns >= cutoff],
                        frame.received_ns, reason, motion_context())

    except Exception as exc:
        LOG.exception("Camera capture failed")
        with shared_lock:
            state.update(state="error", error=str(exc))
        result = 1
    finally:
        if events:
            save_event(events.flush("stop" if not result else "capture_error"))
        with shared_lock:
            state.update(moving=False, event_active=False)
        io_stop.set()
        if capture.pid:
            capture.join(2)
            if capture.is_alive():
                capture.terminate()
                capture.join(2)
            if capture.is_alive():
                capture.kill(); capture.join(1)
        reports.close()
        stop.set()
        capture_done.set()
        thread.join()
        lock.close()
    if writer_error:
        return 1
    return result
