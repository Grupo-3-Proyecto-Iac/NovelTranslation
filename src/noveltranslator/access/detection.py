from .models import AccessResponse, AccessStatus


CAPTCHA_MARKERS = ("captcha", "verify you are human", "human verification", "cf-chl", "challenge")
LOGIN_MARKERS = ("login required", "sign in to continue", "authentication required")
JAVASCRIPT_MARKERS = ("enable javascript", "javascript required", "please enable javascript")


def classify_response(status_code: int | None, text: str = "", *, redirected: bool = False) -> AccessStatus:
    if status_code is None:
        return AccessStatus.UNKNOWN
    if status_code == 429:
        return AccessStatus.RATE_LIMITED
    if status_code == 403:
        return AccessStatus.FORBIDDEN
    if status_code == 404:
        return AccessStatus.NOT_FOUND
    if 500 <= status_code <= 599:
        return AccessStatus.SERVER_ERROR
    if redirected:
        return AccessStatus.REDIRECTED
    lowered = text.lower()
    if any(marker in lowered for marker in CAPTCHA_MARKERS):
        return AccessStatus.CAPTCHA_REQUIRED
    if any(marker in lowered for marker in LOGIN_MARKERS):
        return AccessStatus.LOGIN_REQUIRED
    if any(marker in lowered for marker in JAVASCRIPT_MARKERS):
        return AccessStatus.JAVASCRIPT_REQUIRED
    if 200 <= status_code <= 299:
        return AccessStatus.OK
    return AccessStatus.UNKNOWN


def response_status(response: AccessResponse) -> AccessStatus:
    return classify_response(response.status_code, response.text, redirected=response.url != response.final_url)
