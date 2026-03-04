"""Tests for the Temporal Clusterer engine."""

from datetime import datetime, timedelta

from sqlmodel import select

from src.models import (
    AppConfig,
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
from src.services.integration_properties import REASONING_TEMPORAL_GAP_THRESHOLD


def _setup_base(session):
    """Create minimal Instance + Assessment + Scan scaffolding."""
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


def test_temporal_clusterer_basic_cluster(db_session, db_engine):
    """3 records by same dev within 30-min gap -> 1 cluster of 3."""
    from src.engines.temporal_clusterer import run

    _inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - One",
        sys_updated_by="admin",
        sys_updated_on=base_time,
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script_include",
        name="SI - Two",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=20),
    )
    sr3 = ScanResult(
        scan_id=scan.id,
        sys_id="ccc333",
        table_name="sys_script",
        name="BR - Three",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=40),
    )
    db_session.add_all([sr1, sr2, sr3])
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["clusters_created"] == 1
    assert result["members_created"] == 3
    assert result["records_processed"] == 3
    assert result["records_skipped"] == 0

    clusters = db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()
    assert len(clusters) == 1

    cluster = clusters[0]
    assert cluster.developer == "admin"
    assert cluster.record_count == 3
    assert cluster.avg_gap_minutes == 20.0

    members = db_session.exec(
        select(TemporalClusterMember).where(
            TemporalClusterMember.temporal_cluster_id == cluster.id
        )
    ).all()
    assert len(members) == 3


def test_temporal_clusterer_gap_split(db_session, db_engine):
    """4 records where gap between 2nd and 3rd > threshold splits into 2 clusters of 2."""
    from src.engines.temporal_clusterer import run

    _inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    # First pair: 30 min gap (within 60-min threshold)
    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - One",
        sys_updated_by="admin",
        sys_updated_on=base_time,
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script",
        name="BR - Two",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=30),
    )
    # Gap of 120 min (exceeds 60-min threshold)
    # Second pair: 15 min gap (within threshold)
    sr3 = ScanResult(
        scan_id=scan.id,
        sys_id="ccc333",
        table_name="sys_script",
        name="BR - Three",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=150),
    )
    sr4 = ScanResult(
        scan_id=scan.id,
        sys_id="ddd444",
        table_name="sys_script",
        name="BR - Four",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=165),
    )
    db_session.add_all([sr1, sr2, sr3, sr4])
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["clusters_created"] == 2
    assert result["members_created"] == 4

    clusters = db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()
    assert len(clusters) == 2

    # Each cluster should have 2 members
    for cluster in clusters:
        assert cluster.record_count == 2
        members = db_session.exec(
            select(TemporalClusterMember).where(
                TemporalClusterMember.temporal_cluster_id == cluster.id
            )
        ).all()
        assert len(members) == 2


def test_temporal_clusterer_multiple_developers(db_session, db_engine):
    """Records from 2 devs -> separate clusters per developer."""
    from src.engines.temporal_clusterer import run

    _inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    # Developer A: 2 records within threshold
    sr_a1 = ScanResult(
        scan_id=scan.id,
        sys_id="a1",
        table_name="sys_script",
        name="A - Script 1",
        sys_updated_by="dev_alice",
        sys_updated_on=base_time,
    )
    sr_a2 = ScanResult(
        scan_id=scan.id,
        sys_id="a2",
        table_name="sys_script",
        name="A - Script 2",
        sys_updated_by="dev_alice",
        sys_updated_on=base_time + timedelta(minutes=15),
    )

    # Developer B: 3 records within threshold
    sr_b1 = ScanResult(
        scan_id=scan.id,
        sys_id="b1",
        table_name="sys_ui_policy",
        name="B - Policy 1",
        sys_updated_by="dev_bob",
        sys_updated_on=base_time + timedelta(minutes=5),
    )
    sr_b2 = ScanResult(
        scan_id=scan.id,
        sys_id="b2",
        table_name="sys_ui_policy",
        name="B - Policy 2",
        sys_updated_by="dev_bob",
        sys_updated_on=base_time + timedelta(minutes=25),
    )
    sr_b3 = ScanResult(
        scan_id=scan.id,
        sys_id="b3",
        table_name="sys_ui_policy",
        name="B - Policy 3",
        sys_updated_by="dev_bob",
        sys_updated_on=base_time + timedelta(minutes=45),
    )

    db_session.add_all([sr_a1, sr_a2, sr_b1, sr_b2, sr_b3])
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["clusters_created"] == 2  # one per developer

    clusters = db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()
    assert len(clusters) == 2

    developers = {c.developer for c in clusters}
    assert developers == {"dev_alice", "dev_bob"}

    alice_cluster = [c for c in clusters if c.developer == "dev_alice"][0]
    assert alice_cluster.record_count == 2

    bob_cluster = [c for c in clusters if c.developer == "dev_bob"][0]
    assert bob_cluster.record_count == 3


