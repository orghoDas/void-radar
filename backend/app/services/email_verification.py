"""Deliverability checks that do not damage sending reputation.

The brief is explicit that self-hosted SMTP probing is not a sensible build: it
is unreliable, gets the probing addresses blocklisted, and fails outright
against catch-all domains. Nothing here connects to a mail server.

What it does instead is cheap and safe: syntax, role-address and disposable
detection, and an MX lookup. An MX query is an ordinary DNS read, not a
connection to the recipient's mail server. This cannot prove a mailbox exists,
so it never marks a contact verified - it only rejects addresses that cannot
possibly deliver, before they reach a paid verifier or a send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import dns.exception
import dns.resolver

EMAIL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,}$")

# Role addresses reach a shared inbox. Deliverable, but not a decision-maker,
# and they attract complaints at a much higher rate.
ROLE_LOCAL_PARTS = frozenset({
    # Hiring inboxes dominate this pipeline's contact set, so they matter most.
    "careers", "career", "jobs", "job", "hiring", "recruiting", "recruitment",
    "hr", "talent", "apply", "work", "workwithus", "joinus", "membership",
    "admin", "administrator", "abuse", "billing", "compliance", "contact",
    "enquiries", "enquiry", "feedback", "help", "hello", "hi", "info",
    "inquiries", "legal", "mail", "marketing", "media", "news", "newsletter",
    "no-reply", "noreply", "office", "postmaster", "press", "privacy",
    "sales", "security", "support", "team", "webmaster",
})

DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwaway.email", "yopmail.com", "trashmail.com", "sharklasers.com",
})

FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "protonmail.com", "proton.me", "gmx.com", "mail.com",
})


class VerificationResult(StrEnum):
    DELIVERABLE_DOMAIN = "deliverable_domain"
    INVALID_SYNTAX = "invalid_syntax"
    NO_MX_RECORD = "no_mx_record"
    DISPOSABLE_DOMAIN = "disposable_domain"
    FREE_MAIL_DOMAIN = "free_mail_domain"
    ROLE_ADDRESS = "role_address"
    DNS_ERROR = "dns_error"


@dataclass(frozen=True)
class EmailCheck:
    email: str
    result: VerificationResult
    mx_hosts: tuple[str, ...] = ()

    @property
    def sendable(self) -> bool:
        """Role addresses are sendable but deprioritised, not rejected."""
        return self.result in {
            VerificationResult.DELIVERABLE_DOMAIN,
            VerificationResult.ROLE_ADDRESS,
        }


class MxLookup(Protocol):
    def __call__(self, domain: str) -> tuple[str, ...]:
        ...


def resolve_mx(domain: str) -> tuple[str, ...]:
    answers = dns.resolver.resolve(domain, "MX", lifetime=6.0)
    return tuple(sorted(str(record.exchange).rstrip(".").lower() for record in answers))


def check_email(email: str, *, mx_lookup: MxLookup = resolve_mx) -> EmailCheck:
    normalized = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        return EmailCheck(normalized, VerificationResult.INVALID_SYNTAX)

    local, _, domain = normalized.partition("@")

    if domain in DISPOSABLE_DOMAINS:
        return EmailCheck(normalized, VerificationResult.DISPOSABLE_DOMAIN)
    if domain in FREE_MAIL_DOMAINS:
        return EmailCheck(normalized, VerificationResult.FREE_MAIL_DOMAIN)

    try:
        mx_hosts = mx_lookup(domain)
    except (dns.exception.DNSException, OSError):
        return EmailCheck(normalized, VerificationResult.DNS_ERROR)

    if not mx_hosts:
        return EmailCheck(normalized, VerificationResult.NO_MX_RECORD)

    # Plus-addressing is stripped before the role check so "careers+hn@x.com"
    # is still recognised as a role address.
    base_local = local.split("+", 1)[0]
    if base_local in ROLE_LOCAL_PARTS:
        return EmailCheck(normalized, VerificationResult.ROLE_ADDRESS, mx_hosts)

    return EmailCheck(normalized, VerificationResult.DELIVERABLE_DOMAIN, mx_hosts)
