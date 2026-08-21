from typing import Any

from app.services.github_disqualification import (
    GithubOrgMetrics,
    domain_root,
    fetch_org_metrics,
    org_matches_company,
    signal_for,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeClient:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return FakeResponse(404, {"message": "Not Found"})


def repos(count: int, pushed_at: str) -> list[dict[str, Any]]:
    return [{"pushed_at": pushed_at, "language": "Python"} for _ in range(count)]


def test_large_public_org_is_flagged_as_engineering_org() -> None:
    client = FakeClient({
        "https://api.github.com/orgs/mongodb/repos": FakeResponse(200, repos(30, "2026-08-01T00:00:00Z")),
        "https://api.github.com/orgs/mongodb": FakeResponse(200, {
            "login": "mongodb", "public_repos": 306, "followers": 5000,
            "blog": "http://www.mongodb.com/",
        }),
    })
    metrics = fetch_org_metrics(client, "mongodb.com")
    assert metrics.is_engineering_org is True
    assert signal_for(metrics)[0] == "GITHUB_ENGINEERING_ORG_DETECTED"


def test_small_org_is_not_disqualified() -> None:
    client = FakeClient({
        "https://api.github.com/orgs/storepass/repos": FakeResponse(200, repos(1, "2026-08-01T00:00:00Z")),
        "https://api.github.com/orgs/storepass": FakeResponse(200, {
            "login": "storepass", "public_repos": 1, "blog": "https://storepass.co",
        }),
    })
    metrics = fetch_org_metrics(client, "storepass.co")
    assert metrics.found is True
    assert metrics.is_engineering_org is False
    assert signal_for(metrics)[0] == "GITHUB_ORG_SMALL_FOOTPRINT"


def test_same_named_unrelated_org_is_rejected() -> None:
    """A GitHub org sharing a name is not evidence about the company."""
    client = FakeClient({
        "https://api.github.com/orgs/parabola": FakeResponse(200, {
            "login": "parabola", "public_repos": 0, "blog": "https://parabola-gnulinux.org",
        }),
    })
    metrics = fetch_org_metrics(client, "parabola.io")
    assert metrics.found is False
    assert metrics.is_engineering_org is False
    assert signal_for(metrics)[0] == "NO_GITHUB_ORG_FOUND"


def test_brand_match_across_tlds_is_accepted() -> None:
    assert org_matches_company(
        {"login": "retool", "public_repos": 5, "blog": "https://www.retool.io"},
        "retool.com",
    ) == "blog_brand"


def test_moderate_repos_with_heavy_recent_activity_is_flagged() -> None:
    metrics = GithubOrgMetrics(
        domain="example.com", login="example", public_repos=20, recent_active_repos=12
    )
    assert metrics.is_engineering_org is True


def test_moderate_repos_without_activity_is_not_flagged() -> None:
    metrics = GithubOrgMetrics(
        domain="example.com", login="example", public_repos=20, recent_active_repos=2
    )
    assert metrics.is_engineering_org is False


def test_domain_root_strips_scheme_and_www() -> None:
    assert domain_root("https://www.example.com/careers") == "example.com"
    assert domain_root(None) is None
    assert domain_root("notadomain") is None
