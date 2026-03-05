# Reasoning Layer Phase 2: Remaining Pre-Processing Engines

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the 4 remaining deterministic pre-processing engines (Update Set Analyzer, Temporal Clusterer, Naming Analyzer, Table Co-location) and wire them into the existing engine orchestrator. These engines populate reasoning tables that the AI consumes during grouping/observation passes.

**Architecture:** Each engine follows the established pattern from Phase 1 (`code_reference_parser`, `structural_mapper`): a `run(assessment_id, session)` function that reads ingested data, deletes prior results for idempotency, writes to reasoning tables, and returns a summary dict. All engines live in `src/engines/`. The MCP tool `run_preprocessing_engines` already has a registry-based dispatch — we just add entries.

**Tech Stack:** Python 3.9, SQLModel, SQLAlchemy, SQLite, pytest

**Reference docs:**
- Parent plan: `docs/plans/SN_TA_Reasoning_Layer_Implementation_Plan.md`
- Phase 1 plan: `docs/plans/2026-03-04-reasoning-layer-phase1-data-model.md`
- Grouping signals: `servicenow_global_tech_assessment_mcp/02_working/01_notes/grouping_signals.md`
- Existing engines: `src/engines/code_reference_parser.py`, `src/engines/structural_mapper.py`

**Established patterns to follow:**
- Engine signature: `def run(assessment_id: int, session: Session) -> Dict[str, Any]`
- Idempotency: delete existing rows for the assessment before writing
- Lookup: load ScanResults via `ScanResult → Scan → Assessment` join
- Instance ID: get from `assessment.instance_id`
- Commit: engine calls `session.commit()` at end
- Return dict: `{"success": bool, ..., "errors": [...]}`

---

## Addendum (Approved 2026-03-04): Artifact-Centric Update Set Reasoning

This addendum is REQUIRED and extends Task 0 + Task 1 so Engine 2 mirrors the real analyst workflow:
- Start from customized artifacts.
- Evaluate update set coherence with artifact context.
- Use version history + update set sequence/family signals.
- Keep all links explainable/auditable.

### Addendum A1: New Link Table (`update_set_artifact_link`)

Add a new model in `src/models.py` and migration registration in `src/database.py`:

```python
class UpdateSetArtifactLink(SQLModel, table=True):
    __tablename__ = "update_set_artifact_link"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "scan_result_id", "update_set_id", "link_source",
            name="uq_us_artifact_link_scope"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    update_set_id: int = Field(foreign_key="update_set.id", index=True)

    link_source: str                 # scan_result_current | customer_update_xml | version_history
    is_current: bool = False
    confidence: float = 1.0
    evidence_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

Tests to add in `tests/test_reasoning_data_model.py`:
- `test_update_set_artifact_link_table_exists`
- `test_update_set_artifact_link_round_trip`
- `test_update_set_artifact_link_unique_constraint`

### Addendum A2: Explainability Fields on `update_set_overlap`

Extend `UpdateSetOverlap` with explainability payload (in addition to `signal_type`):

```python
evidence_json: Optional[str] = None   # why these sets are linked
```

Expected JSON examples:
- shared artifacts with names/tables
- matched ticket tokens / family tokens
- vh chain metadata (`source_table`, `source_sys_id`, sequence markers)
- default update set inclusion flags when applicable

Tests:
- assert `evidence_json` exists and is populated for each produced overlap row.

### Addendum A3: Config-Driven Engine Thresholds (No hardcoded tuning)

Per workspace engineering rules, thresholds must be properties (not constants).
Before implementing Engine 2/3/5/6, add properties in `src/services/integration_properties.py` and surface them in UI:

- `reasoning.us.min_shared_records`
- `reasoning.us.name_similarity_min_tokens`
- `reasoning.us.include_default_sets` (bool)
- `reasoning.us.default_signal_weight`
- `reasoning.temporal.gap_threshold_minutes`
- `reasoning.temporal.min_cluster_size`
- `reasoning.naming.min_cluster_size`
- `reasoning.naming.min_prefix_tokens`

Engine code must read these via the existing AppConfig/property pattern.

### Addendum A4: Two-Pass Update Set Analyzer (`base` + `enriched`)

Task 1 must run in two modes:

1. `base` mode:
- deterministic linking only (CUX, VH, names, sequence),
- used when observations are absent.

2. `enriched` mode:
- adds coherence scoring using artifact context:
  - `ScanResult.ai_summary`
  - `ScanResult.ai_observations`
  - `CodeReference` density
  - `StructuralRelationship` density
  - table/developer concentration
- used after simple observations pass.

`run()` signature update:
```python
def run(assessment_id: int, session: Session, mode: str = "base") -> Dict[str, Any]:
```

### Addendum A5: Default Update Set Policy (downgrade, don’t discard)

Do NOT fully exclude Default update set relationships.
Instead:
- include them with lower confidence / weight,
- mark in evidence (`"includes_default": true`),
- emit dedicated signal when appropriate (`signal_type="default_sequence"` or content with downgraded score).

### Addendum A6: Sequence/Family Signal Expansion

Beyond ticket regex, add deterministic family/sequence signals:
- temporal adjacency (`completed_on` / `sys_created_on` windows),
- same-author contiguous commits,
- shared normalized name stem families.

Emit as overlap rows with signal types:
- `name_similarity`
- `temporal_sequence`
- `author_sequence`
- `version_history`
- `content`

### Addendum A7: Test Scenarios Required for Task 1

In `tests/test_update_set_analyzer.py`, add explicit scenarios:
- clean coherent update set bundle,
- noisy/mixed update set bundle,
- feature spread across sequential update sets,
- default update set + non-default bridging,
- enriched mode coherence scoring with pre-populated `ai_summary/ai_observations`,
- explainability payload present and non-empty,
- idempotent rerun equality.

---

## Task 0: Data Model Additions

Three small additions needed before engines can persist their output.

**Files:**
- Modify: `src/models.py`
- Modify: `src/database.py` (migration registration)
- Test: `tests/test_reasoning_data_model.py`

### Step 1: Write failing tests for new models

Append to `tests/test_reasoning_data_model.py`:

```python
def test_update_set_overlap_has_signal_type(db_session):
    """UpdateSetOverlap.signal_type field exists and defaults to 'version_history'."""
    from src.models import UpdateSetOverlap
    assert hasattr(UpdateSetOverlap, "signal_type")


def test_naming_cluster_table_exists(db_session, db_engine):
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db_engine)
    tables = inspector.get_table_names()
    assert "naming_cluster" in tables


def test_naming_cluster_round_trip(db_session):
    from src.models import NamingCluster, Instance, Assessment, AssessmentState, AssessmentType

    inst = Instance(name="test", url="https://test.service-now.com", username="admin", password_encrypted="x")
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(instance_id=inst.id, name="Test", number="ASMT0001",
                      assessment_type=AssessmentType.global_app, state=AssessmentState.pending)
    db_session.add(asmt)
    db_session.flush()

    nc = NamingCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        cluster_token="Custom_Approval",
        token_type="prefix",
        member_count=3,
        member_ids_json="[1,2,3]",
        confidence=0.9,
    )
    db_session.add(nc)
    db_session.commit()

    from sqlmodel import select
    result = db_session.exec(select(NamingCluster).where(NamingCluster.assessment_id == asmt.id)).first()
    assert result is not None
    assert result.cluster_token == "Custom_Approval"
    assert result.member_count == 3


def test_table_colocation_summary_table_exists(db_session, db_engine):
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(db_engine)
    tables = inspector.get_table_names()
    assert "table_colocation_summary" in tables


