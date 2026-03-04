# Reasoning Layer Phase 1: Data Model & First Two Engines

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

## Plan Addendum (2026-03-04)

- Added `temporal_cluster_member` junction table (cluster ↔ `scan_result`) to preserve FK-level traceability for temporal grouping membership.
- This is an intentional extension beyond the original Phase 1 scope and does not change prior tasks; it strengthens relational integrity for Phase 2 Temporal Clusterer implementation.

**Goal:** Add the 4 new tables + new fields needed by the reasoning/grouping pipeline, then build the two highest-value deterministic engines (Code Reference Parser + Structural Mapper).

**Architecture:** New SQLModel tables store engine outputs (code references, structural relationships, update set overlaps, temporal clusters). New fields on existing Feature and ScanResult models track AI pass metadata and confidence scoring. Engines are pure-Python modules in `src/engines/` that read ingested data and populate these tables — no AI, no network calls.

**Tech Stack:** Python 3.9, SQLModel, SQLAlchemy, SQLite, pytest

**Reference docs:**
- Design doc: `docs/plans/SN_TA_Reasoning_Layer_Implementation_Plan.md`
- Grouping signals: `servicenow_global_tech_assessment_mcp/02_working/01_notes/grouping_signals.md`

---

## Task 1: Add GroupingSignalType Enum

**Files:**
- Modify: `src/models.py:8-9` (imports) and `~120` (after FindingCategory enum)

**Step 1: Write the failing test**

Create: `tests/test_reasoning_data_model.py`

```python
"""Tests for reasoning layer data model additions."""

import pytest
from sqlmodel import SQLModel, Session, create_engine

from src.models import (
    Instance, Assessment, Scan, ScanResult, Feature, FeatureScanResult,
    ScanStatus, AssessmentState, AssessmentType,
)


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


def test_grouping_signal_type_enum_exists():
    from src.models import GroupingSignalType
    assert GroupingSignalType.update_set == "update_set"
    assert GroupingSignalType.code_reference == "code_reference"
    assert GroupingSignalType.ai_judgment == "ai_judgment"
    # Verify all 9 members
    assert len(GroupingSignalType) == 9
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_grouping_signal_type_enum_exists -v`

Expected: FAIL — `ImportError: cannot import name 'GroupingSignalType'`

**Step 3: Write minimal implementation**

Add to `src/models.py` after the `FindingCategory` enum (around line 120):

```python
class GroupingSignalType(str, Enum):
    """Signal types used by the feature grouping algorithm."""
    update_set = "update_set"
    table_affinity = "table_affinity"
    naming_convention = "naming_convention"
    code_reference = "code_reference"
    structural_parent_child = "structural_parent_child"
    temporal_proximity = "temporal_proximity"
    reference_field = "reference_field"
    application_package = "application_package"
    ai_judgment = "ai_judgment"
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_grouping_signal_type_enum_exists -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add GroupingSignalType enum for reasoning pipeline"
```

---

## Task 2: Add CodeReference Table

