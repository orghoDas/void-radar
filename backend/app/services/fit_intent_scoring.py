from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.identity.normalize import normalize_domain
from app.schemas.scoring import CompanyScoreResult

FIT_INTENT_SCORE_VERSION = "fit_intent_v0.1"

TARGET_INDUSTRY_TERMS = (
    "b2b",
    "saas",
    "logistics",
    "operations",
    "marketplace",
    "supply chain",
    "fintech",
    "healthtech",
    "insurtech",
    "commerce",
    "productivity",
    # Non-technical sectors that buy software but rarely build it. These are
    # the revised target: the qualifier is absence of engineering capacity,
    # not company size.
    "manufacturing",
    "distribution",
    "wholesale",
    "healthcare",
    "education",
    "university",
    "college",
    "housing",
    "construction",
    "engineering services",
    "professional services",
    "accounting",
    "legal services",
    "local government",
    "council",
    "public sector",
    "utilities",
    "energy",
    "water",
    "transport",
    "rail",
    "haulage",
    "freight",
    "warehousing",
    "facilities",
    "hospitality",
    "retail",
    "agriculture",
    "charity",
    "housing association",
    "nhs",
)

# Matched against company identity only, never against description. For a
# procurement-sourced company the description is the tender text, so a council
# buying consultancy would otherwise be scored as being a consultancy.
# Terms are multi-word for the same reason: bare "agency" matches the Ministry
# of Defence and the Environment Agency, which are buyers.
COMPETITOR_TERMS = (
    "digital agency",
    "software agency",
    "web agency",
    "creative agency",
    "marketing agency",
    "dev agency",
    "development agency",
    "software consultancy",
    "it consultancy",
    "tech consultancy",
    "software development shop",
    "web development agency",
    "design studio",
    "development studio",
)

# Public bodies are buyers by definition and can never be the competitor set.
PUBLIC_BODY_TERMS = (
    "council", "university", "college", "school", "nhs", "ministry",
    "government", "authority", "constabulary", "police", "fire and rescue",
    "ambulance", "hospital", "trust", "library", "museum", "borough",
    "county", "district", "national", "royal", "department for",
    "department of", "office for", "office of", "agency",
)

CRYPTO_TERMS = ("crypto", "web3", "blockchain", "nft", "defi")
FREE_MAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com"}

# An organisation that has run many software tenders is a standing buyer, not
# an accident. The base intent formula takes max + a quarter of the next three,
# so 13 tenders and 4 tenders score almost identically without this.
PROCUREMENT_SIGNAL_TYPES = ("PROCUREMENT_NOTICE", "PROCUREMENT_HISTORY")
REPEAT_BUYER_BONUS_PER_TENDER = 5
REPEAT_BUYER_BONUS_CAP = 25

SIGNAL_INTENT_WEIGHTS = {
    # A published tender states a budget and a deadline outright, which is a
    # stronger intent claim than an inferred one.
    "PROCUREMENT_NOTICE": 90,
    # Bought software before, nothing open now: real evidence of buyer type,
    # weaker evidence of current timing.
    "PROCUREMENT_HISTORY": 40,
    "STALE_ENGINEERING_ROLE": 85,
    "AGING_ENGINEERING_ROLE": 68,
    "HIRING_SPIKE": 78,
    "OPERATIONS_SOFTWARE_NEED": 72,
    "TECH_STACK_NEED": 62,
    "FUNDING_EVENT": 58,
    "PRODUCT_LAUNCH": 52,
    "HIRING_DISCOVERY": 46,
    "ATS_BOARD_DETECTED": 20,
}

TECH_SIGNAL_TYPES = {
    "STALE_ENGINEERING_ROLE",
    "AGING_ENGINEERING_ROLE",
    "HIRING_SPIKE",
    "OPERATIONS_SOFTWARE_NEED",
    "TECH_STACK_NEED",
}


