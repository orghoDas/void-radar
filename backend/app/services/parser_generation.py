"""Phase 8 - hybrid parser generation for repeated page layouts.

An LLM proposes CSS selectors once per source layout; everything afterwards is
deterministic. The model's output is treated as a hypothesis, not a fact: it is
replayed against known pages and only persisted as ``active`` when it clears a
success threshold. Anything below that is stored as ``failed`` so a later run
can see what was already tried, and is never used for extraction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_client import LlmClient, LlmError

# A parser must work on this share of sample pages before it can go active.
DEFAULT_SUCCESS_THRESHOLD = 0.8
# Below this many samples the success rate is not meaningful.
MIN_SAMPLE_SIZE = 5
# A page counts as parsed only if the selectors find at least this many jobs.
MIN_JOBS_PER_PAGE = 1

REQUIRED_SELECTOR_FIELDS = ("job_container", "title", "url")
OPTIONAL_SELECTOR_FIELDS = ("location", "department")

SYSTEM_PROMPT = """You extract CSS selectors from careers pages.

Return a JSON object with these keys:
  job_container: CSS selector matching one element per job posting
  title:         CSS selector for the job title, relative to job_container
  url:           CSS selector for the job link (an <a>), relative to job_container
  location:      CSS selector for location, relative to job_container, or null
  department:    CSS selector for team/department, relative to job_container, or null

