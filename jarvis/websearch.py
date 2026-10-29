"""Web search answering: search -> fetch top pages in parallel -> extract main text -> best matching snippet
(Jarvis Lite: no AI summary; the answer is the most relevant sentence(s) plus links).

Search backends: duckduckgo (ddgs library, no API key) or a SearXNG instance (JSON API).
Results are cached for a few minutes. No internet -> graceful message.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Source:
    title: str
    url: str
    snippet: str = ""
    text: str = ""


@dataclass
class WebAnswer:
    answer: str
    sources: list[Source] = field(default_factory=list)
    ok: bool = True



class WebSearch:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.backend = self.cfg.get("backend", "duckduckgo")     # duckduckgo | searxng
        self.searxng_url = str(self.cfg.get("searxng_url", "")).rstrip("/")
        self.region = self.cfg.get("region", "ru-ru")
        self.max_results = int(self.cfg.get("max_results", 5))
        self.fetch_pages = int(self.cfg.get("fetch_pages", 2))
        self.timeout = float(self.cfg.get("timeout_s", 8))
        self.cache_ttl = float(self.cfg.get("cache_minutes", 15)) * 60
        self._cache: dict[str, tuple[float, WebAnswer]] = {}

    # ------------------------------------------------------------ search
    def search(self, query: str) -> list[Source]:
        if self.backend == "searxng" and self.searxng_url:
            import httpx
            r = httpx.get(f"{self.searxng_url}/search", params={"q": query, "format": "json", "language": "ru"},
                          timeout=self.timeout)
            r.raise_for_status()
            return [Source(x.get("title", ""), x.get("url", ""), x.get("content", ""))
                    for x in r.json().get("results", [])[: self.max_results]]
        try:
            from ddgs import DDGS
        except ImportError:  # older package name
            from duckduckgo_search import DDGS  # type: ignore[no-redef]
        res = DDGS().text(query, region=self.region, max_results=self.max_results) or []
        return [Source(x.get("title", ""), x.get("href") or x.get("url", ""), x.get("body", "")) for x in res]

    def _fetch(self, src: Source) -> Source:
        try:
            import httpx
            r = httpx.get(src.url, timeout=self.timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
                                   "Accept-Language": "ru,en;q=0.8"})
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
                return src
            html = r.text
            text = ""
            try:
                import trafilatura
                text = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True) or ""
            except Exception as e:
                log.debug("trafilatura: %s", e)
            if not text:   # crude fallback
                text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
                text = re.sub(r"<[^>]+>", " ", text)
            src.text = re.sub(r"\s+", " ", text).strip()[:4000]
        except Exception as e:
            log.debug("fetch %s: %s", src.url, e)
        return src

    def gather(self, query: str) -> list[Source]:
        """Search results; pages are downloaded only when no snippet is good enough (Lite: less traffic/CPU)."""
        sources = [s for s in self.search(query) if s.url.startswith("http")]
        if sources and not any(_good(s.snippet) for s in sources) and self.fetch_pages > 0:
            top = sources[: self.fetch_pages]
            with cf.ThreadPoolExecutor(max_workers=max(1, len(top))) as ex:
                list(ex.map(self._fetch, top, timeout=self.timeout * 2))
        return sources

    # ------------------------------------------------------------ answer
    def answer(self, question: str, context: str = "") -> WebAnswer:
        key = (context + "|" + question).strip().lower()
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.cache_ttl:
            return hit[1]
        try:
            sources = self.gather(question if not context else f"{context} {question}")
        except Exception as e:
            log.warning("Веб-поиск: %s", e)
            return WebAnswer("Не могу выйти в интернет, поиск сейчас недоступен.", [], ok=False)
        if not sources:
            return WebAnswer("Ничего толкового не нашёл.", [], ok=False)
        text = short_answer(sources)
        ans = WebAnswer(text, sources)
        self._cache[key] = (time.time(), ans)
        return ans


def _good(text: str) -> bool:
    return len(re.sub(r"\s+", " ", (text or "").strip())) >= 40


def short_answer(sources: list, limit: int = 320) -> str:
    """Jarvis Lite (no AI): the most useful snippet (or, failing that, the start of a downloaded page),
    cut to two sentences, said aloud; the links go to the chat."""
    for attr in ("snippet", "text"):
        for src in sources:
            body = re.sub(r"\s+", " ", (getattr(src, attr, "") or "").strip())
            if len(body) >= 40:
                parts = re.split(r"(?<=[.!?])\s+", body)
                out = " ".join(parts[:2])
                return out[:limit].rstrip(" ,;") + ("…" if len(out) > limit else "")
    first = sources[0]
    return (first.snippet or first.title or "Нашёл ссылки, показал их в окне.").strip()
