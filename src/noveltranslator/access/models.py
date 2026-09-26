from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class AccessStatus(StrEnum):
    OK = "OK"
    REDIRECTED = "REDIRECTED"
    RATE_LIMITED = "RATE_LIMITED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    SERVER_ERROR = "SERVER_ERROR"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    JAVASCRIPT_REQUIRED = "JAVASCRIPT_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TimeoutConfig:
    connect_seconds: float = 10.0
    read_seconds: float = 30.0
    write_seconds: float = 30.0
    pool_seconds: float = 10.0


@dataclass(frozen=True)
class AccessConfig:
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    headers: dict[str, str] = field(default_factory=lambda: {
        "User-Agent": "NovelTranslator/0.1",
        "Accept": "text/html,application/xhtml+xml,text/plain",
        "Accept-Language": "en-US,en;q=0.9",
    })
    follow_redirects: bool = True
    max_response_size_mb: float = 10.0
    min_delay_seconds: float = 0.0
    max_delay_seconds: float = 0.0
    requests_per_minute: int = 0

    @classmethod
    def from_mapping(cls, values: Mapping) -> "AccessConfig":
        timeout = values.get("timeout", {})
        delay = values.get("delay", {})
        defaults = cls()
        return cls(
            timeout=TimeoutConfig(**{key: float(timeout.get(key, getattr(defaults.timeout, key))) for key in ("connect_seconds", "read_seconds", "write_seconds", "pool_seconds")}),
            headers={**defaults.headers, **values.get("headers", {})},
            follow_redirects=bool(values.get("follow_redirects", defaults.follow_redirects)),
            max_response_size_mb=float(values.get("max_response_size_mb", defaults.max_response_size_mb)),
            min_delay_seconds=float(delay.get("min_seconds", defaults.min_delay_seconds)),
            max_delay_seconds=float(delay.get("max_seconds", defaults.max_delay_seconds)),
            requests_per_minute=int(values.get("requests_per_minute", defaults.requests_per_minute)),
        )


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    base_delay_seconds: float = 30.0
    max_delay_seconds: float = 300.0
    backoff_factor: float = 2.0
    max_retry_after_seconds: float = 300.0

    @classmethod
    def from_mapping(cls, values: Mapping) -> "RetryConfig":
        config = cls(**{key: values[key] for key in values if key in cls.__dataclass_fields__})
        if config.max_attempts < 1:
            raise ValueError("retry.max_attempts must be positive")
        return config


@dataclass(frozen=True)
class AccessResponse:
    url: str
    final_url: str
    status_code: int | None
    headers: dict[str, str]
    text: str
    elapsed: float
    access_status: AccessStatus
    attempts: int
    size_bytes: int = 0
    error: str | None = None

    @property
    def content_type(self) -> str | None:
        return self.headers.get("content-type") or self.headers.get("Content-Type")


@dataclass
class AccessStats:
    requests_total: int = 0
    requests_successful: int = 0
    requests_failed: int = 0
    retries_total: int = 0
    rate_limits_encountered: int = 0
    bytes_downloaded: int = 0