**Files:**
- Modify: `src/models.py` (add class after FeatureScanResult, ~line 650)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def _seed_assessment(session):
    """Seed instance → assessment → scan → 2 scan_results. Returns (assessment, sr1, sr2)."""
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    session.add(inst)
    session.flush()
    asmt = Assessment(
        instance_id=inst.id, name="Test Assessment", number="ASMT0001",
        assessment_type=AssessmentType.global_app, state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()
    scan = Scan(assessment_id=asmt.id, name="test scan", status=ScanStatus.completed)
    session.add(scan)
    session.flush()
    sr1 = ScanResult(
        scan_id=scan.id, sys_id="aaa111", table_name="sys_script",
        name="BR - Approval Check",
    )
    sr2 = ScanResult(
        scan_id=scan.id, sys_id="bbb222", table_name="sys_script_include",
        name="ApprovalHelper",
    )
    session.add_all([sr1, sr2])
    session.flush()
    return asmt, sr1, sr2


def test_code_reference_table_round_trip(db_session):
    from src.models import CodeReference

    asmt, sr1, sr2 = _seed_assessment(db_session)

    ref = CodeReference(
        assessment_id=asmt.id,
        source_scan_result_id=sr1.id,
        source_table="sys_script",
        source_field="script",
        source_name="BR - Approval Check",
        reference_type="script_include",
        target_identifier="ApprovalHelper",
        target_scan_result_id=sr2.id,
        line_number=42,
        code_snippet="new ApprovalHelper()",
        confidence=1.0,
    )
    db_session.add(ref)
    db_session.commit()
    db_session.refresh(ref)

    assert ref.id is not None
    assert ref.assessment_id == asmt.id
    assert ref.source_scan_result_id == sr1.id
    assert ref.target_scan_result_id == sr2.id
    assert ref.reference_type == "script_include"
    assert ref.confidence == 1.0
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_code_reference_table_round_trip -v`

Expected: FAIL — `ImportError: cannot import name 'CodeReference'`

**Step 3: Write minimal implementation**

Add to `src/models.py` after the `FeatureScanResult` class (after line ~650):

```python
# ============================================
# TABLE: CodeReference (cross-references in scripts)
# Populated by the Code Reference Parser engine
# ============================================

class CodeReference(SQLModel, table=True):
    """Cross-reference discovered by parsing script/code fields."""
    __tablename__ = "code_reference"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    # Source: which scan result contains the code
    source_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    source_table: str          # e.g., "sys_script"
    source_field: str          # e.g., "script"
    source_name: str           # e.g., "BR - Approval Check"

    # Target: what the code references
    reference_type: str        # "script_include", "table_query", "event", etc.
    target_identifier: str     # The actual string found: class name, table name, etc.
    target_scan_result_id: Optional[int] = Field(
        default=None, foreign_key="scan_result.id"
    )

    # Context
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_code_reference_table_round_trip -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add CodeReference table for script cross-references"
```

---

## Task 3: Add UpdateSetOverlap Table

**Files:**
- Modify: `src/models.py` (add class after CodeReference)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_update_set_overlap_table_round_trip(db_session):
    from src.models import UpdateSetOverlap, UpdateSet
    import json

    asmt, sr1, sr2 = _seed_assessment(db_session)

    # Create two update sets
    us1 = UpdateSet(
        instance_id=1, sn_sys_id="us_aaa", name="RITM Approval v1",
        state="closed", application="global",
    )
    us2 = UpdateSet(
        instance_id=1, sn_sys_id="us_bbb", name="RITM Approval v2",
        state="closed", application="global",
    )
    db_session.add_all([us1, us2])
    db_session.flush()

    overlap = UpdateSetOverlap(
        assessment_id=asmt.id,
        update_set_a_id=us1.id,
        update_set_b_id=us2.id,
        shared_record_count=3,
        shared_records_json=json.dumps([
            {"scan_result_id": sr1.id, "name": "BR - Approval Check", "table": "sys_script"},
        ]),
        overlap_score=0.75,
    )
    db_session.add(overlap)
    db_session.commit()
    db_session.refresh(overlap)

    assert overlap.id is not None
    assert overlap.shared_record_count == 3
    assert overlap.overlap_score == 0.75
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_update_set_overlap_table_round_trip -v`

Expected: FAIL — `ImportError: cannot import name 'UpdateSetOverlap'`

**Step 3: Write minimal implementation**

Add to `src/models.py` after CodeReference:

```python
# ============================================
# TABLE: UpdateSetOverlap (cross-update-set record sharing)
# Populated by the Update Set Analyzer engine
# ============================================

class UpdateSetOverlap(SQLModel, table=True):
    """Records shared between two update sets."""
    __tablename__ = "update_set_overlap"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    update_set_a_id: int = Field(foreign_key="update_set.id", index=True)
    update_set_b_id: int = Field(foreign_key="update_set.id", index=True)

    shared_record_count: int
    shared_records_json: str         # JSON list of {scan_result_id, name, table}
    overlap_score: float             # Normalized: shared / min(a_count, b_count)

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_update_set_overlap_table_round_trip -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add UpdateSetOverlap table for cross-update-set analysis"
```

---

## Task 4: Add TemporalCluster Table

**Files:**
- Modify: `src/models.py` (add class after UpdateSetOverlap)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_temporal_cluster_table_round_trip(db_session):
    from src.models import TemporalCluster
    from datetime import datetime
    import json

    asmt, sr1, sr2 = _seed_assessment(db_session)

    cluster = TemporalCluster(
        assessment_id=asmt.id,
        developer="john.doe",
        cluster_start=datetime(2025, 6, 15, 10, 0, 0),
        cluster_end=datetime(2025, 6, 15, 10, 45, 0),
        record_count=5,
        record_ids_json=json.dumps([sr1.id, sr2.id]),
        avg_gap_minutes=11.25,
        tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()
    db_session.refresh(cluster)

    assert cluster.id is not None
    assert cluster.developer == "john.doe"
    assert cluster.record_count == 5
    assert cluster.avg_gap_minutes == 11.25
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_temporal_cluster_table_round_trip -v`

Expected: FAIL — `ImportError: cannot import name 'TemporalCluster'`

**Step 3: Write minimal implementation**

Add to `src/models.py` after UpdateSetOverlap:

```python
# ============================================
# TABLE: TemporalCluster (developer activity windows)
# Populated by the Temporal Clusterer engine
# ============================================

class TemporalCluster(SQLModel, table=True):
    """Cluster of records created/updated in close time proximity by same developer."""
    __tablename__ = "temporal_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    developer: str
    cluster_start: datetime
    cluster_end: datetime
    record_count: int
    record_ids_json: str              # JSON list of scan_result_ids
    avg_gap_minutes: float
    tables_involved_json: str         # JSON list of distinct tables

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_temporal_cluster_table_round_trip -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add TemporalCluster table for developer activity analysis"
```

---

## Task 5: Add StructuralRelationship Table

**Files:**
- Modify: `src/models.py` (add class after TemporalCluster)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_structural_relationship_table_round_trip(db_session):
    from src.models import StructuralRelationship

    asmt, sr1, sr2 = _seed_assessment(db_session)

    rel = StructuralRelationship(
        assessment_id=asmt.id,
        parent_scan_result_id=sr1.id,
        child_scan_result_id=sr2.id,
        relationship_type="ui_policy_action",
        parent_field="ui_policy",
        confidence=1.0,
    )
    db_session.add(rel)
    db_session.commit()
    db_session.refresh(rel)

    assert rel.id is not None
    assert rel.parent_scan_result_id == sr1.id
    assert rel.child_scan_result_id == sr2.id
    assert rel.relationship_type == "ui_policy_action"
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_structural_relationship_table_round_trip -v`

Expected: FAIL — `ImportError: cannot import name 'StructuralRelationship'`

**Step 3: Write minimal implementation**

Add to `src/models.py` after TemporalCluster:

```python
# ============================================
# TABLE: StructuralRelationship (parent/child metadata links)
# Populated by the Structural Mapper engine
# ============================================

class StructuralRelationship(SQLModel, table=True):
    """Explicit parent/child or structural relationship between artifacts."""
    __tablename__ = "structural_relationship"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    parent_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    child_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    relationship_type: str     # "ui_policy_action", "workflow_activity",
                               # "dictionary_entry", "dictionary_override", etc.
    parent_field: str          # The field that establishes the link
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_structural_relationship_table_round_trip -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add StructuralRelationship table for parent/child artifact links"
```

---

## Task 6: Add New Fields to Feature Model

**Files:**
- Modify: `src/models.py:566-598` (Feature class)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_feature_has_reasoning_fields(db_session):
    """Feature model should have confidence scoring + signal tracking fields."""
    asmt, sr1, sr2 = _seed_assessment(db_session)
    import json

    feature = Feature(
        assessment_id=asmt.id,
        name="RITM Approval Workflow",
        confidence_score=8.5,
        confidence_level="high",
        signals_json=json.dumps([
            {"type": "update_set", "weight": 3},
            {"type": "code_reference", "weight": 4},
        ]),
        primary_table="sc_req_item",
        primary_developer="john.doe",
        pass_number=2,
    )
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)

    assert feature.confidence_score == 8.5
    assert feature.confidence_level == "high"
    assert "update_set" in feature.signals_json
    assert feature.primary_table == "sc_req_item"
    assert feature.primary_developer == "john.doe"
    assert feature.pass_number == 2
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_feature_has_reasoning_fields -v`

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'confidence_score'`

**Step 3: Write minimal implementation**

Add these fields to the `Feature` class in `src/models.py` (before the `created_at` field, around line 587):

```python
    # ---- Reasoning pipeline fields ----
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None       # "high" / "medium" / "low"
    signals_json: Optional[str] = None           # JSON array of contributing signals
    primary_table: Optional[str] = None
    primary_developer: Optional[str] = None
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None
    pass_number: Optional[int] = None            # Which AI pass last updated this
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_feature_has_reasoning_fields -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add confidence scoring + signal tracking fields to Feature"
```

---

## Task 7: Add New Fields to ScanResult Model

**Files:**
- Modify: `src/models.py:428-509` (ScanResult class)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_scan_result_has_reasoning_fields(db_session):
    """ScanResult should have AI pass tracking and summary fields."""
    asmt, sr1, sr2 = _seed_assessment(db_session)
    import json

    sr1.ai_summary = "Business rule that checks approval status on RITM"
    sr1.ai_observations = "Pass 1: Calls ApprovalHelper script include."
    sr1.ai_pass_count = 1
    sr1.related_result_ids_json = json.dumps([sr2.id])

    db_session.add(sr1)
    db_session.commit()
    db_session.refresh(sr1)

    assert sr1.ai_summary == "Business rule that checks approval status on RITM"
    assert sr1.ai_pass_count == 1
    assert str(sr2.id) in sr1.related_result_ids_json
```

**Step 2: Run test to verify it fails**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_scan_result_has_reasoning_fields -v`

Expected: FAIL — `AttributeError` on `ai_summary`

**Step 3: Write minimal implementation**

Add these fields to the `ScanResult` class in `src/models.py` (before `raw_data_json`, around line 507):

```python
    # ---- Reasoning pipeline fields ----
    ai_summary: Optional[str] = None
    ai_observations: Optional[str] = None
    ai_pass_count: int = 0
    related_result_ids_json: Optional[str] = None
```

**Step 4: Run test to verify it passes**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_scan_result_has_reasoning_fields -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/models.py tests/test_reasoning_data_model.py
git commit -m "feat: add AI pass tracking fields to ScanResult"
```

---

## Task 8: Register New Tables in database.py Migration

**Files:**
- Modify: `src/database.py:49-72` (_ensure_model_table_columns list)
- Test: `tests/test_reasoning_data_model.py`

**Step 1: Write the failing test**

Append to `tests/test_reasoning_data_model.py`:

```python
def test_all_reasoning_tables_created(db_engine):
    """All 4 new tables should exist after create_all."""
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()

    assert "code_reference" in tables
    assert "update_set_overlap" in tables
    assert "temporal_cluster" in tables
    assert "structural_relationship" in tables
```

**Step 2: Run test to verify it passes (tables are auto-created by SQLModel)**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py::test_all_reasoning_tables_created -v`

Expected: PASS (SQLModel.metadata.create_all already creates them from the model defs)

**Step 3: Add to _ensure_model_table_columns for ALTER TABLE migration on existing DBs**

In `src/database.py`, add the 4 new table names AND the modified tables to the `_ensure_model_table_columns` list (around line 49-72):

Add these entries to the list:
```python
        "feature",
        "scan_result",
        "code_reference",
        "update_set_overlap",
        "temporal_cluster",
        "structural_relationship",
```

Note: `"feature"` and `"scan_result"` must be added because they have new columns that existing databases won't have. The 4 new tables are included for future-proofing in case columns are added later.

**Step 4: Run full test suite for data model**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_reasoning_data_model.py -v`

Expected: ALL PASS (7 tests)

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/database.py tests/test_reasoning_data_model.py
git commit -m "feat: register reasoning tables in database migration"
```

---

## Task 9: Create Engine Package Skeleton

**Files:**
- Create: `src/engines/__init__.py`
- Create: `src/engines/code_reference_parser.py` (skeleton)
- Create: `src/engines/structural_mapper.py` (skeleton)

**Step 1: Create the package and skeletons**

Create `src/engines/__init__.py`:
```python
"""Pre-processing engines for the reasoning pipeline.

Engines are deterministic, code-only modules that analyze ingested data
and populate relationship/signal tables. They run BEFORE AI analysis.
"""
```

Create `src/engines/code_reference_parser.py`:
```python
"""Engine 1: Code Reference Parser.

Parses script/code fields in artifact detail tables to find cross-references
to other artifacts (script includes, tables, events, etc.).

Input: Artifact detail tables with code_fields
Output: Rows in code_reference table
"""

from typing import Any, Dict, List
from sqlmodel import Session


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the code reference parser engine for an assessment.

    Returns summary dict with counts of references found.
    """
    raise NotImplementedError("Engine not yet implemented")
```

Create `src/engines/structural_mapper.py`:
```python
"""Engine 4: Structural Relationship Mapper.

Maps parent/child relationships between artifacts using known reference
field patterns (e.g., UI Policy → UI Policy Actions).

Input: Artifact detail tables
Output: Rows in structural_relationship table
"""

from typing import Any, Dict, List
from sqlmodel import Session


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the structural mapper engine for an assessment.

    Returns summary dict with counts of relationships found.
    """
    raise NotImplementedError("Engine not yet implemented")
```

**Step 2: Verify imports work**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -c "from src.engines import code_reference_parser, structural_mapper; print('OK')"`

Expected: `OK`

**Step 3: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/engines/
git commit -m "feat: add engines package skeleton with code_reference_parser and structural_mapper"
```

---

## Task 10: Implement Code Reference Parser — Regex Patterns

**Files:**
- Modify: `src/engines/code_reference_parser.py`
- Create: `tests/test_code_reference_parser.py`

This is the core logic — regex patterns that extract cross-references from ServiceNow scripts.

**Step 1: Write the failing tests for regex extraction**

Create `tests/test_code_reference_parser.py`:

```python
"""Tests for the Code Reference Parser engine."""

import pytest


def test_parse_script_include_instantiation():
    """Detect `new ClassName()` pattern."""
    from src.engines.code_reference_parser import extract_references

    script = """
    var helper = new ApprovalHelper();
    helper.checkApproval(current);
    """
    refs = extract_references(script, "sys_script", "script")

    assert len(refs) >= 1
    match = [r for r in refs if r["target_identifier"] == "ApprovalHelper"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_glide_record_query():
    """Detect GlideRecord('table_name') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = """
    var gr = new GlideRecord('incident');
    gr.addQuery('active', true);
    gr.query();
    """
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "incident"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "table_query"


def test_parse_gs_include():
    """Detect gs.include('name') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = "gs.include('ApprovalUtils');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "ApprovalUtils"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_event_queue():
    """Detect gs.eventQueue('event_name') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = "gs.eventQueue('custom.approval.needed', current, gs.getUserID(), '');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "custom.approval.needed"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "event"


def test_parse_glide_ajax():
    """Detect GlideAjax('name') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = "var ga = new GlideAjax('MyAjaxUtil');"
    refs = extract_references(script, "sys_script_client", "script")

    match = [r for r in refs if r["target_identifier"] == "MyAjaxUtil"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_rest_message():
    """Detect RESTMessageV2('name') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = "var rm = new sn_ws.RESTMessageV2('Outbound API', 'post');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "Outbound API"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "rest_message"


def test_parse_workflow_start():
    """Detect workflow.start/startFlow patterns."""
    from src.engines.code_reference_parser import extract_references

    script = "workflow.start('approval_flow', current);"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "approval_flow"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "workflow"


def test_parse_sp_get_widget():
    """Detect $sp.getWidget('id') pattern."""
    from src.engines.code_reference_parser import extract_references

    script = "var widget = $sp.getWidget('my-custom-widget');"
    refs = extract_references(script, "sp_widget", "script")

    match = [r for r in refs if r["target_identifier"] == "my-custom-widget"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "sp_widget"


def test_parse_sys_id_reference():
    """Detect 32-char hex sys_id patterns."""
    from src.engines.code_reference_parser import extract_references

    script = """
    var sysId = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6';
    gr.get(sysId);
    """
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["reference_type"] == "sys_id_reference"]
    assert len(match) == 1
    assert match[0]["target_identifier"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def test_parse_client_g_form():
    """Detect g_form.setValue('field') and g_form.setMandatory('field') patterns."""
    from src.engines.code_reference_parser import extract_references

    script = """
    g_form.setValue('state', '6');
    g_form.setMandatory('u_custom_field', true);
    """
    refs = extract_references(script, "sys_script_client", "script")

    field_refs = [r for r in refs if r["reference_type"] == "field_reference"]
    field_names = {r["target_identifier"] for r in field_refs}
    assert "state" in field_names
    assert "u_custom_field" in field_names


def test_parse_multiple_references_in_one_script():
    """A real-world script should produce multiple references."""
    from src.engines.code_reference_parser import extract_references

    script = """
    var helper = new ApprovalHelper();
    var gr = new GlideRecord('sc_req_item');
    gr.addQuery('sys_id', current.sys_id);
    gr.query();
    if (gr.next()) {
        gs.eventQueue('custom.ritm.approved', gr, gs.getUserID(), '');
    }
    """
    refs = extract_references(script, "sys_script", "script")

    types = {r["reference_type"] for r in refs}
    assert "script_include" in types
    assert "table_query" in types
    assert "event" in types
    assert len(refs) >= 3


def test_extract_references_returns_line_numbers():
    """Each reference should include a line number."""
    from src.engines.code_reference_parser import extract_references

    script = "line1\nvar gr = new GlideRecord('incident');\nline3"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "incident"]
    assert len(match) == 1
    assert match[0]["line_number"] == 2
```

**Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_code_reference_parser.py -v`

Expected: FAIL — `ImportError: cannot import name 'extract_references'`

**Step 3: Implement extract_references**

Replace `src/engines/code_reference_parser.py` with:

```python
"""Engine 1: Code Reference Parser.

Parses script/code fields in artifact detail tables to find cross-references
to other artifacts (script includes, tables, events, etc.).

Input: Artifact detail tables with code_fields
Output: Rows in code_reference table
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from sqlmodel import Session, text

from ..models import CodeReference, ScanResult

# ---------------------------------------------------------------------------
# Regex patterns — each tuple is (compiled_regex, reference_type, group_index)
# group_index is which capture group holds the target identifier
# ---------------------------------------------------------------------------

_PATTERNS: List[Tuple[re.Pattern, str, int]] = [
    # Script include instantiation: new ClassName(...)
    # Exclude built-in SN classes (GlideRecord, GlideAjax, etc.)
    (re.compile(
        r'\bnew\s+(?!Glide(?:Record|Ajax|DateTime|Aggregate|Duration|Schedule|Element|'
        r'Filter|Session|System|Transaction|URI|Sys|Evaluation|App(?:Navigation)?|'
        r'PluginManager|UpdateManager2?|Workflow|DBFunctionBuilder)|'
        r'sn_\w+\.)([A-Z]\w{2,})\s*\('
    ), "script_include", 1),

    # GlideRecord / GlideAggregate table query
    (re.compile(
        r'\bnew\s+Glide(?:Record|Aggregate)\s*\(\s*[\'"]([a-z_][a-z0-9_]*)[\'"]'
    ), "table_query", 1),

    # gs.include('name')
    (re.compile(
        r'\bgs\.include\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "script_include", 1),

    # gs.eventQueue('event_name', ...)
    (re.compile(
        r'\bgs\.eventQueue\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "event", 1),

    # GlideAjax('ScriptIncludeName')
    (re.compile(
        r'\bnew\s+GlideAjax\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "script_include", 1),

    # sn_ws.RESTMessageV2('name', ...) or new RESTMessageV2('name')
    (re.compile(
        r'\b(?:sn_ws\.)?RESTMessageV2\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "rest_message", 1),

    # workflow.start('name') / workflow.startFlow('name')
    (re.compile(
        r'\bworkflow\.start(?:Flow)?\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "workflow", 1),

    # $sp.getWidget('widget-id')
    (re.compile(
        r'\$sp\.getWidget\s*\(\s*[\'"]([^"\']+)[\'"]'
    ), "sp_widget", 1),

    # Sys ID references (32-char lowercase hex) — standalone strings only
    (re.compile(
        r"""(?:['"])([0-9a-f]{32})(?:['"])"""
    ), "sys_id_reference", 1),

    # g_form / g_list client-side field references
    (re.compile(
        r'\bg_(?:form|list)\.\w+\s*\(\s*[\'"]([a-z_]\w*)[\'"]'
    ), "field_reference", 1),

    # current.field_name (server-side field access on current record)
    (re.compile(
        r'\bcurrent\.([a-z_]\w*)\b(?!\s*\()'
    ), "field_reference", 1),
]

