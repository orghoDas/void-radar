#!/usr/bin/env python3
"""Compare accelerator portfolio pages against the current YC baseline.

The probe is read-only. It parses public portfolio pages and reports which
fields appear to be available before we build a proper ingestion actor.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_USER_AGENT = "VoidRadarSourceProbe/0.1 (+https://www.voidstudio.tech/)"
SOURCES = {
    "entrepreneur_first": {
        "label": "Entrepreneurs First",
        "url": "https://www.joinef.com/portfolio/",
        "cache_name": "ef-portfolio.html",
    },
    "seedcamp": {
        "label": "Seedcamp",
        "url": "https://seedcamp.com/our-companies/",
        "cache_name": "seedcamp-companies.html",
    },
    "antler": {
        "label": "Antler",
        "url": "https://www.antler.co/portfolio",
        "cache_name": "antler-portfolio.html",
    },
    "techstars": {
        "label": "Techstars",
        "url": "https://www.techstars.com/portfolio",
        "cache_name": "techstars-portfolio.html",
    },
}


@dataclass(frozen=True)
class ProbePerson:
    name: str | None = None
    role: str | None = None
    linkedin_url: str | None = None


@dataclass
class ProbeRecord:
    company_name: str
    source_record_id: str | None = None
    source_url: str | None = None
    website: str | None = None
    description: str | None = None
    location: str | None = None
    industry: str | None = None
    year_or_stage: str | None = None
    company_linkedin_url: str | None = None
    people: list[ProbePerson] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


@dataclass
class SourceProbeResult:
    source_key: str
    source_label: str
    source_url: str | None
    records_found: int
    records_sampled: int
    company_names: int
    websites: int
    descriptions: int
    locations: int
    industries: int
    year_or_stage: int
    company_linkedin: int
    people: int
    people_with_linkedin: int
    emails: int
    quality_score: int
    notes: list[str]
    sample_records: list[dict]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark accelerator portfolio source data coverage."
    )
    parser.add_argument(
        "--sources",
        default="entrepreneur_first,seedcamp,antler,techstars",
        help="Comma-separated sources to probe.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional directory for cached source HTML files.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached HTML files and fail if a selected cache file is missing.",
    )
    parser.add_argument(
        "--write-cache",
        action="store_true",
        help="Save fetched HTML to --cache-dir.",
    )
    parser.add_argument(
        "--include-yc-baseline",
        action="store_true",
        help="Read current YC coverage from the local database.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
    )
    args = parser.parse_args()

    selected_sources = [source.strip() for source in args.sources.split(",")]
    unknown_sources = [source for source in selected_sources if source not in SOURCES]
    if unknown_sources:
        raise ValueError(f"Unknown sources: {', '.join(unknown_sources)}")

    results: list[SourceProbeResult] = []
    if args.include_yc_baseline:
        yc_baseline = load_yc_baseline(limit=args.limit)
        if yc_baseline:
            results.append(yc_baseline)

    for source_key in selected_sources:
        source = SOURCES[source_key]
        source_url = str(source["url"])
        source_html = read_source_html(
            source_key=source_key,
            source_url=source_url,
            cache_name=str(source["cache_name"]),
            cache_dir=args.cache_dir,
            use_cache=args.use_cache,
            write_cache=args.write_cache,
            timeout=args.timeout,
        )
        records = parse_source_records(source_key, source_html)
        results.append(
            summarize_records(
                source_key=source_key,
                source_label=str(source["label"]),
                source_url=source_url,
                records=records,
                limit=args.limit,
                notes=source_notes(source_key),
            )
        )

    if args.format == "json":
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print(render_table(results))
        print()
        print(json.dumps([asdict(result) for result in results], indent=2))

    return 0


def read_source_html(
    *,
    source_key: str,
    source_url: str,
    cache_name: str,
    cache_dir: Path | None,
    use_cache: bool,
    write_cache: bool,
    timeout: float,
) -> str:
    cache_path = cache_dir / cache_name if cache_dir else None
    if use_cache:
        if not cache_path or not cache_path.exists():
            raise FileNotFoundError(
                f"Missing cache for {source_key}: {cache_path or cache_name}"
            )
        return cache_path.read_text(encoding="utf-8", errors="replace")

    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html, */*;q=0.1",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")

    if write_cache and cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(content, encoding="utf-8")

    return content


def parse_source_records(source_key: str, source_html: str) -> list[ProbeRecord]:
    parsers: dict[str, Callable[[str], list[ProbeRecord]]] = {
        "entrepreneur_first": parse_entrepreneur_first,
        "seedcamp": parse_seedcamp,
        "antler": parse_antler,
        "techstars": parse_techstars,
    }
    return parsers[source_key](source_html)


def parse_entrepreneur_first(source_html: str) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    for block in re.findall(
        r'<div class="tile tile--company\b.*?</div><!-- /tile--company -->',
        source_html,
        flags=re.DOTALL,
    ):
        company_name = attr_value(block, "data-companyname")
        if not company_name:
            continue
        slug = attr_value(block, "data-companyslug") or slugify(company_name)

        people = [
            ProbePerson(
                name=clean_text(person_name),
                role=clean_text(role),
                linkedin_url=person_url if "linkedin.com/" in person_url else None,
            )
            for role, person_url, person_name in re.findall(
                r'<div class="meta__row__role[^"]*"[^>]*>(.*?)</div>'
                r'.*?<a class="text-link" href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                flags=re.DOTALL,
            )
        ]
        locations = extract_class_values(block, "locationtag")
        categories = extract_class_values(block, "categorytag")
        records.append(
            ProbeRecord(
                company_name=clean_text(company_name),
                source_record_id=slug,
                source_url=f"https://www.joinef.com/portfolio/#{slug}",
                description=extract_class_text(block, "tile__description"),
                location=", ".join(locations) or None,
                industry=", ".join(categories) or None,
                year_or_stage=extract_meta_value(block, "Founded"),
                people=people,
                emails=extract_emails(block),
            )
        )

    return dedupe_records(records)


def parse_seedcamp(source_html: str) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    blocks = split_before(source_html, '<div class="company__item mix')
    for block in blocks:
        if "company__item__name" not in block:
            continue

        company_name = extract_class_text(block, "company__item__name")
        if not company_name:
            continue

        class_terms = re.findall(r'<div class="company__item mix ([^"]+)"', block)
        industries = []
        if class_terms:
            industries = [
                clean_text(term.replace("-", " "))
                for term in class_terms[0].split()
                if term not in {"visible", "portfolio", "selected"}
                and not term.isdigit()
            ]

        records.append(
            ProbeRecord(
                company_name=company_name,
                website=first_external_url(block, exclude_domains=("seedcamp.com",)),
                description=extract_class_text(
                    block,
                    "company__item__description__content",
                ),
                industry=", ".join(industries) or None,
                year_or_stage=extract_class_text(block, "company__item__year"),
                emails=extract_emails(block),
            )
        )

    return dedupe_records(records)


def parse_antler(source_html: str) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    blocks = re.findall(
        r'<div[^>]+role="listitem"[^>]*>.*?(?=<div[^>]+role="listitem"|\Z)',
        source_html,
        flags=re.DOTALL,
    )
    if not blocks:
        blocks = split_before(source_html, 'fs-cmsfilter-field="name"')
    for block in blocks:
        company_name = extract_cms_field(block, "name")
        if not company_name:
            continue

        records.append(
            ProbeRecord(
                company_name=company_name,
                website=first_external_url(
                    block,
                    exclude_domains=(
                        "antler.co",
                        "cdn.prod.website-files.com",
                        "uploads-ssl.webflow.com",
                    ),
                ),
                description=extract_cms_field(block, "description"),
                location=extract_cms_field(block, "location"),
                industry=extract_cms_field(block, "sector"),
                year_or_stage=extract_cms_field(block, "year")
                or extract_cms_field(block, "stage"),
                emails=extract_emails(block),
            )
        )

    return dedupe_records(records)


def parse_techstars(source_html: str) -> list[ProbeRecord]:
    text = html.unescape(source_html)
    records: list[ProbeRecord] = []
    for block in re.findall(
        r'\{\\"id\\":\\"[0-9a-f-]+\\".*?\\"session_year\\":(?:null|\d+)\}',
        text,
        flags=re.DOTALL,
    ):
        name = escaped_json_value(block, "name")
        if not name:
            continue

        records.append(
            ProbeRecord(
                company_name=name,
                website=escaped_json_value(block, "website"),
                description=escaped_json_value(block, "description"),
                industry=escaped_json_value(block, "vertical"),
                year_or_stage=escaped_json_value(block, "session_year")
                or escaped_json_value(block, "stage"),
                company_linkedin_url=escaped_json_value(block, "linkedin_url"),
                emails=extract_emails(block),
            )
        )

    if records:
        return dedupe_records(records)

    return parse_techstars_plain_json(text)


def parse_techstars_plain_json(text: str) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    for block in re.findall(r'\{"id":.*?"updatedAt":.*?\}', text):
        name = plain_json_value(block, "name")
        if not name:
            continue
        records.append(
            ProbeRecord(
                company_name=name,
                website=plain_json_value(block, "website"),
                description=plain_json_value(block, "description"),
                industry=plain_json_value(block, "vertical"),
                year_or_stage=plain_json_value(block, "session_year")
                or plain_json_value(block, "stage"),
                company_linkedin_url=plain_json_value(block, "linkedin_url"),
                emails=extract_emails(block),
            )
        )
    return dedupe_records(records)


def summarize_records(
    *,
    source_key: str,
    source_label: str,
    source_url: str | None,
    records: list[ProbeRecord],
    limit: int,
    notes: list[str],
) -> SourceProbeResult:
    sampled = records[:limit]
    people = [person for record in sampled for person in record.people]
    score = quality_score(sampled)
    return SourceProbeResult(
        source_key=source_key,
        source_label=source_label,
        source_url=source_url,
        records_found=len(records),
        records_sampled=len(sampled),
        company_names=sum(1 for record in sampled if record.company_name),
        websites=sum(1 for record in sampled if record.website),
        descriptions=sum(1 for record in sampled if record.description),
        locations=sum(1 for record in sampled if record.location),
        industries=sum(1 for record in sampled if record.industry),
        year_or_stage=sum(1 for record in sampled if record.year_or_stage),
        company_linkedin=sum(1 for record in sampled if record.company_linkedin_url),
        people=len(people),
        people_with_linkedin=sum(1 for person in people if person.linkedin_url),
        emails=sum(len(record.emails) for record in sampled),
        quality_score=score,
        notes=notes,
        sample_records=[record_to_sample(record) for record in sampled[:5]],
    )


def quality_score(records: list[ProbeRecord]) -> int:
    if not records:
        return 0

    record_count = len(records)
    field_score = (
        coverage(records, lambda record: bool(record.website)) * 25
        + coverage(records, lambda record: bool(record.description)) * 15
        + coverage(records, lambda record: bool(record.industry)) * 10
        + coverage(records, lambda record: bool(record.location)) * 10
        + coverage(records, lambda record: bool(record.company_linkedin_url)) * 10
        + min(sum(len(record.people) for record in records) / record_count, 1.0) * 20
        + min(
            sum(
                1
                for record in records
                for person in record.people
                if person.linkedin_url
            )
            / record_count,
            1.0,
        )
        * 10
    )
    return round(field_score)


def coverage(records: list[ProbeRecord], predicate: Callable[[ProbeRecord], bool]) -> float:
    if not records:
        return 0
    return sum(1 for record in records if predicate(record)) / len(records)


def source_notes(source_key: str) -> list[str]:
    return {
        "entrepreneur_first": [
            "Strong named founder/operator coverage with LinkedIn.",
            "Official company website is not consistently exposed on the listing.",
        ],
        "seedcamp": [
            "Strong company website and description coverage.",
            "Founder/contact person data is not visible in the main listing.",
        ],
        "antler": [
            "Company-heavy source; useful for websites, sectors, locations, years.",
            "Founder/contact person data needs a second-stage website/profile pass.",
        ],
        "techstars": [
            "Structured company records include websites and company LinkedIn URLs.",
            "Founder/contact person data is not generally present in portfolio records.",
        ],
    }[source_key]


def load_yc_baseline(limit: int) -> SourceProbeResult | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return None

    engine = create_engine(database_url)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                select
                    count(*) as companies,
                    count(*) filter (where canonical_name is not null) as names,
                    count(*) filter (where canonical_domain is not null) as websites,
                    count(*) filter (where description is not null) as descriptions,
                    count(*) filter (where country is not null or city is not null)
                        as locations,
                    count(*) filter (where industry is not null) as industries,
                    count(*) filter (where company_stage is not null) as stages
                from companies
                """
            )
        ).one()
        founder_row = connection.execute(
            text(
                """
                select
                    count(*) as people,
                    count(fp.linkedin_url) as people_with_linkedin,
                    count(fp.email) as emails
                from founders f
                left join founder_profiles fp on fp.founder_id = f.id
                """
            )
        ).one()
        sample_rows = connection.execute(
            text(
                """
                select canonical_name, canonical_domain, description, industry,
                       country, city, company_stage
                from companies
                order by canonical_name
                limit :limit
                """
            ),
            {"limit": min(limit, 5)},
        ).all()

    sampled = min(int(row.companies), limit)
    records = [
        ProbeRecord(
            company_name=sample.canonical_name,
            website=f"https://{sample.canonical_domain}"
            if sample.canonical_domain
            else None,
            description=sample.description,
            industry=sample.industry,
            location=", ".join(
                part for part in [sample.city, sample.country] if part
            )
            or None,
            year_or_stage=sample.company_stage,
        )
        for sample in sample_rows
    ]
    return SourceProbeResult(
        source_key="yc_local_baseline",
        source_label="Y Combinator local DB",
        source_url=None,
        records_found=int(row.companies),
        records_sampled=sampled,
        company_names=int(row.names),
        websites=int(row.websites),
        descriptions=int(row.descriptions),
        locations=int(row.locations),
        industries=int(row.industries),
        year_or_stage=int(row.stages),
        company_linkedin=0,
        people=int(founder_row.people),
        people_with_linkedin=int(founder_row.people_with_linkedin),
        emails=int(founder_row.emails),
        quality_score=aggregate_quality_score(
            sampled=sampled,
            websites=int(row.websites),
            descriptions=int(row.descriptions),
            industries=int(row.industries),
            locations=int(row.locations),
            company_linkedin=0,
            people=int(founder_row.people),
            people_with_linkedin=int(founder_row.people_with_linkedin),
        ),
        notes=[
            "Baseline is read from the local Void Radar database.",
            "YC founder emails are only counted when explicit profile emails exist.",
        ],
        sample_records=[record_to_sample(record) for record in records],
    )


