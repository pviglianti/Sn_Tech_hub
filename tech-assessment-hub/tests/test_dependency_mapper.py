"""Tests for the Dependency Mapper engine (Engine 7).

Validates dependency chain resolution, circular detection, cluster computation,
and scoring across customized ScanResults.
"""

import json

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    DependencyChain,
    DependencyCluster,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
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
        name="Test",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    return inst, asmt, scan


def _add_scan_result(session, scan, name, table_name="sys_script_include",
                     sys_id=None, origin_type=OriginType.net_new_customer):
    """Add a single ScanResult with the given name and origin_type."""
    import uuid

    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id or str(uuid.uuid4().hex[:32]),
        table_name=table_name,
        name=name,
        origin_type=origin_type,
    )
    session.add(sr)
    session.flush()
    return sr


def _add_code_reference(session, inst, asmt, source, target, ref_type="script_include"):
    """Add a CodeReference between two scan results."""
    cr = CodeReference(
        instance_id=inst.id,
        assessment_id=asmt.id,
        source_scan_result_id=source.id,
        target_scan_result_id=target.id,
        source_table=source.table_name,
        source_field="script",
        source_name=source.name,
        reference_type=ref_type,
        target_identifier=target.name,
    )
    session.add(cr)
    session.flush()
    return cr


def _add_structural_rel(session, inst, asmt, parent, child, rel_type="ui_policy_action"):
    """Add a StructuralRelationship between two scan results."""
    sr = StructuralRelationship(
        instance_id=inst.id,
        assessment_id=asmt.id,
        parent_scan_result_id=parent.id,
        child_scan_result_id=child.id,
        relationship_type=rel_type,
        parent_field="sys_ui_policy",
    )
    session.add(sr)
    session.flush()
    return sr


class TestDependencyModelsExist:
    """DependencyChain and DependencyCluster models can be instantiated."""

    def test_dependency_chain_create(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        sr_a = _add_scan_result(db_session, scan, "Script A")
        sr_b = _add_scan_result(db_session, scan, "Script B")

        chain = DependencyChain(
            scan_id=scan.id,
            instance_id=inst.id,
            assessment_id=asmt.id,
            source_scan_result_id=sr_a.id,
            target_scan_result_id=sr_b.id,
            dependency_type="code_reference",
            direction="outbound",
            hop_count=1,
            chain_path_json=json.dumps([sr_a.id, sr_b.id]),
            chain_weight=3.0,
            criticality="high",
        )
        db_session.add(chain)
        db_session.flush()
        assert chain.id is not None

    def test_dependency_cluster_create(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        sr_a = _add_scan_result(db_session, scan, "Script A")
        sr_b = _add_scan_result(db_session, scan, "Script B")

        cluster = DependencyCluster(
            scan_id=scan.id,
            instance_id=inst.id,
            assessment_id=asmt.id,
            cluster_label="sys_script_include cluster (2 artifacts)",
            member_ids_json=json.dumps([sr_a.id, sr_b.id]),
            member_count=2,
            internal_edge_count=1,
            coupling_score=2.0,
            impact_radius="low",
            change_risk_score=15.0,
            change_risk_level="low",
            circular_dependencies_json=json.dumps([]),
            tables_involved_json=json.dumps(["sys_script_include"]),
        )
        db_session.add(cluster)
        db_session.flush()
        assert cluster.id is not None
