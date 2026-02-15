from src.models import HeadOwner, Instance, OriginType, ScanResult
from src.server import _resolve_head_owner_label


def _build_result(origin_type, head_owner):
    return ScanResult(
        scan_id=1,
        sys_id="abc123",
        table_name="sys_script",
        name="Test",
        origin_type=origin_type,
        head_owner=head_owner,
    )


def test_modified_ootb_uses_sn_label():
    result = _build_result(OriginType.modified_ootb, HeadOwner.customer)
    instance = Instance(
        name="Acme DEV",
        company="Acme",
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    assert _resolve_head_owner_label(result, instance) == "SN"


def test_net_new_customer_prefers_company_name():
    result = _build_result(OriginType.net_new_customer, HeadOwner.customer)
    instance = Instance(
        name="Acme DEV",
        company="Acme Corp",
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    assert _resolve_head_owner_label(result, instance) == "Acme Corp"


def test_net_new_customer_falls_back_to_instance_name():
    result = _build_result(OriginType.net_new_customer, HeadOwner.customer)
    instance = Instance(
        name="Acme DEV",
        company=None,
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    assert _resolve_head_owner_label(result, instance) == "Acme DEV"
