"""Small bounded latency distributions; no per-frame logging or disk writes."""
from collections import defaultdict, deque
import time


class Performance:
    def __init__(self, samples=300):
        self.values = defaultdict(lambda: deque(maxlen=samples))
        self.counters = defaultdict(int)
        self.started = time.monotonic()

    def observe(self, name, value):
        self.values[name].append(float(value))

    def snapshot(self):
        result = {'uptime_seconds': round(time.monotonic() - self.started, 1),
                  'counters': dict(self.counters)}
        for name, samples in self.values.items():
            values = sorted(samples)
            if values:
                result[name] = dict(last=round(samples[-1], 2), p50=round(values[len(values)//2], 2),
                                    p95=round(values[min(len(values)-1, int(len(values)*.95))], 2),
                                    max=round(values[-1], 2), samples=len(values))
        return result
