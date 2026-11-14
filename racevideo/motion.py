"""Reduced-resolution motion analysis and timestamp-based event assembly."""
from __future__ import annotations

from dataclasses import dataclass
import io
import uuid

from PIL import Image, ImageChops, ImageFilter

from .storage import Frame


DEFAULT_ROI = (0.425, 0.15, 0.575, 0.85)


def validate_roi(value):
    """Normalized image coordinates, independent of display letterboxing."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("ROI needs four coordinates")
    x0, y0, x1, y1 = map(float, value)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("ROI must lie inside the image")
    if x1 - x0 < 0.02 - 1e-9 or y1 - y0 < 0.02 - 1e-9:
        raise ValueError("ROI must be at least 2% wide and high")
    return (x0, y0, x1, y1)


class MotionDetector:
    def __init__(self, roi=DEFAULT_ROI, delta=18, fraction=0.025):
        self.roi = validate_roi(roi)
        self.delta = delta
        self.fraction = fraction
        self.previous = None

    def reset(self, roi):
        self.roi = validate_roi(roi)
        self.previous = None  # Moving the ROI itself must not trigger a clip.

    def analyze(self, jpeg: bytes):
        with Image.open(io.BytesIO(jpeg)) as image:
            # Ask libjpeg for reduced grayscale decoding before allocating pixels.
            image.draft("L", (320, 180))
            image.thumbnail((320, 180))
            gray = image.convert("L").filter(ImageFilter.GaussianBlur(0.8))
        w, h = gray.size
        x0, y0, x1, y1 = self.roi
        crop = gray.crop((int(x0 * w), int(y0 * h),
                          max(int(x0 * w) + 1, int(x1 * w)),
                          max(int(y0 * h) + 1, int(y1 * h))))
        previous, self.previous = self.previous, crop
        if previous is None or previous.size != crop.size:
            return False, 0.0
        histogram = ImageChops.difference(previous, crop).histogram()
        score = sum(histogram[self.delta:]) / (crop.width * crop.height)
        return score >= self.fraction, score


@dataclass
class EventClip:
    frames: list[Frame]
    trigger_ns: int
    metadata: dict


class MotionEvents:
    """Keep full-rate compressed frames; only detection is sampled.

    A 0.2s quiet gap holds the motion indication red. Post-roll is a separate
    2s deadline. Renewed motion during post-roll extends the same event.
    Long events split into linked chunks with no dropped intervening frames.
    """
    def __init__(self, pre=0.5, post=2.0, gap=0.2, max_bytes=128 * 1024**2,
                 max_seconds=30,quiet_close=0):
        self.pre_ns, self.post_ns, self.gap_ns = (int(s * 1e9) for s in (pre, post, gap))
        self.max_bytes, self.max_ns = max_bytes, int(max_seconds * 1e9)
        self.quiet_close_ns=min(self.post_ns,int(quiet_close*1e9)) if quiet_close>0 else self.post_ns
        self.frames = []
        self.bytes = 0
        self.event_id = None
        self.last_motion_ns = None
        self.trigger_ns = None
        self.first_motion_ns = None
        self.chunk = 0
        self.context = {}

    @property
    def active(self):
        return self.event_id is not None

    def moving(self, now_ns):
        return (self.last_motion_ns is not None and
                now_ns - self.last_motion_ns < self.gap_ns)

    def _flush(self, reason, close=True):
        result = None
        if self.frames:
            metadata = dict(self.context, event_id=self.event_id, chunk=self.chunk,
                            first_motion_monotonic_ns=self.first_motion_ns,
                            last_motion_monotonic_ns=self.last_motion_ns,
                            pre_roll_seconds=self.pre_ns / 1e9,
                            post_roll_seconds=self.post_ns / 1e9,
                            effective_quiet_close_seconds=self.quiet_close_ns/1e9,
                            gap_seconds=self.gap_ns / 1e9, end_reason=reason)
            result = EventClip(self.frames, self.trigger_ns, metadata)
            self.frames, self.bytes = [], 0
            self.chunk += 1
        if close:
            self.event_id = None
        return result

    def flush(self, reason="stop"):
        """A deliberate stop/ROI change retains the partial event, with a reason."""
        return self._flush(reason)

    def update(self, frame, detected, recent):
        completed = []
        # A new detection after the previous tail expired begins a new event.
        if (self.active and detected and
                frame.monotonic_ns - self.last_motion_ns >= self.quiet_close_ns):
            clip = self._flush("quiet")
            if clip:
                completed.append(clip)
        if detected:
            self.last_motion_ns = frame.monotonic_ns
            if not self.active:
                self.event_id, self.chunk = uuid.uuid4().hex, 0
                self.trigger_ns = frame.received_ns
                self.first_motion_ns = frame.monotonic_ns
                cutoff = frame.monotonic_ns - self.pre_ns
                history = list(recent)
                start = 0
                # Include the frame immediately before the cutoff for >=0.5s
                # context where available, to within one actual frame interval.
                while start + 1 < len(history) and history[start + 1].monotonic_ns <= cutoff:
                    start += 1
                self.frames = history[start:]
                self.bytes = sum(len(f.jpeg) for f in self.frames)
        if self.active:
            if not self.frames or self.frames[-1].monotonic_ns != frame.monotonic_ns:
                self.frames.append(frame)
                self.bytes += len(frame.jpeg)
            quiet = frame.monotonic_ns - self.last_motion_ns >= self.quiet_close_ns
            limited = (self.bytes >= self.max_bytes or
                       frame.monotonic_ns - self.frames[0].monotonic_ns >= self.max_ns)
            if quiet or limited:
                clip = self._flush("quiet" if quiet else "limit", close=quiet)
                if clip:
                    completed.append(clip)
        return completed
