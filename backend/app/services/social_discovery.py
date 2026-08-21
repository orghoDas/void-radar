"""Normalise LinkedIn and X data from Apify Store actors into discovery records.

Store actors are third-party products, so their output shape is neither stable
nor trusted. Every field is read defensively and validated before it becomes a
company: a vendor changing a key name should produce zero records and a loud
count, not silently wrong ones.

The social module is deliberately additive. It emits the same discovery record
shape as every other source, so disabling it removes rows and changes nothing
else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.identity.normalize import normalize_domain

# Hosts that are never the prospect's own domain.
NON_COMPANY_HOSTS = frozenset({
    "linkedin.com", "lnkd.in", "twitter.com", "x.com", "t.co", "bit.ly",
    "facebook.com", "instagram.com", "youtube.com", "youtu.be", "medium.com",
    "github.com", "crunchbase.com", "google.com", "docs.google.com",
})

# Sector words that mark a company as a plausible non-technical buyer. The
# revised thesis targets organisations that need software and do not build it.
NON_TECHNICAL_INDUSTRY_TERMS = (
    "logistics", "transport", "freight", "haulage", "warehousing", "shipping",
    "manufacturing", "distribution", "wholesale", "retail", "construction",
    "healthcare", "hospital", "clinic", "dental", "veterinary", "pharmacy",
    "education", "university", "college", "school", "training",
    "housing", "property", "real estate", "facilities", "hospitality",
    "hotel", "restaurant", "agriculture", "farming", "energy", "utilities",
    "water", "waste", "recycling", "insurance", "accounting", "legal",
    "law firm", "professional services", "consulting engineers", "government",
    "council", "public sector", "charity", "non-profit", "nonprofit",
)

# Company self-descriptions that mean they build software themselves.
TECHNICAL_COMPANY_TERMS = (
    "software development", "software company", "saas platform",
    "developer tools", "open source", "engineering team", "we build software",
    "technology company", "it consultancy", "software agency", "web agency",
    "app development", "digital agency",
)


@dataclass
class SocialNormalisationResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


def first_string(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Vendors disagree on field names; try the plausible ones."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def company_domain(item: dict[str, Any]) -> str | None:
    candidate = first_string(item, ("website", "companyWebsite", "url", "domain", "websiteUrl"))
    domain = normalize_domain(candidate)
    if not domain:
        return None
    root = ".".join(domain.split(".")[-2:])
    if domain in NON_COMPANY_HOSTS or root in NON_COMPANY_HOSTS:
        return None
    return domain


def looks_non_technical(text_value: str) -> bool:
    lowered = text_value.lower()
    if any(term in lowered for term in TECHNICAL_COMPANY_TERMS):
        return False
    return any(term in lowered for term in NON_TECHNICAL_INDUSTRY_TERMS)


def normalize_linkedin_companies(
    items: list[dict[str, Any]],
    *,
    require_non_technical: bool = True,
) -> SocialNormalisationResult:
    result = SocialNormalisationResult()
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            result.reject("not_an_object")
            continue

        name = first_string(item, ("name", "companyName", "title", "fullName"))
        if not name:
            result.reject("no_company_name")
            continue

        domain = company_domain(item)
        if not domain:
            # LinkedIn's own URL is not a company domain; without a website we
            # cannot key the record, and domain is the primary key.
            result.reject("no_resolvable_domain")
            continue
        if domain in seen:
            result.reject("duplicate_domain")
            continue

        industry = first_string(item, ("industry", "industryName", "sector")) or ""
        description = first_string(item, ("description", "about", "tagline", "summary")) or ""
        profile = first_string(item, ("linkedinUrl", "profileUrl", "url", "link")) or ""

        if require_non_technical and not looks_non_technical(f"{industry} {description}"):
            result.reject("not_non_technical")
            continue

        seen.add(domain)
        result.records.append({
            "source": "linkedin_apify",
            "source_record_id": f"linkedin:{domain}",
            "source_url": profile or f"https://{domain}",
            "company_name": name,
            "website": f"https://{domain}",
            "domain": domain,
            "location": first_string(item, ("location", "headquarters", "city")),
            "industry": industry or None,
            "description": description[:2000] or None,
            "employee_count": employee_count(item),
            "event_type": "discovery",
            "raw_source_payload": {"collector": "apify_linkedin", "item": item},
        })

    return result


def employee_count(item: dict[str, Any]) -> int | None:
    value = item.get("employeeCount") or item.get("employees") or item.get("staffCount")
    if isinstance(value, int) and 0 < value < 5_000_000:
        return value
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value.split("-")[0])
        if digits.isdigit() and 0 < int(digits) < 5_000_000:
            return int(digits)
    return None


def normalize_x_posts(items: list[dict[str, Any]]) -> SocialNormalisationResult:
    """X posts rarely name a buyer, so only posts linking a real company count."""
    result = SocialNormalisationResult()
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            result.reject("not_an_object")
            continue

        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        candidate = (
            first_string(item, ("expandedUrl", "outboundUrl"))
            or first_string(author, ("url", "website", "expandedUrl"))
        )
        domain = normalize_domain(candidate) if candidate else None
        if not domain:
            result.reject("no_resolvable_domain")
            continue
        root = ".".join(domain.split(".")[-2:])
        if domain in NON_COMPANY_HOSTS or root in NON_COMPANY_HOSTS:
            result.reject("non_company_host")
            continue
        if domain in seen:
            result.reject("duplicate_domain")
            continue

        name = (
            first_string(author, ("name", "displayName", "userName"))
            or domain.split(".")[0].title()
        )
        text_value = first_string(item, ("text", "full_text", "content")) or ""

        seen.add(domain)
        result.records.append({
            "source": "x_apify",
            "source_record_id": f"x:{domain}",
            "source_url": first_string(item, ("url", "twitterUrl")) or f"https://{domain}",
            "company_name": name,
            "website": f"https://{domain}",
            "domain": domain,
            "description": text_value[:2000] or None,
            "event_type": "discovery",
            "raw_source_payload": {"collector": "apify_x", "item": item},
        })

    return result