def test_temporal_clusterer_no_timestamp(db_session, db_engine):
    """Records missing sys_updated_on are skipped."""
    from src.engines.temporal_clusterer import run

    _inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    # Record with both fields -> will be included
    sr_good1 = ScanResult(
        scan_id=scan.id,
        sys_id="good1",
        table_name="sys_script",
        name="Good Record 1",
        sys_updated_by="admin",
        sys_updated_on=base_time,
    )
    sr_good2 = ScanResult(
        scan_id=scan.id,
        sys_id="good2",
        table_name="sys_script",
        name="Good Record 2",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=10),
    )

    # Record missing sys_updated_on -> should be skipped
    sr_no_time = ScanResult(
        scan_id=scan.id,
        sys_id="no_time",
        table_name="sys_script",
        name="No Timestamp",
        sys_updated_by="admin",
        sys_updated_on=None,
    )

    # Record missing sys_updated_by -> should be skipped
    sr_no_dev = ScanResult(
        scan_id=scan.id,
        sys_id="no_dev",
        table_name="sys_script",
        name="No Developer",
        sys_updated_by=None,
        sys_updated_on=base_time + timedelta(minutes=5),
    )

    db_session.add_all([sr_good1, sr_good2, sr_no_time, sr_no_dev])
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["records_skipped"] == 2
    assert result["records_processed"] == 2
    assert result["clusters_created"] == 1
    assert result["members_created"] == 2


def test_temporal_clusterer_idempotent(db_session, db_engine):
    """Running twice produces same result count (rows deleted and recreated)."""
    from src.engines.temporal_clusterer import run

    _inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - One",
        sys_updated_by="admin",
        sys_updated_on=base_time,
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script",
        name="BR - Two",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=20),
    )
    sr3 = ScanResult(
        scan_id=scan.id,
        sys_id="ccc333",
        table_name="sys_script",
        name="BR - Three",
        sys_updated_by="admin",
        sys_updated_on=base_time + timedelta(minutes=40),
    )
    db_session.add_all([sr1, sr2, sr3])
    db_session.flush()

    # First run
    result1 = run(asmt.id, db_session)
    assert result1["success"] is True
    assert result1["clusters_created"] == 1
    assert result1["members_created"] == 3

    clusters_after_run1 = db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()
    members_after_run1 = db_session.exec(
        select(TemporalClusterMember).where(
            TemporalClusterMember.assessment_id == asmt.id
        )
    ).all()

    # Second run
    result2 = run(asmt.id, db_session)
    assert result2["success"] is True
    assert result2["clusters_created"] == result1["clusters_created"]
    assert result2["members_created"] == result1["members_created"]

    clusters_after_run2 = db_session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == asmt.id)
    ).all()
    members_after_run2 = db_session.exec(
        select(TemporalClusterMember).where(
            TemporalClusterMember.assessment_id == asmt.id
        )
    ).all()

    assert len(clusters_after_run2) == len(clusters_after_run1)
    assert len(members_after_run2) == len(members_after_run1)


def test_temporal_clusterer_respects_instance_scoped_threshold(db_session, db_engine):
    """Instance-scoped temporal gap threshold overrides global/default values."""
    from src.engines.temporal_clusterer import run

    inst, asmt, scan = _setup_base(db_session)
    base_time = datetime(2025, 6, 1, 10, 0, 0)

    db_session.add(
        AppConfig(
            instance_id=None,
            key=REASONING_TEMPORAL_GAP_THRESHOLD,
            value="60",
            description="Global threshold",
        )
    )
    db_session.add(
        AppConfig(
            instance_id=inst.id,
            key=REASONING_TEMPORAL_GAP_THRESHOLD,
            value="10",
            description="Instance threshold",
        )
    )

    # 30-minute gap should cluster with global(60), but not with instance(10)
    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="inst_gap_1",
                table_name="sys_script",
                name="BR - One",
                sys_updated_by="admin",
                sys_updated_on=base_time,
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="inst_gap_2",
                table_name="sys_script",
                name="BR - Two",
                sys_updated_by="admin",
                sys_updated_on=base_time + timedelta(minutes=30),
            ),
        ]
    )
    db_session.flush()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["clusters_created"] == 0
    assert result["members_created"] == 0