def test_table_colocation_summary_round_trip(db_session):
    from src.models import TableColocationSummary, Instance, Assessment, AssessmentState, AssessmentType

    inst = Instance(name="test", url="https://test.service-now.com", username="admin", password_encrypted="x")
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(instance_id=inst.id, name="Test", number="ASMT0001",
                      assessment_type=AssessmentType.global_app, state=AssessmentState.pending)
    db_session.add(asmt)
    db_session.flush()

    tcs = TableColocationSummary(
        instance_id=inst.id,
        assessment_id=asmt.id,
        target_table="incident",
        artifact_count=5,
        artifact_ids_json="[10,11,12,13,14]",
    )
    db_session.add(tcs)
    db_session.commit()

    from sqlmodel import select
    result = db_session.exec(select(TableColocationSummary).where(TableColocationSummary.assessment_id == asmt.id)).first()
    assert result is not None
    assert result.target_table == "incident"
    assert result.artifact_count == 5
```

### Step 2: Run tests to verify they fail

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
python -m pytest tests/test_reasoning_data_model.py -v -k "signal_type or naming_cluster or table_colocation_summary"
```

Expected: FAIL (models/tables don't exist yet)

### Step 3: Add models to `src/models.py`

**3a.** Add `signal_type` field to `UpdateSetOverlap` class (after `overlap_score` line, around line 730):

```python
    signal_type: str = "version_history"  # "version_history", "content", "name_similarity"
```

**3b.** Add `NamingCluster` model (after `TemporalClusterMember` class, before `UpdateSet` class — around line 800):

```python
class NamingCluster(SQLModel, table=True):
    """Cluster of artifacts sharing a naming convention (prefix/suffix)."""
    __tablename__ = "naming_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    cluster_token: str          # The shared prefix or suffix string
    token_type: str             # "prefix" or "suffix"
    member_count: int
    member_ids_json: str        # JSON list of scan_result_ids
    confidence: float = 1.0     # Higher for longer/more specific tokens

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**3c.** Add `TableColocationSummary` model (immediately after `NamingCluster`):

```python
class TableColocationSummary(SQLModel, table=True):
    """Pre-computed summary of artifacts grouped by target table."""
    __tablename__ = "table_colocation_summary"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    target_table: str           # The SN table name (e.g., "incident")
    artifact_count: int
    artifact_ids_json: str      # JSON list of scan_result_ids

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**3d.** Add new models to imports/exports at top of `models.py` and register in `src/database.py`:

In `database.py`, add `NamingCluster`, `TableColocationSummary` to the `_ensure_model_table_columns` function, same pattern as existing reasoning tables. Also add `ALTER TABLE update_set_overlap ADD COLUMN signal_type TEXT DEFAULT 'version_history'` migration.

### Step 4: Run tests to verify they pass

```bash
python -m pytest tests/test_reasoning_data_model.py -v -k "signal_type or naming_cluster or table_colocation_summary"
```

Expected: PASS

### Step 5: Run full suite to check for regressions

```bash
python -m pytest --tb=short -q
```

Expected: All existing tests pass + new tests pass.

### Step 6: Commit

```bash
git add src/models.py src/database.py tests/test_reasoning_data_model.py
git commit -m "feat: add NamingCluster, TableColocationSummary tables + signal_type on UpdateSetOverlap"
```

---

## Task 1: Update Set Analyzer Engine

**Priority:** HIGH — strongest deterministic grouping signal.
**Input:** `ScanResult`, `UpdateSet`, `CustomerUpdateXML`, `VersionHistory` tables
**Output:** Rows in `update_set_overlap` table (3 signal types)

The analyzer runs 3 connected sub-tasks:
1. **Content mapping** — for each UpdateSet, find which ScanResults have CustomerUpdateXML records in it. Then compute pairwise overlap between USes that share scan results.
2. **Name clustering** — parse US names for shared identifiers (TASK/STRY/INC/CHG numbers, common prefixes). Store pairwise relationships with `signal_type="name_similarity"`.
3. **Version history cross-referencing** — for each ScanResult, trace VersionHistory to find all USes it was part of historically. Compute pairwise overlap via VH. Store with `signal_type="version_history"`.

**Files:**
- Create: `src/engines/update_set_analyzer.py`
- Test: `tests/test_update_set_analyzer.py`

### Step 1: Write failing tests

Create `tests/test_update_set_analyzer.py`:

```python
"""Tests for the Update Set Analyzer engine."""

import json
from datetime import datetime

from sqlmodel import select
from sqlalchemy import text

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CustomerUpdateXML,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    UpdateSet,
    UpdateSetOverlap,
    VersionHistory,
)


def _setup_base(db_session):
    """Create instance + assessment + scan for tests."""
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

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="test scan", status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    return inst, asmt, scan


def test_content_overlap_detected(db_session):
    """Two USes share a scan result via CUX records → overlap detected."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us_a = UpdateSet(instance_id=inst.id, sn_sys_id="us_a_001", name="US Alpha")
    us_b = UpdateSet(instance_id=inst.id, sn_sys_id="us_b_002", name="US Beta")
    db_session.add_all([us_a, us_b])
    db_session.flush()

    # Shared artifact: SR-1 has CUX records in BOTH update sets
    sr1 = ScanResult(
        scan_id=scan.id, sys_id="sr1_sysid", table_name="sys_script",
        name="BR - Shared Rule", sys_update_name="sys_script_shared",
    )
    # Unique artifact: SR-2 only in US-A
    sr2 = ScanResult(
        scan_id=scan.id, sys_id="sr2_sysid", table_name="sys_script_include",
        name="SI - Only Alpha", sys_update_name="sys_script_include_alpha",
    )
    db_session.add_all([sr1, sr2])
    db_session.flush()

    # CUX: sr1 appears in both USes, sr2 only in US-A
    cux1 = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux1", name="sys_script_shared",
        update_set_id=us_a.id, target_sys_id="sr1_sysid",
    )
    cux2 = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux2", name="sys_script_shared",
        update_set_id=us_b.id, target_sys_id="sr1_sysid",
    )
    cux3 = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux3", name="sys_script_include_alpha",
        update_set_id=us_a.id, target_sys_id="sr2_sysid",
    )
    db_session.add_all([cux1, cux2, cux3])
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    overlaps = list(db_session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == asmt.id,
            UpdateSetOverlap.signal_type == "content",
        )
    ).all())
    assert len(overlaps) >= 1

    overlap = overlaps[0]
    us_ids = {overlap.update_set_a_id, overlap.update_set_b_id}
    assert us_ids == {us_a.id, us_b.id}
    assert overlap.shared_record_count >= 1


def test_name_similarity_detected(db_session):
    """USes with shared TASK/story numbers in names → name_similarity overlap."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us1", name="STRY0012345 - Login Form")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us2", name="STRY0012345 - Login Validation")
    us3 = UpdateSet(instance_id=inst.id, sn_sys_id="us3", name="STRY9999999 - Unrelated Work")
    db_session.add_all([us1, us2, us3])
    db_session.flush()

    # Need at least one scan result for the engine to run
    sr = ScanResult(
        scan_id=scan.id, sys_id="sr_sysid", table_name="sys_script",
        name="Some BR", sys_update_name="sys_script_some",
    )
    db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    name_overlaps = list(db_session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == asmt.id,
            UpdateSetOverlap.signal_type == "name_similarity",
        )
    ).all())

    # us1 and us2 share "STRY0012345" → should be linked
    matched_pairs = set()
    for o in name_overlaps:
        matched_pairs.add(frozenset([o.update_set_a_id, o.update_set_b_id]))
    assert frozenset([us1.id, us2.id]) in matched_pairs

    # us3 should NOT be linked to us1 or us2
    assert frozenset([us1.id, us3.id]) not in matched_pairs
    assert frozenset([us2.id, us3.id]) not in matched_pairs


def test_version_history_cross_reference(db_session):
    """Scan result VH shows it was in a different US historically → overlap detected."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us_current = UpdateSet(instance_id=inst.id, sn_sys_id="us_current_001", name="US Current")
    us_historical = UpdateSet(instance_id=inst.id, sn_sys_id="us_hist_002", name="US Historical")
    db_session.add_all([us_current, us_historical])
    db_session.flush()

    sr1 = ScanResult(
        scan_id=scan.id, sys_id="sr1_sysid", table_name="sys_script",
        name="BR - Migrated Rule", sys_update_name="sys_script_migrated",
        update_set_id=us_current.id,
    )
    db_session.add(sr1)
    db_session.flush()

    # CUX: sr1 is currently in us_current
    cux = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux1", name="sys_script_migrated",
        update_set_id=us_current.id, target_sys_id="sr1_sysid",
    )
    db_session.add(cux)

    # VH: sr1 was PREVIOUSLY in us_historical
    vh = VersionHistory(
        instance_id=inst.id, sn_sys_id="vh1",
        sys_update_name="sys_script_migrated",
        name="sys_script_migrated",
        state="previous",
        source_table="sys_update_set",
        source_sys_id="us_hist_002",  # matches us_historical.sn_sys_id
    )
    db_session.add(vh)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    vh_overlaps = list(db_session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == asmt.id,
            UpdateSetOverlap.signal_type == "version_history",
        )
    ).all())

    # us_current and us_historical should be linked via sr1's VH
    assert len(vh_overlaps) >= 1
    overlap = vh_overlaps[0]
    us_ids = {overlap.update_set_a_id, overlap.update_set_b_id}
    assert us_ids == {us_current.id, us_historical.id}


def test_default_update_set_excluded_from_content(db_session):
    """Records in the Default update set are excluded from content overlap."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us_default = UpdateSet(instance_id=inst.id, sn_sys_id="us_def", name="Default", is_default=True)
    us_normal = UpdateSet(instance_id=inst.id, sn_sys_id="us_norm", name="Normal US")
    db_session.add_all([us_default, us_normal])
    db_session.flush()

    sr1 = ScanResult(
        scan_id=scan.id, sys_id="sr1_sysid", table_name="sys_script",
        name="BR - In Default", sys_update_name="sys_script_default",
    )
    db_session.add(sr1)
    db_session.flush()

    # CUX: sr1 in both Default and Normal
    cux1 = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux1", name="sys_script_default",
        update_set_id=us_default.id, target_sys_id="sr1_sysid",
    )
    cux2 = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux2", name="sys_script_default",
        update_set_id=us_normal.id, target_sys_id="sr1_sysid",
    )
    db_session.add_all([cux1, cux2])
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    content_overlaps = list(db_session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == asmt.id,
            UpdateSetOverlap.signal_type == "content",
        )
    ).all())

    # Default US should be excluded from content overlap
    for o in content_overlaps:
        assert o.update_set_a_id != us_default.id
        assert o.update_set_b_id != us_default.id


def test_idempotent_rerun(db_session):
    """Running the engine twice produces the same results."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us = UpdateSet(instance_id=inst.id, sn_sys_id="us1", name="US One")
    db_session.add(us)
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id, sys_id="sr_sysid", table_name="sys_script",
        name="BR - Test", sys_update_name="sys_script_test",
    )
    db_session.add(sr)
    db_session.flush()

    cux = CustomerUpdateXML(
        instance_id=inst.id, sn_sys_id="cux1", name="sys_script_test",
        update_set_id=us.id, target_sys_id="sr_sysid",
    )
    db_session.add(cux)
    db_session.commit()

    result1 = run(asmt.id, db_session)
    count1 = len(list(db_session.exec(
        select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == asmt.id)
    ).all()))

    result2 = run(asmt.id, db_session)
    count2 = len(list(db_session.exec(
        select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == asmt.id)
    ).all()))

    assert count1 == count2


def test_no_scan_results_returns_success(db_session):
    """Engine returns success with empty results when no scan results exist."""
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["content_overlaps"] == 0
    assert result["name_overlaps"] == 0
    assert result["vh_overlaps"] == 0
```

### Step 2: Run tests to verify they fail

```bash
python -m pytest tests/test_update_set_analyzer.py -v
```

Expected: FAIL (module doesn't exist yet)

### Step 3: Implement `src/engines/update_set_analyzer.py`

```python
"""Engine 2: Update Set Analyzer.

Analyzes update set relationships to find grouping signals:
1. Content mapping — which scan results share update sets via CUX records
2. Name clustering — update sets with similar names (shared TASK/STRY/INC numbers)
3. Version history cross-referencing — scan results linked through historical USes

Input: ScanResult, UpdateSet, CustomerUpdateXML, VersionHistory tables
Output: Rows in update_set_overlap table (with signal_type discriminator)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from itertools import combinations
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    Assessment,
    CustomerUpdateXML,
    Scan,
    ScanResult,
    UpdateSet,
    UpdateSetOverlap,
    VersionHistory,
)


# Regex patterns for extracting identifiers from update set names.
# Matches common ServiceNow naming conventions: TASK0012345, STRY0012345,
# INC0012345, CHG0012345, RITM0012345, PRB0012345, REQ0012345, etc.
_TICKET_PATTERN = re.compile(
    r"\b((?:TASK|STRY|INC|CHG|RITM|PRB|REQ|SCTASK|CTASK|KB|DFCT|DMND|ENHC)"
    r"\d{5,10})\b",
    re.IGNORECASE,
)

# Minimum number of shared records to create a content overlap entry.
_MIN_SHARED_RECORDS = 1

# Minimum name similarity: at least one shared ticket identifier.
_MIN_SHARED_TOKENS = 1


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the update set analyzer engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "content_overlaps": 0,
            "name_overlaps": 0,
            "vh_overlaps": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    # Load scan results for this assessment.
    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "content_overlaps": 0,
            "name_overlaps": 0,
            "vh_overlaps": 0,
            "update_sets_analyzed": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # Idempotent: delete prior results for this assessment.
    existing = list(
        session.exec(
            select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == assessment_id)
        ).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # Build lookup structures.
    sr_by_sys_id: Dict[str, ScanResult] = {sr.sys_id: sr for sr in scan_results}
    sr_by_update_name: Dict[str, ScanResult] = {}
    for sr in scan_results:
        if sr.sys_update_name:
            sr_by_update_name[sr.sys_update_name] = sr

    sr_sys_ids: Set[str] = set(sr_by_sys_id.keys())

    # Load update sets for the instance.
    update_sets = list(
        session.exec(select(UpdateSet).where(UpdateSet.instance_id == instance_id)).all()
    )
    us_by_id: Dict[int, UpdateSet] = {us.id: us for us in update_sets if us.id is not None}
    us_by_sn_sys_id: Dict[str, UpdateSet] = {us.sn_sys_id: us for us in update_sets}
    default_us_ids: Set[int] = {us.id for us in update_sets if us.is_default and us.id is not None}

    # Load CUX records for the instance.
    cux_records = list(
        session.exec(
            select(CustomerUpdateXML).where(CustomerUpdateXML.instance_id == instance_id)
        ).all()
    )

    errors: List[str] = []

    # ---- Sub-task 1: Content mapping via CUX ----
    content_overlaps = _compute_content_overlaps(
        cux_records, sr_sys_ids, sr_by_update_name, us_by_id,
        default_us_ids, instance_id, assessment_id, session,
    )

    # ---- Sub-task 2: US name clustering ----
    name_overlaps = _compute_name_overlaps(
        update_sets, default_us_ids, instance_id, assessment_id, session,
    )

    # ---- Sub-task 3: Version history cross-referencing ----
    vh_overlaps = _compute_vh_overlaps(
        scan_results, sr_by_update_name, us_by_sn_sys_id, us_by_id,
        default_us_ids, instance_id, assessment_id, session,
    )

    session.commit()

    return {
        "success": True,
        "content_overlaps": content_overlaps,
        "name_overlaps": name_overlaps,
        "vh_overlaps": vh_overlaps,
        "update_sets_analyzed": len(update_sets),
        "errors": errors,
    }


def _compute_content_overlaps(
    cux_records: List[CustomerUpdateXML],
    sr_sys_ids: Set[str],
    sr_by_update_name: Dict[str, ScanResult],
    us_by_id: Dict[int, UpdateSet],
    default_us_ids: Set[int],
    instance_id: int,
    assessment_id: int,
    session: Session,
) -> int:
    """Sub-task 1: Find US pairs that share scan result artifacts via CUX records.

    For each CUX record, link it to a scan result by target_sys_id or by
    sys_update_name (name field). Then build a mapping: US → set of scan_result_ids.
    Compute pairwise overlap for US pairs sharing scan results.
    Excludes the Default update set.
    """
    # Map: update_set_id → set of scan_result_ids (via CUX linkage)
    us_to_sr_ids: Dict[int, Set[int]] = defaultdict(set)

    for cux in cux_records:
        if cux.update_set_id is None or cux.update_set_id in default_us_ids:
            continue

        # Try to link CUX to a scan result.
        sr: Optional[ScanResult] = None
        if cux.target_sys_id and cux.target_sys_id in sr_sys_ids:
            from ..models import ScanResult as SR
            # Use the sr_sys_ids set for existence check, but we need the SR object
            # for its id. Build a more targeted lookup:
            pass

        # Link by target_sys_id first, then by name (sys_update_name).
        matched_sr_id: Optional[int] = None
        if cux.target_sys_id:
            for sid, sr_obj in ((s.sys_id, s) for s in sr_by_update_name.values()):
                pass
            # Simpler: iterate sr_sys_ids is a set of strings
            # We need a dict for id lookup — let's use a different approach.
            pass

        # Cleaner approach: pass sr_by_sys_id instead.
        # (This will be fixed in final implementation — see below)
        if cux.target_sys_id and cux.target_sys_id in sr_sys_ids:
            # We need sr.id, so we use the sr_by_update_name which has ScanResult objects.
            # But keyed by update_name, not sys_id. Let me accept sr_by_sys_id as param.
            pass

        # Link via name (sys_update_name) match.
        sr_match = sr_by_update_name.get(cux.name)
        if sr_match and sr_match.id is not None:
            us_to_sr_ids[cux.update_set_id].add(sr_match.id)

    # Compute pairwise overlap.
    count = 0
    us_ids_with_srs = [uid for uid, srs in us_to_sr_ids.items() if len(srs) > 0]
    for us_a_id, us_b_id in combinations(sorted(us_ids_with_srs), 2):
        shared = us_to_sr_ids[us_a_id] & us_to_sr_ids[us_b_id]
        if len(shared) < _MIN_SHARED_RECORDS:
            continue

        min_count = min(len(us_to_sr_ids[us_a_id]), len(us_to_sr_ids[us_b_id]))
        score = len(shared) / min_count if min_count > 0 else 0.0

        shared_details = [{"scan_result_id": sid} for sid in sorted(shared)]

        session.add(UpdateSetOverlap(
            instance_id=instance_id,
            assessment_id=assessment_id,
            update_set_a_id=us_a_id,
            update_set_b_id=us_b_id,
            shared_record_count=len(shared),
            shared_records_json=json.dumps(shared_details),
            overlap_score=round(score, 4),
            signal_type="content",
        ))
        count += 1

    session.flush()
    return count


def _compute_name_overlaps(
    update_sets: List[UpdateSet],
    default_us_ids: Set[int],
    instance_id: int,
    assessment_id: int,
    session: Session,
) -> int:
    """Sub-task 2: Find US pairs whose names share ticket identifiers.

    Extracts TASK/STRY/INC/CHG/etc. numbers from US names and links
    USes that reference the same ticket.
    """
    # Map: ticket_number → list of US ids
    ticket_to_us_ids: Dict[str, List[int]] = defaultdict(list)

    for us in update_sets:
        if us.id is None or us.id in default_us_ids:
            continue
        tickets = _TICKET_PATTERN.findall(us.name)
        for ticket in tickets:
            ticket_to_us_ids[ticket.upper()].append(us.id)

    count = 0
    seen_pairs: Set[Tuple[int, int]] = set()

    for ticket, us_ids in ticket_to_us_ids.items():
        if len(us_ids) < 2:
            continue
        for us_a_id, us_b_id in combinations(sorted(set(us_ids)), 2):
            pair = (us_a_id, us_b_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            session.add(UpdateSetOverlap(
                instance_id=instance_id,
                assessment_id=assessment_id,
                update_set_a_id=us_a_id,
                update_set_b_id=us_b_id,
                shared_record_count=0,
                shared_records_json=json.dumps({"matched_tickets": [ticket]}),
                overlap_score=0.8,  # High confidence for shared ticket numbers
                signal_type="name_similarity",
            ))
            count += 1

    session.flush()
    return count


def _compute_vh_overlaps(
    scan_results: List[ScanResult],
    sr_by_update_name: Dict[str, ScanResult],
    us_by_sn_sys_id: Dict[str, UpdateSet],
    us_by_id: Dict[int, UpdateSet],
    default_us_ids: Set[int],
    instance_id: int,
    assessment_id: int,
    session: Session,
) -> int:
    """Sub-task 3: Find US pairs linked through version history.

    For each scan result, find all VersionHistory records (by sys_update_name).
    Each VH record with source_table='sys_update_set' tells us the artifact
    was in that update set at some point. Build a mapping: US → set of scan_result_ids
    (via VH) and compute pairwise overlap.
    """
    # Collect all sys_update_names from scan results.
    update_names = [sr.sys_update_name for sr in scan_results if sr.sys_update_name]
    if not update_names:
        return 0

    # Query VH records for our scan results that came from update sets.
    vh_records = list(
        session.exec(
            select(VersionHistory).where(
                VersionHistory.instance_id == instance_id,
                VersionHistory.sys_update_name.in_(update_names),
                VersionHistory.source_table == "sys_update_set",
            )
        ).all()
    )

    if not vh_records:
        return 0

    # Map: US id → set of scan_result_ids (via VH)
    us_to_sr_ids: Dict[int, Set[int]] = defaultdict(set)

    for vh in vh_records:
        if not vh.source_sys_id:
            continue
        us = us_by_sn_sys_id.get(vh.source_sys_id)
        if not us or us.id is None or us.id in default_us_ids:
            continue

        sr = sr_by_update_name.get(vh.sys_update_name)
        if sr and sr.id is not None:
            us_to_sr_ids[us.id].add(sr.id)

    # Also include current US assignments for complete overlap picture.
    for sr in scan_results:
        if sr.update_set_id and sr.update_set_id not in default_us_ids and sr.id is not None:
            us_to_sr_ids[sr.update_set_id].add(sr.id)

    # Compute pairwise overlap.
    count = 0
    us_ids_with_srs = [uid for uid, srs in us_to_sr_ids.items() if len(srs) > 0]
    for us_a_id, us_b_id in combinations(sorted(us_ids_with_srs), 2):
        shared = us_to_sr_ids[us_a_id] & us_to_sr_ids[us_b_id]
        if len(shared) < _MIN_SHARED_RECORDS:
            continue

        min_count = min(len(us_to_sr_ids[us_a_id]), len(us_to_sr_ids[us_b_id]))
        score = len(shared) / min_count if min_count > 0 else 0.0

        shared_details = [{"scan_result_id": sid} for sid in sorted(shared)]

        session.add(UpdateSetOverlap(
            instance_id=instance_id,
            assessment_id=assessment_id,
            update_set_a_id=us_a_id,
            update_set_b_id=us_b_id,
            shared_record_count=len(shared),
            shared_records_json=json.dumps(shared_details),
            overlap_score=round(score, 4),
            signal_type="version_history",
        ))
        count += 1

    session.flush()
    return count
```

**IMPORTANT implementation note for Codex:** The `_compute_content_overlaps` function above has a known issue in the CUX→ScanResult linking logic. The function needs `sr_by_sys_id` (keyed by sys_id) passed as a parameter to properly resolve `cux.target_sys_id`. Fix the function signature to accept `sr_by_sys_id: Dict[str, ScanResult]` and use it:

```python
# In _compute_content_overlaps, replace the CUX→SR linking block with:
matched_sr_id: Optional[int] = None

# Try target_sys_id first (direct sys_id match).
if cux.target_sys_id and cux.target_sys_id in sr_by_sys_id:
    sr_match = sr_by_sys_id[cux.target_sys_id]
    if sr_match.id is not None:
        matched_sr_id = sr_match.id

# Fallback: match by name (sys_update_name).
if matched_sr_id is None:
    sr_match = sr_by_update_name.get(cux.name)
    if sr_match and sr_match.id is not None:
        matched_sr_id = sr_match.id

if matched_sr_id is not None:
    us_to_sr_ids[cux.update_set_id].add(matched_sr_id)
```

And update the `run()` function call to pass `sr_by_sys_id`:

```python
content_overlaps = _compute_content_overlaps(
    cux_records, sr_by_sys_id, sr_by_update_name, us_by_id,
    default_us_ids, instance_id, assessment_id, session,
)
```

### Step 4: Run tests to verify they pass

```bash
python -m pytest tests/test_update_set_analyzer.py -v
```

Expected: All PASS

### Step 5: Run full suite

```bash
python -m pytest --tb=short -q
```

Expected: All pass, no regressions.

### Step 6: Commit

```bash
git add src/engines/update_set_analyzer.py tests/test_update_set_analyzer.py
git commit -m "feat: add Update Set Analyzer engine (content mapping, name clustering, VH cross-ref)"
```

---

## Task 2: Temporal Clusterer Engine

**Priority:** MEDIUM — useful grouping signal, also covers Default US clustering naturally.
**Input:** All `ScanResult` records with timestamp/author fields
**Output:** Rows in `temporal_cluster` + `temporal_cluster_member` tables

**Algorithm:**
1. Load all customized scan results with `sys_updated_on` and `sys_updated_by`
2. Partition by developer (`sys_updated_by`)
3. Within each developer, sort by `sys_updated_on`
4. Sliding window: if gap > threshold → new cluster
5. Write `TemporalCluster` rows + `TemporalClusterMember` junction rows

**Files:**
- Create: `src/engines/temporal_clusterer.py`
- Test: `tests/test_temporal_clusterer.py`

### Step 1: Write failing tests

Create `tests/test_temporal_clusterer.py`:

```python
"""Tests for the Temporal Clusterer engine."""

import json
from datetime import datetime, timedelta

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    TemporalCluster,
    TemporalClusterMember,
)


def _setup_base(db_session):
    """Create instance + assessment + scan for tests."""
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

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="test scan", status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    return inst, asmt, scan


def test_basic_cluster_formed(db_session):
    """Records by same developer within gap threshold → one cluster."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)

    base_time = datetime(2025, 6, 15, 10, 0, 0)
    for i in range(4):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_{i}", table_name="sys_script",
            name=f"BR - Rule {i}", sys_update_name=f"sys_script_{i}",
            sys_updated_on=base_time + timedelta(minutes=5 * i),
            sys_updated_by="john.smith",
        )
        db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["clusters_created"] >= 1

    clusters = list(db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all())
    assert len(clusters) == 1
    assert clusters[0].developer == "john.smith"
    assert clusters[0].record_count == 4

    # Check junction table members.
    members = list(db_session.exec(
        select(TemporalClusterMember).where(
            TemporalClusterMember.temporal_cluster_id == clusters[0].id
        )
    ).all())
    assert len(members) == 4


def test_gap_splits_clusters(db_session):
    """Records with gap > threshold → separate clusters."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)

    base_time = datetime(2025, 6, 15, 10, 0, 0)
    # Cluster 1: 3 records within 10 minutes
    for i in range(3):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_a{i}", table_name="sys_script",
            name=f"BR - Early {i}", sys_update_name=f"sys_script_a{i}",
            sys_updated_on=base_time + timedelta(minutes=5 * i),
            sys_updated_by="jane.doe",
        )
        db_session.add(sr)

    # Cluster 2: 2 records 2 hours later (well beyond 30-min gap)
    for i in range(2):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_b{i}", table_name="sys_script",
            name=f"BR - Late {i}", sys_update_name=f"sys_script_b{i}",
            sys_updated_on=base_time + timedelta(hours=2, minutes=5 * i),
            sys_updated_by="jane.doe",
        )
        db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    clusters = list(db_session.exec(
        select(TemporalCluster).where(
            TemporalCluster.assessment_id == asmt.id,
            TemporalCluster.developer == "jane.doe",
        )
    ).all())
    assert len(clusters) == 2
    counts = sorted([c.record_count for c in clusters])
    assert counts == [2, 3]


def test_different_developers_separate_clusters(db_session):
    """Records by different developers at same time → separate clusters."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)

    base_time = datetime(2025, 6, 15, 10, 0, 0)
    for i in range(3):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_dev1_{i}", table_name="sys_script",
            name=f"BR - Dev1 {i}", sys_update_name=f"sys_script_d1_{i}",
            sys_updated_on=base_time + timedelta(minutes=5 * i),
            sys_updated_by="dev1",
        )
        db_session.add(sr)

    for i in range(2):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_dev2_{i}", table_name="sys_script",
            name=f"BR - Dev2 {i}", sys_update_name=f"sys_script_d2_{i}",
            sys_updated_on=base_time + timedelta(minutes=5 * i),
            sys_updated_by="dev2",
        )
        db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    clusters = list(db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all())
    developers = {c.developer for c in clusters}
    assert "dev1" in developers
    assert "dev2" in developers


def test_single_record_no_cluster(db_session):
    """A single record by a developer doesn't form a cluster (min_cluster_size=2)."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)

    sr = ScanResult(
        scan_id=scan.id, sys_id="sr_solo", table_name="sys_script",
        name="BR - Loner", sys_update_name="sys_script_solo",
        sys_updated_on=datetime(2025, 6, 15, 10, 0, 0),
        sys_updated_by="solo.dev",
    )
    db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["clusters_created"] == 0


def test_idempotent_rerun(db_session):
    """Running twice produces same cluster count."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)

    base_time = datetime(2025, 6, 15, 10, 0, 0)
    for i in range(3):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_{i}", table_name="sys_script",
            name=f"BR - Rule {i}", sys_update_name=f"sys_script_{i}",
            sys_updated_on=base_time + timedelta(minutes=5 * i),
            sys_updated_by="john.smith",
        )
        db_session.add(sr)
    db_session.commit()

    run(asmt.id, db_session)
    count1 = len(list(db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()))

    run(asmt.id, db_session)
    count2 = len(list(db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()))

    assert count1 == count2
```

### Step 2: Run tests to verify they fail

```bash
python -m pytest tests/test_temporal_clusterer.py -v
```

### Step 3: Implement `src/engines/temporal_clusterer.py`

```python
"""Engine 3: Temporal Clusterer.

Groups scan results into developer activity windows based on timestamp
proximity. Same developer + tight time gap = likely related work.

Input: ScanResult records with sys_updated_on + sys_updated_by
Output: Rows in temporal_cluster + temporal_cluster_member tables
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from sqlmodel import Session, select

from ..models import (
    Assessment,
    Scan,
    ScanResult,
    TemporalCluster,
    TemporalClusterMember,
)


# Configurable parameters.
_GAP_THRESHOLD_MINUTES = 30
_MIN_CLUSTER_SIZE = 2


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the temporal clusterer engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "clusters_created": 0,
            "members_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "clusters_created": 0,
            "members_created": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # Idempotent: delete prior results.
    existing_members = list(
        session.exec(
            select(TemporalClusterMember).where(TemporalClusterMember.assessment_id == assessment_id)
        ).all()
    )
    for row in existing_members:
        session.delete(row)
    session.flush()

    existing_clusters = list(
        session.exec(
            select(TemporalCluster).where(TemporalCluster.assessment_id == assessment_id)
        ).all()
    )
    for row in existing_clusters:
        session.delete(row)
    session.flush()

    # Partition by developer, keeping only records with timestamps.
    dev_records: Dict[str, List[ScanResult]] = defaultdict(list)
    for sr in scan_results:
        developer = sr.sys_updated_by or sr.sys_created_by
        timestamp = sr.sys_updated_on or sr.sys_created_on
        if developer and timestamp:
            dev_records[developer].append(sr)

    clusters_created = 0
    members_created = 0
    errors: List[str] = []

    for developer, records in dev_records.items():
        # Sort by timestamp.
        records.sort(key=lambda r: r.sys_updated_on or r.sys_created_on or datetime.min)

        # Sliding window clustering.
        current_cluster: List[ScanResult] = [records[0]]

        for i in range(1, len(records)):
            prev_time = records[i - 1].sys_updated_on or records[i - 1].sys_created_on
            curr_time = records[i].sys_updated_on or records[i].sys_created_on

            if prev_time and curr_time:
                gap_minutes = (curr_time - prev_time).total_seconds() / 60.0
            else:
                gap_minutes = float("inf")

            if gap_minutes <= _GAP_THRESHOLD_MINUTES:
                current_cluster.append(records[i])
            else:
                # Emit cluster if big enough.
                if len(current_cluster) >= _MIN_CLUSTER_SIZE:
                    c, m = _write_cluster(
                        current_cluster, developer, instance_id, assessment_id, session,
                    )
                    clusters_created += c
                    members_created += m
                current_cluster = [records[i]]

        # Don't forget the last cluster.
        if len(current_cluster) >= _MIN_CLUSTER_SIZE:
            c, m = _write_cluster(
                current_cluster, developer, instance_id, assessment_id, session,
            )
            clusters_created += c
            members_created += m

    session.commit()

    return {
        "success": True,
        "clusters_created": clusters_created,
        "members_created": members_created,
        "developers_analyzed": len(dev_records),
        "errors": errors,
    }


def _write_cluster(
    records: List[ScanResult],
    developer: str,
    instance_id: int,
    assessment_id: int,
    session: Session,
) -> tuple:
    """Write a TemporalCluster and its junction members. Returns (clusters, members) counts."""
    timestamps = []
    for r in records:
        t = r.sys_updated_on or r.sys_created_on
        if t:
            timestamps.append(t)

    if not timestamps:
        return 0, 0

    timestamps.sort()
    cluster_start = timestamps[0]
    cluster_end = timestamps[-1]

    # Compute average gap between consecutive timestamps.
    gaps = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
        gaps.append(gap)
    avg_gap = sum(gaps) / len(gaps) if gaps else 0.0

    record_ids = [r.id for r in records if r.id is not None]
    tables = list({r.table_name for r in records})

    cluster = TemporalCluster(
        instance_id=instance_id,
        assessment_id=assessment_id,
        developer=developer,
        cluster_start=cluster_start,
        cluster_end=cluster_end,
        record_count=len(records),
        record_ids_json=json.dumps(record_ids),
        avg_gap_minutes=round(avg_gap, 2),
        tables_involved_json=json.dumps(tables),
    )
    session.add(cluster)
    session.flush()

    members = 0
    for sr in records:
        if sr.id is not None and cluster.id is not None:
            session.add(TemporalClusterMember(
                instance_id=instance_id,
                assessment_id=assessment_id,
                temporal_cluster_id=cluster.id,
                scan_result_id=sr.id,
            ))
            members += 1

    session.flush()
    return 1, members
```

### Step 4: Run tests

```bash
python -m pytest tests/test_temporal_clusterer.py -v
```

### Step 5: Run full suite

```bash
python -m pytest --tb=short -q
```

### Step 6: Commit

```bash
git add src/engines/temporal_clusterer.py tests/test_temporal_clusterer.py
git commit -m "feat: add Temporal Clusterer engine (developer activity windows)"
```

---

## Task 3: Naming Analyzer Engine

**Priority:** MEDIUM — strong when developers follow naming conventions.
**Input:** All `ScanResult` records (name field)
**Output:** Rows in `naming_cluster` table

**Algorithm:**
1. Tokenize all artifact names (split on `_`, `-`, spaces, camelCase boundaries)
2. Build n-gram prefix frequency map
3. Cluster records sharing significant prefixes (appears in 3+ records, length 2+ tokens)
4. Filter generic prefixes (single common tokens like "BR", "CS", "SI")
5. Score by prefix specificity (longer prefix = higher confidence)

**Files:**
- Create: `src/engines/naming_analyzer.py`
- Test: `tests/test_naming_analyzer.py`

### Step 1: Write failing tests

Create `tests/test_naming_analyzer.py`:

```python
"""Tests for the Naming Analyzer engine."""

import json

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    NamingCluster,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


def _setup_base(db_session):
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

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="test scan", status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    return inst, asmt, scan


def test_prefix_cluster_formed(db_session):
    """Artifacts sharing a meaningful prefix → cluster formed."""
    from src.engines.naming_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    names = [
        "Custom_Approval_Business_Rule",
        "Custom_Approval_Client_Script",
        "Custom_Approval_UI_Policy",
        "Custom_Approval_Script_Include",
        "Unrelated_Widget",
    ]
    for i, name in enumerate(names):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_{i}", table_name="sys_script",
            name=name, sys_update_name=f"sys_script_{i}",
        )
        db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["clusters_created"] >= 1

    clusters = list(db_session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == asmt.id)
    ).all())

    # Should find a cluster for "Custom_Approval" with 4 members
    approval_clusters = [c for c in clusters if "custom" in c.cluster_token.lower() and "approval" in c.cluster_token.lower()]
    assert len(approval_clusters) >= 1
    assert approval_clusters[0].member_count >= 4


def test_generic_prefix_filtered(db_session):
    """Single-token generic prefixes like 'BR' are not clustered."""
    from src.engines.naming_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    names = [
        "BR - Something",
        "BR - Other Thing",
        "BR - Third Thing",
    ]
    for i, name in enumerate(names):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_{i}", table_name="sys_script",
            name=name, sys_update_name=f"sys_script_{i}",
        )
        db_session.add(sr)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    # "BR" alone should not form a cluster (too generic)
    clusters = list(db_session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == asmt.id)
    ).all())
    generic = [c for c in clusters if c.cluster_token.strip().upper() == "BR"]
    assert len(generic) == 0


def test_no_scan_results_returns_success(db_session):
    from src.engines.naming_analyzer import run

    inst, asmt, scan = _setup_base(db_session)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["clusters_created"] == 0


def test_idempotent_rerun(db_session):
    from src.engines.naming_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    for i in range(3):
        sr = ScanResult(
            scan_id=scan.id, sys_id=f"sr_{i}", table_name="sys_script",
            name=f"Shared_Prefix_Item_{i}", sys_update_name=f"sys_script_{i}",
        )
        db_session.add(sr)
    db_session.commit()

    run(asmt.id, db_session)
    count1 = len(list(db_session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == asmt.id)
    ).all()))

    run(asmt.id, db_session)
    count2 = len(list(db_session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == asmt.id)
    ).all()))

    assert count1 == count2
```

### Step 2: Run tests to verify they fail

```bash
python -m pytest tests/test_naming_analyzer.py -v
```

### Step 3: Implement `src/engines/naming_analyzer.py`

```python
"""Engine 5: Naming Analyzer.

Clusters scan result artifacts by shared naming conventions (prefixes/suffixes).
Strong when developers follow consistent naming — e.g., all artifacts for a
feature share a "Custom_Approval_" prefix.

Input: ScanResult records (name field)
Output: Rows in naming_cluster table
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    Assessment,
    NamingCluster,
    Scan,
    ScanResult,
)


# Minimum number of artifacts sharing a prefix to form a cluster.
_MIN_CLUSTER_SIZE = 3

# Minimum number of tokens in a prefix to be considered meaningful.
_MIN_PREFIX_TOKENS = 2

# Generic single tokens to ignore (common artifact type abbreviations).
_GENERIC_TOKENS = frozenset({
    "br", "cs", "si", "ui", "cl", "sys", "sp", "wf", "acl", "fix",
    "new", "old", "test", "temp", "tmp", "copy", "v1", "v2", "v3",
})


def _tokenize(name: str) -> List[str]:
    """Split a name into normalized tokens.

    Handles: underscores, hyphens, spaces, camelCase, dots.
    """
    # Insert separator before uppercase letters in camelCase.
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Split on common separators.
    tokens = re.split(r"[\s_\-./]+", name)
    # Normalize: lowercase, filter empty and very short tokens.
    return [t.lower() for t in tokens if len(t) >= 2]


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the naming analyzer engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "clusters_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "clusters_created": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # Idempotent: delete prior results.
    existing = list(
        session.exec(
            select(NamingCluster).where(NamingCluster.assessment_id == assessment_id)
        ).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # Tokenize all names and build prefix frequency map.
    sr_tokens: List[Tuple[ScanResult, List[str]]] = []
    for sr in scan_results:
        tokens = _tokenize(sr.name)
        if tokens:
            sr_tokens.append((sr, tokens))

    # Build prefix → set of scan_result_ids, for prefixes of length >= _MIN_PREFIX_TOKENS.
    prefix_members: Dict[str, Set[int]] = defaultdict(set)

    for sr, tokens in sr_tokens:
        if sr.id is None:
            continue
        # Generate prefixes of increasing length.
        for length in range(_MIN_PREFIX_TOKENS, len(tokens) + 1):
            prefix = "_".join(tokens[:length])
            # Skip if all tokens in prefix are generic.
            if all(t in _GENERIC_TOKENS for t in tokens[:length]):
                continue
            prefix_members[prefix].add(sr.id)

    # Filter to prefixes meeting minimum cluster size.
    # Keep only the longest prefix for each group of members (dedup nested prefixes).
    valid_prefixes = {
        prefix: members
        for prefix, members in prefix_members.items()
        if len(members) >= _MIN_CLUSTER_SIZE
    }

    # Remove shorter prefixes that are strict subsets of longer ones.
    # Sort by length descending so we keep the most specific.
    sorted_prefixes = sorted(valid_prefixes.keys(), key=lambda p: -len(p.split("_")))
    final_clusters: Dict[str, Set[int]] = {}
    consumed_sr_ids: Set[int] = set()

    for prefix in sorted_prefixes:
        members = valid_prefixes[prefix]
        # Only keep this prefix if it adds members not already covered by a longer prefix.
        uncovered = members - consumed_sr_ids
        if len(uncovered) >= _MIN_CLUSTER_SIZE:
            final_clusters[prefix] = members
            consumed_sr_ids |= members
        elif len(members) >= _MIN_CLUSTER_SIZE and prefix not in final_clusters:
            # Even if some members are covered, keep if the full set is large enough
            # and this is a distinct meaningful prefix.
            final_clusters[prefix] = members

    clusters_created = 0
    for prefix, member_ids in final_clusters.items():
        token_count = len(prefix.split("_"))
        # Confidence: longer prefixes are more specific.
        confidence = min(1.0, 0.5 + 0.1 * token_count)

        session.add(NamingCluster(
            instance_id=instance_id,
            assessment_id=assessment_id,
            cluster_token=prefix,
            token_type="prefix",
            member_count=len(member_ids),
            member_ids_json=json.dumps(sorted(member_ids)),
            confidence=round(confidence, 2),
        ))
        clusters_created += 1

    session.commit()

    return {
        "success": True,
        "clusters_created": clusters_created,
        "errors": [],
    }
```

### Step 4: Run tests

```bash
python -m pytest tests/test_naming_analyzer.py -v
```

### Step 5: Run full suite

```bash
python -m pytest --tb=short -q
```

### Step 6: Commit

```bash
git add src/engines/naming_analyzer.py tests/test_naming_analyzer.py
git commit -m "feat: add Naming Analyzer engine (prefix/suffix clustering)"
```

---

## Task 4: Table Co-location Engine

**Priority:** LOW — lightweight, serves visualization + weak grouping signal.
**Input:** All `ScanResult` records
**Output:** Rows in `table_colocation_summary` table

**Files:**
- Create: `src/engines/table_colocation.py`
- Test: `tests/test_table_colocation.py`

### Step 1: Write failing tests

Create `tests/test_table_colocation.py`:

```python
"""Tests for the Table Co-location engine."""

import json

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    TableColocationSummary,
)


def _setup_base(db_session):
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

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="test scan", status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    return inst, asmt, scan


def test_groups_by_target_table(db_session):
    """Artifacts on same table → grouped together."""
    from src.engines.table_colocation import run

    inst, asmt, scan = _setup_base(db_session)

    # 3 on incident, 2 on sys_user
    for i in range(3):
        db_session.add(ScanResult(
            scan_id=scan.id, sys_id=f"sr_inc_{i}", table_name="sys_script",
            name=f"BR - Incident {i}", meta_target_table="incident",
            sys_update_name=f"sys_script_inc_{i}",
        ))
    for i in range(2):
        db_session.add(ScanResult(
            scan_id=scan.id, sys_id=f"sr_user_{i}", table_name="sys_script",
            name=f"BR - User {i}", meta_target_table="sys_user",
            sys_update_name=f"sys_script_user_{i}",
        ))
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["groups_created"] >= 2

    groups = list(db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id,
        )
    ).all())

    by_table = {g.target_table: g for g in groups}
    assert "incident" in by_table
    assert by_table["incident"].artifact_count == 3
    assert "sys_user" in by_table
    assert by_table["sys_user"].artifact_count == 2


def test_no_target_table_excluded(db_session):
    """Artifacts without meta_target_table are not grouped."""
    from src.engines.table_colocation import run

    inst, asmt, scan = _setup_base(db_session)

    db_session.add(ScanResult(
        scan_id=scan.id, sys_id="sr_no_table", table_name="sys_script_include",
        name="SI - No Table", meta_target_table=None,
        sys_update_name="sys_script_include_no_table",
    ))
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["groups_created"] == 0


def test_idempotent_rerun(db_session):
    from src.engines.table_colocation import run

    inst, asmt, scan = _setup_base(db_session)

    db_session.add(ScanResult(
        scan_id=scan.id, sys_id="sr1", table_name="sys_script",
        name="BR - Test", meta_target_table="incident",
        sys_update_name="sys_script_test",
    ))
    db_session.commit()

    run(asmt.id, db_session)
    count1 = len(list(db_session.exec(
        select(TableColocationSummary).where(TableColocationSummary.assessment_id == asmt.id)
    ).all()))

    run(asmt.id, db_session)
    count2 = len(list(db_session.exec(
        select(TableColocationSummary).where(TableColocationSummary.assessment_id == asmt.id)
    ).all()))

    assert count1 == count2
```

### Step 2: Run tests to verify they fail

```bash
python -m pytest tests/test_table_colocation.py -v
```

### Step 3: Implement `src/engines/table_colocation.py`

```python
"""Engine 6: Table Co-location.

Groups artifacts by their target table — a weak but useful grouping signal
and valuable for visualization (spiderweb/relationship maps).

Input: ScanResult records (meta_target_table field)
Output: Rows in table_colocation_summary table
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Set

from sqlmodel import Session, select

from ..models import (
    Assessment,
    Scan,
    ScanResult,
    TableColocationSummary,
)


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the table co-location engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "groups_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "groups_created": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # Idempotent: delete prior results.
    existing = list(
        session.exec(
            select(TableColocationSummary).where(
                TableColocationSummary.assessment_id == assessment_id
            )
        ).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # Group by target table.
    table_groups: Dict[str, List[int]] = defaultdict(list)
    for sr in scan_results:
        if sr.meta_target_table and sr.id is not None:
            table_groups[sr.meta_target_table].append(sr.id)

    groups_created = 0
    for target_table, sr_ids in table_groups.items():
        session.add(TableColocationSummary(
            instance_id=instance_id,
            assessment_id=assessment_id,
            target_table=target_table,
            artifact_count=len(sr_ids),
            artifact_ids_json=json.dumps(sorted(sr_ids)),
        ))
        groups_created += 1

    session.commit()

    return {
        "success": True,
        "groups_created": groups_created,
        "errors": [],
    }
```

### Step 4: Run tests

```bash
python -m pytest tests/test_table_colocation.py -v
```

### Step 5: Run full suite

```bash
python -m pytest --tb=short -q
```

### Step 6: Commit

```bash
git add src/engines/table_colocation.py tests/test_table_colocation.py
git commit -m "feat: add Table Co-location engine (target table grouping)"
```

---

## Task 5: Engine Registry + Tool Update

Wire all 4 new engines into the existing `run_preprocessing_engines` MCP tool.

**Files:**
- Modify: `src/mcp/tools/pipeline/run_engines.py`
- Test: `tests/test_run_engines_tool.py`

### Step 1: Update `_ENGINE_REGISTRY` in `src/mcp/tools/pipeline/run_engines.py`

Replace the existing `_ENGINE_REGISTRY` and `INPUT_SCHEMA` with:

```python
_ENGINE_REGISTRY: Dict[str, str] = {
    "structural_mapper": "src.engines.structural_mapper",
    "code_reference_parser": "src.engines.code_reference_parser",
    "update_set_analyzer": "src.engines.update_set_analyzer",
    "temporal_clusterer": "src.engines.temporal_clusterer",
    "naming_analyzer": "src.engines.naming_analyzer",
    "table_colocation": "src.engines.table_colocation",
}
```

Update the `INPUT_SCHEMA` engines description:

```python
"engines": {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Optional list of engine names to run. "
        "Default: all available engines. "
        "Options: structural_mapper, code_reference_parser, "
        "update_set_analyzer, temporal_clusterer, naming_analyzer, table_colocation"
    ),
},
```

Update the `TOOL_SPEC` description:

```python
TOOL_SPEC = ToolSpec(
    name="run_preprocessing_engines",
    description=(
        "Run deterministic pre-processing engines for an assessment. "
        "Populates structural_relationship, code_reference, update_set_overlap, "
        "temporal_cluster, naming_cluster, and table_colocation_summary tables. "
        "Must be run BEFORE AI analysis passes."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

### Step 2: Update or add test for full engine run

In `tests/test_run_engines_tool.py`, add or update a test that verifies all 6 engines are in the registry:

```python
def test_all_engines_registered():
    """All 6 engines are in the registry."""
    from src.mcp.tools.pipeline.run_engines import _ENGINE_REGISTRY

    expected = {
        "structural_mapper",
        "code_reference_parser",
        "update_set_analyzer",
        "temporal_clusterer",
        "naming_analyzer",
        "table_colocation",
    }
    assert set(_ENGINE_REGISTRY.keys()) == expected
```

### Step 3: Run tests

```bash
python -m pytest tests/test_run_engines_tool.py -v
python -m pytest --tb=short -q
```

### Step 4: Commit

```bash
git add src/mcp/tools/pipeline/run_engines.py tests/test_run_engines_tool.py
git commit -m "feat: wire all 6 engines into run_preprocessing_engines tool"
```

---

## Task 6: Full Regression + Summary

### Step 1: Run full test suite

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub
python -m pytest --tb=short -q
```

Expected: All tests pass (230+ existing + ~25 new = ~255+)

### Step 2: Verify all new files exist

```bash
ls -la src/engines/
# Should show: __init__.py, code_reference_parser.py, structural_mapper.py,
#              update_set_analyzer.py, temporal_clusterer.py, naming_analyzer.py,
#              table_colocation.py
```

### Step 3: Update admin files

Update `servicenow_global_tech_assessment_mcp/00_admin/context.md` — add to Current Status:

```
- **Reasoning Layer Phase 2 engines complete** (Codex, 2026-03-04): added 4 remaining engines
  (update_set_analyzer, temporal_clusterer, naming_analyzer, table_colocation) to `src/engines/`.
  All 6 engines registered in `run_preprocessing_engines` MCP tool. New persistence tables
  (NamingCluster, TableColocationSummary) + signal_type on UpdateSetOverlap. Full suite green.
```

Update `servicenow_global_tech_assessment_mcp/00_admin/todos.md` — mark completed:

```
- [x] [owner:codex] Deterministic engine: Update set overlap analysis tool
- [x] [owner:codex] Deterministic engine: Temporal clustering tool
- [x] [owner:codex] Deterministic engine: Table co-location tool
- [x] [owner:codex] Deterministic engine: Naming analyzer tool (added)
```

### Step 4: Final commit

```bash
git add servicenow_global_tech_assessment_mcp/00_admin/context.md \
        servicenow_global_tech_assessment_mcp/00_admin/todos.md
git commit -m "docs: update admin files for Phase 2 engine completion"
```

---

## Summary: What Gets Created/Modified

### New Files (6)

| File | Engine | Lines (est.) |
|------|--------|-------------|
| `src/engines/update_set_analyzer.py` | Update Set Analyzer | ~280 |
| `src/engines/temporal_clusterer.py` | Temporal Clusterer | ~170 |
| `src/engines/naming_analyzer.py` | Naming Analyzer | ~150 |
| `src/engines/table_colocation.py` | Table Co-location | ~80 |
| `tests/test_update_set_analyzer.py` | US Analyzer tests | ~200 |
| `tests/test_temporal_clusterer.py` | Temporal tests | ~150 |
| `tests/test_naming_analyzer.py` | Naming tests | ~120 |
| `tests/test_table_colocation.py` | Co-location tests | ~90 |

### Modified Files (4)

| File | Changes |
|------|---------|
| `src/models.py` | Add NamingCluster, TableColocationSummary, signal_type on UpdateSetOverlap |
| `src/database.py` | Register new tables + ALTER TABLE migration |
| `src/mcp/tools/pipeline/run_engines.py` | Add 4 engines to registry |
| `tests/test_reasoning_data_model.py` | Tests for new models |

---

## Next Plan Link

After Phase 2 completion, continue with UI + iterative AI grouping orchestration in:

`docs/plans/2026-03-04-reasoning-layer-phase3-ui-ai-feature-orchestration.md`
