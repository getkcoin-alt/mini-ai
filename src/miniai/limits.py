"""Single-process pilot limits. Use a shared limiter before adding replicas."""

from collections import OrderedDict, deque
from threading import Lock
from time import monotonic


class WindowLimiter:
    def __init__(self, max_keys: int = 10000):
        self.events = OrderedDict()
        self.lock = Lock()
        self.max_keys = max_keys

    def allow(self, key: str, count: int, seconds: int) -> bool:
        now = monotonic()
        with self.lock:
            queue = self.events.setdefault(key, deque())
            self.events.move_to_end(key)
            while queue and queue[0] <= now - seconds:
                queue.popleft()
            if len(queue) >= count:
                return False
            queue.append(now)
            while len(self.events) > self.max_keys:
                self.events.popitem(last=False)
            return True

    def blocked(self, key: str, count: int, seconds: int) -> bool:
        now = monotonic()
        with self.lock:
            queue = self.events.get(key, deque())
            while queue and queue[0] <= now - seconds:
                queue.popleft()
            return len(queue) >= count
