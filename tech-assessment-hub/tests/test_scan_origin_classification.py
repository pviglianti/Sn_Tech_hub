from src.models import HeadOwner, OriginType
from src.services.scan_executor import (
    _classify_origin,
    _is_store_application_current,
    _normalize_version_ref,
)


def test_store_application_current_with_customization_is_modified_ootb():
    """Guide: OOB current + customer signal → modified_ootb (was incorrectly ootb_untouched)."""
    version_record = {"source_table": "sys_store_app", "source": "abc123"}

    origin_type, head_owner = _classify_origin(version_record, has_metadata_customization=True)

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_store_application_source_text_with_customization_is_modified_ootb():
    """Guide: OOB current + customer signal → modified_ootb."""
    version_record = {"source_table": "sys_update_set", "source": "Store Application: Incident"}

    origin_type, head_owner = _classify_origin(version_record, has_metadata_customization=True)

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_sys_upgrade_history_current_with_customization_is_modified_ootb():
    """Guide: OOB current + customer signal → modified_ootb."""
    version_record = {"source_table": "sys_upgrade_history", "source": "0f3a42"}

    origin_type, head_owner = _classify_origin(version_record, has_metadata_customization=True)

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_system_upgrade_source_text_with_customization_is_modified_ootb():
    """Guide: OOB current + customer signal → modified_ootb."""
    version_record = {"source_table": "sys_update_set", "source": "System Upgrade: Washington DC Patch 2"}

    origin_type, head_owner = _classify_origin(version_record, has_metadata_customization=True)

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_customer_source_with_baseline_is_modified_ootb():
    version_record = {"source_table": "sys_update_set", "source": "d6f2b2"}

    origin_type, head_owner = _classify_origin(version_record, has_metadata_customization=True)

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_customer_source_without_baseline_is_net_new_customer():
    version_record = {"source_table": "sys_update_set", "source": "d6f2b2"}

    origin_type, head_owner = _classify_origin(
        version_record, has_metadata_customization=False, has_customer_update=True,
    )

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


def test_version_record_only_without_customer_update_is_unknown():
    """Guide: hasAny + !hasOOB + !hasCustomer + !changed → unknown (history exists, can't classify)."""
    version_record = {"source_table": "sys_update_set", "source": "d6f2b2"}

    origin_type, head_owner = _classify_origin(
        version_record, has_metadata_customization=False, has_customer_update=False,
    )

    assert origin_type == OriginType.unknown
    assert head_owner == HeadOwner.unknown


def test_has_customer_update_without_version_marks_net_new():
    origin_type, head_owner = _classify_origin(None, has_metadata_customization=False, has_customer_update=True)

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


def test_empty_current_source_but_customer_update_marks_net_new():
    version_record = {"source_table": "", "source": "", "source_display": ""}

    origin_type, head_owner = _classify_origin(
        version_record,
        has_metadata_customization=False,
        has_customer_update=True,
    )

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


# --- Earliest version history fallback (step 4) tests ---

def test_earliest_vh_update_set_source_marks_customer_created():
    """No CUX, no metadata_customization, but earliest VH source is update_set -- Customer Created."""
    earliest = {"source_table": "sys_update_set", "source": "abc123"}

    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        earliest_version_record=earliest,
    )

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


def test_earliest_vh_store_source_marks_ootb_modified():
    """No CUX, no metadata_customization, but earliest VH source is Store -- OOTB Modified."""
    earliest = {"source_table": "sys_store_app", "source": "def456"}

    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        earliest_version_record=earliest,
    )

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_earliest_vh_upgrade_source_marks_ootb_modified():
    """No CUX, no metadata_customization, but earliest VH source is Upgrade -- OOTB Modified."""
    earliest = {"source_table": "sys_upgrade_history", "source": "ghi789"}

    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        earliest_version_record=earliest,
    )

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_earliest_vh_ignored_when_customer_update_exists():
    """Earliest VH fallback should NOT be used when customer_update exists (step 3 wins)."""
    earliest = {"source_table": "sys_store_app", "source": "xyz"}

    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=True,
        earliest_version_record=earliest,
    )

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


