"""Classify a company as a software builder or a software buyer (Phase C).

Keyword matching cannot read a multilingual company set. A model reading the
site can, in any language, which is the point of doing this with an LLM rather
than an ever-growing word list.

The verdict is a claim until it is corroborated. Every signal the model reports
must be quoted from the fetched page text; anything it cannot be shown to have
read is dropped, and a verdict left with no surviving evidence is downgraded to
``unclear`` rather than trusted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_client import LlmClient, LlmError

CompanyType = Literal["software_vendor", "agency", "non_technical_buyer", "unclear"]

MAX_SIGNALS = 8
MAX_SIGNAL_CHARS = 200
# A quote shorter than this matches by accident; "IT" appears on every page.
MIN_QUOTE_CHARS = 12

SYSTEM_PROMPT = """You read a company's own website and decide whether they
build software or buy it.

Return JSON:
  company_type         one of: software_vendor, agency, non_technical_buyer, unclear
  builds_software      one of: true, false, unknown
  sector               short sector label in English, e.g. "university",
                       "municipality", "hospital", "logistics", or null
  engineering_signals  array of exact quotes from the page showing they build software
  buyer_signals        array of exact quotes showing they buy software or lack
                       an engineering team
  confidence           number between 0 and 1

Definitions:
  software_vendor      sells software as its product
  agency               sells software development or design services to others
  non_technical_buyer  any other organisation: it uses software but its business
                       is something else
  unclear              the page does not support a decision

Rules:
- Quotes must be copied exactly from the page. Never paraphrase or invent them.
- The page may be in any language. Quote it in its original language.
- Return an empty array rather than a quote you cannot find on the page.
"""


class ClassificationPayload(BaseModel):
    company_type: CompanyType
    builds_software: Literal["true", "false", "unknown"] = "unknown"

    @field_validator("builds_software", mode="before")
    @classmethod
    def coerce_boolean(cls, value: Any) -> Any:
        """JSON has real booleans; the model returns true, not "true"."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "unknown"
        if isinstance(value, str):
            return value.strip().lower()
        return value
    sector: str | None = Field(default=None, max_length=80)
    engineering_signals: list[str] = Field(default_factory=list)
    buyer_signals: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


@dataclass
class ClassificationResult:
    payload: ClassificationPayload
    notes: list[str] = field(default_factory=list)

    @property
    def excluded(self) -> bool:
        return self.payload.company_type in {"software_vendor", "agency"}


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _attested(quotes: list[str], haystack: str, notes: list[str], label: str) -> list[str]:
    kept: list[str] = []
    for quote in quotes[:MAX_SIGNALS]:
        if not isinstance(quote, str):
            continue
        trimmed = quote.strip()[:MAX_SIGNAL_CHARS]
        if len(trimmed) < MIN_QUOTE_CHARS:
            notes.append(f"dropped short {label} quote: {trimmed!r}")
            continue
        if _normalise(trimmed) not in haystack:
            notes.append(f"dropped unattested {label} quote: {trimmed[:60]!r}")
            continue
        kept.append(trimmed)
    return kept


def validate_classification(
    raw: dict[str, Any], *, page_text: str
) -> ClassificationResult:
    try:
        payload = ClassificationPayload.model_validate(raw)
    except ValidationError as error:
        raise LlmError(f"Classifier output failed schema validation: {error}") from error

    notes: list[str] = []
    haystack = _normalise(page_text)

    payload.engineering_signals = _attested(
        payload.engineering_signals, haystack, notes, "engineering"
    )
    payload.buyer_signals = _attested(payload.buyer_signals, haystack, notes, "buyer")

    # A builder verdict with no surviving evidence is an assertion, not a finding.
    if payload.company_type in {"software_vendor", "agency"} and not payload.engineering_signals:
        notes.append(
            f"downgraded {payload.company_type} to unclear: no attested engineering evidence"
        )
        payload.company_type = "unclear"
        payload.builds_software = "unknown"

    if notes:
        payload.confidence = round(max(0.1, payload.confidence - 0.15 * len(notes)), 4)

    return ClassificationResult(payload=payload, notes=notes)


def classify_company(
    client: LlmClient, *, company_domain: str, page_text: str
) -> ClassificationResult:
    raw = client.complete_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Company domain: {company_domain}\n\nPages:\n{page_text}",
    )
    return validate_classification(raw, page_text=page_text)


def persist_classification(
    db: Session,
    *,
    company_id: str,
    result: ClassificationResult,
    model: str,
    source_urls: list[str],
) -> str:
    payload = result.payload
    classification_id = str(uuid4())
    db.execute(
        text(
            """
            insert into company_classification (
                id, company_id, company_type, builds_software, sector,
                engineering_signals, buyer_signals, confidence, model,
                validation_notes, source_urls
            ) values (
                :id, :company_id, :company_type, :builds_software, :sector,
                cast(:engineering_signals as jsonb), cast(:buyer_signals as jsonb),
                :confidence, :model, cast(:validation_notes as jsonb),
                cast(:source_urls as jsonb)
            )
            on conflict (company_id) do update set
                company_type = excluded.company_type,
                builds_software = excluded.builds_software,
                sector = excluded.sector,
                engineering_signals = excluded.engineering_signals,
                buyer_signals = excluded.buyer_signals,
                confidence = excluded.confidence,
                model = excluded.model,
                validation_notes = excluded.validation_notes,
                source_urls = excluded.source_urls,
                classified_at = now(),
                updated_at = now()
            """
        ),
        {
            "id": classification_id,
            "company_id": company_id,
            "company_type": payload.company_type,
            "builds_software": payload.builds_software,
            "sector": payload.sector,
            "engineering_signals": json.dumps(payload.engineering_signals),
            "buyer_signals": json.dumps(payload.buyer_signals),
            "confidence": payload.confidence,
            "model": model,
            "validation_notes": json.dumps(result.notes),
            "source_urls": json.dumps(source_urls),
        },
    )
    db.commit()
    return classification_id
