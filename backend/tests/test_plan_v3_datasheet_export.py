from scripts.export_plan_v3_datasheet import tier_for_company


def base_row(**overrides):
    row = {
        "company_type": "non_technical_buyer",
        "signal_types": "PROCUREMENT_NOTICE",
        "contact_kinds": "person",
        "penalties": [],
        "has_engineering_org": False,
    }
    row.update(overrides)
    return row


def test_tier_a_requires_buyer_live_need_and_person_contact() -> None:
    tier = tier_for_company(base_row())

    assert tier.label == "A"
    assert "person-level contact" in tier.reason


def test_tier_b_allows_role_inbox_for_live_buyer() -> None:
    tier = tier_for_company(base_row(contact_kinds="role_inbox"))

    assert tier.label == "B"


def test_tier_c_is_historical_procurement_buyer() -> None:
    tier = tier_for_company(
        base_row(signal_types="PROCUREMENT_HISTORY", contact_kinds="")
    )

    assert tier.label == "C"


def test_tier_x_excludes_software_vendors() -> None:
    tier = tier_for_company(base_row(company_type="software_vendor"))

    assert tier.label == "X"
    assert "software_vendor" in tier.reason


def test_unclear_high_intent_stays_tier_d() -> None:
    tier = tier_for_company(base_row(company_type="unclear"))

    assert tier.label == "D"
