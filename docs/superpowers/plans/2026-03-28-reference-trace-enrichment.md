# Reference Trace Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `enrichment` pipeline stage that traces code references from scanned artifacts to discover related customizations on out-of-scope tables, queries ServiceNow to pull them, and inserts them as adjacent scan results.

**Architecture:** New pipeline stage between `scans` and `engines`. A lightweight reference parser extracts table names from code fields. An enrichment handler queries the SN instance for artifacts on discovered tables, creates an enrichment Scan, and inserts ScanResults with `is_adjacent=True`. Configurable via properties system with exclusion list and artifact cap.

**Tech Stack:** Python 3.9+, SQLModel, requests (via ServiceNowClient), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/models.py` | Modify | Add `enrichment` to PipelineStage and ScanType enums |
| `src/services/reference_parser.py` | Create | Lightweight regex extraction of table names from code strings |
| `src/services/enrichment_tracer.py` | Create | Orchestrates: parse refs → filter tables → query SN → create scan results |
| `src/mcp/tools/pipeline/run_enrichment.py` | Create | MCP tool handler + TOOL_SPEC for the enrichment stage |
| `src/services/integration_properties.py` | Modify | Add enrichment config properties |
| `src/server.py` | Modify | Add enrichment to pipeline stage order + stage handler dispatch |
| `tests/test_reference_parser.py` | Create | Unit tests for regex reference extraction |
| `tests/test_enrichment_tracer.py` | Create | Integration tests for enrichment orchestration |

---

### Task 1: Add Enum Values

**Files:**
- Modify: `tech-assessment-hub/src/models.py`

- [ ] **Step 1: Write test for new enum values**

Create `tech-assessment-hub/tests/test_enrichment_tracer.py`:

```python
"""Tests for the Reference Trace Enrichment feature.

Validates reference parsing, table discovery, SN querying, and
enrichment scan creation.
"""

import json

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    OriginType,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


class TestEnumValues:
    """PipelineStage and ScanType include enrichment."""

    def test_pipeline_stage_has_enrichment(self):
        assert hasattr(PipelineStage, "enrichment")
        assert PipelineStage.enrichment.value == "enrichment"

    def test_scan_type_has_enrichment(self):
        assert hasattr(ScanType, "enrichment")
        assert ScanType.enrichment.value == "enrichment"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_enrichment_tracer.py::TestEnumValues -v
```

Expected: FAIL with `AssertionError` (no `enrichment` attribute)

- [ ] **Step 3: Add enrichment to PipelineStage enum**

In `src/models.py`, add `enrichment` to the `PipelineStage` enum (after `scans`, before `engines` at ~line 39):

```python
class PipelineStage(str, Enum):
    """Assessment reasoning pipeline stages after scans complete."""
    scans = "scans"
    enrichment = "enrichment"
    engines = "engines"
    ai_analysis = "ai_analysis"
    observations = "observations"
    review = "review"
    grouping = "grouping"
    ai_refinement = "ai_refinement"
    recommendations = "recommendations"
    report = "report"
    complete = "complete"
```

- [ ] **Step 4: Add enrichment to ScanType enum**

In `src/models.py`, add to the `ScanType` enum (after `code_search` at ~line 90):

```python
    enrichment = "enrichment"
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_enrichment_tracer.py::TestEnumValues -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tech-assessment-hub/src/models.py tech-assessment-hub/tests/test_enrichment_tracer.py
git commit -m "feat: add enrichment to PipelineStage and ScanType enums"
```

---

### Task 2: Build Reference Parser Service

**Files:**
- Create: `tech-assessment-hub/src/services/reference_parser.py`
- Create: `tech-assessment-hub/tests/test_reference_parser.py`

- [ ] **Step 1: Write tests for reference extraction**

Create `tech-assessment-hub/tests/test_reference_parser.py`:

```python
"""Tests for the lightweight reference parser.

Validates regex extraction of table names, script includes, events,
REST messages, and field references from code strings.
"""

import pytest

from src.services.reference_parser import extract_table_references


