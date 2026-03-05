"""Tests for BestPractice seed data."""

from sqlmodel import Session, select

from src.models import BestPractice, BestPracticeCategory
from src.seed_data import seed_best_practices


def test_seed_best_practices_creates_records(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    assert len(all_bps) >= 40  # Design calls for ~41 seed checks


def test_seed_best_practices_idempotent(db_session: Session):
    seed_best_practices(db_session)
    count_1 = len(db_session.exec(select(BestPractice)).all())
    seed_best_practices(db_session)
    count_2 = len(db_session.exec(select(BestPractice)).all())
    assert count_1 == count_2  # Running twice doesn't duplicate


def test_seed_best_practices_all_categories_covered(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    categories_present = {bp.category for bp in all_bps}
    # At minimum: technical_server, technical_client, architecture, process, security, performance, upgradeability
    expected = {
        BestPracticeCategory.technical_server,
        BestPracticeCategory.technical_client,
        BestPracticeCategory.architecture,
        BestPracticeCategory.process,
        BestPracticeCategory.security,
        BestPracticeCategory.performance,
        BestPracticeCategory.upgradeability,
    }
    assert expected.issubset(categories_present)


def test_seed_best_practices_codes_unique(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    codes = [bp.code for bp in all_bps]
    assert len(codes) == len(set(codes))  # No duplicate codes


def test_seed_best_practices_critical_checks_present(db_session: Session):
    seed_best_practices(db_session)
    critical_codes = {"SRV_CURRENT_UPDATE_BEFORE", "SRV_CURRENT_UPDATE_AFTER",
                      "ARCH_EXTEND_CORE_TABLE", "SEC_CREDENTIALS_IN_CODE"}
    all_codes = {bp.code for bp in db_session.exec(select(BestPractice)).all()}
    assert critical_codes.issubset(all_codes)