# Fields to ignore as field_reference (too generic / built-in GlideRecord methods)
_IGNORE_FIELDS = frozenset({
    "sys_id", "sys_created_on", "sys_updated_on", "sys_created_by",
    "sys_updated_by", "sys_mod_count", "sys_class_name", "sys_domain",
    "update", "insert", "deleteRecord", "next", "get", "initialize",
    "isNewRecord", "isValid", "isValidRecord", "setWorkflow", "autoSysFields",
    "setLimit", "getRowCount", "getUniqueValue", "getDisplayValue",
    "getTableName", "nil", "changes", "changesFrom", "changesTo",
    "operation", "isActionAborted", "setAbortAction", "addQuery", "query",
    "orderBy", "orderByDesc", "hasNext", "getValue", "setValue",
    "getElement", "getED", "getLabel", "getRecordClassName",
    "canRead", "canWrite", "canCreate", "canDelete",
})


def extract_references(
    script: str,
    source_table: str,
    source_field: str,
) -> List[Dict[str, Any]]:
    """Extract cross-references from a script string.

    Args:
        script: The script/code content to parse.
        source_table: The SN table this script belongs to (e.g., "sys_script").
        source_field: The field name containing the script (e.g., "script").

    Returns:
        List of dicts, each with keys:
            reference_type, target_identifier, line_number, code_snippet, confidence
    """
    if not script or not script.strip():
        return []

    results: List[Dict[str, Any]] = []
    lines = script.split("\n")
    seen: set = set()  # Deduplicate (type, target) within one script

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip comment-only lines
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue

        for pattern, ref_type, group_idx in _PATTERNS:
            for match in pattern.finditer(line):
                target = match.group(group_idx)

                # Filter out noise
                if ref_type == "field_reference" and target in _IGNORE_FIELDS:
                    continue
                if ref_type == "table_query" and target in ("true", "false", "null"):
                    continue

                dedup_key = (ref_type, target)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Build snippet: the matched line, trimmed
                snippet = stripped[:200] if len(stripped) > 200 else stripped

                results.append({
                    "reference_type": ref_type,
                    "target_identifier": target,
                    "line_number": line_idx,
                    "code_snippet": snippet,
                    "confidence": 1.0,
                })

    return results


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the code reference parser engine for an assessment.

    Returns summary dict with counts of references found.
    """
    raise NotImplementedError("Full engine run not yet implemented — see Task 11")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_code_reference_parser.py -v`

Expected: ALL PASS (12 tests)

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/engines/code_reference_parser.py tests/test_code_reference_parser.py
git commit -m "feat: implement extract_references regex patterns for code reference parser"
```

---

## Task 11: Implement Code Reference Parser — Full Engine Run

**Files:**
- Modify: `src/engines/code_reference_parser.py` (implement `run()`)
- Test: `tests/test_code_reference_parser.py`

The `run()` function queries artifact detail tables for code fields, calls `extract_references` on each, and writes `CodeReference` rows.

**Step 1: Write the failing test**

Append to `tests/test_code_reference_parser.py`:

```python
from sqlmodel import SQLModel, Session, create_engine, text
from src.models import (
    Instance, Assessment, Scan, ScanResult, CodeReference,
    ScanStatus, AssessmentState, AssessmentType,
)


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def seeded_assessment(db_session, db_engine):
    """Seed an assessment with 2 scan results + a fake artifact detail table."""
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id, name="Test", number="ASMT0001",
        assessment_type=AssessmentType.global_app, state=AssessmentState.pending,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(assessment_id=asmt.id, name="test scan", status=ScanStatus.completed)
    db_session.add(scan)
    db_session.flush()

    sr_br = ScanResult(
        scan_id=scan.id, sys_id="aaa111", table_name="sys_script",
        name="BR - Approval Check",
    )
    sr_si = ScanResult(
        scan_id=scan.id, sys_id="bbb222", table_name="sys_script_include",
        name="ApprovalHelper",
    )
    db_session.add_all([sr_br, sr_si])
    db_session.flush()

    # Create a minimal artifact detail table to simulate real data
    with db_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asmt_business_rule (
                id INTEGER PRIMARY KEY,
                scan_result_id INTEGER,
                sn_sys_id TEXT,
                name TEXT,
                script TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO asmt_business_rule (scan_result_id, sn_sys_id, name, script)
            VALUES (:sr_id, :sys_id, :name, :script)
        """), {
            "sr_id": sr_br.id,
            "sys_id": "aaa111",
            "name": "BR - Approval Check",
            "script": "var helper = new ApprovalHelper();\nvar gr = new GlideRecord('sc_req_item');\ngr.query();",
        })
        conn.commit()

    return asmt, sr_br, sr_si