class TestGlideRecordExtraction:
    def test_basic_glide_record(self):
        code = "var gr = new GlideRecord('contract_sla');"
        refs = extract_table_references(code)
        assert "contract_sla" in refs

    def test_glide_aggregate(self):
        code = "var ga = new GlideAggregate('cmn_schedule');"
        refs = extract_table_references(code)
        assert "cmn_schedule" in refs

    def test_double_quotes(self):
        code = 'var gr = new GlideRecord("task_sla");'
        refs = extract_table_references(code)
        assert "task_sla" in refs

    def test_multiple_tables(self):
        code = """
        var gr = new GlideRecord('incident');
        var gr2 = new GlideRecord('contract_sla');
        var ga = new GlideAggregate('task_sla');
        """
        refs = extract_table_references(code)
        assert "incident" in refs
        assert "contract_sla" in refs
        assert "task_sla" in refs

    def test_no_glide_record(self):
        code = "var x = 1 + 2;"
        refs = extract_table_references(code)
        assert len(refs) == 0

    def test_ignores_comments(self):
        code = "// var gr = new GlideRecord('should_ignore');"
        refs = extract_table_references(code)
        assert "should_ignore" not in refs


class TestScriptIncludeExtraction:
    def test_custom_class(self):
        code = "var util = new SLAUtils();"
        refs = extract_table_references(code)
        # Script includes don't map to tables, so should not be in table refs
        assert "SLAUtils" not in refs

    def test_gs_include(self):
        code = "gs.include('SLARepair');"
        refs = extract_table_references(code)
        assert "SLARepair" not in refs


class TestEventExtraction:
    def test_event_queue(self):
        code = "gs.eventQueue('sla.breach', current, '', '');"
        refs = extract_table_references(code)
        # Events don't directly map to tables
        assert "sla.breach" not in refs


class TestRESTMessageExtraction:
    def test_rest_message(self):
        code = "var r = new sn_ws.RESTMessageV2('My REST Message', 'post');"
        refs = extract_table_references(code)
        # REST messages don't map to tables
        assert "My REST Message" not in refs


class TestFieldReferenceExtraction:
    def test_dot_walk_current(self):
        code = "var dept = current.caller_id.department;"
        refs = extract_table_references(code)
        # field_reference type — we extract the field name but it's not a table
        # This test validates we DON'T falsely add field names as tables
        assert "caller_id" not in refs
        assert "department" not in refs


class TestDeduplication:
    def test_same_table_referenced_twice(self):
        code = """
        var gr1 = new GlideRecord('contract_sla');
        var gr2 = new GlideRecord('contract_sla');
        """
        refs = extract_table_references(code)
        assert refs.count("contract_sla") == 1


class TestExtractAllReferences:
    """Test the full extract_all_references function that returns typed refs."""

    def test_returns_all_types(self):
        from src.services.reference_parser import extract_all_references

        code = """
        var gr = new GlideRecord('contract_sla');
        var util = new SLAUtils();
        gs.eventQueue('sla.breach', current, '', '');
        var r = new sn_ws.RESTMessageV2('My REST', 'post');
        """
        refs = extract_all_references(code)

        table_refs = [r for r in refs if r["type"] == "table_query"]
        script_refs = [r for r in refs if r["type"] == "script_include"]
        event_refs = [r for r in refs if r["type"] == "event"]
        rest_refs = [r for r in refs if r["type"] == "rest_message"]

        assert len(table_refs) >= 1
        assert table_refs[0]["target"] == "contract_sla"
        assert len(script_refs) >= 1
        assert len(event_refs) >= 1
        assert len(rest_refs) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_reference_parser.py -v 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement reference_parser.py**

Create `tech-assessment-hub/src/services/reference_parser.py`:

