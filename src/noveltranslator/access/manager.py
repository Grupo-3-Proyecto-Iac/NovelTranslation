from .http_client import HttpClient
from .models import AccessResponse


class AccessManager:
    """Facade used by sources; source code never talks to HTTPX directly."""

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def fetch(self, url: str) -> AccessResponse:
        return self.client.get(url)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "AccessManager":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

