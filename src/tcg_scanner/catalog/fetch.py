from __future__ import annotations

import threading
import time

import httpx


class Fetcher:
    """Polite HTTP client for the card database."""

    BASE_URL = "https://onepiece.limitlesstcg.com"

    def __init__(self, client: httpx.Client | None = None, delay: float = 0.2) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": "tcg-scanner/0.1 (personal card scanner)"},
            timeout=30.0,
            follow_redirects=True,
        )
        self._delay = delay
        self._last = 0.0
        self._lock = threading.Lock()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str) -> httpx.Response:
        # The lock spaces request starts even when downloads run in a pool.
        with self._lock:
            wait = self._delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        response = self._client.get(url)
        response.raise_for_status()
        return response

    def text(self, path: str) -> str:
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        return self._get(url).text

    def content(self, url: str) -> bytes:
        return self._get(url).content