def test_engine_run_populates_code_references(db_session, seeded_assessment):
    """Full engine run should create CodeReference rows from artifact detail scripts."""
    from src.engines.code_reference_parser import run

    asmt, sr_br, sr_si = seeded_assessment

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["references_created"] >= 2  # ApprovalHelper + sc_req_item

    # Check DB
    refs = db_session.exec(
        CodeReference.__table__.select().where(CodeReference.assessment_id == asmt.id)
    ).fetchall() if hasattr(CodeReference, '__table__') else []

    # Alternative: use sqlmodel select
    from sqlmodel import select
    refs = db_session.exec(
        select(CodeReference).where(CodeReference.assessment_id == asmt.id)
    ).all()

    assert len(refs) >= 2
    ref_types = {r.reference_type for r in refs}
    assert "script_include" in ref_types
    assert "table_query" in ref_types


def test_engine_run_resolves_target_scan_result(db_session, seeded_assessment):
    """Engine should resolve target_identifier to target_scan_result_id when possible."""
    from src.engines.code_reference_parser import run
    from sqlmodel import select

    asmt, sr_br, sr_si = seeded_assessment

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == asmt.id,
            CodeReference.reference_type == "script_include",
            CodeReference.target_identifier == "ApprovalHelper",
        )
    ).all()

    assert len(refs) == 1
    # Should resolve to sr_si because sr_si.name == "ApprovalHelper"
    assert refs[0].target_scan_result_id == sr_si.id
