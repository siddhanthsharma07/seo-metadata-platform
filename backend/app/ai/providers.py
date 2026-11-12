"""LLM provider abstraction with strict JSON-schema outputs, retries and usage tracking."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable

from app.config import get_settings

log = logging.getLogger(__name__)

# USD per 1M tokens (input, output, cache_read). Update as provider pricing changes.
PRICING: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
    "gpt-5": (1.25, 10.0, 0.125),
    "gpt-5-mini": (0.25, 2.0, 0.025),
    "gpt-4.1": (2.0, 8.0, 0.5),
    "gpt-4o": (2.5, 10.0, 1.25),
}

ANTHROPIC_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]
OPENAI_MODELS = ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"]

# Models that accept server-side refusal fallbacks ("default" routing).
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
# Models that accept output_config.effort.
_EFFORT_PREFIXES = ("claude-fable", "claude-mythos", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                    "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-5")


class AIError(Exception):
    pass


class AIConfigError(AIError):
    """Provider not configured (e.g. missing API key)."""


class AIRefusalError(AIError):
    pass


@dataclass
class Usage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0

    @property
    def cost_usd(self) -> float:
        p = PRICING.get(self.model)
        if not p:
            return 0.0
        uncached = max(0, self.input_tokens)
        return round((uncached * p[0] + self.output_tokens * p[1] + self.cache_read_tokens * p[2]) / 1_000_000, 6)


UsageCallback = Callable[[str, Usage, bool, str | None], None]


class LLMProvider:
    name = "base"

    def __init__(self, model: str, api_key: str, effort: str = "medium", on_usage: UsageCallback | None = None,
                 max_output_tokens: int = 8000):
        self.model = model
        self.api_key = api_key
        self.effort = effort
        self.on_usage = on_usage
        self.max_output_tokens = max_output_tokens

    def _call(self, system: str, user: str, schema: dict, schema_name: str) -> tuple[str, Usage]:
        raise NotImplementedError

    def complete_json(self, stage: str, system: str, user: str, schema: dict, schema_name: str) -> dict:
        """Call the model and return a dict matching ``schema``. One extra retry on invalid JSON."""
        last_err: Exception | None = None
        for attempt in range(2):
            started = time.monotonic()
            try:
                text, usage = self._call(system, user, schema, schema_name)
                usage.latency_ms = int((time.monotonic() - started) * 1000)
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    self._report(stage, usage, False, f"Invalid JSON: {exc}")
                    last_err = AIError(f"Model returned invalid JSON: {exc}")
                    continue
                missing = [k for k in schema.get("required", []) if k not in data]
                if missing:
                    self._report(stage, usage, False, f"Missing keys {missing}")
                    last_err = AIError(f"Model output missing keys: {missing}")
                    continue
                self._report(stage, usage, True, None)
                return data
            except (AIConfigError, AIRefusalError):
                raise
            except AIError as exc:
                last_err = exc
                self._report(stage, Usage(self.name, self.model, latency_ms=int((time.monotonic() - started) * 1000)), False, str(exc))
        raise last_err or AIError("Unknown AI error")

    def _report(self, stage: str, usage: Usage, ok: bool, error: str | None):
        if self.on_usage:
            try:
                self.on_usage(stage, usage, ok, error)
            except Exception:  # noqa: BLE001
                log.exception("usage callback failed")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=self.api_key, max_retries=4,
                                          timeout=get_settings().ai_request_timeout_seconds)

    def _call(self, system: str, user: str, schema: dict, schema_name: str) -> tuple[str, Usage]:
        a = self._anthropic
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if self.model.startswith(_EFFORT_PREFIXES) and self.effort:
            output_config["effort"] = self.effort
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_output_tokens,
            # The per-project system prompt is identical across pages -> cacheable prefix.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        try:
            if self.model in _FALLBACK_MODELS:
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                resp = self.client.messages.create(**kwargs)
        except a.AuthenticationError as exc:
            raise AIConfigError("Anthropic rejected the API key (401). Check ANTHROPIC_API_KEY or the key in Settings.") from exc
        except a.PermissionDeniedError as exc:
            raise AIConfigError(f"Anthropic API key lacks permission: {exc.message}") from exc
        except a.NotFoundError as exc:
            raise AIConfigError(f"Model '{self.model}' not found for this Anthropic account.") from exc
        except a.BadRequestError as exc:
            raise AIError(f"Anthropic request rejected: {exc.message}") from exc
        except a.RateLimitError as exc:
            raise AIError("Anthropic rate limit reached after retries; try lower concurrency.") from exc
        except a.APIStatusError as exc:
            raise AIError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise AIError(f"Could not reach Anthropic API: {exc}") from exc
        u = resp.usage
        usage = Usage(
            "anthropic", self.model,
            input_tokens=(u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0),
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )
        if resp.stop_reason == "refusal":
            self._report("refusal", usage, False, "refusal")
            raise AIRefusalError("The model declined to process this page.")
        if resp.stop_reason == "max_tokens":
            raise AIError("Model output was truncated (max_tokens).")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        return text, usage


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        import openai

        self._openai = openai
        self.client = openai.OpenAI(api_key=self.api_key, max_retries=4, timeout=get_settings().ai_request_timeout_seconds)

    def _call(self, system: str, user: str, schema: dict, schema_name: str) -> tuple[str, Usage]:
        o = self._openai
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
            )
        except o.AuthenticationError as exc:
            raise AIConfigError("OpenAI rejected the API key (401). Check OPENAI_API_KEY or the key in Settings.") from exc
        except o.NotFoundError as exc:
            raise AIConfigError(f"Model '{self.model}' not available for this OpenAI account.") from exc
        except o.BadRequestError as exc:
            raise AIError(f"OpenAI request rejected: {exc}") from exc
        except o.RateLimitError as exc:
            raise AIError("OpenAI rate limit reached after retries.") from exc
        except o.APIStatusError as exc:
            raise AIError(f"OpenAI API error {exc.status_code}") from exc
        except o.APIConnectionError as exc:
            raise AIError(f"Could not reach OpenAI API: {exc}") from exc
        choice = resp.choices[0]
        u = resp.usage
        cached = 0
        if u and getattr(u, "prompt_tokens_details", None):
            cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
        usage = Usage("openai", self.model, input_tokens=(u.prompt_tokens if u else 0) - cached,
                      output_tokens=u.completion_tokens if u else 0, cache_read_tokens=cached)
        if getattr(choice.message, "refusal", None):
            raise AIRefusalError(f"The model declined: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise AIError("Model output was truncated (length).")
        return choice.message.content or "", usage


def resolve_api_key(provider: str, user_key: str | None) -> str:
    if user_key:
        return user_key
    s = get_settings()
    key = s.anthropic_api_key if provider == "anthropic" else s.openai_api_key
    if not key:
        env = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        raise AIConfigError(
            f"No {provider} API key configured. Set {env} in backend/.env or add a key under Settings > AI providers."
        )
    return key


def make_provider(provider: str, model: str | None, api_key: str, effort: str = "medium",
                  on_usage: UsageCallback | None = None) -> LLMProvider:
    s = get_settings()
    if provider == "anthropic":
        return AnthropicProvider(model or s.default_anthropic_model, api_key, effort, on_usage)
    if provider == "openai":
        return OpenAIProvider(model or s.default_openai_model, api_key, effort, on_usage)
    raise AIConfigError(f"Unknown AI provider '{provider}'.")
