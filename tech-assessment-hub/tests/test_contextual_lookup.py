"""Tests for the contextual lookup service (local-first, SN fallback)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    Fact,
    Feature,
    FeatureScanResult,
    Instance,
    Scan,
    ScanResult,
    TableDefinition,
    UpdateSet,
    UpdateSetArtifactLink,
)
from src.services.encryption import encrypt_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_instance(session) -> Instance:
    inst = Instance(
        name="ctx-lookup-inst",
        url="https://ctx.service-now.com",
        username="admin",
        password_encrypted=encrypt_password("secret"),
    )
    session.add(inst)
    session.commit()
    session.refresh(inst)
    return inst


def _make_assessment(session, instance: Instance) -> Assessment:
    asmt = Assessment(
        number="ASMT0000099",
        name="Ctx Lookup Test",
        instance_id=instance.id,
    )
    session.add(asmt)
    session.commit()
    session.refresh(asmt)
    return asmt


def _make_scan(session, assessment: Assessment) -> Scan:
    scan = Scan(
        assessment_id=assessment.id,
        scan_type="metadata",
        name="Test Scan",
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)
    return scan


def _make_scan_result(session, scan: Scan, **kwargs) -> ScanResult:
    defaults = dict(
        scan_id=scan.id,
        sys_id="abc123",
        table_name="sys_script_include",
        name="TestScript",
        origin_type="net_new_customer",
    )
    defaults.update(kwargs)
    sr = ScanResult(**defaults)
    session.add(sr)
    session.commit()
    session.refresh(sr)
    return sr


def _make_table_definition(session, instance: Instance, table_name: str) -> TableDefinition:
    td = TableDefinition(
        instance_id=instance.id,
        sn_sys_id=f"td_{table_name}",
        name=table_name,
    )
    session.add(td)
    session.commit()
    session.refresh(td)
    return td


def _make_update_set(session, instance: Instance, name: str = "US - Test Changes") -> UpdateSet:
    us = UpdateSet(
        instance_id=instance.id,
        sn_sys_id="us_001",
        name=name,
        state="complete",
    )
    session.add(us)
    session.commit()
    session.refresh(us)
    return us


# ---------------------------------------------------------------------------
# detect_references
# ---------------------------------------------------------------------------

class TestDetectReferences:
    """Tests for detect_references()."""

    def test_finds_incident_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Check INC0012345 for details")
        assert len(refs) == 1
        assert refs[0]["type"] == "incident"
        assert refs[0]["number"] == "INC0012345"
        assert refs[0]["table"] == "incident"

    def test_finds_change_request(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Related to CHG0054321")
        assert len(refs) == 1
        assert refs[0]["type"] == "change_request"
        assert refs[0]["number"] == "CHG0054321"
        assert refs[0]["table"] == "change_request"

    def test_finds_ritm_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("See RITM0099887")
        assert len(refs) == 1
        assert refs[0]["type"] == "sc_req_item"
        assert refs[0]["number"] == "RITM0099887"
        assert refs[0]["table"] == "sc_req_item"

    def test_finds_request_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Under REQ0001234")
        assert len(refs) == 1
        assert refs[0]["type"] == "sc_request"

    def test_finds_problem_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Root cause PRB0005678")
        assert len(refs) == 1
        assert refs[0]["type"] == "problem"
        assert refs[0]["table"] == "problem"

    def test_finds_task_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Assigned TASK0011111")
        assert len(refs) == 1
        assert refs[0]["type"] == "task"
        assert refs[0]["table"] == "task"

    def test_finds_work_order_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Created WO0045678")
        assert len(refs) == 1
        assert refs[0]["type"] == "wm_order"
        assert refs[0]["table"] == "wm_order"

    def test_finds_work_order_task_wotask(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Work on WOTASK0055555")
        assert len(refs) == 1
        assert refs[0]["type"] == "wm_task"
        assert refs[0]["table"] == "wm_task"

    def test_finds_work_order_task_wot(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Also WOT0066666 is pending")
        assert len(refs) == 1
        assert refs[0]["type"] == "wm_task"
        assert refs[0]["table"] == "wm_task"

    def test_finds_kb_reference(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("Refer to KB0012345")
        assert len(refs) == 1
        assert refs[0]["type"] == "kb_knowledge"
        assert refs[0]["table"] == "kb_knowledge"

    def test_empty_text_returns_empty_list(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("")
        assert refs == []

    def test_no_references_in_text(self):
        from src.services.contextual_lookup import detect_references

        refs = detect_references("This text has no ServiceNow references at all.")
        assert refs == []

    def test_multiple_references_in_one_text(self):
        from src.services.contextual_lookup import detect_references

        text = "INC0012345 is related to CHG0054321 and PRB0005678"
        refs = detect_references(text)
        assert len(refs) == 3
        types = {r["type"] for r in refs}
        assert types == {"incident", "change_request", "problem"}

    def test_deduplicates_same_reference(self):
        from src.services.contextual_lookup import detect_references

        text = "INC0012345 appears again INC0012345"
        refs = detect_references(text)
        assert len(refs) == 1

    def test_wotask_not_matched_as_wo(self):
        """WOTASK should be detected as wm_task, not wm_order."""
        from src.services.contextual_lookup import detect_references

        refs = detect_references("WOTASK0012345 is a work order task")
        assert len(refs) == 1
        assert refs[0]["type"] == "wm_task"
        assert refs[0]["table"] == "wm_task"


# ---------------------------------------------------------------------------
# check_local_table_data
# ---------------------------------------------------------------------------

class TestCheckLocalTableData:
    """Tests for check_local_table_data()."""

    def test_returns_true_when_table_definition_exists(self, db_session):
        from src.services.contextual_lookup import check_local_table_data

        inst = _make_instance(db_session)
        _make_table_definition(db_session, inst, "incident")
        assert check_local_table_data(db_session, inst.id, "incident") is True

    def test_returns_false_when_no_table_definition(self, db_session):
        from src.services.contextual_lookup import check_local_table_data

        inst = _make_instance(db_session)
        assert check_local_table_data(db_session, inst.id, "incident") is False

    def test_scoped_to_instance(self, db_session):
        from src.services.contextual_lookup import check_local_table_data

        inst1 = _make_instance(db_session)
        inst2 = Instance(
            name="other-inst",
            url="https://other.service-now.com",
            username="admin",
            password_encrypted=encrypt_password("pw2"),
        )
        db_session.add(inst2)
        db_session.commit()
        db_session.refresh(inst2)

        _make_table_definition(db_session, inst1, "incident")
        assert check_local_table_data(db_session, inst1.id, "incident") is True
        assert check_local_table_data(db_session, inst2.id, "incident") is False


# ---------------------------------------------------------------------------
# lookup_reference_local
# ---------------------------------------------------------------------------

class TestLookupReferenceLocal:
    """Tests for lookup_reference_local()."""

    def test_returns_cached_fact_when_present(self, db_session):
        from src.services.contextual_lookup import lookup_reference_local

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0012345", "table": "incident"}

        # Plant a Fact in the cache
        fact = Fact(
            instance_id=inst.id,
            module="tech_assessment",
            topic_type="reference_lookup",
            topic_value="incident",
            fact_key="ref:incident:INC0012345",
            fact_value=json.dumps({"number": "INC0012345", "short_description": "Server down"}),
            created_by="computed",
            confidence=1.0,
            valid_until=datetime.utcnow() + timedelta(hours=12),
        )
        db_session.add(fact)
        db_session.commit()

        result = lookup_reference_local(db_session, inst.id, ref)
        assert result is not None
        assert result["number"] == "INC0012345"
        assert result["short_description"] == "Server down"

    def test_returns_none_when_no_cache(self, db_session):
        from src.services.contextual_lookup import lookup_reference_local

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0099999", "table": "incident"}
        result = lookup_reference_local(db_session, inst.id, ref)
        assert result is None

    def test_ignores_expired_cache(self, db_session):
        from src.services.contextual_lookup import lookup_reference_local

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0012345", "table": "incident"}

        # Plant an expired Fact
        fact = Fact(
            instance_id=inst.id,
            module="tech_assessment",
            topic_type="reference_lookup",
            topic_value="incident",
            fact_key="ref:incident:INC0012345",
            fact_value=json.dumps({"number": "INC0012345", "short_description": "Old"}),
            created_by="computed",
            confidence=1.0,
            valid_until=datetime.utcnow() - timedelta(hours=1),
        )
        db_session.add(fact)
        db_session.commit()

        result = lookup_reference_local(db_session, inst.id, ref)
        assert result is None


# ---------------------------------------------------------------------------
# lookup_reference_remote
# ---------------------------------------------------------------------------

class TestLookupReferenceRemote:
    """Tests for lookup_reference_remote()."""

    @patch("src.services.contextual_lookup.decrypt_password", return_value="secret")
    @patch("src.services.contextual_lookup.ServiceNowClient")
    def test_queries_sn_and_caches_result(self, mock_sn_cls, mock_decrypt, db_session):
        from src.services.contextual_lookup import lookup_reference_remote

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0012345", "table": "incident"}

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"number": "INC0012345", "short_description": "Server crash", "state": "2"}
        ]
        mock_sn_cls.return_value = mock_client

        result = lookup_reference_remote(db_session, inst.id, ref)
        assert result is not None
        assert result["number"] == "INC0012345"
        assert result["short_description"] == "Server crash"

        # Verify cached as Fact
        cached = db_session.exec(
            select(Fact).where(
                Fact.instance_id == inst.id,
                Fact.topic_type == "reference_lookup",
                Fact.fact_key == "ref:incident:INC0012345",
            )
        ).first()
        assert cached is not None
        cached_data = json.loads(cached.fact_value)
        assert cached_data["number"] == "INC0012345"

    @patch("src.services.contextual_lookup.decrypt_password", return_value="secret")
    @patch("src.services.contextual_lookup.ServiceNowClient")
    def test_returns_none_when_no_records(self, mock_sn_cls, mock_decrypt, db_session):
        from src.services.contextual_lookup import lookup_reference_remote

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0099999", "table": "incident"}

        mock_client = MagicMock()
        mock_client.get_records.return_value = []
        mock_sn_cls.return_value = mock_client

        result = lookup_reference_remote(db_session, inst.id, ref)
        assert result is None

    @patch("src.services.contextual_lookup.decrypt_password", return_value="secret")
    @patch("src.services.contextual_lookup.ServiceNowClient")
    def test_returns_none_on_sn_error(self, mock_sn_cls, mock_decrypt, db_session):
        from src.services.contextual_lookup import lookup_reference_remote

        inst = _make_instance(db_session)
        ref = {"type": "incident", "number": "INC0012345", "table": "incident"}

        mock_client = MagicMock()
        mock_client.get_records.side_effect = Exception("SN unavailable")
        mock_sn_cls.return_value = mock_client

        result = lookup_reference_remote(db_session, inst.id, ref)
        assert result is None


# ---------------------------------------------------------------------------
# resolve_references
# ---------------------------------------------------------------------------

class TestResolveReferences:
    """Tests for resolve_references()."""

    def test_mode_never_returns_unresolved_refs(self, db_session):
        from src.services.contextual_lookup import resolve_references

        inst = _make_instance(db_session)
        text = "Check INC0012345 and CHG0054321"

        results = resolve_references(db_session, inst.id, text, enrichment_mode="never")
        assert len(results) == 2
        for r in results:
            assert r["resolved"] is False
            assert r["data"] is None
            assert r["source"] is None

    def test_mode_auto_resolves_locally_first(self, db_session):
        from src.services.contextual_lookup import resolve_references

        inst = _make_instance(db_session)

        # Plant a local cache hit
        fact = Fact(
            instance_id=inst.id,
            module="tech_assessment",
            topic_type="reference_lookup",
            topic_value="incident",
            fact_key="ref:incident:INC0012345",
            fact_value=json.dumps({"number": "INC0012345", "short_description": "Cached hit"}),
            created_by="computed",
            confidence=1.0,
            valid_until=datetime.utcnow() + timedelta(hours=12),
        )
        db_session.add(fact)
        db_session.commit()

        results = resolve_references(db_session, inst.id, "See INC0012345", enrichment_mode="auto")
        assert len(results) == 1
        assert results[0]["resolved"] is True
        assert results[0]["source"] == "local"
        assert results[0]["data"]["short_description"] == "Cached hit"

    @patch("src.services.contextual_lookup.decrypt_password", return_value="secret")
    @patch("src.services.contextual_lookup.ServiceNowClient")
    def test_mode_auto_falls_back_to_remote(self, mock_sn_cls, mock_decrypt, db_session):
        from src.services.contextual_lookup import resolve_references

        inst = _make_instance(db_session)

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"number": "INC0012345", "short_description": "Remote hit"}
        ]
        mock_sn_cls.return_value = mock_client

        results = resolve_references(db_session, inst.id, "See INC0012345", enrichment_mode="auto")
        assert len(results) == 1
        assert results[0]["resolved"] is True
        assert results[0]["source"] == "remote"
        assert results[0]["data"]["short_description"] == "Remote hit"

    @patch("src.services.contextual_lookup.decrypt_password", return_value="secret")
    @patch("src.services.contextual_lookup.ServiceNowClient")
    def test_mode_always_queries_remote_even_if_local_exists(self, mock_sn_cls, mock_decrypt, db_session):
        from src.services.contextual_lookup import resolve_references

        inst = _make_instance(db_session)

        # Plant a local cache hit
        fact = Fact(
            instance_id=inst.id,
            module="tech_assessment",
            topic_type="reference_lookup",
            topic_value="incident",
            fact_key="ref:incident:INC0012345",
            fact_value=json.dumps({"number": "INC0012345", "short_description": "Old cached"}),
            created_by="computed",
            confidence=1.0,
            valid_until=datetime.utcnow() + timedelta(hours=12),
        )
        db_session.add(fact)
        db_session.commit()

        mock_client = MagicMock()
        mock_client.get_records.return_value = [
            {"number": "INC0012345", "short_description": "Fresh remote"}
        ]
        mock_sn_cls.return_value = mock_client

        results = resolve_references(db_session, inst.id, "See INC0012345", enrichment_mode="always")
        assert len(results) == 1
        assert results[0]["resolved"] is True
        assert results[0]["source"] == "remote"
        assert results[0]["data"]["short_description"] == "Fresh remote"

    def test_no_references_returns_empty(self, db_session):
        from src.services.contextual_lookup import resolve_references

        inst = _make_instance(db_session)
        results = resolve_references(db_session, inst.id, "No refs here.", enrichment_mode="auto")
        assert results == []


# ---------------------------------------------------------------------------
# gather_artifact_context
# ---------------------------------------------------------------------------

class TestGatherArtifactContext:
    """Tests for gather_artifact_context()."""

    def test_returns_structured_context(self, db_session):
        from src.services.contextual_lookup import gather_artifact_context

        inst = _make_instance(db_session)
        asmt = _make_assessment(db_session, inst)
        scan = _make_scan(db_session, asmt)
        sr = _make_scan_result(
            db_session,
            scan,
            observations="See INC0012345 for background",
            disposition="keep_as_is",
        )

        result = gather_artifact_context(db_session, inst.id, sr.id, enrichment_mode="never")

        assert "artifact" in result
        assert result["artifact"]["name"] == "TestScript"
        assert result["artifact"]["table_name"] == "sys_script_include"
        assert "human_context" in result
        assert result["human_context"]["observations"] == "See INC0012345 for background"
        assert result["human_context"]["disposition"] == "keep_as_is"
        assert "references" in result
        # In "never" mode, references are detected but not resolved
        assert len(result["references"]) == 1
        assert result["references"][0]["number"] == "INC0012345"
        assert result["references"][0]["resolved"] is False
        assert "has_local_table_data" in result

    def test_returns_none_artifact_for_missing_scan_result(self, db_session):
        from src.services.contextual_lookup import gather_artifact_context

        inst = _make_instance(db_session)
        result = gather_artifact_context(db_session, inst.id, 99999, enrichment_mode="never")
        assert result["artifact"] is None

    def test_includes_update_set_links(self, db_session):
        from src.services.contextual_lookup import gather_artifact_context

        inst = _make_instance(db_session)
        asmt = _make_assessment(db_session, inst)
        scan = _make_scan(db_session, asmt)
        sr = _make_scan_result(db_session, scan)
        us = _make_update_set(db_session, inst, name="US - INC0055555 Fix")

        # Create the link
        link = UpdateSetArtifactLink(
            instance_id=inst.id,
            assessment_id=asmt.id,
            scan_result_id=sr.id,
            update_set_id=us.id,
            link_source="scan_result_current",
        )
        db_session.add(link)
        db_session.commit()

        result = gather_artifact_context(db_session, inst.id, sr.id, enrichment_mode="never")
        assert len(result["update_sets"]) == 1
        assert result["update_sets"][0]["name"] == "US - INC0055555 Fix"
        # References from update set names should be detected
        assert any(r["number"] == "INC0055555" for r in result["references"])

    def test_includes_feature_membership(self, db_session):
        from src.services.contextual_lookup import gather_artifact_context

        inst = _make_instance(db_session)
        asmt = _make_assessment(db_session, inst)
        scan = _make_scan(db_session, asmt)
        sr = _make_scan_result(db_session, scan)

        feature = Feature(
            assessment_id=asmt.id,
            name="Login Feature",
        )
        db_session.add(feature)
        db_session.commit()
        db_session.refresh(feature)

        link = FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=sr.id,
        )
        db_session.add(link)
        db_session.commit()

        result = gather_artifact_context(db_session, inst.id, sr.id, enrichment_mode="never")
        assert len(result["human_context"]["features"]) == 1
        assert result["human_context"]["features"][0]["name"] == "Login Feature"

    def test_has_local_table_data_flag(self, db_session):
        from src.services.contextual_lookup import gather_artifact_context

        inst = _make_instance(db_session)
        asmt = _make_assessment(db_session, inst)
        scan = _make_scan(db_session, asmt)
        sr = _make_scan_result(db_session, scan, table_name="incident")

        # No table definition yet
        result = gather_artifact_context(db_session, inst.id, sr.id, enrichment_mode="never")
        assert result["has_local_table_data"] is False

        # Add table definition
        _make_table_definition(db_session, inst, "incident")
        result = gather_artifact_context(db_session, inst.id, sr.id, enrichment_mode="never")
        assert result["has_local_table_data"] is True
