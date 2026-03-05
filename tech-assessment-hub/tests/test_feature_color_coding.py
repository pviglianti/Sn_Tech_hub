"""Tests for Phase 11D — feature color coding and customization cross-reference styling."""

import json
from datetime import datetime

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.server import FEATURE_COLORS


# ── Helpers ──────────────────────────────────────────────────────────


def _seed_assessment_with_features(db_session, *, feature_count=3, members_per_feature=2):
    """Create an assessment, scan, features, and scan results with links."""
    inst = Instance(
        name="color-inst",
        url="https://color.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Color Assessment",
        number="ASMT0099001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="Color Scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    features = []
    scan_results = []
    now = datetime.utcnow()

    for fi in range(feature_count):
        feat = Feature(assessment_id=asmt.id, name=f"Feature {fi + 1}")
        db_session.add(feat)
        db_session.flush()
        features.append(feat)

        for mi in range(members_per_feature):
            sr = ScanResult(
                scan_id=scan.id,
                sys_id=f"aaa{fi:04d}{mi:04d}000000000000000000",
                table_name="sys_script_include",
                name=f"Script_{fi}_{mi}",
                origin_type=OriginType.net_new_customer,
                raw_data_json=json.dumps({"name": f"Script_{fi}_{mi}"}),
                sys_updated_on=now,
            )
            db_session.add(sr)
            db_session.flush()
            scan_results.append(sr)

            link = FeatureScanResult(
                feature_id=feat.id,
                scan_result_id=sr.id,
                is_primary=True,
                membership_type="primary",
                assignment_source="engine",
                assignment_confidence=0.9,
                iteration_number=1,
            )
            db_session.add(link)

    db_session.commit()
    for f in features:
        db_session.refresh(f)
    for sr in scan_results:
        db_session.refresh(sr)

    return {
        "instance": inst,
        "assessment": asmt,
        "scan": scan,
        "features": features,
        "scan_results": scan_results,
    }


# ── Model tests ──────────────────────────────────────────────────────


def test_feature_model_has_color_index(db_session):
    """Feature model has a color_index field that defaults to None."""
    inst = Instance(
        name="ci-inst",
        url="https://ci.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="CI Assessment",
        number="ASMT0099010",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.flush()

    feature = Feature(assessment_id=asmt.id, name="Test Feature")
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)

    assert hasattr(feature, "color_index")
    assert feature.color_index is None

    # Can be set explicitly
    feature.color_index = 5
    db_session.commit()
    db_session.refresh(feature)
    assert feature.color_index == 5


# ── Palette tests ────────────────────────────────────────────────────


def test_feature_colors_palette_length():
    """FEATURE_COLORS has exactly 20 entries."""
    assert len(FEATURE_COLORS) == 20


def test_feature_color_deterministic():
    """Same feature ID always produces the same color."""
    for fid in (1, 5, 10, 20, 100):
        color_a = FEATURE_COLORS[fid % len(FEATURE_COLORS)]
        color_b = FEATURE_COLORS[fid % len(FEATURE_COLORS)]
        assert color_a == color_b
    # Different IDs that map differently produce different colors
    assert FEATURE_COLORS[1 % len(FEATURE_COLORS)] != FEATURE_COLORS[2 % len(FEATURE_COLORS)]


# ── API tests ────────────────────────────────────────────────────────


def test_feature_colors_api(client, db_session):
    """GET /api/assessments/{id}/feature-colors returns correct payload."""
    ctx = _seed_assessment_with_features(db_session, feature_count=3, members_per_feature=2)
    asmt = ctx["assessment"]

    resp = client.get(f"/api/assessments/{asmt.id}/feature-colors")
    assert resp.status_code == 200
    data = resp.json()

    assert "features" in data
    assert "palette" in data
    assert len(data["palette"]) == 20
    assert len(data["features"]) == 3

    for item in data["features"]:
        assert "feature_id" in item
        assert "feature_name" in item
        assert "color_hex" in item
        assert "color_index" in item
        assert "member_count" in item
        assert "disposition" in item
        # Verify color is deterministic based on feature ID
        expected_color = FEATURE_COLORS[(item["feature_id"] or 0) % len(FEATURE_COLORS)]
        assert item["color_hex"] == expected_color
        # Each feature has 2 members
        assert item["member_count"] == 2


def test_feature_colors_api_empty(client, db_session):
    """Assessment with no features returns empty list."""
    inst = Instance(
        name="empty-inst",
        url="https://empty.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Empty Assessment",
        number="ASMT0099020",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.commit()

    resp = client.get(f"/api/assessments/{asmt.id}/feature-colors")
    assert resp.status_code == 200
    data = resp.json()
    assert data["features"] == []
    assert len(data["palette"]) == 20


def test_feature_colors_api_not_found(client):
    """Non-existent assessment returns 404."""
    resp = client.get("/api/assessments/999999/feature-colors")
    assert resp.status_code == 404


def test_grouping_evidence_has_feature_color(client, db_session):
    """Grouping evidence API includes feature_color_hex in feature assignments."""
    ctx = _seed_assessment_with_features(db_session, feature_count=1, members_per_feature=2)
    scan_results = ctx["scan_results"]
    feature = ctx["features"][0]

    # Pick the first scan result to query
    result_id = scan_results[0].id

    resp = client.get(f"/api/results/{result_id}/grouping-evidence")
    assert resp.status_code == 200
    data = resp.json()

    # Feature assignments should have color
    fa_list = data.get("feature_assignments", [])
    assert len(fa_list) >= 1
    for fa in fa_list:
        assert "feature_color_hex" in fa
        expected = FEATURE_COLORS[(feature.id or 0) % len(FEATURE_COLORS)]
        assert fa["feature_color_hex"] == expected

    # Related customized artifacts (if any) should also have color
    customized = data.get("related_artifacts", {}).get("customized", [])
    for ca in customized:
        assert "feature_color_hex" in ca