Rules:
- Selectors must be plain CSS that a standard engine can run.
- Prefer stable structural or semantic selectors over generated class hashes.
- job_container must match repeated sibling elements, one per job.
- Return null for a field you cannot locate. Do not invent selectors.
"""


# Modern careers pages open with kilobytes of <head>, inline scripts and CSS.
# Naive truncation feeds the model none of the job markup, and it correctly
# answers "I cannot find these selectors". Strip the noise first so the budget
# is spent on structure.
PROMPT_HTML_BUDGET = 24000
STRIPPED_TAGS = ("script", "style", "noscript", "svg", "head", "iframe", "path")
# Framework hydration payloads and inline data URIs blow the budget on one node.
NOISY_ATTRIBUTES = ("style", "srcset", "sizes", "integrity", "nonce")


def condense_html_for_prompt(html: str, budget: int = PROMPT_HTML_BUDGET) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag_name in STRIPPED_TAGS:
        for node in soup.find_all(tag_name):
            node.decompose()

    for node in soup.find_all(True):
        for attribute in list(node.attrs):
            if attribute in NOISY_ATTRIBUTES or attribute.startswith("data-"):
                del node.attrs[attribute]

    text_value = str(soup)
    collapsed = re.sub(r"\s+", " ", text_value)
    return collapsed[:budget]


@dataclass(frozen=True)
class PageSample:
    url: str
    html: str


@dataclass(frozen=True)
class ParserSelectors:
    job_container: str
    title: str
    url: str
    location: str | None = None
    department: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "job_container": self.job_container,
            "title": self.title,
            "url": self.url,
            "location": self.location,
            "department": self.department,
        }


@dataclass
class PageParseResult:
    url: str
    jobs: list[dict[str, str | None]] = field(default_factory=list)
    error: str | None = None
    min_jobs: int = MIN_JOBS_PER_PAGE

    @property
    def succeeded(self) -> bool:
        return self.error is None and len(self.jobs) >= self.min_jobs


@dataclass
class ValidationResult:
    sample_size: int
    pages_succeeded: int
    page_results: list[PageParseResult]

    @property
    def success_rate(self) -> float:
        if not self.sample_size:
            return 0.0
        return self.pages_succeeded / self.sample_size

    def meets_threshold(
        self,
        threshold: float = DEFAULT_SUCCESS_THRESHOLD,
        *,
        min_sample_size: int = MIN_SAMPLE_SIZE,
    ) -> bool:
        return self.sample_size >= min_sample_size and self.success_rate >= threshold


def selectors_from_payload(payload: dict[str, Any]) -> ParserSelectors:
    """Validate raw model output before it is allowed anywhere near the database."""
    missing = [
        name
        for name in REQUIRED_SELECTOR_FIELDS
        if not isinstance(payload.get(name), str) or not payload[name].strip()
    ]
    if missing:
        raise LlmError(f"Model omitted required selector fields: {', '.join(missing)}")

    optional: dict[str, str | None] = {}
    for name in OPTIONAL_SELECTOR_FIELDS:
        value = payload.get(name)
        optional[name] = value.strip() if isinstance(value, str) and value.strip() else None

    return ParserSelectors(
        job_container=payload["job_container"].strip(),
        title=payload["title"].strip(),
        url=payload["url"].strip(),
        **optional,
    )


def generate_selectors(client: LlmClient, samples: list[PageSample]) -> ParserSelectors:
    if not samples:
        raise LlmError("At least one sample page is required to generate a parser")

    prompt_sections = []
    for sample in samples[:3]:
        condensed = condense_html_for_prompt(sample.html)
        prompt_sections.append(f"URL: {sample.url}\nHTML:\n{condensed}")

    payload = client.complete_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt="\n\n---\n\n".join(prompt_sections),
    )
    return selectors_from_payload(payload)


def _text_of(node: Any, selector: str | None) -> str | None:
    if not selector:
        return None
    found = node.select_one(selector)
    if found is None:
        return None
    value = found.get_text(" ", strip=True)
    return value or None


def apply_selectors(
    selectors: ParserSelectors,
    html: str,
    *,
    base_url: str,
) -> list[dict[str, str | None]]:
    """Deterministic extraction. No model call happens here."""
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[dict[str, str | None]] = []

    for container in soup.select(selectors.job_container):
        title = _text_of(container, selectors.title)
        link = container.select_one(selectors.url)
        href = link.get("href") if link is not None else None
        if not title or not href:
            continue
        jobs.append(
            {
                "title": title,
                "url": urljoin(base_url, str(href)),
                "location": _text_of(container, selectors.location),
                "department": _text_of(container, selectors.department),
            }
        )
    return jobs


def validate_selectors(
    selectors: ParserSelectors,
    samples: list[PageSample],
    *,
    min_jobs_per_page: int = MIN_JOBS_PER_PAGE,
) -> ValidationResult:
    results: list[PageParseResult] = []
    for sample in samples:
        try:
            jobs = apply_selectors(selectors, sample.html, base_url=sample.url)
            results.append(
                PageParseResult(url=sample.url, jobs=jobs, min_jobs=min_jobs_per_page)
            )
        except Exception as error:  # invalid selector syntax, malformed HTML
            results.append(
                PageParseResult(url=sample.url, error=str(error), min_jobs=min_jobs_per_page)
            )

    return ValidationResult(
        sample_size=len(samples),
        pages_succeeded=sum(1 for result in results if result.succeeded),
        page_results=results,
    )


def persist_parser_version(
    db: Session,
    *,
    source_key: str,
    schema_version: str,
    selectors: ParserSelectors,
    validation: ValidationResult,
    threshold: float = DEFAULT_SUCCESS_THRESHOLD,
    min_sample_size: int = MIN_SAMPLE_SIZE,
    notes: str | None = None,
) -> dict[str, Any]:
    """Store the attempt, marking it active only when validation clears the bar."""
    active = validation.meets_threshold(threshold, min_sample_size=min_sample_size)
    status = "active" if active else "failed"
    parser_id = str(uuid4())
    now = datetime.now(UTC)

    if active:
        # One active parser per source: retire whatever it replaces.
        db.execute(
            text(
                """
                update parser_versions
                set status = 'retired', updated_at = :now
                where source_key = :source_key and status = 'active'
                """
            ),
            {"source_key": source_key, "now": now},
        )

    db.execute(
        text(
            """
            insert into parser_versions (
                id, source_key, schema_version, selectors, generated_at,
                validated_at, success_rate, sample_size, status, notes,
                created_at, updated_at
            ) values (
                :id, :source_key, :schema_version, :selectors, :now,
                :now, :success_rate, :sample_size, :status, :notes, :now, :now
            )
            """
        ),
        {
            "id": parser_id,
            "source_key": source_key,
            "schema_version": schema_version,
            "selectors": json.dumps(selectors.as_dict()),
            "now": now,
            "success_rate": round(validation.success_rate, 4),
            "sample_size": validation.sample_size,
            "status": status,
            "notes": notes,
        },
    )
    db.commit()

    return {
        "parser_version_id": parser_id,
        "source_key": source_key,
        "schema_version": schema_version,
        "status": status,
        "success_rate": round(validation.success_rate, 4),
        "sample_size": validation.sample_size,
        "selectors": selectors.as_dict(),
    }


def load_active_parser(db: Session, source_key: str) -> ParserSelectors | None:
    row = db.execute(
        text(
            """
            select selectors from parser_versions
            where source_key = :source_key and status = 'active'
            order by generated_at desc limit 1
            """
        ),
        {"source_key": source_key},
    ).first()
    if row is None:
        return None

    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return selectors_from_payload(payload)


def generate_and_validate(
    db: Session,
    client: LlmClient,
    *,
    source_key: str,
    schema_version: str,
    samples: list[PageSample],
    threshold: float = DEFAULT_SUCCESS_THRESHOLD,
    min_sample_size: int = MIN_SAMPLE_SIZE,
    min_jobs_per_page: int = MIN_JOBS_PER_PAGE,
) -> dict[str, Any]:
    selectors = generate_selectors(client, samples)
    validation = validate_selectors(selectors, samples, min_jobs_per_page=min_jobs_per_page)
    result = persist_parser_version(
        db,
        source_key=source_key,
        schema_version=schema_version,
        selectors=selectors,
        validation=validation,
        threshold=threshold,
        min_sample_size=min_sample_size,
    )
    result["pages_succeeded"] = validation.pages_succeeded
    result["page_results"] = [
        {"url": page.url, "jobs_found": len(page.jobs), "error": page.error}
        for page in validation.page_results
    ]
    return result
