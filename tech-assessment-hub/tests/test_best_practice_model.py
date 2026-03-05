"""Tests for the BestPractice model."""

import pytest
from sqlmodel import Session, select

from src.models import BestPractice, BestPracticeCategory


def test_best_practice_category_enum_values():
    assert BestPracticeCategory.technical_server == "technical_server"
    assert BestPracticeCategory.technical_client == "technical_client"
    assert BestPracticeCategory.architecture == "architecture"
    assert BestPracticeCategory.process == "process"
    assert BestPracticeCategory.security == "security"
    assert BestPracticeCategory.performance == "performance"
    assert BestPracticeCategory.upgradeability == "upgradeability"
    assert BestPracticeCategory.catalog == "catalog"
    assert BestPracticeCategory.integration == "integration"


def test_best_practice_create(db_session: Session):
    bp = BestPractice(
        code="TEST_001",
        title="Test Best Practice",
        category=BestPracticeCategory.technical_server,
        severity="high",
        description="A test best practice.",
        detection_hint="Look for test pattern",
        recommendation="Do something else",
        is_active=True,
    )
    db_session.add(bp)
    db_session.commit()
    db_session.refresh(bp)

    assert bp.id is not None
    assert bp.code == "TEST_001"
    assert bp.category == BestPracticeCategory.technical_server
    assert bp.is_active is True


def test_best_practice_unique_code(db_session: Session):
    bp1 = BestPractice(
        code="UNIQUE_001",
        title="First",
        category=BestPracticeCategory.process,
        severity="medium",
    )
    db_session.add(bp1)
    db_session.commit()

    bp2 = BestPractice(
        code="UNIQUE_001",
        title="Duplicate",
        category=BestPracticeCategory.process,
        severity="medium",
    )
    db_session.add(bp2)
    with pytest.raises(Exception):
        db_session.commit()


def test_best_practice_defaults(db_session: Session):
    bp = BestPractice(
        code="DEFAULTS_001",
        title="Defaults Test",
        category=BestPracticeCategory.security,
        severity="low",
    )
    db_session.add(bp)
    db_session.commit()
    db_session.refresh(bp)

    assert bp.is_active is True
    assert bp.description is None
    assert bp.applies_to is None
    assert bp.source_url is None
    assert bp.created_at is not None
    assert bp.updated_at is not None


def test_best_practice_filter_by_category(db_session: Session):
    for i, cat in enumerate(["technical_server", "technical_client", "architecture"]):
        db_session.add(BestPractice(
            code=f"FILTER_{i}",
            title=f"Filter test {i}",
            category=BestPracticeCategory(cat),
            severity="medium",
        ))
    db_session.commit()

    server_bps = db_session.exec(
        select(BestPractice).where(
            BestPractice.category == BestPracticeCategory.technical_server
        )
    ).all()
    assert len(server_bps) == 1
    assert server_bps[0].code == "FILTER_0"
