"""Runtime model extraction of company websites, for qualified companies only.

This is the genuine long tail: a few hundred domains, a few hundred distinct
layouts, no repeated structure to exploit. A generated parser cannot help, so
the model reads the page directly.

Nothing here reaches the database unvalidated. Model output is a claim; the
validation layer below is what turns it into a record. The load-bearing check
is cross-referencing: an extracted email whose domain is not the company's own
domain is discarded, because a model inventing contact details invents them at
a plausible but wrong domain.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm_client import LlmClient, LlmError

EXTRACTION_METHOD = "llm_website_extraction"

# Guards against a model returning an essay or a list of a thousand items.
MAX_TECHNOLOGY_MENTIONS = 25
MAX_CONTACT_ROUTES = 10
MAX_DECISION_MAKERS = 10
MAX_TEXT_FIELD_CHARS = 600

EMAIL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,}$")

SYSTEM_PROMPT = """You read a company's own website and return structured facts.

Return a JSON object with:
  positioning:          one sentence on what the company sells, or null
  business_model:       e.g. "B2B SaaS subscription", or null
  customer_type:        who buys it, or null
  technology_mentions:  array of technologies named on the site
  contact_routes:       array of email addresses published on the site
  decision_makers:      array of {name, role} for people explicitly named
  service_fit_evidence: one sentence on why they might need external
                        engineering help, or null

Rules:
- Only report what appears on the pages. Do not infer, guess, or complete.
- Never construct an email address. Copy addresses only if written on the page.
- Return null or an empty array when something is absent. An empty answer is
  correct and useful; an invented one is not.
"""


class DecisionMaker(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    role: str | None = Field(default=None, max_length=160)


class CompanyProfile(BaseModel):
    positioning: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_CHARS)
    business_model: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_CHARS)
    customer_type: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_CHARS)
    technology_mentions: list[str] = Field(default_factory=list)
    contact_routes: list[str] = Field(default_factory=list)
    decision_makers: list[DecisionMaker] = Field(default_factory=list)
    service_fit_evidence: str | None = Field(default=None, max_length=MAX_TEXT_FIELD_CHARS)


class ReachabilityCheck(Protocol):
    def __call__(self, url: str) -> bool:
        ...


@dataclass
class ValidatedProfile:
    profile: CompanyProfile
    notes: list[str] = field(default_factory=list)
    confidence: float = 0.0


def _clean_list(values: Any, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text_value = value.strip()
        if text_value and text_value not in cleaned:
            cleaned.append(text_value[:120])
        if len(cleaned) >= limit:
            break
    return cleaned


def validate_profile(
    payload: dict[str, Any],
    *,
    company_domain: str,
    page_text: str = "",
) -> ValidatedProfile:
    """Turn a model claim into a record, or reject the parts that fail."""
    notes: list[str] = []

    raw = dict(payload)
    raw["technology_mentions"] = _clean_list(
        raw.get("technology_mentions"), MAX_TECHNOLOGY_MENTIONS
    )
    raw["contact_routes"] = _clean_list(raw.get("contact_routes"), MAX_CONTACT_ROUTES)

    decision_makers = raw.get("decision_makers")
    if isinstance(decision_makers, list):
        raw["decision_makers"] = [
            item for item in decision_makers[:MAX_DECISION_MAKERS] if isinstance(item, dict)
        ]
    else:
        raw["decision_makers"] = []

    try:
        profile = CompanyProfile.model_validate(raw)
    except ValidationError as error:
        raise LlmError(f"Model output failed schema validation: {error}") from error

    # Cross-reference: an address off the company's own domain is the signature
    # of a fabrication, so it is dropped rather than stored.
    kept_routes: list[str] = []
    for email in profile.contact_routes:
        normalized = email.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            notes.append(f"dropped malformed contact route: {email}")
            continue
        if normalized.split("@", 1)[1] != company_domain.lower():
            notes.append(f"dropped off-domain contact route: {normalized}")
            continue
        kept_routes.append(normalized)
    profile.contact_routes = kept_routes

    # A named person who does not appear anywhere in the fetched text was not
    # read off the page.
    if page_text:
        haystack = page_text.lower()
        kept_people: list[DecisionMaker] = []
        for person in profile.decision_makers:
            if person.name.lower() in haystack:
                kept_people.append(person)
            else:
                notes.append(f"dropped unattested decision maker: {person.name}")
        profile.decision_makers = kept_people

    # Confidence reflects how much survived, not how sure the model sounded.
    populated = sum(
        1
        for value in (
            profile.positioning, profile.business_model, profile.customer_type,
            profile.service_fit_evidence,
        )
        if value
    )
    confidence = min(0.95, 0.4 + 0.1 * populated + 0.05 * len(profile.contact_routes))
    if notes:
        confidence = max(0.2, confidence - 0.1 * len(notes))

    return ValidatedProfile(profile=profile, notes=notes, confidence=round(confidence, 4))


def extract_company_profile(
    client: LlmClient,
    *,
    company_domain: str,
    page_text: str,
) -> ValidatedProfile:
    payload = client.complete_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Company domain: {company_domain}\n\nPages:\n{page_text}",
    )
    return validate_profile(payload, company_domain=company_domain, page_text=page_text)


def record_llm_usage(
    db: Session,
    *,
    company_id: str | None,
    purpose: str,
    usage: Any,
    succeeded: bool = True,
    error: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into llm_usage (
                id, company_id, purpose, model, prompt_tokens, completion_tokens,
                total_tokens, cost_usd, succeeded, error
            ) values (
                :id, :company_id, :purpose, :model, :prompt_tokens, :completion_tokens,
                :total_tokens, :cost_usd, :succeeded, :error
            )
            """
        ),
        {
            "id": str(uuid4()),
            "company_id": company_id,
            "purpose": purpose,
            "model": getattr(usage, "model", "unknown"),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
            "cost_usd": getattr(usage, "cost_usd", 0.0),
            "succeeded": succeeded,
            "error": error,
        },
    )
    db.commit()


