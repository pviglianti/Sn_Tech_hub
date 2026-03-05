from src.models import Assessment, AssessmentState, AssessmentType, Feature, FeatureRecommendation, Instance


def _seed_feature(db_session):
    inst = Instance(
        name="rec-inst",
        url="https://rec-inst.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Recommendation Assessment",
        number="ASMT0088001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.flush()

    feature = Feature(assessment_id=asmt.id, name="Legacy Approval Feature")
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)
    return feature


def test_upsert_feature_recommendation_create_and_update(db_session):
    from src.mcp.tools.core.feature_recommendation import handle

    feature = _seed_feature(db_session)

    created = handle(
        {
            "feature_id": feature.id,
            "recommendation_type": "replace",
            "ootb_capability_name": "Flow Designer Approval",
            "product_name": "ServiceNow ITSM Pro",
            "sku_or_license": "ITSM_PRO",
            "fit_confidence": 0.84,
            "requires_plugins": ["com.glide.hub.flow_engine"],
            "evidence": {"signals": ["code_reference"]},
        },
        db_session,
    )
    assert created["success"] is True
    rec_id = created["recommendation_id"]
    assert rec_id is not None

    updated = handle(
        {
            "feature_id": feature.id,
            "recommendation_id": rec_id,
            "recommendation_type": "refactor",
            "fit_confidence": 0.66,
            "rationale": "Partial OOTB replacement possible.",
        },
        db_session,
    )
    assert updated["success"] is True
    assert updated["recommendation_type"] == "refactor"

    row = db_session.get(FeatureRecommendation, rec_id)
    assert row is not None
    assert row.recommendation_type == "refactor"
    assert row.fit_confidence == 0.66
    assert row.rationale == "Partial OOTB replacement possible."


def test_registry_includes_feature_recommendation_tool():
    from src.mcp.registry import build_registry

    registry = build_registry()
    assert registry.has_tool("upsert_feature_recommendation")