```

**Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_code_reference_parser.py::test_engine_run_populates_code_references -v`

Expected: FAIL — `NotImplementedError: Full engine run not yet implemented`

**Step 3: Implement the `run()` function**

In `src/engines/code_reference_parser.py`, replace the `run()` function:

```python
def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the code reference parser engine for an assessment.

    1. Find all scan results for this assessment
    2. For each scan result with a matching artifact detail table that has code_fields,
       extract references from those code fields
    3. Write CodeReference rows
    4. Run resolution pass to link target_identifier to existing ScanResults

    Returns summary dict.
    """
    from ..artifact_detail_defs import ARTIFACT_DETAIL_DEFS
    from sqlmodel import select

    # Step 1: Get all scan results for this assessment (via scans)
    scan_results = session.exec(
        select(ScanResult)
        .join(ScanResult.scan)
        .where(ScanResult.scan.has(assessment_id=assessment_id))
    ).all()

    if not scan_results:
        return {"success": True, "references_created": 0, "message": "No scan results found"}

    # Build lookup: table_name -> [code_fields]
    table_code_fields: Dict[str, List[str]] = {}
    table_local_name: Dict[str, str] = {}
    for sn_table, defn in ARTIFACT_DETAIL_DEFS.items():
        code_fields = defn.get("code_fields", [])
        if code_fields:
            table_code_fields[sn_table] = code_fields
            table_local_name[sn_table] = defn["local_table"]

    # Step 2: Group scan results by table_name
    sr_by_table: Dict[str, List[ScanResult]] = {}
    sr_by_id: Dict[int, ScanResult] = {}
    for sr in scan_results:
        sr_by_table.setdefault(sr.table_name, []).append(sr)
        sr_by_id[sr.id] = sr

    # Build name-based lookup for resolution
    sr_by_name: Dict[str, List[ScanResult]] = {}
    for sr in scan_results:
        sr_by_name.setdefault(sr.name, []).append(sr)

    references_created = 0
    tables_processed = 0
    errors: List[str] = []

    # Step 3: For each table type with code fields, query the detail table
    for sn_table, code_fields in table_code_fields.items():
        if sn_table not in sr_by_table:
            continue

        local_table = table_local_name[sn_table]

        # Check if detail table exists
        try:
            check = session.exec(
                text(f"SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
                params={"tbl": local_table},
            ).first()
        except Exception:
            check = None

        if not check:
            continue

        tables_processed += 1

        # Build column list for query
        cols = ", ".join(["scan_result_id"] + code_fields)
        try:
            rows = session.exec(
                text(f"SELECT {cols} FROM {local_table} WHERE scan_result_id IS NOT NULL")
            ).fetchall()
        except Exception as e:
            errors.append(f"Error reading {local_table}: {e}")
            continue

        for row in rows:
            sr_id = row[0]
            sr = sr_by_id.get(sr_id)
            if not sr:
                continue

            for field_idx, field_name in enumerate(code_fields, start=1):
                script_content = row[field_idx]
                if not script_content or not isinstance(script_content, str):
                    continue

                refs = extract_references(script_content, sn_table, field_name)
                for ref_data in refs:
                    cr = CodeReference(
                        assessment_id=assessment_id,
                        source_scan_result_id=sr.id,
                        source_table=sn_table,
                        source_field=field_name,
                        source_name=sr.name,
                        reference_type=ref_data["reference_type"],
                        target_identifier=ref_data["target_identifier"],
                        line_number=ref_data.get("line_number"),
                        code_snippet=ref_data.get("code_snippet"),
                        confidence=ref_data.get("confidence", 1.0),
                    )
                    session.add(cr)
                    references_created += 1

    session.flush()

    # Step 4: Resolution pass — link target_identifier to existing ScanResults
    resolved_count = 0
    unresolved_refs = session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == assessment_id,
            CodeReference.target_scan_result_id == None,  # noqa: E711
        )
    ).all()

    for cr in unresolved_refs:
        target_sr = _resolve_target(cr, sr_by_name, sr_by_table)
        if target_sr:
            cr.target_scan_result_id = target_sr.id
            session.add(cr)
            resolved_count += 1

    session.commit()

    return {
        "success": True,
        "references_created": references_created,
        "resolved_count": resolved_count,
        "tables_processed": tables_processed,
        "errors": errors,
    }


def _resolve_target(
    cr: "CodeReference",
    sr_by_name: Dict[str, List["ScanResult"]],
    sr_by_table: Dict[str, List["ScanResult"]],
) -> Optional["ScanResult"]:
    """Try to resolve a CodeReference's target_identifier to a ScanResult.

    Resolution strategies by reference_type:
    - script_include: Match by name (api_name / name)
    - table_query: Match by table_name on ScanResult (meta_target_table)
    - Others: Match by name as fallback
    """
    target = cr.target_identifier

    if cr.reference_type == "script_include":
        # Direct name match against sys_script_include results
        candidates = sr_by_name.get(target, [])
        for c in candidates:
            if c.table_name == "sys_script_include":
                return c
        # Fallback: any table with matching name
        if candidates:
            return candidates[0]

    elif cr.reference_type == "table_query":
        # Match scan results whose meta_target_table == target
        # This is less useful for direct resolution, skip for now
        pass

    else:
        # Generic name match
        candidates = sr_by_name.get(target, [])
        if candidates:
            return candidates[0]

    return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_code_reference_parser.py -v`

