"""Throttled, allowlisted HTTP client for SEC EDGAR.

Threat model (docs/threat-models/form4.md):
- SSRF / feed spoofing: the client refuses any host outside ALLOWED_HOSTS, HTTPS only.
  Belt and braces with the network-level egress allowlist in deployment.
- Availability abuse against us or by us: hard throttle well under SEC's fair-access
  ceiling, exponential backoff on 429/5xx, declared User-Agent required.
- Integrity: every response is checksummed (sha256) before storage; the raw layer
  stores the checksum so any later reprocessing can verify the payload.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

ALLOWED_HOSTS = {"www.sec.gov", "sec.gov"}
MIN_INTERVAL_SECONDS = 0.25  # ~4 req/s, comfortably under SEC's stated 10 req/s ceiling
MAX_RETRIES = 4


@dataclass(frozen=True)
class FetchResult:
    url: str
    content: bytes
    sha256: str


class EdgarClient:
    def __init__(self, user_agent: str, min_interval: float = MIN_INTERVAL_SECONDS):
        if "@" not in user_agent:
            raise ValueError("user_agent must include a contact address per SEC fair access policy")
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
            follow_redirects=False,
        )
        self._min_interval = min_interval
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _check_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"refusing non-https URL: {url}")
        if parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"refusing host outside EDGAR allowlist: {parsed.hostname}")

    def get(self, url: str) -> FetchResult:
        self._check_url(url)
        backoff = 1.0
        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            resp = self._client.get(url)
            if resp.status_code == 200:
                content = resp.content
                return FetchResult(url=url, content=content, sha256=hashlib.sha256(content).hexdigest())
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
        raise RuntimeError(f"unreachable retry state for {url}")

    def close(self) -> None:
        self._client.close()
