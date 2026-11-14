"""Bounded IPC for capture, analysis and latest-only live preview.

Only compressed bytes are retained in the ring. No decoder or disk operation
runs under its lock. Spawned workers do not inherit Tk, SQLite or FFmpeg state.
"""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from fractions import Fraction
import mmap
import logging
import multiprocessing as mp
import os
from pathlib import Path
import signal
import struct
import time

from .storage import Frame


def context():
    return mp.get_context('spawn')


class ProcessFlag:
    """One-byte process signal with no lock a terminated child can strand.

    Setting only changes zero to one; readers poll at bounded intervals. This
    avoids Event/Condition acquisition during GUI shutdown after worker failure.
    """
    def __init__(self):
        self.value=context().RawValue(ctypes.c_ubyte,0)

    def set(self):
        self.value.value=1

    def is_set(self):
        return bool(self.value.value)

    def wait(self,timeout):
        deadline=time.monotonic()+max(0,timeout)
        while not self.is_set():
            remaining=deadline-time.monotonic()
            if remaining<=0:return False
            time.sleep(min(.01,remaining))
        return True


class Entry(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in
                ('received', 'monotonic', 'pts', 'numerator', 'denominator', 'offset', 'size', 'bad_packets')]


class FrameRing:
    """One producer, independent cursors, bounded bytes AND metadata entries.

    Readers copy a small batch under the lock. A slow reader never pins old
    entries. Sequence gaps explicitly report overwrites, including huge frames.
    """
    def __init__(self, max_bytes, slots=8192):
        ctx = context()
        self.capacity, self.slots = int(max_bytes), slots
        self.data = ctx.RawArray(ctypes.c_ubyte, self.capacity)
        self.entries = ctx.RawArray(Entry, slots)
        self.head = ctx.RawValue(ctypes.c_int64, 0)
        self.tail = ctx.RawValue(ctypes.c_int64, 0)
        self.used = ctx.RawValue(ctypes.c_int64, 0)
        self.position = ctx.RawValue(ctypes.c_int64, 0)
        self.oversized = ctx.RawValue(ctypes.c_int64, 0)
        self.bad_packets = ctx.RawValue(ctypes.c_int64, 0)
        self.lock = ctx.Lock()

    @contextmanager
    def locked(self):
        if not self.lock.acquire(timeout=.25):
            raise RuntimeError('Compressed ring lock stalled; worker may have failed')
        try:
            yield
        finally:
            self.lock.release()

    def append(self, frame):
        size = len(frame.jpeg)
        with self.locked():
            if size > self.capacity:
                self.oversized.value += 1
                return False
            while self.tail.value < self.head.value and (
                    self.used.value + size > self.capacity or
                    self.head.value - self.tail.value >= self.slots):
                self.used.value -= self.entries[self.tail.value % self.slots].size
                self.tail.value += 1
            offset = self.position.value
            view = memoryview(self.data).cast('B')
            first = min(size, self.capacity - offset)
            view[offset:offset + first] = frame.jpeg[:first]
            if first < size:
                view[:size - first] = frame.jpeg[first:]
            base = Fraction(frame.time_base) if frame.time_base else Fraction(0)
            e = self.entries[self.head.value % self.slots]
            e.received, e.monotonic = frame.received_ns, frame.monotonic_ns
            e.pts = frame.source_pts if frame.source_pts is not None else -(2**63)
            e.numerator, e.denominator = base.numerator, base.denominator
            e.offset, e.size = offset, size
            e.bad_packets = frame.capture_bad_packets
            self.position.value = (offset + size) % self.capacity
            self.used.value += size
            self.head.value += 1
            return True

    def read(self, cursor, limit=4):
        frames = []
        with self.locked():
            missed = max(0, self.tail.value - cursor)
            cursor = max(cursor, self.tail.value)
            view = memoryview(self.data).cast('B')
            end = min(self.head.value, cursor + limit)
            for seq in range(cursor, end):
                e = self.entries[seq % self.slots]
                first = min(e.size, self.capacity - e.offset)
                jpeg = bytes(view[e.offset:e.offset + first])
                if first < e.size:
                    jpeg += bytes(view[:e.size - first])
                frames.append(Frame(e.received, e.monotonic,
                                    None if e.pts == -(2**63) else e.pts,
                                    f'{e.numerator}/{e.denominator}' if e.numerator else None, jpeg, e.bad_packets))
            oldest = self.entries[self.tail.value % self.slots].monotonic if self.head.value > self.tail.value else 0
            newest = self.entries[(self.head.value - 1) % self.slots].monotonic if self.head.value else 0
            info = dict(ring_bytes=self.used.value, ring_capacity_bytes=self.capacity,
                        ring_frames=self.head.value - self.tail.value,
                        ring_seconds=max(0, newest - oldest) / 1e9,
                        capture_frames=self.head.value, oversized_frames=self.oversized.value,
                        capture_bad_packets=self.bad_packets.value,
                        analysis_backlog_frames=self.head.value - end,
                        newest_monotonic_ns=newest)
        return end, frames, missed, info


