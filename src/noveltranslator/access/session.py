from .http_client import HttpClient


class AccessSession:
    """Context-managed HTTP session wrapper; cookies are process-local only."""

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def __enter__(self) -> HttpClient:
        return self.client

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.client.close()