@dataclass
class ScoreContext:
    positive_reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    trigger_evidence: list[dict] = field(default_factory=list)
    disqualified: bool = False

    def add_penalty(self, reason: str, *, disqualifying: bool = False) -> None:
        self.penalties.append(reason)
        if disqualifying:
            self.disqualified = True


def score_companies(
    db: Session,
    *,
    company_ids: list[str] | None = None,
    limit: int = 50,
    score_version: str | None = None,
) -> list[CompanyScoreResult]:
    ids = company_ids or candidate_company_ids(db, limit=limit)
    return [
        score_company(
            db,
            company_id=company_id,
            score_version=score_version,
        )
        for company_id in ids[:limit]
    ]


def score_company(
    db: Session,
    *,
    company_id: str,
    score_version: str | None = None,
) -> CompanyScoreResult:
    version = score_version or FIT_INTENT_SCORE_VERSION
    company = fetch_company(db, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="company_not_found",
        )

    context = ScoreContext()
    signals = fetch_company_signals(db, company_id)
    active_jobs = active_relevant_job_count(db, company_id)

    fit_score = calculate_fit_score(db, company, active_jobs, context)
    intent_score = calculate_intent_score(signals, context)

    if context.disqualified:
        fit_score = min(fit_score, 35)
        intent_score = min(intent_score, 45)

    total_score = round(fit_score * intent_score / 100)
    score_id = insert_score(
        db,
        company_id=company_id,
        score_version=version,
        fit_score=fit_score,
        intent_score=intent_score,
        total_score=total_score,
        context=context,
    )
    db.commit()

    return CompanyScoreResult(
        company_id=company_id,
        score_id=score_id,
        score_version=version,
        fit_score=fit_score,
        intent_score=intent_score,
        total_score=total_score,
        positive_reasons=context.positive_reasons,
        penalties=context.penalties,
        trigger_evidence=context.trigger_evidence,
        disqualified=context.disqualified,
    )