```python
"""Lightweight reference parser for enrichment tracing.

Extracts table names, script include names, event names, and REST message
names from code strings using regex. Simpler than the full code_reference_parser
engine — this only needs to identify WHAT is referenced, not resolve it to
specific scan result IDs.

Used by the enrichment stage to discover out-of-scope tables.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

# Regex patterns for reference extraction.
# Reuses the same patterns as code_reference_parser but returns raw identifiers
# instead of resolved scan result IDs.

_TABLE_PATTERNS = [
    (re.compile(r"\bnew\s+Glide(?:Record|Aggregate)\s*\(\s*['\"]([a-z_][a-z0-9_]*)['\"]"), "table_query"),
]

_SCRIPT_INCLUDE_PATTERNS = [
    (
        re.compile(
            r"\bnew\s+"
            r"(?!Glide(?:Record|Ajax|DateTime|Aggregate|Duration|Schedule|Element|"
            r"Filter|Session|System|Transaction|URI|Sys|Evaluation|App(?:Navigation)?|"
            r"PluginManager|UpdateManager2?|Workflow|DBFunctionBuilder)\b)"
            r"(?!sn_\w+\.)"
            r"([A-Z]\w{2,})\s*\("
        ),
        "script_include",
    ),
    (re.compile(r"\bgs\.include\s*\(\s*['\"]([^\"']+)['\"]"), "script_include"),
    (re.compile(r"\bnew\s+GlideAjax\s*\(\s*['\"]([^\"']+)['\"]"), "script_include"),
]

_EVENT_PATTERNS = [
    (re.compile(r"\bgs\.eventQueue\s*\(\s*['\"]([^\"']+)['\"]"), "event"),
]

_REST_PATTERNS = [
    (re.compile(r"\bnew\s+(?:sn_ws\.)?RESTMessageV2\s*\(\s*['\"]([^\"']+)['\"]"), "rest_message"),
]

_ALL_PATTERNS = _TABLE_PATTERNS + _SCRIPT_INCLUDE_PATTERNS + _EVENT_PATTERNS + _REST_PATTERNS

# Code fields to parse from raw_data_json
CODE_FIELDS = [
    "script",
    "code_body",
    "meta_code_body",
    "condition",
    "client_script",
    "server_script",
    "template",
]


def extract_table_references(code: str) -> List[str]:
    """Extract unique table names referenced in code via GlideRecord/GlideAggregate.

    Returns a deduplicated list of table names. Does NOT include script includes,
    events, or REST messages — only actual SN table names.
    """
    if not code or not code.strip():
        return []

    tables: Set[str] = set()
    for line in code.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        for pattern, _ref_type in _TABLE_PATTERNS:
            for match in pattern.finditer(line):
                target = match.group(1).strip()
                if target:
                    tables.add(target)

    return sorted(tables)


def extract_all_references(code: str) -> List[Dict[str, str]]:
    """Extract all typed references from code.

    Returns list of dicts: {"type": "table_query|script_include|event|rest_message", "target": "identifier"}
    """
    if not code or not code.strip():
        return []

    refs: List[Dict[str, str]] = []
    seen: Set[tuple] = set()

    for line in code.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        for pattern, ref_type in _ALL_PATTERNS:
            for match in pattern.finditer(line):
                target = match.group(1).strip()
                if target and (ref_type, target) not in seen:
                    seen.add((ref_type, target))
                    refs.append({"type": ref_type, "target": target})

    return refs


def extract_tables_from_scan_result(raw_data_json: Optional[str]) -> List[str]:
    """Extract table references from a ScanResult's raw_data_json.

    Parses all code fields and returns unique table names.
    """
    if not raw_data_json:
        return []

    try:
        data = json.loads(raw_data_json)
    except (json.JSONDecodeError, TypeError):
        return []

    all_tables: Set[str] = set()
    for field_name in CODE_FIELDS:
        code = data.get(field_name)
        if code and isinstance(code, str):
            all_tables.update(extract_table_references(code))

    return sorted(all_tables)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_reference_parser.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/reference_parser.py tech-assessment-hub/tests/test_reference_parser.py
git commit -m "feat: add lightweight reference parser for enrichment tracing"
```

---

### Task 3: Build Enrichment Tracer Service

**Files:**
- Create: `tech-assessment-hub/src/services/enrichment_tracer.py`
- Modify: `tech-assessment-hub/tests/test_enrichment_tracer.py` (add integration tests)

- [ ] **Step 1: Add integration tests to test_enrichment_tracer.py**

Append to existing `tech-assessment-hub/tests/test_enrichment_tracer.py`:

