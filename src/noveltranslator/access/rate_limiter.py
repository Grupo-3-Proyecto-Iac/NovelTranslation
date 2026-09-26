import random
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Spaces requests with an optional delay and rolling requests/minute cap."""

    def __init__(self, min_delay_seconds: float = 0.0, max_delay_seconds: float = 0.0, requests_per_minute: int = 0, *, sleep_func: Callable[[float], None] = time.sleep, time_func: Callable[[], float] = time.monotonic, random_func: Callable[[float, float], float] = random.uniform) -> None:
        if min_delay_seconds < 0 or max_delay_seconds < min_delay_seconds:
            raise ValueError("delay range is invalid")
        if requests_per_minute < 0:
            raise ValueError("requests_per_minute cannot be negative")
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.requests_per_minute = requests_per_minute
        self.sleep_func = sleep_func
        self.time_func = time_func
        self.random_func = random_func
        self._request_times: deque[float] = deque()
        self._last_request: float | None = None

    def wait(self) -> float:
        now = self.time_func()
        while self._request_times and now - self._request_times[0] >= 60:
            self._request_times.popleft()
        delay = 0.0
        if self._last_request is not None:
            delay = max(delay, self.random_func(self.min_delay_seconds, self.max_delay_seconds))
        if self.requests_per_minute and len(self._request_times) >= self.requests_per_minute:
            delay = max(delay, 60 - (now - self._request_times[0]))
        if delay > 0:
            self.sleep_func(delay)
        timestamp = self.time_func()
        self._request_times.append(timestamp)
        self._last_request = timestamp
        return delay
