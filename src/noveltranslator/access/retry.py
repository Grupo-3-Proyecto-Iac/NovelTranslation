from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Mapping

import httpx

from .models import RetryConfig


RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


class RetryPolicy:
    def __init__(self, config: RetryConfig | None = None) -> None:
        self.config = config or RetryConfig()

    def should_retry_status(self, status_code: int) -> bool:
        return status_code in RETRYABLE_STATUS_CODES

    def should_retry_exception(self, error: Exception) -> bool:
        return isinstance(error, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))

    def retry_delay(self, attempt: int, headers: Mapping[str, str] | None = None, now: datetime | None = None) -> float:
        retry_after = self._retry_after(headers or {}, now)
        if retry_after is not None:
            return min(retry_after, self.config.max_retry_after_seconds, self.config.max_delay_seconds)
        exponential = self.config.base_delay_seconds * (self.config.backoff_factor ** max(0, attempt - 1))
        return min(exponential, self.config.max_delay_seconds)

    def _retry_after(self, headers: Mapping[str, str], now: datetime | None) -> float | None:
        value = headers.get("retry-after") or headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                current = now or datetime.now(timezone.utc)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return max(0.0, (target - current).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None
