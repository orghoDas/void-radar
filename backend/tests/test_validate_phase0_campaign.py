from pathlib import Path

from scripts.validate_phase0_campaign import validate_campaign_csv


def write_csv(path: Path, rows: list[str]) -> None:
    header = (
        "company,domain,segment,country,trigger_type,trigger_summary,"
        "trigger_url,role_title,role_age_days,target_person,target_role,email,"
        "email_source,email_verification,message_angle,status,outcome,notes"
    )
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def test_phase0_campaign_template_row_is_send_ready(tmp_path: Path) -> None:
    csv_path = tmp_path / "campaign.csv"
    write_csv(
        csv_path,
        [
            (
                "Example AI,example.ai,B2B SaaS,United States,stale_hiring,"
                "Backend role open 92 days,https://boards.greenhouse.io/example/jobs/1,"
                "Senior Backend Engineer,92,Jane Doe,VP Engineering,jane@example.ai,"
                "verified_provider,provider_verified,Backend hiring bottleneck,ready,,"
            )
        ],
    )

    result = validate_campaign_csv(csv_path)

    assert result.rows_seen == 1
    assert result.send_ready == 1
    assert result.issues == []


def test_phase0_campaign_rejects_missing_trigger_and_unverified_email(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "campaign.csv"
    write_csv(
        csv_path,
        [
            (
                "Example AI,example.ai,B2B SaaS,United States,stale_hiring,"
                "Backend role open 92 days,,Senior Backend Engineer,92,Jane Doe,"
                "VP Engineering,jane@example.ai,verified_provider,unverified,"
                "Backend hiring bottleneck,ready,,"
            )
        ],
    )

    result = validate_campaign_csv(csv_path)

    assert result.rows_seen == 1
    assert result.send_ready == 0
    assert {issue.field for issue in result.issues} == {
        "trigger_url",
        "email_verification",
    }


def test_phase0_campaign_rejects_generic_or_external_email(tmp_path: Path) -> None:
    csv_path = tmp_path / "campaign.csv"
    write_csv(
        csv_path,
        [
            (
                "Example AI,example.ai,B2B SaaS,United States,stale_hiring,"
                "Backend role open 92 days,https://boards.greenhouse.io/example/jobs/1,"
                "Senior Backend Engineer,92,Jane Doe,VP Engineering,info@other.ai,"
                "verified_provider,provider_verified,Backend hiring bottleneck,ready,,"
            )
        ],
    )

    result = validate_campaign_csv(csv_path)

    assert result.rows_seen == 1
    assert result.send_ready == 0
    assert {issue.message for issue in result.issues} == {
        "must be a person-level email for Phase 0",
        "email domain must match company domain",
    }
