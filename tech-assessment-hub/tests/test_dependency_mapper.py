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
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)
from src.engines.dependency_mapper import run


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


class TestDependencyMapperEngine:
    """Integration tests for the dependency_mapper engine run() function."""

    def test_basic_chain_persisted(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        result = run(asmt.id, db_session)

        assert result["success"] is True
        assert result["chains_created"] >= 1
        assert result["errors"] == []

        chains = list(db_session.exec(
            select(DependencyChain).where(DependencyChain.assessment_id == asmt.id)
        ).all())
        assert len(chains) >= 1
        direct = [c for c in chains if c.source_scan_result_id == a.id
                  and c.target_scan_result_id == b.id]
        assert len(direct) == 1
        assert direct[0].hop_count == 1
        assert direct[0].dependency_type == "code_reference"

    def test_cluster_persisted(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        result = run(asmt.id, db_session)
        assert result["clusters_created"] >= 1

        clusters = list(db_session.exec(
            select(DependencyCluster).where(DependencyCluster.assessment_id == asmt.id)
        ).all())
        assert len(clusters) >= 1
        member_ids = json.loads(clusters[0].member_ids_json)
        assert set(member_ids) == {a.id, b.id}

    def test_idempotent(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        run(asmt.id, db_session)
        result2 = run(asmt.id, db_session)

        chains = list(db_session.exec(
            select(DependencyChain).where(DependencyChain.assessment_id == asmt.id)
        ).all())
        clusters = list(db_session.exec(
            select(DependencyCluster).where(DependencyCluster.assessment_id == asmt.id)
        ).all())
        assert result2["success"] is True
        assert len(chains) == result2["chains_created"]
        assert len(clusters) == result2["clusters_created"]

    def test_only_customized_in_clusters(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "CustomA")
        ootb = _add_scan_result(db_session, scan, "OOTB",
                                origin_type=OriginType.ootb_untouched)
        _add_code_reference(db_session, inst, asmt, a, ootb)

        result = run(asmt.id, db_session)
        assert result["clusters_created"] == 0

    def test_assessment_not_found(self, db_session):
        result = run(999999, db_session)
        assert result["success"] is False
        assert "Assessment not found" in result["errors"][0]

    def test_no_scan_results(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        result = run(asmt.id, db_session)
        assert result["success"] is True
        assert result["chains_created"] == 0
        assert result["clusters_created"] == 0

    def test_transitive_chain_persisted(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "A")
        b = _add_scan_result(db_session, scan, "B")
        node_c = _add_scan_result(db_session, scan, "C")
        _add_code_reference(db_session, inst, asmt, a, b)
        _add_code_reference(db_session, inst, asmt, b, node_c)

        result = run(asmt.id, db_session)

        chains = list(db_session.exec(
            select(DependencyChain).where(
                DependencyChain.assessment_id == asmt.id,
                DependencyChain.dependency_type == "transitive",
            )
        ).all())
        a_to_c = [ch for ch in chains
                   if ch.source_scan_result_id == a.id
                   and ch.target_scan_result_id == node_c.id]
        assert len(a_to_c) == 1
        assert a_to_c[0].hop_count == 2

    def test_circular_detected_in_cluster(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "A")
        b = _add_scan_result(db_session, scan, "B")
        _add_code_reference(db_session, inst, asmt, a, b)
        _add_code_reference(db_session, inst, asmt, b, a)

        result = run(asmt.id, db_session)

        clusters = list(db_session.exec(
            select(DependencyCluster).where(DependencyCluster.assessment_id == asmt.id)
        ).all())
        assert len(clusters) == 1
        circulars = json.loads(clusters[0].circular_dependencies_json)
        assert len(circulars) >= 1

    def test_shared_dependency_chain(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "CustomA")
        b = _add_scan_result(db_session, scan, "CustomB")
        ootb = _add_scan_result(db_session, scan, "SharedOOTB",
                                origin_type=OriginType.ootb_untouched)
        _add_code_reference(db_session, inst, asmt, a, ootb)
        _add_code_reference(db_session, inst, asmt, b, ootb)

        result = run(asmt.id, db_session)

        assert result["clusters_created"] >= 1
        clusters = list(db_session.exec(
            select(DependencyCluster).where(DependencyCluster.assessment_id == asmt.id)
        ).all())
        member_ids = json.loads(clusters[0].member_ids_json)
        assert a.id in member_ids
        assert b.id in member_ids

    def test_change_risk_propagates_to_feature(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA", table_name="sys_script")
        b = _add_scan_result(db_session, scan, "ScriptB", table_name="sys_script_include")
        _add_code_reference(db_session, inst, asmt, a, b)

        feature = Feature(
            assessment_id=asmt.id,
            name="Working Feature 01",
        )
        db_session.add(feature)
        db_session.flush()

        db_session.add(FeatureScanResult(feature_id=feature.id, scan_result_id=a.id))
        db_session.commit()

        result = run(asmt.id, db_session)

        db_session.refresh(feature)

        assert result["success"] is True
        assert feature.change_risk_score is not None
        assert feature.change_risk_level in {"low", "medium", "high", "critical"}
