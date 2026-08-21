"""Minimal OpenRouter client for parser generation.

Phase 8 uses an LLM once per source layout to propose CSS selectors, then runs
those selectors deterministically. Nothing here writes to the database: callers
must validate the proposal against known pages before persisting it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import get_settings


@dataclass
class LlmUsage:
    """Token counts and cost for one call, so spend is attributable."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class LlmClient(Protocol):
    """Injectable so parser generation is testable without network access."""

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...

    @property
    def last_usage(self) -> LlmUsage | None:
        ...


class LlmError(RuntimeError):
    pass


@dataclass
class OpenRouterClient:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 90.0
    _last_usage: LlmUsage | None = None

    @property
    def last_usage(self) -> LlmUsage | None:
        return self._last_usage

    @classmethod
    def from_settings(cls) -> OpenRouterClient:
        settings = get_settings()
        if not settings.openrouter_api_key:
            raise LlmError(
                "OPENROUTER_API_KEY is not set; add it to .env before generating parsers"
            )
        return cls(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url.rstrip("/"),
            model=settings.openrouter_model,
        )

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "usage": {"include": True},
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise LlmError(f"OpenRouter request failed: {error}") from error

        body = response.json()
        usage = body.get("usage") or {}
        self._last_usage = LlmUsage(
            model=str(body.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            # OpenRouter reports actual charged cost when usage accounting is
            # enabled; absent that it is 0 and spend must be read from the
            # dashboard rather than silently guessed from token counts.
            cost_usd=float(usage.get("cost") or 0.0),
        )

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as error:
            raise LlmError(f"Unexpected OpenRouter response shape: {body}") from error

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise LlmError(f"Model did not return JSON: {content[:400]}") from error

        if not isinstance(parsed, dict):
            raise LlmError(f"Model returned {type(parsed).__name__}, expected object")
        return parsed
