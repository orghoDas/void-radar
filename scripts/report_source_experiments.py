"""Report source-level funnel quality for real-world lead experiments."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from app.db.session import get_engine
from sqlalchemy import text

DEFAULT_CSV_PATH = Path("campaigns/source-experiments/source-quality-report.csv")
DEFAULT_MD_PATH = Path("campaigns/source-experiments/source-quality-report.md")
LEGACY_SOURCE_KEYS = frozenset({"y_combinator", "entrepreneur_first"})

CSV_COLUMNS = [
    "source_key",
    "source_type",
    "source_records",
    "linked_companies",
    "signal_companies",
    "signals",
    "score_20_companies",
    "score_50_companies",
    "ats_boards",
    "job_postings",
    "manual_verified_contacts",
    "provider_verified_contacts",
    "verified_contacts",
    "sent",
    "positive_replies",
    "meetings",
    "bounces",
    "record_to_signal_company_rate",
    "score20_to_signal_company_rate",
    "contact_to_score20_rate",
    "decision",
]


@dataclass(frozen=True)
class SourceExperimentReport:
    source_key: str
    source_type: str
    source_records: int
    linked_companies: int
    signal_companies: int
    signals: int
    score_20_companies: int
    score_50_companies: int
    ats_boards: int
    job_postings: int
    manual_verified_contacts: int
    provider_verified_contacts: int
    sent: int
    positive_replies: int
    meetings: int
    bounces: int

    @property
    def is_legacy(self) -> bool:
        return self.source_key in LEGACY_SOURCE_KEYS

    @property
    def verified_contacts(self) -> int:
        return self.manual_verified_contacts + self.provider_verified_contacts

    @property
    def record_to_signal_company_rate(self) -> float:
        return safe_rate(self.signal_companies, self.source_records)

    @property
    def score20_to_signal_company_rate(self) -> float:
        return safe_rate(self.score_20_companies, self.signal_companies)

    @property
    def contact_to_score20_rate(self) -> float:
        return safe_rate(self.verified_contacts, self.score_20_companies)

    @property
    def decision(self) -> str:
        if self.is_legacy:
            return "legacy_archived_source"
        if self.positive_replies or self.meetings:
            return "scale_commercially"
        if self.score_20_companies >= 20 and self.verified_contacts == 0:
            return "scale_source_fix_contacts"
        if self.source_records >= 20 and self.score_20_companies < 5:
            return "drop_or_rework_source"
        if self.source_records < 20:
            return "needs_more_sample"
        if self.verified_contacts:
            return "ready_for_small_outreach"
        return "keep_testing"

    def as_row(self) -> dict[str, str | int]:
        return {
            "source_key": self.source_key,
            "source_type": self.source_type,
            "source_records": self.source_records,
            "linked_companies": self.linked_companies,
            "signal_companies": self.signal_companies,
            "signals": self.signals,
            "score_20_companies": self.score_20_companies,
            "score_50_companies": self.score_50_companies,
            "ats_boards": self.ats_boards,
            "job_postings": self.job_postings,
            "manual_verified_contacts": self.manual_verified_contacts,
            "provider_verified_contacts": self.provider_verified_contacts,
            "verified_contacts": self.verified_contacts,
            "sent": self.sent,
            "positive_replies": self.positive_replies,
            "meetings": self.meetings,
            "bounces": self.bounces,
            "record_to_signal_company_rate": format_rate(
                self.record_to_signal_company_rate
            ),
            "score20_to_signal_company_rate": format_rate(
                self.score20_to_signal_company_rate
            ),
            "contact_to_score20_rate": format_rate(self.contact_to_score20_rate),
            "decision": self.decision,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--md-path", type=Path, default=DEFAULT_MD_PATH)
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include archived YC/EF source adapters in the report.",
    )
    args = parser.parse_args()

    reports = fetch_source_reports(include_legacy=args.include_legacy)
    write_csv(args.csv_path, reports)
    write_markdown(args.md_path, reports)

    print(f"sources_reported: {len(reports)}")
    print(f"csv_path: {args.csv_path}")
    print(f"md_path: {args.md_path}")
    return 0


def fetch_source_reports(*, include_legacy: bool = False) -> list[SourceExperimentReport]:
    with get_engine().connect() as conn:
        rows = conn.execute(text(source_report_sql())).mappings().all()

    reports = [
        SourceExperimentReport(
            source_key=str(row["source_key"]),
            source_type=str(row["source_type"] or ""),
            source_records=int(row["source_records"] or 0),
            linked_companies=int(row["linked_companies"] or 0),
            signal_companies=int(row["signal_companies"] or 0),
            signals=int(row["signals"] or 0),
            score_20_companies=int(row["score_20_companies"] or 0),
            score_50_companies=int(row["score_50_companies"] or 0),
            ats_boards=int(row["ats_boards"] or 0),
            job_postings=int(row["job_postings"] or 0),
            manual_verified_contacts=int(row["manual_verified_contacts"] or 0),
            provider_verified_contacts=int(row["provider_verified_contacts"] or 0),
            sent=int(row["sent"] or 0),
            positive_replies=int(row["positive_replies"] or 0),
            meetings=int(row["meetings"] or 0),
            bounces=int(row["bounces"] or 0),
        )
        for row in rows
    ]
    if include_legacy:
        return reports
    return [report for report in reports if not report.is_legacy]


def write_csv(path: Path, reports: list[SourceExperimentReport]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(report.as_row() for report in reports)


def write_markdown(path: Path, reports: list[SourceExperimentReport]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Source Quality Report",
        "",
        "This report measures real-world discovery sources through the full lead funnel.",
        "",
        "```text",
        "source -> company -> signal -> score -> contact -> outcome",
        "```",
        "",
    ]

    if not reports:
        lines.extend(["No source data found.", ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    lines.extend(
        [
            "| Source | Records | Signals | Score >=20 | Contacts | Outcomes | Decision |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for report in reports:
        outcomes = (
            f"{report.sent} sent / {report.positive_replies} positive / "
            f"{report.meetings} meetings"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    report.source_key,
                    str(report.source_records),
                    str(report.signals),
                    str(report.score_20_companies),
                    str(report.verified_contacts),
                    outcomes,
                    report.decision,
                ]
            )
            + " |"
        )

    lines.extend(["", "## Next Actions", ""])
    for report in reports:
        lines.append(f"- `{report.source_key}`: {action_for_decision(report.decision)}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def action_for_decision(decision: str) -> str:
    actions = {
        "scale_commercially": "Scale collection and outreach; it has commercial proof.",
        "scale_source_fix_contacts": (
            "Keep this source, but improve contact resolution before widening sends."
        ),
        "drop_or_rework_source": "Pause or rework parser/source selection.",
        "needs_more_sample": "Collect a larger sample before deciding.",
        "ready_for_small_outreach": "Run a small suppression-checked outreach test.",
        "keep_testing": "Keep bounded experiments and compare against other sources.",
        "legacy_archived_source": (
            "Archived legacy adapter; exclude from active MVP source decisions."
        ),
    }
    return actions.get(decision, "Review manually.")


def source_report_sql() -> str:
    return """
        with source_companies as (
            select
                s.source_key,
                s.source_type,
                sr.company_id
            from sources s
            join source_records sr on sr.source_id = s.id
            where sr.company_id is not null

            union

            select
                s.source as source_key,
                'signal' as source_type,
                s.company_id
            from signals s
            where s.company_id is not null
              and s.source is not null
              and s.source <> ''
        ),
        source_record_counts as (
            select
                s.source_key,
                s.source_type,
                count(sr.id) as source_records,
                count(distinct sr.company_id) filter (where sr.company_id is not null)
                    as linked_companies
            from sources s
            left join source_records sr on sr.source_id = s.id
            group by s.source_key, s.source_type
        ),
        signal_counts as (
            select
                source as source_key,
                count(*) as signals,
                count(distinct company_id) as signal_companies
            from signals
            where source is not null
              and source <> ''
            group by source
        ),
        latest_scores as (
            select distinct on (company_id)
                company_id,
                coalesce(total_score, overall_score) as total_score
            from scores
            order by company_id, calculated_at desc
        ),
        score_counts as (
            select
                sc.source_key,
                count(distinct sc.company_id) filter (where ls.total_score >= 20)
                    as score_20_companies,
                count(distinct sc.company_id) filter (where ls.total_score >= 50)
                    as score_50_companies
            from source_companies sc
            left join latest_scores ls on ls.company_id = sc.company_id
            group by sc.source_key
        ),
        ats_counts as (
            select
                sc.source_key,
                count(distinct ab.id) as ats_boards,
                count(distinct jp.id) as job_postings
            from source_companies sc
            left join ats_boards ab on ab.company_id = sc.company_id
            left join job_postings jp on jp.company_id = sc.company_id
            group by sc.source_key
        ),
        contact_counts as (
            select
                sc.source_key,
                count(distinct ct.id) filter (
                    where ct.verification_status = 'manual_verified'
                ) as manual_verified_contacts,
                count(distinct ct.id) filter (
                    where ct.verification_status = 'provider_verified'
                ) as provider_verified_contacts
            from source_companies sc
            left join contacts ct on ct.company_id = sc.company_id
            group by sc.source_key
        ),
        outcome_counts as (
            select
                sc.source_key,
                count(distinct o.id) filter (where o.event = 'sent') as sent,
                count(distinct o.id) filter (where o.event = 'positive_reply')
                    as positive_replies,
                count(distinct o.id) filter (where o.event = 'meeting_booked')
                    as meetings,
                count(distinct o.id) filter (where o.event = 'bounced') as bounces
            from source_companies sc
            left join outcomes o on o.company_id = sc.company_id
            group by sc.source_key
        )
        select
            coalesce(src.source_key, sig.source_key) as source_key,
            coalesce(src.source_type, 'signal') as source_type,
            coalesce(src.source_records, 0) as source_records,
            coalesce(src.linked_companies, 0) as linked_companies,
            coalesce(sig.signal_companies, 0) as signal_companies,
            coalesce(sig.signals, 0) as signals,
            coalesce(score.score_20_companies, 0) as score_20_companies,
            coalesce(score.score_50_companies, 0) as score_50_companies,
            coalesce(ats.ats_boards, 0) as ats_boards,
            coalesce(ats.job_postings, 0) as job_postings,
            coalesce(contact.manual_verified_contacts, 0) as manual_verified_contacts,
            coalesce(contact.provider_verified_contacts, 0) as provider_verified_contacts,
            coalesce(outcome.sent, 0) as sent,
            coalesce(outcome.positive_replies, 0) as positive_replies,
            coalesce(outcome.meetings, 0) as meetings,
            coalesce(outcome.bounces, 0) as bounces
        from source_record_counts src
        full outer join signal_counts sig on sig.source_key = src.source_key
        left join score_counts score
            on score.source_key = coalesce(src.source_key, sig.source_key)
        left join ats_counts ats
            on ats.source_key = coalesce(src.source_key, sig.source_key)
        left join contact_counts contact
            on contact.source_key = coalesce(src.source_key, sig.source_key)
        left join outcome_counts outcome
            on outcome.source_key = coalesce(src.source_key, sig.source_key)
        order by score_20_companies desc, source_records desc, source_key
    """


def safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0
    return numerator / denominator


def format_rate(value: float) -> str:
    return f"{value:.1%}"


if __name__ == "__main__":
    raise SystemExit(main())
