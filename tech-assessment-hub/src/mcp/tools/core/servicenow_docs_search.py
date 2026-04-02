"""MCP tools for lightweight ServiceNow web documentation lookup.

These tools are intentionally narrow and read-only. They help the AI confirm
target-application context from official/public ServiceNow web content when the
assessment metadata alone is not enough for a nuanced scope decision.
"""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse

import requests
from sqlmodel import Session

from ...registry import ToolSpec

_USER_AGENT = "tech-assessment-hub/1.0 (+https://localhost)"
_SEARCH_URL = "https://html.duckduckgo.com/html/"
_ALLOWED_HOST_TOKENS = (
    "servicenow.com",
    "docs.servicenow.com",
    "developer.servicenow.com",
    "community.servicenow.com",
)
_MAX_SEARCH_RESULTS = 5
_MAX_FETCH_CHARS = 12000

SEARCH_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "ServiceNow product/app question to search, e.g. 'Incident Management major incident'.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "Optional maximum number of search results to return.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

FETCH_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "Absolute ServiceNow web URL returned by search_servicenow_docs.",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


def _decode_duckduckgo_href(raw_href: str) -> str:
    parsed = urlparse(raw_href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target or "")
    return raw_href


def _is_allowed_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(token in host for token in _ALLOWED_HOST_TOKENS)


def _strip_html(raw_html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", raw_html)
    cleaned = re.sub(r"(?i)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</p>", "\n", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \\t\\r\\f\\v]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def handle_search_servicenow_docs(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    del session
    query = str(params.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")

    max_results = max(1, min(int(params.get("max_results") or _MAX_SEARCH_RESULTS), 10))
    search_query = f"site:servicenow.com {query}"
    response = requests.get(
        _SEARCH_URL,
        params={"q": search_query},
        timeout=15,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()

    matches: List[Dict[str, Any]] = []
    pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for raw_href, raw_title in pattern.findall(response.text):
        url = _decode_duckduckgo_href(html.unescape(raw_href))
        if not url or not _is_allowed_url(url):
            continue
        title = _strip_html(raw_title)
        if not title:
            continue
        matches.append({"title": title, "url": url})
        if len(matches) >= max_results:
            break

    return {
        "results": matches,
        "query": query,
        "search_scope": "ServiceNow web properties",
    }


def handle_fetch_web_document(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    del session
    url = str(params.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    if not _is_allowed_url(url):
        raise ValueError("Only ServiceNow web URLs are allowed.")

    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    text = _strip_html(response.text)
    return {
        "url": url,
        "text": text[:_MAX_FETCH_CHARS],
        "truncated": len(text) > _MAX_FETCH_CHARS,
    }


SEARCH_TOOL_SPEC = ToolSpec(
    name="search_servicenow_docs",
    description=(
        "Search official/public ServiceNow web content for product and target-application context. "
        "Use this sparingly to confirm what belongs to the assessed ServiceNow app scope."
    ),
    input_schema=SEARCH_INPUT_SCHEMA,
    handler=handle_search_servicenow_docs,
    permission="read",
)

FETCH_TOOL_SPEC = ToolSpec(
    name="fetch_web_document",
    description=(
        "Fetch and summarize text from a ServiceNow web URL previously returned by "
        "search_servicenow_docs."
    ),
    input_schema=FETCH_INPUT_SCHEMA,
    handler=handle_fetch_web_document,
    permission="read",
)