```python
from unittest.mock import MagicMock, patch
import uuid

from src.services.enrichment_tracer import (
    run_enrichment,
    _collect_in_scope_tables,
    _discover_out_of_scope_tables,
    DEFAULT_EXCLUDED_TABLES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_base(session):
    """Create Instance + Assessment + Scan scaffolding."""
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test Assessment",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="initial scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    return inst, asmt, scan


def _add_scan_result(session, scan, name, table_name="sys_script",
                     sys_id=None, raw_data_json=None,
                     origin_type=OriginType.net_new_customer):
    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id or uuid.uuid4().hex[:32],
        table_name=table_name,
        name=name,
        origin_type=origin_type,
        raw_data_json=raw_data_json,
    )
    session.add(sr)
    session.flush()
    return sr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCollectInScopeTables:
    """_collect_in_scope_tables returns distinct table_names from scan results."""

    def test_basic(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script")
        _add_scan_result(db_session, scan, "CS1", table_name="sys_script_client")
        _add_scan_result(db_session, scan, "BR2", table_name="sys_script")

        tables = _collect_in_scope_tables(db_session, asmt.id)
        assert "sys_script" in tables
        assert "sys_script_client" in tables
        assert len(tables) == 2


class TestDiscoverOutOfScopeTables:
    """_discover_out_of_scope_tables filters correctly."""

    def test_filters_in_scope_and_excluded(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        code = json.dumps({
            "script": """
            var gr = new GlideRecord('contract_sla');
            var gr2 = new GlideRecord('incident');
            var gr3 = new GlideRecord('sys_user');
            """
        })
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script",
                         raw_data_json=code)
        # incident is already in scope (add a scan result on it)
        _add_scan_result(db_session, scan, "BR2", table_name="incident")

        in_scope = _collect_in_scope_tables(db_session, asmt.id)
        discovered = _discover_out_of_scope_tables(
            db_session, asmt.id, in_scope, DEFAULT_EXCLUDED_TABLES
        )
        assert "contract_sla" in discovered
        assert "incident" not in discovered  # already in scope
        assert "sys_user" not in discovered  # excluded


class TestRunEnrichment:
    """Integration tests for the full run_enrichment function."""

    @patch("src.services.enrichment_tracer.create_client_for_instance")
    def test_creates_enrichment_scan(self, mock_client_factory, db_session):
        """Enrichment creates a new scan and scan results."""
        inst, asmt, scan = _setup_base(db_session)
        code = json.dumps({
            "script": "var gr = new GlideRecord('contract_sla');"
        })
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script",
                         raw_data_json=code)

        # Mock the SN client
        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {
                "sys_id": "abc123def456abc123def456abc123de",
                "name": "SLA Business Rule",
                "sys_class_name": "sys_script",
                "sys_update_name": "sys_script_sla_br",
                "sys_scope": "global",
                "sys_package": "",
                "active": "true",
                "script": "// some code",
            }
        ]
        mock_client_factory.return_value = mock_client

        result = run_enrichment(asmt.id, db_session)

        assert result["success"] is True
        assert result["artifacts_discovered"] >= 1
        assert "contract_sla" in result["tables_traced"]

        # Verify enrichment scan was created
        enrichment_scans = list(db_session.exec(
            select(Scan).where(
                Scan.assessment_id == asmt.id,
                Scan.scan_type == ScanType.enrichment,
            )
        ).all())
        assert len(enrichment_scans) == 1

        # Verify scan results are adjacent
        enrichment_results = list(db_session.exec(
            select(ScanResult).where(
                ScanResult.scan_id == enrichment_scans[0].id
            )
        ).all())
        assert len(enrichment_results) >= 1
        assert all(sr.is_adjacent for sr in enrichment_results)

    @patch("src.services.enrichment_tracer.create_client_for_instance")
    def test_no_out_of_scope_refs(self, mock_client_factory, db_session):
        """If all references are in-scope, no enrichment scan is created."""
        inst, asmt, scan = _setup_base(db_session)
        code = json.dumps({
            "script": "var gr = new GlideRecord('sys_script');"
        })
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script",
                         raw_data_json=code)

        result = run_enrichment(asmt.id, db_session)

        assert result["success"] is True
        assert result["artifacts_discovered"] == 0
        assert len(result["tables_traced"]) == 0

    @patch("src.services.enrichment_tracer.create_client_for_instance")
    def test_idempotent(self, mock_client_factory, db_session):
        """Running enrichment twice cleans up old enrichment scan."""
        inst, asmt, scan = _setup_base(db_session)
        code = json.dumps({
            "script": "var gr = new GlideRecord('contract_sla');"
        })
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script",
                         raw_data_json=code)

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"sys_id": "abc123def456abc123def456abc123de",
             "name": "SLA BR", "sys_class_name": "sys_script",
             "sys_update_name": "x", "sys_scope": "global",
             "sys_package": "", "active": "true"}
        ]
        mock_client_factory.return_value = mock_client

        run_enrichment(asmt.id, db_session)
        result2 = run_enrichment(asmt.id, db_session)

        enrichment_scans = list(db_session.exec(
            select(Scan).where(
                Scan.assessment_id == asmt.id,
                Scan.scan_type == ScanType.enrichment,
            )
        ).all())
        # Only one enrichment scan should exist (old one deleted)
        assert len(enrichment_scans) == 1
        assert result2["success"] is True

    def test_assessment_not_found(self, db_session):
        result = run_enrichment(999999, db_session)
        assert result["success"] is False
        assert "not found" in result["errors"][0].lower()

    @patch("src.services.enrichment_tracer.create_client_for_instance")
    def test_deduplication(self, mock_client_factory, db_session):
        """Artifacts already in original scan are not duplicated."""
        inst, asmt, scan = _setup_base(db_session)
        existing_sys_id = "abc123def456abc123def456abc123de"
        code = json.dumps({
            "script": "var gr = new GlideRecord('contract_sla');"
        })
        _add_scan_result(db_session, scan, "BR1", table_name="sys_script",
                         raw_data_json=code)
        # This artifact already exists from the original scan
        _add_scan_result(db_session, scan, "Existing SLA BR",
                         table_name="sys_script",
                         sys_id=existing_sys_id)

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"sys_id": existing_sys_id, "name": "Existing SLA BR",
             "sys_class_name": "sys_script", "sys_update_name": "x",
             "sys_scope": "global", "sys_package": "", "active": "true"}
        ]
        mock_client_factory.return_value = mock_client

        result = run_enrichment(asmt.id, db_session)

        # Should not create a duplicate
        assert result["artifacts_discovered"] == 0

    @patch("src.services.enrichment_tracer.create_client_for_instance")
    def test_enrichment_provenance_in_ai_observations(self, mock_client_factory, db_session):
        """Discovered artifacts have enrichment provenance in ai_observations."""
        inst, asmt, scan = _setup_base(db_session)
        code = json.dumps({
            "script": "var gr = new GlideRecord('contract_sla');"
        })
        source_sr = _add_scan_result(db_session, scan, "BR1",
                                     table_name="sys_script",
                                     raw_data_json=code)

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"sys_id": "new123def456abc123def456abc123de",
             "name": "SLA BR", "sys_class_name": "sys_script",
             "sys_update_name": "x", "sys_scope": "global",
             "sys_package": "", "active": "true", "script": "// code"}
        ]
        mock_client_factory.return_value = mock_client

        run_enrichment(asmt.id, db_session)

        enrichment_results = list(db_session.exec(
            select(ScanResult).where(
                ScanResult.is_adjacent == True
            )
        ).all())
        assert len(enrichment_results) >= 1
        ai_obs = json.loads(enrichment_results[0].ai_observations)
        assert ai_obs["enrichment_source"]["discovered_via"] == "reference_trace"
        assert ai_obs["enrichment_source"]["discovered_table"] == "contract_sla"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_enrichment_tracer.py::TestRunEnrichment::test_creates_enrichment_scan -v 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement enrichment_tracer.py**

Create `tech-assessment-hub/src/services/enrichment_tracer.py`:

```python
"""Reference trace enrichment service.

Discovers out-of-scope tables referenced by scanned artifacts, queries
ServiceNow for customized artifacts on those tables, and inserts them
as adjacent scan results in a new enrichment scan.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from sqlmodel import Session, select

from ..models import (
    Assessment,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from .reference_parser import extract_tables_from_scan_result
from .sn_client_factory import create_client_for_instance

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_TABLES: Set[str] = {
    "sys_user",
    "sys_user_group",
    "task",
    "sys_dictionary",
    "sys_db_object",
    "sys_choice",
    "sys_metadata",
    "sys_update_xml",
    "sys_glide_object",
    "sys_properties",
    "sys_number",
    "sys_documentation",
    "sys_translated_text",
}

# Artifact types to query per discovered table
_ARTIFACT_QUERIES = [
    {"table": "sys_script", "query_field": "collection", "label": "Business Rules"},
    {"table": "sys_script_client", "query_field": "table", "label": "Client Scripts"},
    {"table": "sys_ui_policy", "query_field": "table", "label": "UI Policies"},
    {"table": "sys_ui_action", "query_field": "table", "label": "UI Actions"},
    {"table": "sys_security_acl", "query_field": "name", "query_op": "LIKE", "label": "ACLs"},
    {"table": "sys_dictionary_override", "query_field": "name", "label": "Dictionary Overrides"},
]

_SN_FIELDS = [
    "sys_id", "name", "sys_class_name", "sys_update_name",
    "sys_scope", "sys_package", "active",
    "sys_updated_on", "sys_updated_by", "sys_created_on", "sys_created_by",
    "script", "condition",
]


def _collect_in_scope_tables(session: Session, assessment_id: int) -> Set[str]:
    """Return distinct table_name values from all scan results for this assessment."""
    scans = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scans:
        return set()

    results = session.exec(
        select(ScanResult.table_name)
        .where(ScanResult.scan_id.in_(scans))  # type: ignore[attr-defined]
    ).all()

    return {r for r in results if r}


def _discover_out_of_scope_tables(
    session: Session,
    assessment_id: int,
    in_scope_tables: Set[str],
    excluded_tables: Set[str],
) -> Set[str]:
    """Parse code in scan results to find referenced tables not in scope."""
    scans = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scans:
        return set()

    scan_results = list(session.exec(
        select(ScanResult)
        .where(ScanResult.scan_id.in_(scans))  # type: ignore[attr-defined]
    ).all())

    referenced_tables: Set[str] = set()
    for sr in scan_results:
        tables = extract_tables_from_scan_result(sr.raw_data_json)
        referenced_tables.update(tables)

    # Filter out in-scope and excluded
    out_of_scope = referenced_tables - in_scope_tables - excluded_tables
    return out_of_scope


def _get_existing_sys_ids(session: Session, assessment_id: int) -> Set[str]:
    """Return set of all sys_ids already in scan results for this assessment."""
    scans = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scans:
        return set()

    results = session.exec(
        select(ScanResult.sys_id)
        .where(ScanResult.scan_id.in_(scans))  # type: ignore[attr-defined]
    ).all()

    return {r for r in results if r}


def _query_artifacts_for_table(
    client: Any,
    target_table: str,
    max_per_table: int,
) -> List[Dict[str, Any]]:
    """Query SN for artifacts associated with a target table."""
    all_artifacts: List[Dict[str, Any]] = []

    for query_def in _ARTIFACT_QUERIES:
        try:
            query_op = query_def.get("query_op", "=")
            if query_op == "LIKE":
                query = f"{query_def['query_field']}LIKE{target_table}"
            else:
                query = f"{query_def['query_field']}={target_table}"

            records = client.get_records(
                table=query_def["table"],
                query=query,
                fields=_SN_FIELDS,
                limit=max_per_table,
            )

            for record in records:
                record["_source_table"] = query_def["table"]
                record["_artifact_type"] = query_def["label"]
                all_artifacts.append(record)

        except Exception as exc:
            logger.warning(
                "Failed to query %s for table %s: %s",
                query_def["table"], target_table, exc,
            )
            continue

    return all_artifacts[:max_per_table]


def _build_referencing_map(
    session: Session,
    assessment_id: int,
    out_of_scope_tables: Set[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Build a map of discovered_table -> [referencing scan results]."""
    scans = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scans:
        return {}

    scan_results = list(session.exec(
        select(ScanResult)
        .where(ScanResult.scan_id.in_(scans))  # type: ignore[attr-defined]
    ).all())

    ref_map: Dict[str, List[Dict[str, Any]]] = {t: [] for t in out_of_scope_tables}
    for sr in scan_results:
        tables = extract_tables_from_scan_result(sr.raw_data_json)
        for table in tables:
            if table in ref_map:
                ref_map[table].append({
                    "scan_result_id": sr.id,
                    "name": sr.name,
                    "reference_type": "table_query",
                })

    return ref_map


