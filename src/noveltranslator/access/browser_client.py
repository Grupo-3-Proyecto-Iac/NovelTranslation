from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from .detection import classify_response
from .models import AccessResponse, AccessStatus


class BrowserClient:
    """Optional browser access where the user completes challenges manually."""

    def __init__(self, *, profile_directory: Path, headless: bool = False, timeout_ms: int = 45_000) -> None:
        if headless:
            raise ValueError("assisted browser mode requires a visible browser")
        self.profile_directory = Path(profile_directory)
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._context = None
        self._page = None

    def fetch(self, url: str) -> AccessResponse:
        self._validate_url(url)
        page = self._get_page()
        started = time.monotonic()
        response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self._wait_for_settle(page)
        result = self._response(url, response, page, started)
        if result.access_status in {
            AccessStatus.CAPTCHA_REQUIRED,
            AccessStatus.FORBIDDEN,
            AccessStatus.RATE_LIMITED,
            AccessStatus.LOGIN_REQUIRED,
            AccessStatus.JAVASCRIPT_REQUIRED,
        }:
            print(
                "\nAcceso asistido: completa manualmente el CAPTCHA, inicio de sesión "
                "o verificación en el navegador y pulsa ENTER aquí para continuar."
            )
            input()
            response = page.reload(wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._wait_for_settle(page)
            result = self._response(url, response, page, started)
        return result

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._context = None
        self._page = None
        self._playwright = None

    def _get_page(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "El modo asistido requiere Playwright. Instala "
                "'noveltranslator[browser]' y ejecuta 'python -m playwright install chromium'."
            ) from exc
        self.profile_directory.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_directory), headless=False
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    @staticmethod
    def _wait_for_settle(page) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass

    @staticmethod
    def _response(url: str, response, page, started: float) -> AccessResponse:
        status_code = response.status if response is not None else None
        final_url = page.url or url
        text = page.content()
        headers = response.all_headers() if response is not None else {}
        status = classify_response(status_code, text, redirected=final_url != url)
        return AccessResponse(
            url=url, final_url=final_url, status_code=status_code, headers=headers,
            text=text, elapsed=time.monotonic() - started, access_status=status,
            attempts=1, size_bytes=len(text.encode("utf-8")),
        )

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only valid http:// and https:// URLs are supported")