def test_no_data_at_all_still_unknown():
    """No version, no CUX, no metadata_customization, no earliest VH -- unknown."""
    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        earliest_version_record=None,
    )

    assert origin_type == OriginType.unknown_no_history
    assert head_owner == HeadOwner.unknown


# --- Utility tests ---

def test_normalize_version_ref_prefers_display_value():
    value = {"value": "sys_store_app", "display_value": "Store Application: Incident"}
    assert _normalize_version_ref(value) == "Store Application: Incident"


def test_store_detection_handles_display_value_dict():
    version_record = {"source": {"value": "sys_store_app", "display_value": "Store Application: Incident"}}
    assert _is_store_application_current(version_record) is True


# --- Gap 1: OOB current + customer history → modified_ootb (not ootb_untouched) ---

def test_ootb_current_with_customer_update_is_modified_ootb():
    """Guide: hasOOB + hasCustomer → modified_ootb. Current code wrongly returns ootb_untouched."""
    version_record = {"source_table": "sys_store_app", "source": "abc123"}

    origin_type, head_owner = _classify_origin(
        version_record,
        has_metadata_customization=False,
        has_customer_update=True,
    )

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_ootb_current_with_changed_baseline_is_modified_ootb():
    """Guide: hasOOB + changed → modified_ootb."""
    version_record = {"source_table": "sys_upgrade_history", "source": "0f3a42"}

    origin_type, head_owner = _classify_origin(
        version_record,
        has_metadata_customization=False,
        changed_baseline_now=True,
    )

    assert origin_type == OriginType.modified_ootb
    assert head_owner == HeadOwner.store_upgrade


def test_ootb_current_no_customer_signals_is_ootb_untouched():
    """Guide: hasOOB + !hasCustomer + !changed → ootb_untouched."""
    version_record = {"source_table": "sys_store_app", "source": "abc123"}

    origin_type, head_owner = _classify_origin(
        version_record,
        has_metadata_customization=False,
        has_customer_update=False,
        changed_baseline_now=False,
    )

    assert origin_type == OriginType.ootb_untouched
    assert head_owner == HeadOwner.store_upgrade


# --- Gap 2: changed_baseline_now as signal for net_new_customer ---

def test_changed_baseline_without_ootb_is_net_new_customer():
    """Guide: !hasOOB + changed → net_new_customer."""
    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        changed_baseline_now=True,
    )

    assert origin_type == OriginType.net_new_customer
    assert head_owner == HeadOwner.customer


# --- Gap 3: unknown (has history) vs unknown_no_history (no history at all) ---

def test_earliest_vh_unclassifiable_source_is_unknown():
    """Guide: hasAny but !hasOOB + !hasCustomer + !changed → unknown (not unknown_no_history).

    Earliest VH from a source that is neither OOB nor update_set means history
    exists but we can't classify it.
    """
    earliest = {"source_table": "sys_some_other_table", "source": "xyz789"}

    origin_type, head_owner = _classify_origin(
        None,
        has_metadata_customization=False,
        has_customer_update=False,
        earliest_version_record=earliest,
    )

    assert origin_type == OriginType.unknown
    assert head_owner == HeadOwner.unknown


def test_current_version_exists_but_unclassifiable_is_unknown():
    """Guide: hasAny but !hasOOB + !hasCustomer + !changed → unknown.

    Current version record exists (history exists) but no signals matched.
    """
    version_record = {"source_table": "sys_update_set", "source": "d6f2b2"}

    origin_type, head_owner = _classify_origin(
        version_record,
        has_metadata_customization=False,
        has_customer_update=False,
        changed_baseline_now=False,
    )

    assert origin_type == OriginType.unknown
    assert head_owner == HeadOwner.unknown
