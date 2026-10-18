from __future__ import annotations

import random
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import (
    CRAWL_DELAY_SECONDS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    SITE_ORIGIN,
    USER_AGENT,
    redact,
)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class PoliteClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        self._robots = RobotFileParser()
        self._robots_loaded = False
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _load_robots(self) -> None:
        if self._robots_loaded:
            return
        robots_url = urljoin(SITE_ORIGIN, "/robots.txt")
        try:
            response = self._request("GET", robots_url, respect_robots=False, polite_gap=False)
            self._robots.parse(response.text.splitlines())
        except Exception:
            self._robots.parse(["User-agent: *", "Allow: /"])
        self._robots_loaded = True

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.path.endswith("/hit"):
            return False
        site_host = urlparse(SITE_ORIGIN).netloc
        if parsed.netloc and parsed.netloc != site_host:
            return True
        self._load_robots()
        return self._robots.can_fetch(USER_AGENT, url)

    def _polite_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_for = CRAWL_DELAY_SECONDS - elapsed
        if wait_for > 0:
            time.sleep(wait_for)

    def _request(
        self,
        method: str,
        url: str,
        *,
        respect_robots: bool = True,
        polite_gap: bool = True,
        **kwargs,
    ) -> httpx.Response:
        if respect_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            if polite_gap:
                self._polite_wait()
            try:
                response = self._client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                if response.status_code in RETRY_STATUSES:
                    retry_after = response.headers.get("Retry-After")
                    sleep_s = delay
                    if retry_after:
                        try:
                            sleep_s = max(sleep_s, float(retry_after))
                        except ValueError:
                            pass
                    if attempt >= MAX_RETRIES:
                        response.raise_for_status()
                    time.sleep(sleep_s + random.uniform(0, 0.4))
                    delay *= 2
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                self._last_request_at = time.monotonic()
                if attempt >= MAX_RETRIES:
                    raise RuntimeError(redact(str(exc))) from exc
                time.sleep(delay + random.uniform(0, 0.4))
                delay *= 2
        assert last_error is not None
        raise last_error

    def get_text(self, url: str, polite_gap: bool = True) -> httpx.Response:
        return self._request("GET", url, polite_gap=polite_gap)

    def get_bytes(self, url: str, polite_gap: bool = True) -> httpx.Response:
        return self._request("GET", url, polite_gap=polite_gap)
