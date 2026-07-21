"""URL fetching + evidence-grounding — the reusable core of verify_sources.py.

The `resolves` and `grounded` assertions need to read live pages. That's I/O,
so it is injected: assertions take a `Fetcher`, the default hits the network,
and tests pass a `DictFetcher` so the whole engine still runs offline with no
network and no API key.

Ported verbatim in spirit from signal-scout/scripts/verify_sources.py:
  - old.reddit.com rewrite (reddit serves a bot-verification stub to scripts)
  - BOT_WALLED domains that 403/429 real fetches (unverifiable, NOT dead)
  - page-length-invariant word-overlap grounding (a short true quote inside a
    huge page must still score high; a whole-string ratio would not)
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, Optional, Protocol
from urllib.parse import urlparse

BOT_WALLED_DOMAINS = ("reddit.com", "x.com", "twitter.com", "linkedin.com", "glassdoor.com", "indeed.com")
CHALLENGE_MARKERS = ("please wait for verification", "checking your browser")


@dataclass
class FetchResult:
    status: Optional[int]
    text: str
    bot_walled: bool = False


class Fetcher(Protocol):
    def fetch(self, url: str, timeout: int = 10) -> FetchResult: ...


def bot_walled_host(url: str) -> Optional[str]:
    host = urlparse(url).netloc.lower()
    for domain in BOT_WALLED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _canonicalize(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() in ("reddit.com", "www.reddit.com"):
        return parsed._replace(netloc="old.reddit.com").geturl()
    return url


def _is_challenge(status: Optional[int], text: str) -> bool:
    if status != 200 or len(text) > 200:
        return False
    lowered = text.lower()
    return any(m in lowered for m in CHALLENGE_MARKERS)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._chunks)).strip()


class UrllibFetcher:
    """Default network fetcher. Mirrors verify_sources.py behavior."""

    def fetch(self, url: str, timeout: int = 10) -> FetchResult:
        domain = bot_walled_host(url)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (litmus verifier)"})
        try:
            with urllib.request.urlopen(_canonicalize(url), timeout=timeout) as resp:  # type: ignore[arg-type]
                status = resp.status
                charset = resp.headers.get_content_charset() or "utf-8"
                raw = resp.read(2_000_000).decode(charset, errors="ignore")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) and domain:
                return FetchResult(exc.code, "", bot_walled=True)
            return FetchResult(exc.code, "")
        except Exception:
            return FetchResult(None, "")
        parser = _TextExtractor()
        parser.feed(raw)
        text = parser.text()
        if _is_challenge(status, raw) and domain:
            return FetchResult(status, "", bot_walled=True)
        return FetchResult(status, text)


class DictFetcher:
    """Offline fetcher for tests: maps url -> FetchResult (or plain text)."""

    def __init__(self, pages: Dict[str, object]):
        self._pages = pages

    def fetch(self, url: str, timeout: int = 10) -> FetchResult:
        val = self._pages.get(url)
        if val is None:
            return FetchResult(404, "")
        if isinstance(val, FetchResult):
            return val
        return FetchResult(200, str(val))


def grounding_ratio(evidence: str, page_text: str) -> float:
    """Fraction of the evidence's distinguishing words (4+ chars) that appear
    anywhere on the page. Page-length-invariant, unlike a whole-string ratio."""
    if not evidence or not page_text:
        return 0.0
    words = re.findall(r"[A-Za-z0-9']{4,}", evidence.lower())[:40]
    if not words:
        return 0.0
    page_words = set(re.findall(r"[A-Za-z0-9']{4,}", page_text.lower()))
    hits = sum(1 for w in words if w in page_words)
    return hits / len(words)