Expected: ALL PASS (14 tests)

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/engines/code_reference_parser.py tests/test_code_reference_parser.py
git commit -m "feat: implement full code reference parser engine with resolution"
```

---

## Task 12: Implement Structural Mapper Engine

**Files:**
- Modify: `src/engines/structural_mapper.py`
- Create: `tests/test_structural_mapper.py`

The structural mapper finds parent/child relationships between artifacts using known reference field patterns.

**Step 1: Write the failing test**

Create `tests/test_structural_mapper.py`:

```python
"""Tests for the Structural Mapper engine."""

import pytest
from sqlmodel import SQLModel, Session, create_engine, select, text
from src.models import (
    Instance, Assessment, Scan, ScanResult, StructuralRelationship,
    ScanStatus, AssessmentState, AssessmentType,
)


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def seeded_data(db_session, db_engine):
    """Seed assessment + scan results + fake artifact detail tables with parent/child data."""
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id, name="Test", number="ASMT0001",
        assessment_type=AssessmentType.global_app, state=AssessmentState.pending,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(assessment_id=asmt.id, name="test scan", status=ScanStatus.completed)
    db_session.add(scan)
    db_session.flush()

    # Parent: a UI Policy
    sr_policy = ScanResult(
        scan_id=scan.id, sys_id="pol_aaa111", table_name="sys_ui_policy",
        name="Make Priority Mandatory",
    )
    # Child: a UI Policy Action
    sr_action = ScanResult(
        scan_id=scan.id, sys_id="act_bbb222", table_name="sys_ui_policy_action",
        name="Set Priority Mandatory",
    )
    # Parent: a table definition
    sr_table = ScanResult(
        scan_id=scan.id, sys_id="tbl_ccc333", table_name="sys_db_object",
        name="incident", meta_target_table="incident",
    )
    # Child: a dictionary entry for that table
    sr_dict = ScanResult(
        scan_id=scan.id, sys_id="dict_ddd444", table_name="sys_dictionary",
        name="incident.u_custom_field", meta_target_table="incident",
    )
    db_session.add_all([sr_policy, sr_action, sr_table, sr_dict])
    db_session.flush()

    # Create fake artifact detail tables with reference fields
    with db_engine.connect() as conn:
        # UI Policy Actions have a ui_policy reference field
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asmt_ui_policy_action (
                id INTEGER PRIMARY KEY,
                scan_result_id INTEGER,
                sn_sys_id TEXT,
                name TEXT,
                ui_policy TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO asmt_ui_policy_action (scan_result_id, sn_sys_id, name, ui_policy)
            VALUES (:sr_id, :sys_id, :name, :ui_policy)
        """), {
            "sr_id": sr_action.id,
            "sys_id": "act_bbb222",
            "name": "Set Priority Mandatory",
            "ui_policy": "pol_aaa111",  # References parent by sys_id
        })

        # Dictionary entries have a name field = "table_name.element_name"
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asmt_dictionary (
                id INTEGER PRIMARY KEY,
                scan_result_id INTEGER,
                sn_sys_id TEXT,
                name TEXT,
                element TEXT,
                collection_name TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO asmt_dictionary (scan_result_id, sn_sys_id, name, element, collection_name)
            VALUES (:sr_id, :sys_id, :name, :element, :collection)
        """), {
            "sr_id": sr_dict.id,
            "sys_id": "dict_ddd444",
            "name": "incident.u_custom_field",
            "element": "u_custom_field",
            "collection": "incident",
        })
        conn.commit()

    return asmt, sr_policy, sr_action, sr_table, sr_dict


