import httpx
import pytest

from noveltranslator.access.detection import classify_response
from noveltranslator.access.http_client import HttpClient
from noveltranslator.access.models import AccessConfig, AccessStatus, RetryConfig
from noveltranslator.access.rate_limiter import RateLimiter
from noveltranslator.access.retry import RetryPolicy


def client_for(handler, sleeps=None, *, max_attempts=3, access=None):
    sleeps = sleeps if sleeps is not None else []
    return HttpClient(
        access or AccessConfig(),
        RetryConfig(max_attempts=max_attempts, base_delay_seconds=30, max_delay_seconds=300),
        transport=httpx.MockTransport(handler),
        sleep_func=sleeps.append,
    )


def test_http_200_and_metadata():
    def handler(request):
        return httpx.Response(200, request=request, text="áéñ 한글 日本語", headers={"content-type": "text/html; charset=utf-8"})

    client = client_for(handler)
    response = client.get("https://example.test/page")
    client.close()
    assert response.access_status is AccessStatus.OK
    assert response.text == "áéñ 한글 日本語"
    assert response.content_type == "text/html; charset=utf-8"
    assert response.attempts == 1
    assert client.stats.requests_successful == 1


@pytest.mark.parametrize(("status", "classification"), [(403, AccessStatus.FORBIDDEN), (404, AccessStatus.NOT_FOUND), (500, AccessStatus.SERVER_ERROR), (502, AccessStatus.SERVER_ERROR), (503, AccessStatus.SERVER_ERROR), (504, AccessStatus.SERVER_ERROR)])
def test_status_classification_and_non_retryable_errors(status, classification):
    client = client_for(lambda request: httpx.Response(status, request=request), max_attempts=3)
    response = client.get("https://example.test/page")
    client.close()
    assert response.access_status is classification
    assert response.attempts == (3 if status in {502, 503, 504} else 1)


def test_429_retry_after_is_respected_without_real_sleep():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, request=request, headers={"Retry-After": "30"}) if len(calls) == 1 else httpx.Response(200, request=request, text="ok")

    sleeps = []
    client = client_for(handler, sleeps)
    response = client.get("https://example.test/page")
    client.close()
    assert response.access_status is AccessStatus.OK
    assert response.attempts == 2
    assert sleeps == [30.0]
    assert client.stats.rate_limits_encountered == 1


def test_retry_recovery_and_exhaustion():
    recovery_calls = []

    def recovery(request):
        recovery_calls.append(1)
        return httpx.Response(503 if len(recovery_calls) < 3 else 200, request=request, text="ok")

    sleeps = []
    client = client_for(recovery, sleeps)
    response = client.get("https://example.test/recovery")
    client.close()
    assert response.access_status is AccessStatus.OK
    assert response.attempts == 3
    assert sleeps == [30.0, 60.0]

    client = client_for(lambda request: httpx.Response(503, request=request), max_attempts=3)
    response = client.get("https://example.test/fail")
    client.close()
    assert response.access_status is AccessStatus.SERVER_ERROR
    assert response.attempts == 3


def test_timeout_and_connection_error_are_controlled_and_limited():
    timeout_calls = []

    def timeout(request):
        timeout_calls.append(1)
        raise httpx.ReadTimeout("timed out", request=request)

    client = client_for(timeout, max_attempts=2)
    response = client.get("https://example.test/timeout")
    client.close()
    assert response.access_status is AccessStatus.TIMEOUT
    assert response.attempts == 2

    client = client_for(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request)), max_attempts=2)
    response = client.get("https://example.test/offline")
    client.close()
    assert response.access_status is AccessStatus.NETWORK_ERROR
    assert response.attempts == 2


def test_detection_heuristics():
    assert classify_response(200, "Verify you are human") is AccessStatus.CAPTCHA_REQUIRED
    assert classify_response(200, "Please enable JavaScript to continue") is AccessStatus.JAVASCRIPT_REQUIRED
    assert classify_response(200, "Sign in to continue") is AccessStatus.LOGIN_REQUIRED


def test_redirects_are_preserved():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(302, request=request, headers={"location": "https://example.test/new"})
        return httpx.Response(200, request=request, text="new")

    client = client_for(handler)
    response = client.get("https://example.test/old")
    client.close()
    assert response.final_url == "https://example.test/new"
    assert response.access_status is AccessStatus.REDIRECTED


@pytest.mark.parametrize("url", ["file:///tmp/a", "ftp://example.test/a", "javascript:alert(1)", "not-a-url"])
def test_invalid_schemes_are_rejected_before_request(url):
    client = client_for(lambda request: pytest.fail("network must not be called"))
    with pytest.raises(ValueError):
        client.get(url)
    client.close()


def test_rate_limiter_uses_injected_clock_and_sleeper():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2, 2, 2, sleep_func=sleep, time_func=lambda: now[0], random_func=lambda minimum, maximum: minimum)
    assert limiter.wait() == 0
    assert limiter.wait() == 2
    assert limiter.wait() == 58
    assert sleeps == [2, 58]


def test_retry_policy_caps_retry_after_and_supports_backoff():
    policy = RetryPolicy(RetryConfig(max_attempts=3, base_delay_seconds=5, max_delay_seconds=20, backoff_factor=2, max_retry_after_seconds=10))
    assert policy.retry_delay(1) == 5
    assert policy.retry_delay(3) == 20
    assert policy.retry_delay(1, {"Retry-After": "100"}) == 10


def test_response_size_limit():
    config = AccessConfig(max_response_size_mb=0.000001)
    client = client_for(lambda request: httpx.Response(200, request=request, content=b"too large"), access=config)
    response = client.get("https://example.test/large")
    client.close()
    assert response.access_status is AccessStatus.INVALID_RESPONSE
