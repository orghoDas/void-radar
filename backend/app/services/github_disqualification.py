"""GitHub engineering-org detection, used to remove companies from the list.

A company with hundreds of active public repositories has an engineering
organisation and will not outsource development. GitHub is ground truth about
this, where headcount estimates and job counts are only inference.

The check is deliberately inverted: it never adds a company or raises a score.
It only produces evidence for disqualification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

GITHUB_API = "https://api.github.com"

# A same-named org is not necessarily this company, so a match must be
# corroborated by the org's own website field pointing at the same registrable
# domain. Without that, "parabola" the open-source project would disqualify
# parabola.io the company.
RECENT_PUSH_WINDOW_DAYS = 90

# Thresholds. The brief's example is "forty active public repositories and heavy
# weekly commit volume". Two independent routes to the same conclusion so a
# company with few but very active repos is still caught.
STRONG_REPO_COUNT = 40
MODERATE_REPO_COUNT = 15
MODERATE_RECENT_ACTIVE_REPOS = 10


class HttpFetcher(Protocol):
    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        ...


@dataclass
class GithubOrgMetrics:
    domain: str
    login: str | None = None
    public_repos: int = 0
    recent_active_repos: int = 0
    followers: int = 0
    blog: str | None = None
    matched_by: str | None = None
    languages: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.login is not None

    @property
    def is_engineering_org(self) -> bool:
        if not self.found:
            return False
        if self.public_repos >= STRONG_REPO_COUNT:
            return True
        return (
            self.public_repos >= MODERATE_REPO_COUNT
            and self.recent_active_repos >= MODERATE_RECENT_ACTIVE_REPOS
        )

    def as_evidence(self) -> dict[str, Any]:
        return {
            "collector": "github-disqualification",
            "domain": self.domain,
            "login": self.login,
            "public_repos": self.public_repos,
            "recent_active_repos": self.recent_active_repos,
            "followers": self.followers,
            "blog": self.blog,
            "matched_by": self.matched_by,
            "languages": self.languages[:8],
            "window_days": RECENT_PUSH_WINDOW_DAYS,
        }


def domain_root(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"^https?://", "", value.strip().lower()).split("/")[0]
    cleaned = cleaned.removeprefix("www.")
    if not cleaned or "." not in cleaned:
        return None
    return cleaned


def org_login_guess(domain: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", domain.split(".")[0].lower())


def org_matches_company(org: dict[str, Any], domain: str) -> str | None:
    """Return how the org was corroborated, or None to reject the match."""
    blog_root = domain_root(org.get("blog"))
    if blog_root and blog_root == domain:
        return "blog_exact"
    if blog_root and blog_root.split(".")[0] == domain.split(".")[0]:
        # retool.io vs retool.com - same brand, different TLD.
        return "blog_brand"
    login = str(org.get("login", "")).lower()
    if login and login == org_login_guess(domain) and int(org.get("public_repos") or 0) > 0:
        return "login_exact"
    return None


def fetch_org_metrics(
    client: HttpFetcher,
    domain: str,
    *,
    headers: dict[str, str] | None = None,
) -> GithubOrgMetrics:
    metrics = GithubOrgMetrics(domain=domain)
    login = org_login_guess(domain)
    if not login:
        return metrics

    response = client.get(f"{GITHUB_API}/orgs/{login}", headers=headers)
    if response.status_code != 200:
        return metrics

    org = response.json()
    matched_by = org_matches_company(org, domain)
    if not matched_by:
        return metrics

    metrics.login = org.get("login")
    metrics.public_repos = int(org.get("public_repos") or 0)
    metrics.followers = int(org.get("followers") or 0)
    metrics.blog = org.get("blog")
    metrics.matched_by = matched_by

    repos_response = client.get(
        f"{GITHUB_API}/orgs/{metrics.login}/repos?sort=pushed&per_page=50",
        headers=headers,
    )
    if repos_response.status_code == 200:
        cutoff = datetime.now(UTC) - timedelta(days=RECENT_PUSH_WINDOW_DAYS)
        languages: list[str] = []
        for repo in repos_response.json():
            pushed_at = repo.get("pushed_at")
            if pushed_at:
                try:
                    when = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when >= cutoff:
                    metrics.recent_active_repos += 1
            language = repo.get("language")
            if language and language not in languages:
                languages.append(language)
        metrics.languages = languages

    return metrics


def signal_for(metrics: GithubOrgMetrics) -> tuple[str, str, float]:
    """Return (signal_type, description, confidence)."""
    if metrics.is_engineering_org:
        return (
            "GITHUB_ENGINEERING_ORG_DETECTED",
            (
                f"GitHub org {metrics.login} has {metrics.public_repos} public repos "
                f"({metrics.recent_active_repos} pushed in {RECENT_PUSH_WINDOW_DAYS} days); "
                "substantial in-house engineering."
            ),
            0.9,
        )
    if metrics.found:
        return (
            "GITHUB_ORG_SMALL_FOOTPRINT",
            (
                f"GitHub org {metrics.login} has only {metrics.public_repos} public repos; "
                "no substantial in-house engineering detected."
            ),
            0.7,
        )
    return (
        "NO_GITHUB_ORG_FOUND",
        f"No corroborated GitHub organisation found for {metrics.domain}.",
        0.6,
    )
