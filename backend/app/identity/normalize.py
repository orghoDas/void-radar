from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.identity.tld_data import IANA_TLDS


COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(inc|inc\.|llc|ltd|ltd\.|limited|corp|corp\.|corporation|co|co\.|"
    r"company|plc|gmbh|ag|bv|s\.a\.|sa|sas|pte|pty)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedLocation:
    raw: str | None
    city: str | None
    country: str | None


def normalize_company_display_name(value: str | None) -> str | None:
    if not value:
        return None

    normalized = " ".join(value.strip().split())
    return normalized or None


def normalize_company_match_name(value: str | None) -> str | None:
    display_name = normalize_company_display_name(value)
    if not display_name:
        return None

    without_suffixes = COMPANY_SUFFIX_PATTERN.sub("", display_name)
    normalized = re.sub(r"[^a-z0-9]+", "", without_suffixes.lower())
    return normalized or None


# Discovery sources that read domains out of free text produce hostnames whose
# suffix is the next word in the sentence: "...our process.We are hiring" parses
# as "process.we", and "middesk.com at" as "middesk.comat". Validating the suffix
# against IANA rejects the first shape and repairs the second.
GLUED_SUFFIX_PATTERN = re.compile(
    r"^(?P<host>.+\.(?:com|org|net|io|ai|dev|co))(?P<extra>[a-z]{2,10})$"
)


def has_valid_tld(hostname: str) -> bool:
    return hostname.rpartition(".")[2] in IANA_TLDS


def repair_glued_suffix(hostname: str) -> str:
    """Recover ``middesk.comat`` -> ``middesk.com``.

    Only attempted when the suffix is already invalid, so a genuine domain such
    as ``cockpit.at`` is never truncated.
    """
    if has_valid_tld(hostname):
        return hostname
    match = GLUED_SUFFIX_PATTERN.match(hostname)
    return match.group("host") if match else hostname


def normalize_domain(value: str | None) -> str | None:
    if not value:
        return None

    candidate = value.strip()
    if not candidate:
        return None

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    hostname = parsed.hostname
    if not hostname:
        return None

    hostname = hostname.lower().strip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]

    if not hostname or "." not in hostname:
        return None

    hostname = repair_glued_suffix(hostname)
    if not has_valid_tld(hostname):
        return None

    return hostname


def normalize_location(value: str | None) -> NormalizedLocation:
    if not value:
        return NormalizedLocation(raw=None, city=None, country=None)

    raw = " ".join(value.strip().split())
    if not raw:
        return NormalizedLocation(raw=None, city=None, country=None)

    primary_location = raw.split(";")[0].strip()
    parts = [part.strip() for part in primary_location.split(",") if part.strip()]

    city = parts[0] if parts else None
    country = parts[-1] if len(parts) > 1 else None

    country = normalize_country_name(country)

    return NormalizedLocation(raw=raw, city=city, country=country)


def normalize_country_name(value: str | None) -> str | None:
    if not value:
        return None

    country = value.strip()
    aliases = {
        "usa": "United States",
        "us": "United States",
        "u.s.": "United States",
        "u.s.a.": "United States",
        "united states of america": "United States",
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
    }

    return aliases.get(country.lower(), country)

