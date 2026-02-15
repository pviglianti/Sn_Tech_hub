from datetime import datetime

from src.models import (
    CustomerUpdateXML,
    Instance,
    UpdateSet,
    VersionHistory,
)
from src.services.scan_executor import (
    _lookup_version_history_local,
    _resolve_update_set_id_local,
)


def test_lookup_version_history_by_update_name(db_session, sample_instance):
    row = VersionHistory(
        instance_id=sample_instance.id,
        sys_update_name="sys_script_abc123",
        sn_sys_id="vh-1",
        name="sys_script_abc123",
        state="current",
        sys_recorded_at=datetime(2026, 2, 7, 10, 0, 0),
    )
    db_session.add(row)
    db_session.commit()

    found = _lookup_version_history_local(
        session=db_session,
        instance_id=sample_instance.id,
        sys_update_name="sys_script_abc123",
        sys_metadata_sys_id="abc123",
    )
    assert found is not None
    assert found.sn_sys_id == "vh-1"


def test_lookup_version_history_fallback_by_sys_customer_update(db_session, sample_instance):
    row = VersionHistory(
        instance_id=sample_instance.id,
        sys_update_name="different_name",
        sn_sys_id="vh-2",
        name="different_name",
        state="current",
        customer_update_sys_id="cfg-999",
        sys_recorded_at=datetime(2026, 2, 7, 11, 0, 0),
    )
    db_session.add(row)
    db_session.commit()

    found = _lookup_version_history_local(
        session=db_session,
        instance_id=sample_instance.id,
        sys_update_name="no_match_here",
        sys_metadata_sys_id="cfg-999",
    )
    assert found is not None
    assert found.sn_sys_id == "vh-2"


def test_resolve_update_set_id_uses_remote_update_set(db_session, sample_instance):
    update_set = UpdateSet(
        instance_id=sample_instance.id,
        sn_sys_id="us-remote-1",
        name="Remote Loaded Set",
    )
    db_session.add(update_set)
    db_session.commit()
    db_session.refresh(update_set)

    customer_update = CustomerUpdateXML(
        instance_id=sample_instance.id,
        sn_sys_id="cux-1",
        name="sys_script_abc123",
        remote_update_set="us-remote-1",
    )
    db_session.add(customer_update)
    db_session.commit()
    db_session.refresh(customer_update)

    resolved = _resolve_update_set_id_local(
        session=db_session,
        instance_id=sample_instance.id,
        customer_update=customer_update,
    )
    assert resolved == update_set.id