def aggregate_quality_score(
    *,
    sampled: int,
    websites: int,
    descriptions: int,
    industries: int,
    locations: int,
    company_linkedin: int,
    people: int,
    people_with_linkedin: int,
) -> int:
    if not sampled:
        return 0
    return round(
        min(websites / sampled, 1.0) * 25
        + min(descriptions / sampled, 1.0) * 15
        + min(industries / sampled, 1.0) * 10
        + min(locations / sampled, 1.0) * 10
        + min(company_linkedin / sampled, 1.0) * 10
        + min(people / sampled, 1.0) * 20
        + min(people_with_linkedin / sampled, 1.0) * 10
    )


def render_table(results: list[SourceProbeResult]) -> str:
    headers = [
        "Source",
        "Records",
        "Websites",
        "People",
        "People LinkedIn",
        "Company LinkedIn",
        "Emails",
        "Score",
    ]
    rows = [
        [
            result.source_label,
            f"{result.records_sampled}/{result.records_found}",
            str(result.websites),
            str(result.people),
            str(result.people_with_linkedin),
            str(result.company_linkedin),
            str(result.emails),
            str(result.quality_score),
        ]
        for result in results
    ]
    widths = [
        max(len(row[index]) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    lines = [format_row(headers, widths), format_row(["-" * w for w in widths], widths)]
    lines.extend(format_row(row, widths) for row in rows)
    return "\n".join(lines)


def format_row(row: list[str], widths: list[int]) -> str:
    return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))


