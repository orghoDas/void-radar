"""Export scored companies into a contact-provider target CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.db.session import get_engine
from app.identity.normalize import normalize_domain
from sqlalchemy import text

DEFAULT_TARGETS_PATH = Path("campaigns/phase-6/contact-provider-targets.csv")
DEFAULT_IMPORT_TEMPLATE_PATH = Path("campaigns/phase-6/verified-contact-import-template.csv")

GENERIC_OR_BAD_DOMAINS = {
    "bit.ly",
    "github.com",
    "linkedin.com",
    "node.js",
    "x.com",
}

IMPORT_COLUMNS = [
    "company_id",
    "company_domain",
    "company",
    "target_roles",
    "full_name",
    "role",
    "email",
    "source_type",
    "source_url",
    "provider_name",
    "verification_status",
    "confidence",
    "reason_to_write",
    "evidence_urls",
    "score",
]

TARGET_COLUMNS = [
    "company_id",
    "company",
    "domain",
    "score_id",
    "score",
    "fit_score",
    "intent_score",
    "target_roles",
    "reason_to_write",
    "evidence_urls",
    "signal_types",
    "positive_reasons",
    "penalties",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-total-score", type=int, default=20)
    parser.add_argument("--targets-path", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument(
        "--import-template-path",
        type=Path,
        default=DEFAULT_IMPORT_TEMPLATE_PATH,
    )
    args = parser.parse_args()

    targets = fetch_targets(limit=args.limit, min_total_score=args.min_total_score)
    write_targets(args.targets_path, targets)
    write_import_template(args.import_template_path, targets)

    print(f"targets_exported: {len(targets)}")
    print(f"targets_path: {args.targets_path}")
    print(f"import_template_path: {args.import_template_path}")
    return 0


def fetch_targets(*, limit: int, min_total_score: int) -> list[dict]:
    rows = []
    with get_engine().connect() as conn:
        result = conn.execute(
            text(
                """
                with latest_scores as (
                    select distinct on (s.company_id) s.*
                    from scores s
                    order by s.company_id, s.calculated_at desc
                )
                select
                    c.id as company_id,
                    c.canonical_name as company,
                    c.canonical_domain as domain,
                    ls.id as score_id,
                    coalesce(ls.total_score, ls.overall_score) as score,
                    coalesce(ls.fit_score, ls.company_fit) as fit_score,
                    coalesce(ls.intent_score, ls.opportunity_strength) as intent_score,
                    ls.scoring_inputs,
                    ls.positive_reasons,
                    ls.penalties
                from latest_scores ls
                join companies c on c.id = ls.company_id
                where coalesce(ls.total_score, ls.overall_score) >= :min_total_score
                  and c.canonical_domain is not null
                  and c.canonical_domain <> ''
                  and not exists (
                        select 1
                        from suppression sp
                        where lower(coalesce(sp.domain, '')) = lower(c.canonical_domain)
                  )
                order by
                    coalesce(ls.total_score, ls.overall_score) desc,
                    c.canonical_name
                limit :limit
                """
            ),
            {"limit": limit * 2, "min_total_score": min_total_score},
        ).mappings()
        rows = [dict(row) for row in result]

    targets = []
    for row in rows:
        domain = normalize_domain(row["domain"])
        if not is_provider_target_domain(domain):
            continue

        scoring_inputs = load_json_value(row["scoring_inputs"])
        trigger_evidence = scoring_inputs.get("trigger_evidence", [])
        signal_types = signal_types_from_evidence(trigger_evidence)
        evidence_urls = evidence_urls_from_evidence(trigger_evidence)
        reason_to_write = reason_to_write_from_evidence(
            trigger_evidence,
            load_json_value(row["positive_reasons"], default=[]),
        )
        if not reason_to_write or not evidence_urls:
            continue

        targets.append(
            {
                "company_id": str(row["company_id"]),
                "company": row["company"],
                "domain": domain,
                "score_id": str(row["score_id"]),
                "score": int(row["score"]),
                "fit_score": int(row["fit_score"]),
                "intent_score": int(row["intent_score"]),
                "target_roles": "; ".join(target_roles_for_signals(signal_types)),
                "reason_to_write": reason_to_write,
                "evidence_urls": ";".join(evidence_urls),
                "signal_types": ";".join(signal_types),
                "positive_reasons": "; ".join(
                    load_json_value(row["positive_reasons"], default=[])
                ),
                "penalties": "; ".join(load_json_value(row["penalties"], default=[])),
            }
        )
        if len(targets) >= limit:
            break

    return targets


def write_targets(path: Path, targets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(targets)


def write_import_template(path: Path, targets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=IMPORT_COLUMNS)
        writer.writeheader()
        for target in targets:
            writer.writerow(
                {
                    "company_id": target["company_id"],
                    "company_domain": target["domain"],
                    "company": target["company"],
                    "target_roles": target["target_roles"],
                    "source_type": "verified_provider",
                    "provider_name": "",
                    "verification_status": "provider_verified",
                    "confidence": "0.95",
                    "reason_to_write": target["reason_to_write"],
                    "evidence_urls": target["evidence_urls"],
                    "score": target["score"],
                }
            )


def is_provider_target_domain(domain: str | None) -> bool:
    if not domain or domain in GENERIC_OR_BAD_DOMAINS:
        return False
    if domain.count(".") > 3:
        return False
    suffix = domain.rsplit(".", 1)[-1]
    return suffix.isalpha() and 2 <= len(suffix) <= 12


def target_roles_for_signals(signal_types: list[str]) -> list[str]:
    roles = []
    if any(
        signal_type in signal_types
        for signal_type in ("STALE_ENGINEERING_ROLE", "AGING_ENGINEERING_ROLE")
    ):
        roles.extend(["CTO", "VP Engineering", "Head of Product", "Founder"])
    if "HIRING_SPIKE" in signal_types:
        roles.extend(["CTO", "VP Engineering", "COO", "Founder"])
    if "OPERATIONS_SOFTWARE_NEED" in signal_types:
        roles.extend(["COO", "Head of Operations", "Head of Digital", "Founder"])
    if "HIRING_DISCOVERY" in signal_types and not roles:
        roles.extend(["CTO", "VP Engineering", "Head of Talent", "Founder"])
    if "FUNDING_EVENT" in signal_types:
        roles.append("Founder")
    return sorted(set(roles))


def signal_types_from_evidence(trigger_evidence: list[dict]) -> list[str]:
    signal_types = []
    for evidence in trigger_evidence:
        signal_type = evidence.get("signal_type")
        if signal_type and signal_type not in signal_types:
            signal_types.append(str(signal_type))
    return signal_types


def evidence_urls_from_evidence(trigger_evidence: list[dict]) -> list[str]:
    urls = []
    for evidence in trigger_evidence:
        for url in evidence.get("job_urls", []):
            if url and url not in urls:
                urls.append(str(url))
        source_url = evidence.get("source_url")
        if source_url and source_url not in urls:
            urls.append(str(source_url))
    return urls


def reason_to_write_from_evidence(
    trigger_evidence: list[dict],
    positive_reasons: list[str],
) -> str:
    for evidence in trigger_evidence:
        description = str(evidence.get("description") or "").strip()
        if description:
            return description
    return positive_reasons[0] if positive_reasons else ""


def load_json_value(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


if __name__ == "__main__":
    raise SystemExit(main())