def test_structural_mapper_finds_ui_policy_action(db_session, seeded_data):
    """Should find UI Policy → UI Policy Action relationship."""
    from src.engines.structural_mapper import run

    asmt, sr_policy, sr_action, sr_table, sr_dict = seeded_data
    result = run(asmt.id, db_session)

    assert result["success"] is True

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "ui_policy_action",
        )
    ).all()

    assert len(rels) >= 1
    rel = rels[0]
    assert rel.parent_scan_result_id == sr_policy.id
    assert rel.child_scan_result_id == sr_action.id


def test_structural_mapper_returns_summary(db_session, seeded_data):
    """Engine run should return a summary with counts."""
    from src.engines.structural_mapper import run

    asmt, *_ = seeded_data
    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert "relationships_created" in result
    assert result["relationships_created"] >= 1
```

**Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_structural_mapper.py -v`

Expected: FAIL — `NotImplementedError: Engine not yet implemented`

**Step 3: Implement the structural mapper**

Replace `src/engines/structural_mapper.py` with:

```python
"""Engine 4: Structural Relationship Mapper.

Maps parent/child relationships between artifacts using known reference
field patterns (e.g., UI Policy → UI Policy Actions).

Input: Artifact detail tables
Output: Rows in structural_relationship table
"""

from typing import Any, Dict, List, Optional, Tuple
from sqlmodel import Session, select, text

from ..models import ScanResult, StructuralRelationship

# ---------------------------------------------------------------------------
# Known relationship mappings
# Each tuple: (child_sn_table, child_local_table, ref_field, parent_sn_table, relationship_type)
# ref_field: column in child detail table that holds parent sys_id or name
# ---------------------------------------------------------------------------

_RELATIONSHIP_MAPPINGS: List[Dict[str, str]] = [
    {
        "child_sn_table": "sys_ui_policy_action",
        "child_local_table": "asmt_ui_policy_action",
        "ref_field": "ui_policy",
        "ref_type": "sys_id",        # References parent by sys_id
        "parent_sn_table": "sys_ui_policy",
        "relationship_type": "ui_policy_action",
    },
    {
        "child_sn_table": "sys_dictionary",
        "child_local_table": "asmt_dictionary",
        "ref_field": "collection_name",
        "ref_type": "table_name",     # References parent table by name
        "parent_sn_table": "sys_db_object",
        "relationship_type": "dictionary_entry",
    },
    {
        "child_sn_table": "sys_dictionary_override",
        "child_local_table": "asmt_dictionary_override",
        "ref_field": "collection_name",
        "ref_type": "table_name",
        "parent_sn_table": "sys_dictionary",
        "relationship_type": "dictionary_override",
    },
]


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the structural mapper engine for an assessment.

    1. Get all scan results for this assessment
    2. For each known relationship mapping, query child detail tables
    3. Match reference fields to parent scan results
    4. Write StructuralRelationship rows

    Returns summary dict.
    """
    # Get all scan results for this assessment
    scan_results = session.exec(
        select(ScanResult)
        .join(ScanResult.scan)
        .where(ScanResult.scan.has(assessment_id=assessment_id))
    ).all()

    if not scan_results:
        return {"success": True, "relationships_created": 0, "message": "No scan results"}

    # Build lookups
    sr_by_sys_id: Dict[str, ScanResult] = {}
    sr_by_id: Dict[int, ScanResult] = {}
    sr_by_table_and_name: Dict[Tuple[str, str], ScanResult] = {}
    sr_by_meta_target: Dict[str, List[ScanResult]] = {}

    for sr in scan_results:
        sr_by_sys_id[sr.sys_id] = sr
        sr_by_id[sr.id] = sr
        sr_by_table_and_name[(sr.table_name, sr.name)] = sr
        if sr.meta_target_table:
            sr_by_meta_target.setdefault(sr.meta_target_table, []).append(sr)

    relationships_created = 0
    mappings_processed = 0
    errors: List[str] = []

    for mapping in _RELATIONSHIP_MAPPINGS:
        child_local = mapping["child_local_table"]
        ref_field = mapping["ref_field"]
        ref_type = mapping["ref_type"]
        parent_sn_table = mapping["parent_sn_table"]
        rel_type = mapping["relationship_type"]

        # Check if child detail table exists
        try:
            check = session.exec(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
                params={"tbl": child_local},
            ).first()
        except Exception:
            check = None

        if not check:
            continue

        mappings_processed += 1

        # Query child records with their reference field
        try:
            rows = session.exec(
                text(f"SELECT scan_result_id, {ref_field} FROM {child_local} WHERE scan_result_id IS NOT NULL AND {ref_field} IS NOT NULL")
            ).fetchall()
        except Exception as e:
            errors.append(f"Error reading {child_local}: {e}")
            continue

        for row in rows:
            child_sr_id = row[0]
            ref_value = row[1]

            if not ref_value or not child_sr_id:
                continue

            child_sr = sr_by_id.get(child_sr_id)
            if not child_sr:
                continue

            # Resolve parent
            parent_sr = _resolve_parent(
                ref_value, ref_type, parent_sn_table,
                sr_by_sys_id, sr_by_table_and_name, sr_by_meta_target,
            )

            if parent_sr and parent_sr.id != child_sr.id:
                rel = StructuralRelationship(
                    assessment_id=assessment_id,
                    parent_scan_result_id=parent_sr.id,
                    child_scan_result_id=child_sr.id,
                    relationship_type=rel_type,
                    parent_field=ref_field,
                    confidence=1.0,
                )
                session.add(rel)
                relationships_created += 1

    session.commit()

    return {
        "success": True,
        "relationships_created": relationships_created,
        "mappings_processed": mappings_processed,
        "errors": errors,
    }


def _resolve_parent(
    ref_value: str,
    ref_type: str,
    parent_sn_table: str,
    sr_by_sys_id: Dict[str, "ScanResult"],
    sr_by_table_and_name: Dict[Tuple[str, str], "ScanResult"],
    sr_by_meta_target: Dict[str, List["ScanResult"]],
) -> Optional["ScanResult"]:
    """Resolve a reference field value to a parent ScanResult."""

    if ref_type == "sys_id":
        # Direct sys_id lookup
        return sr_by_sys_id.get(ref_value)

    elif ref_type == "table_name":
        # Match by meta_target_table on parent scan results
        candidates = sr_by_meta_target.get(ref_value, [])
        for c in candidates:
            if c.table_name == parent_sn_table:
                return c
        # Fallback: match by name
        return sr_by_table_and_name.get((parent_sn_table, ref_value))

    elif ref_type == "name":
        return sr_by_table_and_name.get((parent_sn_table, ref_value))

    return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_structural_mapper.py -v`

