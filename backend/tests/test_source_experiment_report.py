from __future__ import annotations

from scripts.report_source_experiments import (
    SourceExperimentReport,
    action_for_decision,
)


def test_source_report_flags_signal_source_with_contact_blocker() -> None:
    report = SourceExperimentReport(
        source_key="hn-who-is-hiring",
        source_type="public_forum",
        source_records=100,
        linked_companies=100,
        signal_companies=100,
        signals=100,
        score_20_companies=80,
        score_50_companies=0,
        ats_boards=2,
        job_postings=1,
        manual_verified_contacts=0,
        provider_verified_contacts=0,
        sent=0,
        positive_replies=0,
        meetings=0,
        bounces=0,
    )

    assert report.decision == "scale_source_fix_contacts"
    assert report.record_to_signal_company_rate == 1
    assert report.score20_to_signal_company_rate == 0.8


def test_source_report_flags_commercial_proof_first() -> None:
    report = SourceExperimentReport(
        source_key="niche-job-board",
        source_type="job_board",
        source_records=12,
        linked_companies=10,
        signal_companies=10,
        signals=10,
        score_20_companies=3,
        score_50_companies=1,
        ats_boards=1,
        job_postings=5,
        manual_verified_contacts=2,
        provider_verified_contacts=0,
        sent=2,
        positive_replies=1,
        meetings=0,
        bounces=0,
    )

    assert report.decision == "scale_commercially"


def test_source_report_marks_yc_and_ef_as_legacy() -> None:
    for source_key in ["y_combinator", "entrepreneur_first"]:
        report = SourceExperimentReport(
            source_key=source_key,
            source_type="accelerator",
            source_records=100,
            linked_companies=100,
            signal_companies=0,
            signals=0,
            score_20_companies=0,
            score_50_companies=0,
            ats_boards=0,
            job_postings=0,
            manual_verified_contacts=0,
            provider_verified_contacts=0,
            sent=0,
            positive_replies=0,
            meetings=0,
            bounces=0,
        )

        assert report.is_legacy
        assert report.decision == "legacy_archived_source"
        assert "Archived legacy adapter" in action_for_decision(report.decision)