# A single mmap file is a bounded latest-JPEG mailbox, not an append-only stream.
# flock covers only a memory copy. Nonblocking writes skip publication rather
# than holding up ingestion. Independent opens are required for flock ownership.
HEADER = struct.Struct('<QQI')  # wall time, monotonic time, JPEG length
MAILBOX_BYTES = 16 * 1024 * 1024


def preview_path(db):
    return Path(str(Path(db).resolve()) + '.preview')


class PreviewSource:
    def __init__(self, db, create=False):
        import fcntl
        self.fcntl = fcntl
        path = preview_path(db)
        if create:
            temporary = path.with_name(path.name + f'.{os.getpid()}')
            self.fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            os.ftruncate(self.fd, MAILBOX_BYTES)
            os.replace(temporary, path)
        else:
            self.fd = os.open(path, os.O_RDONLY)
        self.map = mmap.mmap(self.fd, MAILBOX_BYTES,
                             access=mmap.ACCESS_WRITE if create else mmap.ACCESS_READ)
        self.inode = os.fstat(self.fd).st_ino

    def write(self, frame):
        if len(frame.jpeg) > MAILBOX_BYTES - HEADER.size:
            return False
        try:
            self.fcntl.flock(self.fd, self.fcntl.LOCK_EX | self.fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        try:
            self.map[HEADER.size:HEADER.size + len(frame.jpeg)] = frame.jpeg
            self.map[:HEADER.size] = HEADER.pack(frame.received_ns, frame.monotonic_ns, len(frame.jpeg))
        finally:
            self.fcntl.flock(self.fd, self.fcntl.LOCK_UN)
        return True

    def read(self, previous):
        try:
            self.fcntl.flock(self.fd, self.fcntl.LOCK_SH | self.fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        try:
            received, monotonic, size = HEADER.unpack(self.map[:HEADER.size])
            if received == previous or not 0 < size <= MAILBOX_BYTES - HEADER.size:
                return None
            return received, monotonic, bytes(self.map[HEADER.size:HEADER.size + size])
        finally:
            self.fcntl.flock(self.fd, self.fcntl.LOCK_UN)

    def close(self):
        self.map.close()
        os.close(self.fd)


class PacketGuard:
    """Skip isolated damaged MJPEG frames, but fail a persistently unusable stream.

    Marker/FFmpeg checks do not decode or prove that every JPEG is error-free.
    """
    def __init__(self,now,max_consecutive=60,max_bad_seconds=2):
        self.last_good=now
        self.max_consecutive=max_consecutive
        self.max_bad_seconds=max_bad_seconds
        self.bad_packets=0
        self.consecutive=0

    def accept(self,jpeg,now,corrupt=False):
        if not corrupt and jpeg.startswith(b'\xff\xd8') and jpeg.rfind(b'\xff\xd9')>=2:
            self.last_good=now;self.consecutive=0
            return True
        self.bad_packets+=1;self.consecutive+=1
        if self.consecutive>=self.max_consecutive or now-self.last_good>=self.max_bad_seconds:
            raise RuntimeError(f'Camera stream unusable: {self.consecutive} consecutive damaged JPEG packets; {self.bad_packets} total')
        return False


def capture_worker(args, ring, stop, done, reports):
    """Camera I/O only: no image decode, motion work, SQLite, or GUI."""
    import av
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    source = container = None
    started = time.monotonic()
    try:
        source = PreviewSource(args.db, create=True)
        container = av.open(args.device, format='v4l2', options={
            'input_format': 'mjpeg', 'video_size': f'{args.width}x{args.height}',
            'framerate': str(args.fps)})
        stream = container.streams.video[0]
        if stream.codec_context.name != 'mjpeg':
            raise RuntimeError('Camera must supply MJPEG output')
        actual_rate=stream.average_rate
        reports.put(dict(width=stream.codec_context.width, height=stream.codec_context.height,
                         negotiated_fps=float(actual_rate) if actual_rate else None))
        from collections import deque
        from queue import Full
        frame_times=deque(maxlen=1024);next_metrics=0
        next_preview = 0
        guard=PacketGuard(time.monotonic())
        last_bad_log=0
        for packet in container.demux(stream):
            if stop.is_set() or not mp.parent_process().is_alive():
                break
            if not packet.size:
                continue
            now = time.monotonic()
            jpeg=bytes(packet)
            try:
                accepted=guard.accept(jpeg,now,getattr(packet,'is_corrupt',False))
            finally:
                ring.bad_packets.value=guard.bad_packets
            if not accepted:
                if now-last_bad_log>=1:
                    logging.warning('Discarded damaged camera JPEG: %d bytes; %d packets lost in this session',len(jpeg),guard.bad_packets)
                    last_bad_log=now
                continue
            frame_times.append(now)
            while len(frame_times)>1 and now-frame_times[0]>3:frame_times.popleft()
            if now>=next_metrics and len(frame_times)>1:
                span=frame_times[-1]-frame_times[0]
                metrics=dict(capture_fps=(len(frame_times)-1)/span if span>0 else 0,
                             capture_window_seconds=span,capture_metrics_ns=time.time_ns())
                try:reports.put_nowait(metrics)
                except Full:pass
                next_metrics=now+1
            frame = Frame(time.time_ns(), time.monotonic_ns(), packet.pts,
                          str(packet.time_base) if packet.time_base else None, jpeg, guard.bad_packets)
            if not ring.append(frame):
                raise RuntimeError('Camera JPEG exceeds configured compressed ring capacity')
            if now >= next_preview:
                source.write(frame)
                next_preview = now + 1 / 20
            if args.run_seconds and now - started >= args.run_seconds:
                break
        if not stop.is_set() and not args.run_seconds:
            raise RuntimeError('Camera stream ended unexpectedly')
    except Exception as exc:
        reports.put(dict(error=str(exc)))
    finally:
        if container:
            container.close()
        if source:
            source.close()
        done.set()


class PreparedHeader(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in
                ('produced', 'skipped', 'received_ns', 'monotonic_ns', 'prepared_ns',
                 'width', 'height', 'pid')] + [('decode_ms', ctypes.c_double)]


class PreparedImage:
    """Latest RGB image in shared memory; GUI reads never wait on a worker.

    No pipe feeder, serialization backlog, or blocking recv of a partial image.
    A failed worker holding the lock causes skipped reads, not a frozen Tk loop.
    """
    def __init__(self):
        ctx = context()
        self.data = ctx.RawArray(ctypes.c_ubyte, 1920*1080*3)
        self.header = ctx.RawValue(PreparedHeader)
        self.lock = ctx.Lock()
        self.previous = 0

    def write(self, payload):
        if not self.lock.acquire(block=False):
            return False
        try:
            rgb = payload['rgb']
            if len(rgb) > len(self.data):
                return False
            memoryview(self.data).cast('B')[:len(rgb)] = rgb
            for name, _ in PreparedHeader._fields_:
                setattr(self.header, name, payload.get(name, 0))
            self.header.width, self.header.height = payload['size']
            return True
        finally:
            self.lock.release()

    def read(self):
        if not self.lock.acquire(block=False):
            return None
        try:
            h = self.header
            if not h.produced or h.produced == self.previous:
                return None
            result = {name:getattr(h, name) for name, _ in PreparedHeader._fields_}
            result['size'] = (h.width, h.height)
            result['rgb'] = bytes(memoryview(self.data).cast('B')[:h.width*h.height*3])
            self.previous = h.produced
            return result
        finally:
            self.lock.release()


def preview_worker(db, size, output, stop):
    import io
    from PIL import Image
    from . import storage
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    source = connection = None
    previous, previous_size = 0, None
    produced = skipped = 0
    try:
        next_tick = time.monotonic()
        while not stop.wait(max(0, next_tick-time.monotonic())):
            if not mp.parent_process().is_alive():
                break
            next_tick = max(next_tick + 1 / 20, time.monotonic())
            try:
                path = preview_path(db)
                if source and path.stat().st_ino != source.inode:
                    source.close(); source = None; previous = 0
                if source is None and path.exists():
                    source = PreviewSource(db)
                if not size.get_lock().acquire(timeout=.05):
                    continue
                try:
                    target = tuple(size.get_obj()[:])
                finally:
                    size.get_lock().release()
                changed_size = target != previous_size
                item = source.read(0 if changed_size else previous) if source else None
                if source is None:
                    if connection is None:
                        connection = storage.connect(db, readonly=True)
                    status = storage.read_runtime(connection)
                    stamp = status.get('last_frame_ns', 0)
                    if status.get('preview') and (stamp != previous or changed_size):
                        item = (stamp, 0, status['preview'])
                if item is None:
                    continue
                received, monotonic, jpeg = item
                started = time.perf_counter()
                with Image.open(io.BytesIO(jpeg)) as image:
                    image.draft('RGB', target)
                    image.thumbnail(target)
                    rgb = image.convert('RGB')
                produced += 1
                raw = rgb.tobytes()
                payload = dict(received_ns=received, monotonic_ns=monotonic,
                               prepared_ns=time.monotonic_ns(), size=rgb.size, rgb=raw,
                               decode_ms=(time.perf_counter() - started) * 1000,
                               produced=produced, skipped=skipped, pid=os.getpid())
                if not output.write(payload):
                    skipped += 1
                previous, previous_size = received, target
            except (OSError, ValueError, storage.sqlite3.Error):
                if source:
                    source.close(); source = None
                stop.wait(.2)
    finally:
        if source:
            source.close()
        if connection:
            connection.close()


class LivePreview:
    def __init__(self, db, width=1100, height=650):
        ctx = context()
        self.size = ctx.Array('i', [width, height])
        self.output = PreparedImage()
        self.stop = ProcessFlag()
        self.process = ctx.Process(target=preview_worker, args=(str(db), self.size, self.output, self.stop),
                                   name='racevideo-preview', daemon=True)
        self.process.start()

    def resize(self, width, height):
        # Cap display transfers even on a very large desktop; originals stay 4K.
        scale = min(1, 1920 / max(1, width), 1080 / max(1, height))
        if self.size.get_lock().acquire(block=False):
            try:
                self.size.get_obj()[:] = [max(1, int(width * scale)), max(1, int(height * scale))]
            finally:
                self.size.get_lock().release()

    def latest(self):
        return self.output.read()

    def close(self):
        self.stop.set()
        self.process.join(1)
        if self.process.is_alive():
            self.process.terminate(); self.process.join(1)