Expected: ALL PASS (2 tests)

**Step 5: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/engines/structural_mapper.py tests/test_structural_mapper.py
git commit -m "feat: implement structural mapper engine for parent/child relationships"
```

---

## Task 13: Create MCP Tool — run_preprocessing_engines

**Files:**
- Create: `src/mcp/tools/pipeline/run_engines.py`
- Modify: `src/mcp/registry.py:180-185` (register new tool)
- Test: `tests/test_run_engines_tool.py`

**Step 1: Write the failing test**

Create `tests/test_run_engines_tool.py`:

```python
"""Tests for the run_preprocessing_engines MCP tool."""

import pytest
from sqlmodel import SQLModel, Session, create_engine, text
from src.models import (
    Instance, Assessment, Scan, ScanResult, CodeReference, StructuralRelationship,
    ScanStatus, AssessmentState, AssessmentType,
)


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def seeded(db_session, db_engine):
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id, name="Test", number="ASMT0001",
        assessment_type=AssessmentType.global_app, state=AssessmentState.pending,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(assessment_id=asmt.id, name="test scan", status=ScanStatus.completed)
    db_session.add(scan)
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id, sys_id="aaa111", table_name="sys_script",
        name="BR Test",
    )
    db_session.add(sr)
    db_session.flush()

    # Create minimal artifact detail table
    with db_engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS asmt_business_rule (
                id INTEGER PRIMARY KEY, scan_result_id INTEGER,
                sn_sys_id TEXT, name TEXT, script TEXT
            )
        """))
        conn.execute(text("""
            INSERT INTO asmt_business_rule (scan_result_id, sn_sys_id, name, script)
            VALUES (:sr_id, 'aaa111', 'BR Test', 'var gr = new GlideRecord(''incident'');')
        """), {"sr_id": sr.id})
        conn.commit()

    return asmt


def test_run_engines_tool_executes(db_session, seeded):
    from src.mcp.tools.pipeline.run_engines import handle

    result = handle({"assessment_id": seeded.id}, db_session)

    assert result["success"] is True
    assert "engines_run" in result
    assert len(result["engines_run"]) >= 1


def test_run_engines_tool_spec_exists():
    from src.mcp.tools.pipeline.run_engines import TOOL_SPEC
    assert TOOL_SPEC.name == "run_preprocessing_engines"
    assert TOOL_SPEC.permission == "write"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_run_engines_tool.py -v`

Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement the tool**

Create `src/mcp/tools/pipeline/run_engines.py`:

```python
"""MCP tool: run_preprocessing_engines — orchestrate pre-processing engines.

Runs deterministic pre-processing engines for an assessment.
Must be called BEFORE AI analysis passes.
"""

from typing import Any, Dict, List
from sqlmodel import Session

from ...registry import ToolSpec


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to run engines for.",
        },
        "engines": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional list of engine names to run. "
                "Default: all available engines. "
                "Options: code_reference_parser, structural_mapper"
            ),
        },
    },
    "required": ["assessment_id"],
}

# Available engines in execution order
_ENGINE_REGISTRY = {
    "structural_mapper": "src.engines.structural_mapper",
    "code_reference_parser": "src.engines.code_reference_parser",
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    requested = params.get("engines")

    if requested:
        engine_names = [e for e in requested if e in _ENGINE_REGISTRY]
    else:
        engine_names = list(_ENGINE_REGISTRY.keys())

    engines_run: List[Dict[str, Any]] = []
    errors: List[str] = []

    for name in engine_names:
        module_path = _ENGINE_REGISTRY[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            result = mod.run(assessment_id, session)
            engines_run.append({"engine": name, **result})
        except Exception as e:
            errors.append(f"{name}: {e}")
            engines_run.append({"engine": name, "success": False, "error": str(e)})

    return {
        "success": len(errors) == 0,
        "assessment_id": assessment_id,
        "engines_run": engines_run,
        "errors": errors,
    }


TOOL_SPEC = ToolSpec(
    name="run_preprocessing_engines",
    description=(
        "Run pre-processing engines for an assessment. "
        "Populates code_reference and structural_relationship tables. "
        "Must be run BEFORE AI analysis passes."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

**Step 4: Register the tool in registry.py**

In `src/mcp/registry.py`, add after line 185 (after feature_grouping registration):

```python
    from .tools.pipeline.run_engines import TOOL_SPEC as run_engines_tool
    registry.register(run_engines_tool)
```

**Step 5: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/test_run_engines_tool.py -v`

Expected: ALL PASS (2 tests)

**Step 6: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add src/mcp/tools/pipeline/run_engines.py src/mcp/registry.py tests/test_run_engines_tool.py
git commit -m "feat: add run_preprocessing_engines MCP tool"
```

---

## Task 14: Run Full Test Suite

**Step 1: Run all existing tests to check for regressions**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub && python -m pytest tests/ -v --tb=short 2>&1 | head -80`

Expected: ALL PASS — no regressions from the new models/fields

**Step 2: If any failures, fix them before proceeding**

Common failure modes:
- If existing tests import all models and the new ones cause issues → check for circular imports
- If `_ensure_model_table_columns` fails → verify table names match `__tablename__` exactly

**Step 3: Final commit if any fixes were needed**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
git add -A
git commit -m "fix: resolve any regressions from reasoning layer data model"
```

---

## Summary of Deliverables

After completing all 14 tasks, the codebase will have:

| Component | Status |
|-----------|--------|
| `GroupingSignalType` enum | NEW |
| `CodeReference` table | NEW |
| `UpdateSetOverlap` table | NEW |
| `TemporalCluster` table | NEW |
| `StructuralRelationship` table | NEW |
| Feature confidence/signals fields | ADDED |
| ScanResult AI pass tracking fields | ADDED |
| `src/engines/` package | NEW |
| Code Reference Parser engine (regex + run) | IMPLEMENTED |
| Structural Mapper engine | IMPLEMENTED |
| `run_preprocessing_engines` MCP tool | NEW |
| 4 test files with ~25+ tests | NEW |

**What comes next (Phase 2 remainder):**
- Update Set Analyzer engine
- Temporal Clusterer engine
- Naming Analyzer engine
- Table Co-location engine
- Engine Orchestrator (runs all engines)

**Then Phase 3:**
- Rewrite `feature_grouping.py` with 4-phase clustering algorithm