def run_enrichment(
    assessment_id: int,
    session: Session,
    *,
    max_artifacts_per_table: int = 50,
    excluded_tables: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Run reference trace enrichment for an assessment.

    Returns summary dict with keys:
        success, tables_in_scope, references_found, tables_traced,
        tables_excluded, artifacts_discovered, enrichment_scan_id, errors
    """
    if excluded_tables is None:
        excluded_tables = DEFAULT_EXCLUDED_TABLES

    # 1. Validate assessment
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "tables_in_scope": 0,
            "references_found": 0,
            "tables_traced": [],
            "tables_excluded": [],
            "artifacts_discovered": 0,
            "enrichment_scan_id": None,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    # 2. Delete existing enrichment scan for idempotency
    existing_enrichment_scans = list(session.exec(
        select(Scan).where(
            Scan.assessment_id == assessment_id,
            Scan.scan_type == ScanType.enrichment,
        )
    ).all())
    for old_scan in existing_enrichment_scans:
        # Delete scan results first
        old_results = list(session.exec(
            select(ScanResult).where(ScanResult.scan_id == old_scan.id)
        ).all())
        for old_result in old_results:
            session.delete(old_result)
        session.delete(old_scan)
    session.flush()

    # 3. Collect in-scope tables
    in_scope_tables = _collect_in_scope_tables(session, assessment_id)

    # 4. Discover out-of-scope tables from code references
    out_of_scope_tables = _discover_out_of_scope_tables(
        session, assessment_id, in_scope_tables, excluded_tables
    )

    if not out_of_scope_tables:
        session.commit()
        return {
            "success": True,
            "tables_in_scope": len(in_scope_tables),
            "references_found": 0,
            "tables_traced": [],
            "tables_excluded": [],
            "artifacts_discovered": 0,
            "enrichment_scan_id": None,
            "errors": [],
            "message": "No out-of-scope table references found",
        }

    # 5. Build referencing map for provenance
    ref_map = _build_referencing_map(session, assessment_id, out_of_scope_tables)

    # 6. Query SN for artifacts on discovered tables
    instance = session.get(Instance, assessment.instance_id)
    if not instance:
        return {
            "success": False,
            "tables_in_scope": len(in_scope_tables),
            "references_found": len(out_of_scope_tables),
            "tables_traced": sorted(out_of_scope_tables),
            "tables_excluded": [],
            "artifacts_discovered": 0,
            "enrichment_scan_id": None,
            "errors": ["Instance not found for assessment"],
        }

    client = create_client_for_instance(instance)
    existing_sys_ids = _get_existing_sys_ids(session, assessment_id)

    # 7. Create enrichment scan
    enrichment_scan = Scan(
        assessment_id=assessment_id,
        scan_type=ScanType.enrichment,
        name="Reference Trace Enrichment",
        status=ScanStatus.running,
        started_at=datetime.utcnow(),
    )
    session.add(enrichment_scan)
    session.flush()

    # 8. Query and insert artifacts
    errors: List[str] = []
    artifacts_discovered = 0
    tables_traced: List[str] = []

    for target_table in sorted(out_of_scope_tables):
        try:
            artifacts = _query_artifacts_for_table(
                client, target_table, max_artifacts_per_table
            )
            table_added = 0

            for artifact in artifacts:
                sys_id = artifact.get("sys_id", "")
                if not sys_id or sys_id in existing_sys_ids:
                    continue

                # Build enrichment provenance
                provenance = {
                    "enrichment_source": {
                        "discovered_via": "reference_trace",
                        "referenced_by": ref_map.get(target_table, []),
                        "discovered_table": target_table,
                        "enrichment_scan_id": enrichment_scan.id,
                    }
                }

                sr = ScanResult(
                    scan_id=enrichment_scan.id,
                    sys_id=sys_id,
                    table_name=artifact.get("_source_table", "unknown"),
                    name=artifact.get("name") or artifact.get("sys_update_name") or sys_id,
                    display_value=artifact.get("name"),
                    sys_class_name=artifact.get("sys_class_name"),
                    sys_update_name=artifact.get("sys_update_name"),
                    sys_scope=artifact.get("sys_scope"),
                    sys_package=artifact.get("sys_package"),
                    meta_target_table=target_table,
                    is_adjacent=True,
                    raw_data_json=json.dumps(artifact),
                    ai_observations=json.dumps(provenance),
                )
                session.add(sr)
                existing_sys_ids.add(sys_id)
                table_added += 1
                artifacts_discovered += 1

            if table_added > 0:
                tables_traced.append(target_table)

        except Exception as exc:
            errors.append(f"Error querying {target_table}: {exc}")
            logger.warning("Enrichment query failed for %s: %s", target_table, exc)

    # 9. Finalize
    enrichment_scan.status = ScanStatus.completed
    enrichment_scan.completed_at = datetime.utcnow()
    enrichment_scan.records_found = artifacts_discovered
    session.commit()

    return {
        "success": True,
        "tables_in_scope": len(in_scope_tables),
        "references_found": len(out_of_scope_tables),
        "tables_traced": tables_traced,
        "tables_excluded": sorted(out_of_scope_tables - set(tables_traced)),
        "artifacts_discovered": artifacts_discovered,
        "enrichment_scan_id": enrichment_scan.id,
        "errors": errors,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_enrichment_tracer.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/enrichment_tracer.py tech-assessment-hub/tests/test_enrichment_tracer.py
git commit -m "feat: add enrichment tracer service with SN queries and provenance tracking"
```

---

### Task 4: Create MCP Tool and Register Pipeline Stage

**Files:**
- Create: `tech-assessment-hub/src/mcp/tools/pipeline/run_enrichment.py`
- Modify: `tech-assessment-hub/src/server.py`
- Modify: `tech-assessment-hub/src/services/integration_properties.py`

- [ ] **Step 1: Create the MCP tool handler**

Create `tech-assessment-hub/src/mcp/tools/pipeline/run_enrichment.py`:

```python
"""MCP tool: run_enrichment.

Runs reference trace enrichment for an assessment — discovers out-of-scope
tables referenced by scanned artifacts and pulls their customizations from
ServiceNow.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....services.assessment_phase_progress import checkpoint_phase_progress, start_phase_progress
from ....services.enrichment_tracer import run_enrichment


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to run enrichment for.",
        },
    },
    "required": ["assessment_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])

    start_phase_progress(
        session,
        assessment_id,
        "enrichment",
        total_items=1,
        allow_resume=False,
        checkpoint={"source": "run_enrichment_tool"},
        commit=False,
    )

    result = run_enrichment(assessment_id, session)

    checkpoint_phase_progress(
        session,
        assessment_id,
        "enrichment",
        completed_items=1,
        total_items=1,
        status="completed" if result["success"] else "failed",
        checkpoint={
            "tables_traced": result.get("tables_traced", []),
            "artifacts_discovered": result.get("artifacts_discovered", 0),
            "errors": result.get("errors", []),
        },
        commit=False,
    )
    session.commit()

    return result


TOOL_SPEC = ToolSpec(
    name="run_enrichment",
    description=(
        "Run reference trace enrichment for an assessment. "
        "Discovers out-of-scope tables referenced by scanned artifacts, "
        "queries ServiceNow for customizations on those tables, and "
        "inserts them as adjacent scan results."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

- [ ] **Step 2: Update pipeline stage order in server.py**

In `src/server.py`, update `_PIPELINE_STAGE_ORDER` to insert `enrichment` after `scans`:

```python
_PIPELINE_STAGE_ORDER: List[str] = [
    PipelineStage.scans.value,
    PipelineStage.enrichment.value,
    PipelineStage.engines.value,
    PipelineStage.ai_analysis.value,
    PipelineStage.observations.value,
    PipelineStage.review.value,
    PipelineStage.grouping.value,
    PipelineStage.ai_refinement.value,
    PipelineStage.recommendations.value,
    PipelineStage.report.value,
    PipelineStage.complete.value,
]
```

Update `_PIPELINE_STAGE_LABELS` to include enrichment:

```python
    PipelineStage.enrichment.value: "Enrichment",
```

Add the stage handler in the dispatch block (after the scans handler, before engines):

```python
        elif stage == PipelineStage.enrichment.value:
            from src.mcp.tools.pipeline.run_enrichment import handle as enrichment_handle
            enrichment_result = enrichment_handle(
                {"assessment_id": assessment_id}, session
            )
            stage_result = enrichment_result
```

(Match the exact pattern of how other stages dispatch — read the surrounding code for the right variable names and indentation.)

- [ ] **Step 3: Add enrichment configuration properties**

In `src/services/integration_properties.py`:

Add key constants (after dependency mapper keys):

```python
ENRICHMENT_ENABLED = "enrichment.enabled"
ENRICHMENT_MAX_ARTIFACTS_PER_TABLE = "enrichment.max_artifacts_per_table"
ENRICHMENT_EXCLUDED_TABLES = "enrichment.excluded_tables"
```

Add to `PROPERTY_DEFAULTS`:

```python
    ENRICHMENT_ENABLED: "true",
    ENRICHMENT_MAX_ARTIFACTS_PER_TABLE: "50",
    ENRICHMENT_EXCLUDED_TABLES: json.dumps([
        "sys_user", "sys_user_group", "task", "sys_dictionary",
        "sys_db_object", "sys_choice", "sys_metadata", "sys_update_xml",
        "sys_glide_object", "sys_properties", "sys_number",
        "sys_documentation", "sys_translated_text"
    ]),
```

Add `IntegrationPropertyDefinition` entries to `PROPERTY_DEFINITIONS`.

- [ ] **Step 4: Run full test suite**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ --tb=short 2>&1 | tail -15
```

Expected: ALL PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/mcp/tools/pipeline/run_enrichment.py tech-assessment-hub/src/server.py tech-assessment-hub/src/services/integration_properties.py
git commit -m "feat: register enrichment pipeline stage with MCP tool and config properties"
```

---

### Task 5: Full Test Suite Verification

**Files:**
- All previously created/modified files

- [ ] **Step 1: Run all new tests**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_reference_parser.py tech-assessment-hub/tests/test_enrichment_tracer.py -v
```

Expected: ALL PASS

- [ ] **Step 2: Run complete test suite**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ --tb=short 2>&1 | tail -15
```

Expected: ALL PASS with no regressions

- [ ] **Step 3: Final commit if cleanup needed**

Only if test failures required fixes.
