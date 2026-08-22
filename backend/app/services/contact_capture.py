"""Capture every contact and web presence for a company (Phase D).

Plan v3 inverts the earlier policy. Previously the pipeline kept only
decision-makers and exported only verified addresses. The deliverable is now a
datasheet handed to someone else, so nothing is discarded: everything found is
stored and labelled, and the recipient decides what to use.

No address is ever constructed. Every contact here was published somewhere and
carries the URL it was read from, so "where did you get this" always has an
answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.email_verification import ROLE_LOCAL_PARTS, check_email

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"
)

# Pages that actually carry contact details, in rough order of usefulness.
CONTACT_PATHS = (
    "", "/contact", "/contact-us", "/contacts", "/about", "/about-us",
    "/team", "/our-team", "/people", "/leadership", "/staff",
    "/careers", "/jobs", "/support", "/help", "/press", "/media",
    "/imprint", "/impressum", "/legal", "/privacy",
)

PRESENCE_PATTERNS = (
    ("linkedin", re.compile(r"linkedin\.com/(company|in)/", re.I)),
    ("x", re.compile(r"(twitter\.com|x\.com)/[A-Za-z0-9_]+", re.I)),
    ("ats_board", re.compile(r"(greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|myworkdayjobs\.com)", re.I)),
    ("careers", re.compile(r"/(careers|jobs|vacancies|join-us)", re.I)),
    ("blog", re.compile(r"/(blog|news|insights)", re.I)),
    ("docs", re.compile(r"(docs\.|/docs|/documentation)", re.I)),
)

# Local parts that are extraction artifacts rather than mailboxes.
JUNK_LOCAL_PARTS = frozenset({"email", "your", "name", "example", "user", "someone"})


@dataclass
class CapturedContact:
    email: str | None
    full_name: str | None
    role: str | None
    phone: str | None
    contact_kind: str
    on_company_domain: bool
    deliverability: str | None
    source_type: str
    source_url: str
    raw_evidence: dict[str, Any] = field(default_factory=dict)


def classify_local_part(email: str) -> str:
    local = email.split("@", 1)[0].split("+", 1)[0].lower()
    if local in ROLE_LOCAL_PARTS:
        return "role_inbox"
    # A person's address usually carries a name shape: jane, jane.doe, j.doe.
    if re.fullmatch(r"[a-z]{2,}([._-][a-z]{2,})?", local):
        return "person"
    return "generic"


def extract_emails(html: str, *, page_url: str, company_domain: str) -> list[CapturedContact]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, CapturedContact] = {}

    def add(raw_email: str, how: str) -> None:
        email = raw_email.strip().lower().rstrip(".,;:)")
        if "@" not in email:
            return
        local, _, host = email.partition("@")
        if not local or local.split("+", 1)[0] in JUNK_LOCAL_PARTS:
            return
        if host.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            return
        if email in found:
            return
        check = check_email(email)
        found[email] = CapturedContact(
            email=email,
            full_name=None,
            role=None,
            phone=None,
            contact_kind=classify_local_part(email),
            on_company_domain=host == company_domain.lower(),
            deliverability=check.result.value,
            source_type="website",
            source_url=page_url,
            raw_evidence={"extraction": how},
        )

    # mailto links first: they are unambiguous, unlike text that merely looks
    # like an address.
    for anchor in soup.select("a[href^=mailto]"):
        href = anchor.get("href", "")
        add(href[7:].split("?")[0], "mailto")

    # Inserting separators stops adjacent block text merging into one token,
    # which previously produced addresses like "preferencescontacthi@x.com".
    for match in EMAIL_PATTERN.findall(soup.get_text(" ", strip=True)):
        add(match, "page_text")

    return list(found.values())


def extract_phones(html: str, *, page_url: str) -> list[CapturedContact]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, CapturedContact] = {}

    def normalize_phone(value: str) -> str | None:
        phone = value.strip()
        if phone.lower().startswith("tel:"):
            phone = phone[4:]
        phone = re.sub(r"\s+", " ", phone).strip(" .,:;()")
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 8 or len(digits) > 16:
            return None
        return phone

    def add(raw_phone: str, how: str) -> None:
        phone = normalize_phone(raw_phone)
        if not phone or phone in found:
            return
        found[phone] = CapturedContact(
            email=None,
            full_name=None,
            role=None,
            phone=phone,
            contact_kind="unknown",
            on_company_domain=False,
            deliverability="no_email",
            source_type="website",
            source_url=page_url,
            raw_evidence={"extraction": how},
        )

    for anchor in soup.select("a[href^=tel]"):
        add(anchor.get("href", ""), "tel")

    for match in PHONE_PATTERN.findall(soup.get_text(" ", strip=True)):
        add(match, "page_text")

    return list(found.values())


def extract_web_presence(html: str, *, page_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    presence: dict[str, dict[str, str]] = {}

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        url = urljoin(page_url, href)
        if not urlparse(url).scheme.startswith("http"):
            continue
        for kind, pattern in PRESENCE_PATTERNS:
            if pattern.search(url):
                presence.setdefault(url, {
                    "url": url,
                    "presence_kind": kind,
                    "title": (anchor.get_text(" ", strip=True) or "")[:120] or None,
                    "discovered_from": page_url,
                })
                break

    return list(presence.values())


def persist_contacts(db: Session, *, company_id: str, contacts: list[CapturedContact]) -> int:
    stored = 0
    for contact in contacts:
        result = db.execute(
            text(
                """
                insert into company_contacts_all (
                    id, company_id, email, full_name, role, phone, contact_kind,
                    on_company_domain, deliverability, source_type, source_url,
                    raw_evidence
                ) values (
                    :id, :company_id, :email, :full_name, :role, :phone, :contact_kind,
                    :on_company_domain, :deliverability, :source_type, :source_url,
                    cast(:raw_evidence as jsonb)
                )
                on conflict (company_id, email) do update set
                    last_seen_at = now(),
                    deliverability = excluded.deliverability,
                    contact_kind = excluded.contact_kind,
                    updated_at = now()
                """
            ),
            {
                "id": str(uuid4()), "company_id": company_id, "email": contact.email,
                "full_name": contact.full_name, "role": contact.role,
                "phone": contact.phone, "contact_kind": contact.contact_kind,
                "on_company_domain": contact.on_company_domain,
                "deliverability": contact.deliverability,
                "source_type": contact.source_type, "source_url": contact.source_url,
                "raw_evidence": json.dumps(contact.raw_evidence),
            },
        )
        stored += result.rowcount or 0
    db.commit()
    return stored


def persist_web_presence(db: Session, *, company_id: str, entries: list[dict[str, str]]) -> int:
    stored = 0
    for entry in entries:
        result = db.execute(
            text(
                """
                insert into company_web_presence (
                    id, company_id, url, presence_kind, title, discovered_from
                ) values (
                    :id, :company_id, :url, :presence_kind, :title, :discovered_from
                )
                on conflict (company_id, url) do update set last_seen_at = now()
                """
            ),
            {"id": str(uuid4()), "company_id": company_id, **entry},
        )
        stored += result.rowcount or 0
    db.commit()
    return stored