def record_to_sample(record: ProbeRecord) -> dict:
    return {
        "company_name": record.company_name,
        "source_record_id": record.source_record_id,
        "source_url": record.source_url,
        "website": record.website,
        "description": record.description,
        "location": record.location,
        "industry": record.industry,
        "year_or_stage": record.year_or_stage,
        "company_linkedin_url": record.company_linkedin_url,
        "people": [asdict(person) for person in record.people[:3]],
        "emails": record.emails,
    }


def dedupe_records(records: list[ProbeRecord]) -> list[ProbeRecord]:
    deduped: dict[str, ProbeRecord] = {}
    for record in records:
        key = clean_text(record.company_name).lower()
        if key and key not in deduped:
            deduped[key] = record
    return list(deduped.values())


def split_before(value: str, marker: str) -> list[str]:
    parts = value.split(marker)
    return [parts[0], *[marker + part for part in parts[1:]]]


def extract_class_text(block: str, class_name: str) -> str | None:
    match = re.search(
        rf'<[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</[^>]+>',
        block,
        flags=re.DOTALL,
    )
    return clean_text(match.group(1)) if match else None


def extract_class_values(block: str, class_name: str) -> list[str]:
    return [
        value
        for value in (
            clean_text(match)
            for match in re.findall(
                rf'<[^>]*class=[\'"][^\'"]*\b{re.escape(class_name)}\b[^\'"]*[\'"]'
                r"[^>]*>(.*?)</[^>]+>",
                block,
                flags=re.DOTALL,
            )
        )
        if value
    ]