def persist_enrichment(
    db: Session,
    *,
    company_id: str,
    validated: ValidatedProfile,
    model: str,
    source_urls: list[str],
) -> str:
    profile = validated.profile
    enrichment_id = str(uuid4())
    db.execute(
        text(
            """
            insert into company_enrichment (
                id, company_id, positioning, business_model, customer_type,
                technology_mentions, contact_routes, decision_makers,
                service_fit_evidence, extraction_method, model, confidence,
                validation_notes, source_urls
            ) values (
                :id, :company_id, :positioning, :business_model, :customer_type,
                cast(:technology_mentions as jsonb), cast(:contact_routes as jsonb),
                cast(:decision_makers as jsonb), :service_fit_evidence,
                :extraction_method, :model, :confidence,
                cast(:validation_notes as jsonb), cast(:source_urls as jsonb)
            )
            on conflict (company_id, extraction_method) do update set
                positioning = excluded.positioning,
                business_model = excluded.business_model,
                customer_type = excluded.customer_type,
                technology_mentions = excluded.technology_mentions,
                contact_routes = excluded.contact_routes,
                decision_makers = excluded.decision_makers,
                service_fit_evidence = excluded.service_fit_evidence,
                model = excluded.model,
                confidence = excluded.confidence,
                validation_notes = excluded.validation_notes,
                source_urls = excluded.source_urls,
                updated_at = now()
            """
        ),
        {
            "id": enrichment_id,
            "company_id": company_id,
            "positioning": profile.positioning,
            "business_model": profile.business_model,
            "customer_type": profile.customer_type,
            "technology_mentions": json.dumps(profile.technology_mentions),
            "contact_routes": json.dumps(profile.contact_routes),
            "decision_makers": json.dumps([p.model_dump() for p in profile.decision_makers]),
            "service_fit_evidence": profile.service_fit_evidence,
            "extraction_method": EXTRACTION_METHOD,
            "model": model,
            "confidence": validated.confidence,
            "validation_notes": json.dumps(validated.notes),
            "source_urls": json.dumps(source_urls),
        },
    )
    db.commit()
    return enrichment_id
