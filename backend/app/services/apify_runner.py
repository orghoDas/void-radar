"""Run Apify Store actors and collect their dataset output.

Social sources are consumed as third-party data products rather than scrapers
we operate: a Store actor is run by its vendor's code on Apify's platform, and
we pay per result. That keeps collection mechanics - proxies, blocking, site
changes - outside this codebase, and it is the reason the social module can be
disabled without touching anything else.

Nothing here parses vendor output. It returns raw items; normalisation and
validation happen in social_discovery so untrusted third-party shapes never
reach the database directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

APIFY_API = "https://api.apify.com/v2"
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


class ApifyError(RuntimeError):
    pass


@dataclass
class ActorRun:
    run_id: str
    status: str
    dataset_id: str | None
    stats: dict[str, Any]


@dataclass
class ApifyRunner:
    token: str
    timeout_seconds: float = 60.0

    @classmethod
    def from_settings(cls) -> ApifyRunner:
        settings = get_settings()
        if not settings.apify_token:
            raise ApifyError("APIFY_TOKEN is not set; add it to .env")
        return cls(token=settings.apify_token)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self, actor_id: str, payload: dict[str, Any]) -> ActorRun:
        # Store actor ids use username/name; the API path wants username~name.
        path_id = actor_id.replace("/", "~")
        try:
            response = httpx.post(
                f"{APIFY_API}/acts/{path_id}/runs",
                headers=self._headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ApifyError(f"Failed to start {actor_id}: {error}") from error

        data = response.json().get("data", {})
        return ActorRun(
            run_id=data.get("id", ""),
            status=data.get("status", "UNKNOWN"),
            dataset_id=data.get("defaultDatasetId"),
            stats=data.get("stats", {}),
        )

    def wait(self, run: ActorRun, *, poll_seconds: float = 10.0,
             max_wait_seconds: float = 1800.0) -> ActorRun:
        deadline = time.time() + max_wait_seconds
        current = run
        while current.status not in TERMINAL_STATES:
            if time.time() > deadline:
                raise ApifyError(
                    f"Run {current.run_id} did not finish within {max_wait_seconds}s"
                )
            time.sleep(poll_seconds)
            try:
                response = httpx.get(
                    f"{APIFY_API}/actor-runs/{current.run_id}",
                    headers=self._headers,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise ApifyError(f"Failed to poll run: {error}") from error
            data = response.json().get("data", {})
            current = ActorRun(
                run_id=data.get("id", current.run_id),
                status=data.get("status", "UNKNOWN"),
                dataset_id=data.get("defaultDatasetId", current.dataset_id),
                stats=data.get("stats", {}),
            )
        return current

    def dataset_items(self, dataset_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        try:
            response = httpx.get(
                f"{APIFY_API}/datasets/{dataset_id}/items",
                headers=self._headers,
                params={"limit": limit, "clean": "true"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ApifyError(f"Failed to fetch dataset {dataset_id}: {error}") from error
        items = response.json()
        return items if isinstance(items, list) else []

    def run_and_collect(
        self, actor_id: str, payload: dict[str, Any], *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        run = self.wait(self.start(actor_id, payload))
        if run.status != "SUCCEEDED":
            raise ApifyError(f"Actor {actor_id} finished with status {run.status}")
        if not run.dataset_id:
            return []
        return self.dataset_items(run.dataset_id, limit=limit)
