class BrowserClient:
    """Reserved browser boundary; Playwright is intentionally not a dependency yet."""

    def fetch(self, url: str):
        raise NotImplementedError("Browser access is planned for a later sprint")