def company_classification(db: Session, company_id: str) -> tuple[str, str | None] | None:
    """Model verdict on whether this company builds software or buys it.

    Reads a stored verdict only; classification never runs inside scoring, so a
    re-score is deterministic and free.
    """
    row = db.execute(
        text(
            """
            select company_type, sector from company_classification
            where company_id = :company_id limit 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return (str(row[0]), row[1]) if row else None


def github_small_footprint_signal(db: Session, company_id: str) -> bool:
    """Confirmed absence of a public engineering org is positive evidence."""
    row = db.execute(
        text(
            """
            select 1 from signals
            where company_id = :company_id
              and signal_type = 'GITHUB_ORG_SMALL_FOOTPRINT'
            limit 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return row is not None


def github_engineering_org_signal(db: Session, company_id: str) -> str | None:
    """Ground truth beats inference: a large active public org will not outsource."""
    row = db.execute(
        text(
            """
            select description from signals
            where company_id = :company_id
              and signal_type = 'GITHUB_ENGINEERING_ORG_DETECTED'
            order by detected_at desc limit 1
            """
        ),
        {"company_id": company_id},
    ).first()
    return str(row[0]) if row else None

def calculate_fit_score(
    db: Session,
    company: dict,
    active_jobs: int,
    context: ScoreContext,
) -> int:
    score = 45
    domain = normalize_domain(company.get("canonical_domain"))
    company_text = " ".join(
        str(value or "")
        for value in (
            company.get("canonical_name"),
            company.get("canonical_domain"),
            company.get("description"),
            company.get("industry"),
            company.get("country"),
            company.get("city"),
            company.get("company_stage"),
        )
    ).lower()

    # What the company IS, as opposed to what a tender says it wants to buy.
    identity_text = " ".join(
        str(value or "")
        for value in (
            company.get("canonical_name"),
            company.get("canonical_domain"),
            company.get("industry"),
        )
    ).lower()

    if domain:
        score += 10
        context.positive_reasons.append("Company has a resolvable domain.")
    else:
        score -= 30
        context.add_penalty("No accessible company domain.", disqualifying=True)

    if domain in FREE_MAIL_DOMAINS:
        score -= 30
        context.add_penalty("Company domain is a free-mail domain.", disqualifying=True)

    if suppressed_domain_exists(db, domain):
        score -= 40
        context.add_penalty("Domain is suppressed.", disqualifying=True)

    matched_industries = matched_terms(company_text, TARGET_INDUSTRY_TERMS)
    if matched_industries:
        score += 18
        context.positive_reasons.append(
            f"Industry fit matches {', '.join(matched_industries[:3])}."
        )
    else:
        score -= 6
        context.add_penalty("No explicit target-industry fit found.")

    employee_estimate = company.get("employee_estimate")
    if employee_estimate is not None:
        employee_count = int(employee_estimate)
        if 10 <= employee_count <= 250:
            score += 12
            context.positive_reasons.append("Company size fits serviceable SMB/mid-market.")
        elif employee_count > 500:
            # Not disqualifying on its own. The GitHub check below decides
            # whether they actually have engineering capacity.
            score -= 6
            context.add_penalty(
                "Large company; verify engineering capacity before outreach."
            )
        elif employee_count < 5:
            score -= 8
            context.add_penalty("Company may be too small for paid engineering help.")

    if active_jobs:
        score += min(12, active_jobs * 3)
        context.positive_reasons.append(
            f"{active_jobs} active relevant hiring signal(s) support service fit."
        )

    if active_jobs >= 15:
        score -= 22
        context.add_penalty(
            "Large active engineering hiring footprint may indicate strong in-house team.",
            disqualifying=True,
        )

    github_org = github_engineering_org_signal(db, company["id"])
    if github_org:
        score -= 35
        context.add_penalty(
            f"GitHub shows substantial in-house engineering: {github_org}",
            disqualifying=True,
        )
    elif github_small_footprint_signal(db, company["id"]):
        score += 14
        context.positive_reasons.append(
            "GitHub shows no substantial in-house engineering footprint."
        )

    classification = company_classification(db, company["id"])
    if classification:
        verdict, sector = classification
        if verdict in {"software_vendor", "agency"}:
            score -= 40
            context.add_penalty(
                f"Classified as {verdict}: builds software rather than buying it.",
                disqualifying=True,
            )
        elif verdict == "non_technical_buyer":
            score += 20
            label = f" ({sector})" if sector else ""
            context.positive_reasons.append(
                f"Classified as a non-technical buyer{label}."
            )

    if matched_terms(identity_text, COMPETITOR_TERMS) and not matched_terms(
        identity_text, PUBLIC_BODY_TERMS
    ):
        score -= 35
        context.add_penalty("Agency/consultancy competitor.", disqualifying=True)

    crypto_matches = matched_terms(identity_text, CRYPTO_TERMS)
    if crypto_matches and not matched_industries:
        score -= 25
        context.add_penalty("Crypto-only or unclear business.", disqualifying=True)

    verified_contacts = verified_contact_count(db, company["id"])
    if verified_contacts:
        score += 5
        context.positive_reasons.append("Verified contact evidence already exists.")

    return clamp_score(score)


def calculate_intent_score(signals: list[dict], context: ScoreContext) -> int:
    if not signals:
        context.add_penalty("No trigger signals found.")
        return 0

    contributions: list[int] = []
    seen_signal_types: set[str] = set()
    for signal in signals:
        signal_type = str(signal["signal_type"])
        base_weight = SIGNAL_INTENT_WEIGHTS.get(signal_type)
        if not base_weight:
            continue

        contribution = round(base_weight * signal_decay(signal.get("detected_at")))
        if contribution <= 0:
            continue
        contributions.append(contribution)
        seen_signal_types.add(signal_type)
        context.trigger_evidence.append(
            {
                "signal_id": str(signal["id"]),
                "signal_type": signal_type,
                "description": signal["description"],
                "source_url": signal["source_url"],
                "detected_at": iso_datetime(signal.get("detected_at")),
                "confidence": float(signal["confidence"] or 0),
                "job_urls": job_urls_from_signal(signal),
            }
        )

    if not contributions:
        context.add_penalty("Signals exist, but none are high-intent MVP triggers.")
        return 0

    primary = max(contributions)
    secondary = sum(sorted(contributions, reverse=True)[1:4])
    score = min(100, primary + round(secondary * 0.25))

    tender_count = sum(
        1 for signal in signals
        if str(signal["signal_type"]) in PROCUREMENT_SIGNAL_TYPES
    )
    if tender_count > 1:
        bonus = min(
            REPEAT_BUYER_BONUS_CAP,
            (tender_count - 1) * REPEAT_BUYER_BONUS_PER_TENDER,
        )
        score = min(100, score + bonus)
        context.positive_reasons.append(
            f"Repeat software buyer: {tender_count} tenders on record."
        )

    if seen_signal_types & TECH_SIGNAL_TYPES:
        context.positive_reasons.append("Company has technical/product hiring intent.")
    if "HIRING_SPIKE" in seen_signal_types:
        context.positive_reasons.append("Hiring spike indicates fresh urgency.")
    if "FUNDING_EVENT" in seen_signal_types:
        context.positive_reasons.append("Funding event may increase budget timing.")

    return clamp_score(score)


def insert_score(
    db: Session,
    *,
    company_id: str,
    score_version: str,
    fit_score: int,
    intent_score: int,
    total_score: int,
    context: ScoreContext,
) -> str:
    score_id = str(uuid4())
    now = datetime.now(UTC)
    scoring_inputs = {
        "score_version": score_version,
        "formula": "total_score = fit_score * intent_score / 100",
        "positive_reasons": context.positive_reasons,
        "penalties": context.penalties,
        "trigger_evidence": context.trigger_evidence,
        "disqualified": context.disqualified,
    }
    db.execute(
        text(json_insert_sql(db, score_insert_sql(), ("positive_reasons", "penalties", "scoring_inputs"))),
        {
            "id": score_id,
            "company_id": company_id,
            "company_fit": fit_score,
            "opportunity_strength": intent_score,
            "timing": intent_score,
            "technical_capacity_gap": technical_capacity_gap_score(context),
            "commercial_potential": fit_score,
            "source_confidence": source_confidence_score(context),
            "overall_score": total_score,
            "positive_reasons": json.dumps(context.positive_reasons, sort_keys=True),
            "penalties": json.dumps(context.penalties, sort_keys=True),
            "fit_score": fit_score,
            "intent_score": intent_score,
            "total_score": total_score,
            "score_version": score_version,
            "scoring_inputs": json.dumps(scoring_inputs, sort_keys=True),
            "calculated_at": now,
            "model_version": score_version,
        },
    )
    return score_id


def candidate_company_ids(db: Session, *, limit: int) -> list[str]:
    rows = db.execute(
        text(
            """
            select distinct c.id
            from companies c
            join signals s on s.company_id = c.id
            order by c.id
            limit :limit
            """
        ),
        {"limit": limit},
    ).scalars()
    return [str(row) for row in rows]


def fetch_company(db: Session, company_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            select
                id,
                canonical_name,
                canonical_domain,
                description,
                industry,
                country,
                city,
                company_stage,
                employee_estimate
            from companies
            where id = :company_id
            """
        ),
        {"company_id": company_id},
    ).mappings().first()
    return dict(row) if row else None


def fetch_company_signals(db: Session, company_id: str) -> list[dict]:
    rows = db.execute(
        text(
            """
            select
                id,
                signal_type,
                description,
                source_url,
                detected_at,
                confidence,
                raw_evidence
            from signals
            where company_id = :company_id
            order by detected_at desc, created_at desc
            """
        ),
        {"company_id": company_id},
    ).mappings()
    return [dict(row) for row in rows]


def active_relevant_job_count(db: Session, company_id: str) -> int:
    rows = db.execute(
        text(
            """
            select title, department, description_text, stack_terms
            from job_postings
            where company_id = :company_id
              and is_active = true
            """
        ),
        {"company_id": company_id},
    ).mappings()
    count = 0
    for row in rows:
        text_value = " ".join(
            str(value)
            for value in (
                row["title"],
                row["department"],
                row["description_text"],
                " ".join(load_json_value(row["stack_terms"], default=[])),
            )
            if value
        ).lower()
        if any(term in text_value for term in ("engineer", "developer", "software", "product", "data", "automation", "platform")):
            count += 1
    return count


def suppressed_domain_exists(db: Session, domain: str | None) -> bool:
    if not domain:
        return False
    row = db.execute(
        text(
            """
            select 1
            from suppression
            where lower(domain) = :domain
            limit 1
            """
        ),
        {"domain": domain.lower()},
    ).scalar_one_or_none()
    return bool(row)


def verified_contact_count(db: Session, company_id: str) -> int:
    return int(
        db.execute(
            text(
                """
                select count(*)
                from contacts
                where company_id = :company_id
                  and verification_status in ('provider_verified', 'manual_verified')
                """
            ),
            {"company_id": company_id},
        ).scalar_one()
        or 0
    )


def technical_capacity_gap_score(context: ScoreContext) -> int:
    if any(
        evidence["signal_type"] in TECH_SIGNAL_TYPES
        for evidence in context.trigger_evidence
    ):
        return 85
    return 50 if context.trigger_evidence else 0


def source_confidence_score(context: ScoreContext) -> int:
    evidence_count = len(context.trigger_evidence)
    if evidence_count >= 3:
        return 90
    if evidence_count == 2:
        return 75
    if evidence_count == 1:
        return 60
    return 0


def signal_decay(value) -> float:
    detected_at = parse_datetime_value(value)
    if not detected_at:
        return 0.8
    age_days = max(0, (datetime.now(UTC) - detected_at).days)
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.8
    if age_days <= 180:
        return 0.55
    return 0.25


def job_urls_from_signal(signal: dict) -> list[str]:
    raw_evidence = load_json_value(signal.get("raw_evidence"))
    urls = raw_evidence.get("job_urls")
    if isinstance(urls, list):
        return [str(url) for url in urls if url]
    source_url = signal.get("source_url")
    return [str(source_url)] if source_url else []


def matched_terms(text_value: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text_value]


def clamp_score(value: int) -> int:
    return max(0, min(100, value))


def iso_datetime(value) -> str | None:
    parsed = parse_datetime_value(value)
    return parsed.isoformat() if parsed else None


def parse_datetime_value(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_json_value(value, default=None):
    if value is None:
        return {} if default is None else default
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def json_insert_sql(db: Session, sql: str, fields: tuple[str, ...]) -> str:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return sql
    for json_field in fields:
        sql = sql.replace(f":{json_field}", f"cast(:{json_field} as jsonb)")
    return sql


def score_insert_sql() -> str:
    return """
        insert into scores (
            id,
            company_id,
            company_fit,
            opportunity_strength,
            timing,
            technical_capacity_gap,
            commercial_potential,
            source_confidence,
            overall_score,
            positive_reasons,
            penalties,
            fit_score,
            intent_score,
            total_score,
            score_version,
            scoring_inputs,
            calculated_at,
            model_version
        )
        values (
            :id,
            :company_id,
            :company_fit,
            :opportunity_strength,
            :timing,
            :technical_capacity_gap,
            :commercial_potential,
            :source_confidence,
            :overall_score,
            :positive_reasons,
            :penalties,
            :fit_score,
            :intent_score,
            :total_score,
            :score_version,
            :scoring_inputs,
            :calculated_at,
            :model_version
        )
    """
