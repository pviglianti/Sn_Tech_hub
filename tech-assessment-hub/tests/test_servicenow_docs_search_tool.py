from unittest.mock import MagicMock, patch

import pytest

from src.mcp.registry import build_registry
from src.mcp.tools.core.servicenow_docs_search import (
    handle_fetch_web_document,
    handle_search_servicenow_docs,
)


def test_servicenow_docs_tools_registered():
    registry = build_registry()
    assert registry.has_tool("search_servicenow_docs")
    assert registry.has_tool("fetch_web_document")


@patch("src.mcp.tools.core.servicenow_docs_search.requests.get")
def test_search_servicenow_docs_parses_results(mock_get, db_session):
    mock_response = MagicMock()
    mock_response.text = """
    <html><body>
      <a class="result__a" href="https://docs.servicenow.com/bundle/xanadu-it-service-management/page/product/incident-management/concept/c_IncidentManagement.html">
        Incident Management overview
      </a>
      <a class="result__a" href="https://developer.servicenow.com/dev.do#!/guides">
        Developer guides
      </a>
    </body></html>
    """
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    payload = handle_search_servicenow_docs(
        {"query": "Incident Management"},
        db_session,
    )

    assert payload["query"] == "Incident Management"
    assert len(payload["results"]) == 2
    assert payload["results"][0]["title"] == "Incident Management overview"
    assert payload["results"][0]["url"].startswith("https://docs.servicenow.com/")


@patch("src.mcp.tools.core.servicenow_docs_search.requests.get")
def test_fetch_web_document_strips_markup(mock_get, db_session):
    mock_response = MagicMock()
    mock_response.text = """
    <html><body>
      <h1>Incident Management</h1>
      <p>Use Incident Management to restore service quickly.</p>
      <script>ignored()</script>
    </body></html>
    """
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    payload = handle_fetch_web_document(
        {"url": "https://docs.servicenow.com/bundle/xanadu-it-service-management/page/product/incident-management/concept/c_IncidentManagement.html"},
        db_session,
    )

    assert payload["url"].startswith("https://docs.servicenow.com/")
    assert "Incident Management" in payload["text"]
    assert "ignored" not in payload["text"]


def test_fetch_web_document_rejects_non_servicenow_urls(db_session):
    with pytest.raises(ValueError):
        handle_fetch_web_document({"url": "https://example.com/not-allowed"}, db_session)
