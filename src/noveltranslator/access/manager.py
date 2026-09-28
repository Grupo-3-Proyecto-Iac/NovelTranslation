from .http_client import HttpClient
from .models import AccessResponse, AccessStatus


_BROWSER_FALLBACK_STATUSES = {
    AccessStatus.CAPTCHA_REQUIRED,
    AccessStatus.FORBIDDEN,
    AccessStatus.RATE_LIMITED,
    AccessStatus.LOGIN_REQUIRED,
    AccessStatus.JAVASCRIPT_REQUIRED,
}


class AccessManager:
    """Facade used by sources; source code never talks to HTTPX directly."""

    def __init__(self, client: HttpClient | None = None, browser_client=None) -> None:
        self.client = client or HttpClient()
        self.browser_client = browser_client

    def fetch(self, url: str) -> AccessResponse:
        response = self.client.get(url)
        if self.browser_client is not None and response.access_status in _BROWSER_FALLBACK_STATUSES:
            return self.browser_client.fetch(url)
        return response

    def close(self) -> None:
        self.client.close()
        if self.browser_client is not None:
            self.browser_client.close()

    def __enter__(self) -> "AccessManager":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

