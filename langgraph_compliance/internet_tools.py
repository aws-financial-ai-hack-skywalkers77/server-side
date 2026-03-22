from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from config import Config

logger = logging.getLogger(__name__)


def _allowlist_domains() -> list[str]:
    raw = (Config.LANGGRAPH_WEB_ALLOWLIST or "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    if not allowlist:
        return True
    for entry in allowlist:
        if h == entry or h.endswith("." + entry):
            return True
    return False


def _is_private_or_reserved_host(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(hostname)
        return bool(
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        )
    except ValueError:
        return False


def validate_public_https_url(url: str) -> tuple[bool, str]:
    if not url or not isinstance(url, str):
        return False, "empty_url"
    u = url.strip()
    try:
        parsed = urlparse(u)
    except Exception:
        return False, "parse_error"
    if parsed.scheme.lower() != "https":
        return False, "https_only"
    host = parsed.hostname
    if not host:
        return False, "missing_host"
    if _is_private_or_reserved_host(host):
        return False, "blocked_host"
    try:
        if ipaddress.ip_address(host).version:
            return False, "ip_literal_blocked"
    except ValueError:
        pass
    allowlist = _allowlist_domains()
    if allowlist and not _host_allowed(host, allowlist):
        return False, "not_on_allowlist"
    return True, "ok"


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str, max_len: int) -> str:
    t = _HTML_TAG_RE.sub(" ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


def internet_search(query: str, max_results: int | None = None) -> dict[str, Any]:
    """
    DuckDuckGo text search (no API key). Returns titles, hrefs, snippets.
    Disabled automatically when LANGGRAPH_WEB_ENABLED is false (caller should gate).
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty_query", "results": []}
    lim = max_results if max_results is not None else Config.LANGGRAPH_MAX_SEARCH_HITS
    lim = max(1, min(lim, 15))
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo_search not installed; internet_search unavailable")
        return {"ok": False, "error": "ddgs_not_installed", "results": []}

    results: list[dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=lim):
                href = (r.get("href") or r.get("url") or "").strip()
                ok, reason = validate_public_https_url(href)
                if not ok:
                    continue
                results.append(
                    {
                        "title": (r.get("title") or "")[:300],
                        "url": href,
                        "snippet": (r.get("body") or "")[:800],
                    }
                )
    except Exception as exc:
        logger.exception("internet_search failed: %s", exc)
        return {"ok": False, "error": str(exc), "results": []}

    return {"ok": True, "query": q, "results": results}


def fetch_url_text(url: str, max_bytes: int | None = None) -> dict[str, Any]:
    """HTTPS GET with size cap; returns text/plain or stripped HTML snippet."""
    ok, reason = validate_public_https_url(url)
    if not ok:
        return {"ok": False, "error": reason, "url": url, "text": ""}
    cap = max_bytes if max_bytes is not None else Config.LANGGRAPH_FETCH_MAX_BYTES
    headers = {"User-Agent": Config.LANGGRAPH_USER_AGENT}
    ctype = ""
    try:
        with httpx.Client(
            timeout=Config.LANGGRAPH_HTTP_TIMEOUT_SEC,
            follow_redirects=True,
            headers=headers,
        ) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return {
                        "ok": False,
                        "error": f"http_{resp.status_code}",
                        "url": url,
                        "text": "",
                    }
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    chunks.append(chunk)
                    if total >= cap:
                        break
                raw = b"".join(chunks)[:cap]
    except Exception as exc:
        logger.exception("fetch_url_text failed: %s", exc)
        return {"ok": False, "error": str(exc), "url": url, "text": ""}
    text = raw.decode("utf-8", errors="replace")
    if "html" in ctype or text.lstrip().lower().startswith("<!doctype html"):
        text = _strip_html(text, 12000)
    else:
        text = text[:12000]
    return {"ok": True, "url": url, "content_type": ctype, "text": text}


def build_langchain_tools() -> list:
    """Tools an LLM (or human operator) can call — gated by workflow `enable_web`."""

    @tool
    def search_public_web(query: str) -> str:
        """Search the public web for factual context (HTTPS results only). Use vendor + product + 'pricing' sparingly."""
        payload = internet_search(query)
        if not payload.get("ok"):
            return f"search_failed: {payload.get('error')}"
        lines = []
        for i, r in enumerate(payload.get("results") or [], 1):
            lines.append(f"{i}. {r.get('title')}\n   {r.get('url')}\n   {r.get('snippet')}")
        return "\n\n".join(lines) if lines else "no_results"

    @tool
    def fetch_public_url(url: str) -> str:
        """Fetch a public HTTPS URL and return a short text excerpt (allowlist may apply)."""
        payload = fetch_url_text(url)
        if not payload.get("ok"):
            return f"fetch_failed: {payload.get('error')}"
        return payload.get("text") or ""

    return [search_public_web, fetch_public_url]
