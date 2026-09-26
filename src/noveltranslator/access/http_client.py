import logging
import time
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from .detection import classify_response
from .models import AccessConfig, AccessResponse, AccessStats, AccessStatus, RetryConfig
from .rate_limiter import RateLimiter
from .retry import RetryPolicy

logger = logging.getLogger("noveltranslator.access")


class HttpClient:
    """Synchronous, reusable HTTP boundary for future source adapters."""

    def __init__(self, access_config: AccessConfig | None = None, retry_config: RetryConfig | None = None, *, transport: httpx.BaseTransport | None = None, sleep_func: Callable[[float], None] = time.sleep, time_func: Callable[[], float] = time.monotonic, rate_limiter: RateLimiter | None = None) -> None:
        self.config = access_config or AccessConfig()
        self.retry_policy = RetryPolicy(retry_config or RetryConfig())
        self.rate_limiter = rate_limiter or RateLimiter(self.config.min_delay_seconds, self.config.max_delay_seconds, self.config.requests_per_minute, sleep_func=sleep_func, time_func=time_func)
        self.sleep_func = sleep_func
        self.time_func = time_func
        self.stats = AccessStats()
        timeout = httpx.Timeout(self.config.timeout.read_seconds, connect=self.config.timeout.connect_seconds, write=self.config.timeout.write_seconds, pool=self.config.timeout.pool_seconds)
        self._client = httpx.Client(headers=self.config.headers, timeout=timeout, follow_redirects=self.config.follow_redirects, transport=transport)

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> AccessResponse:
        self._validate_url(url)
        started = self.time_func()
        max_attempts = self.retry_policy.config.max_attempts
        for attempt in range(1, max_attempts + 1):
            self.rate_limiter.wait()
            self.stats.requests_total += 1
            logger.info("HTTP GET started: %s (attempt %d/%d)", url, attempt, max_attempts)
            try:
                response = self._client.get(url)
                elapsed = self.time_func() - started
                size = len(response.content)
                self.stats.bytes_downloaded += size
                if size > self.config.max_response_size_mb * 1024 * 1024:
                    self.stats.requests_failed += 1
                    return AccessResponse(url, str(response.url), response.status_code, dict(response.headers), "", elapsed, AccessStatus.INVALID_RESPONSE, attempt, size, "response exceeds configured size limit")
                status = classify_response(response.status_code, response.text, redirected=str(response.url) != url)
                if status == AccessStatus.RATE_LIMITED:
                    self.stats.rate_limits_encountered += 1
                if self.retry_policy.should_retry_status(response.status_code) and attempt < max_attempts:
                    self.stats.retries_total += 1
                    delay = self.retry_policy.retry_delay(attempt, response.headers)
                    logger.warning("HTTP retry after status %s in %.2f seconds: %s", response.status_code, delay, url)
                    self.sleep_func(delay)
                    continue
                if status in {AccessStatus.OK, AccessStatus.REDIRECTED}:
                    self.stats.requests_successful += 1
                else:
                    self.stats.requests_failed += 1
                logger.info("HTTP GET completed: %s (%s)", url, status.value)
                return AccessResponse(url, str(response.url), response.status_code, dict(response.headers), response.text, elapsed, status, attempt, size)
            except httpx.TimeoutException as exc:
                if attempt < max_attempts:
                    self.stats.retries_total += 1
                    delay = self.retry_policy.retry_delay(attempt)
                    logger.warning("HTTP timeout; retrying in %.2f seconds: %s", delay, url)
                    self.sleep_func(delay)
                    continue
                self.stats.requests_failed += 1
                logger.error("Request timed out: %s", url)
                return AccessResponse(url, url, None, {}, "", self.time_func() - started, AccessStatus.TIMEOUT, attempt, error=str(exc))
            except httpx.RequestError as exc:
                if attempt < max_attempts and self.retry_policy.should_retry_exception(exc):
                    self.stats.retries_total += 1
                    delay = self.retry_policy.retry_delay(attempt)
                    logger.warning("HTTP request error; retrying in %.2f seconds: %s", delay, url)
                    self.sleep_func(delay)
                    continue
                self.stats.requests_failed += 1
                logger.error("Request failed: %s", url)
                return AccessResponse(url, url, None, {}, "", self.time_func() - started, AccessStatus.NETWORK_ERROR, attempt, error=str(exc))
        raise RuntimeError("retry loop exhausted unexpectedly")

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only valid http:// and https:// URLs are supported")