def extract_meta_value(block: str, label: str) -> str | None:
    match = re.search(
        rf'>{re.escape(label)}</[^>]+>\s*<[^>]+>(.*?)</[^>]+>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return clean_text(match.group(1)) if match else None


def extract_cms_field(block: str, field_name: str) -> str | None:
    match = re.search(
        rf'fs-cmsfilter-field="{re.escape(field_name)}"[^>]*>(.*?)</[^>]+>',
        block,
        flags=re.DOTALL,
    )
    return clean_text(match.group(1)) if match else None


def attr_value(block: str, attr_name: str) -> str | None:
    match = re.search(rf'{re.escape(attr_name)}="([^"]*)"', block)
    return html.unescape(match.group(1)) if match else None


def first_external_url(block: str, *, exclude_domains: tuple[str, ...]) -> str | None:
    for url in re.findall(r'href=["\'](https?://[^"\']+)["\']', block):
        lowered = url.lower()
        if any(domain in lowered for domain in exclude_domains):
            continue
        if any(
            skipped in lowered
            for skipped in (
                "linkedin.com/",
                "twitter.com/",
                "x.com/",
                "facebook.com/",
                "instagram.com/",
            )
        ):
            continue
        return html.unescape(url)
    return None


def escaped_json_value(block: str, key: str) -> str | None:
    quoted = re.search(
        rf'\\"{re.escape(key)}\\":\\"(.*?)\\"',
        block,
        flags=re.DOTALL,
    )
    if quoted:
        return clean_json_text(quoted.group(1))

    unquoted = re.search(rf'\\"{re.escape(key)}\\":(null|\d+)', block)
    if not unquoted or unquoted.group(1) == "null":
        return None
    return unquoted.group(1)


def plain_json_value(block: str, key: str) -> str | None:
    quoted = re.search(rf'"{re.escape(key)}":"(.*?)"', block, flags=re.DOTALL)
    if quoted:
        return clean_json_text(quoted.group(1))

    unquoted = re.search(rf'"{re.escape(key)}":(null|\d+)', block)
    if not unquoted or unquoted.group(1) == "null":
        return None
    return unquoted.group(1)


def clean_json_text(value: str) -> str | None:
    cleaned = clean_text(value.replace("\\/", "/").replace('\\"', '"'))
    return cleaned or None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def slugify(value: str | None) -> str:
    cleaned = clean_text(value) or ""
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned.lower()).strip("-")
    return slug or "unknown"


def extract_emails(value: str) -> list[str]:
    return sorted(
        {
            email.lower()
            for email in re.findall(
                r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                html.unescape(value),
                flags=re.IGNORECASE,
            )
        }
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Source probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
