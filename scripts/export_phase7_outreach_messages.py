"""Export personalized pilot outreach drafts from Phase 7 observations."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from app.db.session import get_engine
from sqlalchemy import text

DEFAULT_OUTREACH_PATH = Path("campaigns/phase-6/outreach-pilot-export.csv")
DEFAULT_MESSAGES_CSV_PATH = Path("campaigns/phase-7/outreach-message-drafts.csv")
DEFAULT_MESSAGES_MD_PATH = Path("campaigns/phase-7/outreach-message-drafts.md")
DEFAULT_OUTCOMES_PATH = Path("campaigns/phase-7/outreach-outcomes-template.csv")

OBSERVATION_SOURCE = "phase7_company_research"
DEFAULT_SENDER_NAME = "Orgho"

MESSAGE_COLUMNS = [
    "send_status",
    "company",
    "domain",
    "email",
    "contact_name",
    "role",
    "subject",
    "body",
    "word_count",
    "reason_to_write",
    "personalization_basis",
    "evidence_urls",
    "company_id",
    "contact_id",
    "score_id",
]

OUTCOME_COLUMNS = [
    "company",
    "domain",
    "email",
    "contact_id",
    "company_id",
    "event",
    "occurred_at",
    "notes",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outreach-path", type=Path, default=DEFAULT_OUTREACH_PATH)
    parser.add_argument("--csv-path", type=Path, default=DEFAULT_MESSAGES_CSV_PATH)
    parser.add_argument("--md-path", type=Path, default=DEFAULT_MESSAGES_MD_PATH)
    parser.add_argument("--outcomes-path", type=Path, default=DEFAULT_OUTCOMES_PATH)
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME)
    args = parser.parse_args()

    rows = load_outreach_rows(args.outreach_path)
    observations = fetch_observations([row["company_id"] for row in rows])
    drafts = [
        draft_for_row(row, observations.get(row["company_id"], {}), args.sender_name)
        for row in rows
    ]

    write_messages_csv(args.csv_path, drafts)
    write_messages_md(args.md_path, drafts)
    write_outcomes_template(args.outcomes_path, drafts)

    print(f"drafts_exported: {len(drafts)}")
    print(f"csv_path: {args.csv_path}")
    print(f"md_path: {args.md_path}")
    print(f"outcomes_path: {args.outcomes_path}")
    return 0


def draft_for_row(
    row: dict[str, str],
    observations: dict[str, Any],
    sender_name: str,
) -> dict[str, str]:
    contact_name = row.get("contact_name") or first_name_from_email(row["email"])
    project_area = project_area_from_observations(observations)
    basis = personalization_basis(observations)
    detail_sentence = detail_sentence_for(observations)

    subject = f"Quick thought on {project_area}"
    body = "\n".join(
        [
            f"Hi {contact_name},",
            "",
            (
                f"I saw {row['company']} is hiring. {capitalize_first(detail_sentence)} "
                f"That usually means there is approved work waiting on capacity."
            ),
            "",
            (
                "Void helps teams ship backend integrations, internal tools, and "
                "automation support without waiting on every full-time hire."
            ),
            "",
            (
                f"Worth sending 2-3 concrete ways we could reduce the load around "
                f"{project_area}?"
            ),
            "",
            f"Best,\n{sender_name}",
        ]
    )

    return {
        "send_status": "draft",
        "company": row["company"],
        "domain": row["domain"],
        "email": row["email"],
        "contact_name": contact_name,
        "role": row.get("role", ""),
        "subject": subject,
        "body": body,
        "word_count": str(word_count(body)),
        "reason_to_write": row["reason_to_write"],
        "personalization_basis": basis,
        "evidence_urls": row["evidence_urls"],
        "company_id": row["company_id"],
        "contact_id": row["contact_id"],
        "score_id": row["score_id"],
    }


def project_area_from_observations(observations: dict[str, Any]) -> str:
    service_fit = lower_join(observations.get("service_fit_evidence"))
    tech = lower_join(observations.get("technology_mentions"))
    customer_terms = lower_join(observations.get("customer_terms"))
    positioning = lower_join(observations.get("positioning"))

    if "decision" in positioning or "performance" in positioning:
        return "decision and performance systems"
    if (
        "manufacturing" in positioning
        or whole_term_in_text("erp", service_fit)
        or whole_term_in_text("qms", service_fit)
        or "plant floor" in service_fit
        or "machines" in service_fit
    ):
        return "plant workflow and systems integration"
    if "agent" in positioning or "workflow" in tech or "automation" in tech:
        return "agent workflow integrations"
    if "operations" in customer_terms or "operations" in service_fit:
        return "operations workflow automation"
    return "the open engineering work"


def detail_sentence_for(observations: dict[str, Any]) -> str:
    positioning = clean_scalar(observations.get("positioning"))
    service_fit = clean_list(observations.get("service_fit_evidence"))
    tech_mentions = clean_list(observations.get("technology_mentions"))

    if positioning:
        return f"your site says: {trim_sentence(positioning, 24)}."
    if service_fit:
        return f"the site points to {trim_sentence(service_fit[0], 24)}."
    if tech_mentions:
        return f"the site mentions {', '.join(tech_mentions[:3])}."
    return "the hiring signal points to product or engineering load."


def personalization_basis(observations: dict[str, Any]) -> str:
    bits = []
    positioning = clean_scalar(observations.get("positioning"))
    technology = clean_list(observations.get("technology_mentions"))
    service_fit = clean_list(observations.get("service_fit_evidence"))
    if positioning:
        bits.append(f"positioning: {trim_sentence(positioning, 18)}")
    if technology:
        bits.append(f"tech: {', '.join(technology[:5])}")
    if service_fit:
        bits.append(f"fit: {trim_sentence(service_fit[0], 18)}")
    return " | ".join(bits)


def fetch_observations(company_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not company_ids:
        return {}

    params = {f"company_id_{index}": company_id for index, company_id in enumerate(company_ids)}
    placeholders = ", ".join(f":{key}" for key in params)
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                f"""
                select company_id, field_name, value
                from observations
                where source = :source
                  and company_id in ({placeholders})
                order by collected_at desc, created_at desc
                """
            ),
            {"source": OBSERVATION_SOURCE, **params},
        ).mappings()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            company_id = str(row["company_id"])
            field_name = str(row["field_name"])
            result.setdefault(company_id, {})
            if field_name not in result[company_id]:
                result[company_id][field_name] = parse_jsonish(row["value"])
    return result


def load_outreach_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        rows = [normalize_row(row) for row in csv.DictReader(csv_file)]
    return [
        row
        for row in rows
        if row.get("company_id") and row.get("contact_id") and row.get("email")
    ]


def write_messages_csv(path: Path, drafts: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=MESSAGE_COLUMNS)
        writer.writeheader()
        writer.writerows(drafts)


def write_messages_md(path: Path, drafts: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Phase 7 Outreach Message Drafts", ""]
    for draft in drafts:
        lines.extend(
            [
                f"## {draft['company']}",
                "",
                f"To: {draft['email']}",
                "",
                f"Subject: {draft['subject']}",
                "",
                "```text",
                draft["body"],
                "```",
                "",
                f"Basis: {draft['personalization_basis']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outcomes_template(path: Path, drafts: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTCOME_COLUMNS)
        writer.writeheader()
        for draft in drafts:
            writer.writerow(
                {
                    "company": draft["company"],
                    "domain": draft["domain"],
                    "email": draft["email"],
                    "contact_id": draft["contact_id"],
                    "company_id": draft["company_id"],
                    "event": "",
                    "occurred_at": "",
                    "notes": "",
                }
            )


def first_name_from_email(email: str) -> str:
    local_part = email.split("@", 1)[0]
    cleaned = re.sub(r"[^a-zA-Z]+", " ", local_part).strip()
    if not cleaned:
        return "there"
    return cleaned.split()[0].capitalize()


def trim_sentence(value: str, max_words: int) -> str:
    cleaned = value.strip()
    sentence_match = re.match(r"^(.+?[.!?])(?:\s|$)", cleaned)
    if sentence_match:
        sentence_words = sentence_match.group(1).split()
        if 5 <= len(sentence_words) <= max_words:
            return sentence_match.group(1).rstrip(".")

    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned.rstrip(".")
    trimmed_words = words[:max_words]
    while trimmed_words and trimmed_words[-1].lower().strip(".,;:") in {
        "and",
        "as",
        "for",
        "not",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }:
        trimmed_words.pop()
    return " ".join(trimmed_words).rstrip(".,;:")


def capitalize_first(value: str) -> str:
    if not value:
        return value
    return value[0].upper() + value[1:]


def word_count(value: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", value))


def lower_join(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value).lower()
    return str(value or "").lower()


def whole_term_in_text(term: str, value: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", value))


def clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def clean_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().strip('"')
    return ""


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    if text_value[0] in "[{\"":
        try:
            return json.loads(text_value)
        except json.JSONDecodeError:
            return text_value.strip('"')
    return text_value


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}


if __name__ == "__main__":
    raise SystemExit(main())
