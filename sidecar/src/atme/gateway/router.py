"""Multi-provider LLM gateway (LiteLLM) with roles, schema enforcement, and a cost ledger.

Design per ADR-0002 + plan S4:
  - Roles (reasoner/researcher/writer/layouter) map to ANY provider model string LiteLLM
    accepts; nothing is hardcoded. The researcher role MUST be web-grounded - validated here.
  - Every structured call goes through the repair ladder:
      parse -> validate vs JSON Schema -> repair-prompt with validator errors -> raise.
  - A per-job ledger records tokens/cost per call.

Backend injection: agents receive a complete-callable so tests run fully offline against
scripted fixtures; production wires litellm via make_litellm_complete().
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

log = logging.getLogger(__name__)

ROLES = ("reasoner", "researcher", "writer", "layouter")
WEB_GROUNDING_HINTS = ("perplexity", "sonar", "search", "grounding", "web")
FENCE = chr(96) * 3


@dataclass
class RoleConfig:
    model: str                      # e.g. "openai/gpt-4o-mini", "perplexity/sonar-pro"
    temperature: float = 0.4
    max_tokens: int | None = None
    api_key: str | None = None
    api_base: str | None = None
    web_grounded: bool = False


@dataclass
class LedgerEntry:
    role: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    attempt: int = 1
    ok: bool = True
    error: str | None = None
    wall_ms: int = 0


@dataclass
class Ledger:
    entries: list[LedgerEntry] = field(default_factory=list)

    def add(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    def summary(self) -> dict:
        by_role: dict[str, dict] = {}
        for e in self.entries:
            slot = by_role.setdefault(e.role, {"calls": 0, "prompt_tokens": 0,
                                               "completion_tokens": 0, "cost_usd": 0.0})
            slot["calls"] += 1
            slot["prompt_tokens"] += e.prompt_tokens
            slot["completion_tokens"] += e.completion_tokens
            if e.cost_usd:
                slot["cost_usd"] += e.cost_usd
        return {"roles": by_role,
                "total_cost_usd": round(sum(s["cost_usd"] for s in by_role.values()), 6),
                "total_calls": len(self.entries)}


CompleteFn = Callable[..., str]


class CompletionText(str):
    """String-compatible provider result carrying usage metadata."""

    def __new__(cls, value: str, *, model: str, prompt_tokens: int = 0,
                completion_tokens: int = 0, cost_usd: float | None = None):
        obj = str.__new__(cls, value)
        obj.model = model
        obj.prompt_tokens = prompt_tokens
        obj.completion_tokens = completion_tokens
        obj.cost_usd = cost_usd
        return obj


def make_litellm_complete(role: str, cfg: RoleConfig) -> CompleteFn:
    """Production completion function bound to one role config."""
    from litellm import completion

    if role == "researcher" and not cfg.web_grounded and not any(
            h in cfg.model.lower() for h in WEB_GROUNDING_HINTS):
        raise ValueError("researcher role must map to a web-grounded model (got %r); see ADR-0002"
                         % cfg.model)

    def complete(system: str, user: str, **kwargs: Any) -> str:
        if role == "researcher" and cfg.web_grounded and not any(
                hint in cfg.model.lower() for hint in ("perplexity", "sonar")):
            kwargs.setdefault("web_search_options", {})
        resp = completion(
            model=cfg.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=kwargs.pop("temperature", cfg.temperature),
            max_tokens=kwargs.pop("max_tokens", cfg.max_tokens),
            api_key=cfg.api_key,
            api_base=cfg.api_base,
            **kwargs,
        )
        usage = getattr(resp, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        hidden = getattr(resp, "_hidden_params", {}) or {}
        cost = hidden.get("response_cost")
        if cost is None:
            try:
                from litellm import completion_cost

                cost = completion_cost(completion_response=resp)
            except Exception:  # noqa: BLE001 - cost support varies by provider
                cost = None
        return CompletionText(
            resp.choices[0].message.content or "",
            model=str(getattr(resp, "model", None) or cfg.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=float(cost) if cost is not None else None,
        )

    return complete


def extract_json(text: str) -> Any:
    """Parse JSON out of a model response, tolerating markdown fences."""
    text = text.strip()
    m = re.search(re.escape(FENCE) + r"(?:json)?\s*(.*?)\s*" + re.escape(FENCE),
                  text, re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def validate_schema(instance: Any, schema: dict) -> list[str]:
    return [e.message for e in Draft202012Validator(schema).iter_errors(instance)]


class SchemaViolation(RuntimeError):
    pass


def _accepts_system_first(fn: CompleteFn) -> bool:
    """litellm wrapper signature is (system, user); fixture fakes use (user, system=...)."""
    try:
        params = list(inspect.signature(fn).parameters)
        return params[:1] != ["user"]
    except (TypeError, ValueError):
        return True


def structured_call(
    complete_fn: CompleteFn,
    ledger: Ledger,
    role: str,
    system: str,
    user: str,
    schema: dict | None = None,
    max_repair_rounds: int = 3,
    model_label: str = "-",
) -> tuple[Any, list[str]]:
    """One (possibly repaired) structured completion; every attempt is ledgered."""
    current_user = user
    notes: list[str] = []
    last_error = ""
    system_first = _accepts_system_first(complete_fn)

    for attempt in range(1, max_repair_rounds + 2):
        t0 = time.perf_counter()
        entry = LedgerEntry(role=role, model=model_label, attempt=attempt)

        try:
            raw = (complete_fn(system, current_user) if system_first
                   else complete_fn(current_user, system=system))
        except Exception as exc:  # transport errors also get repair rounds
            entry.ok, entry.error = False, "transport: %s" % str(exc)[:180]
            entry.wall_ms = int((time.perf_counter() - t0) * 1000)
            ledger.add(entry)
            last_error = "transport: %s" % entry.error
            current_user = user + "\n\nThe previous call failed (%s). Try again." % last_error
            continue
        entry.model = str(getattr(raw, "model", None) or model_label)
        entry.prompt_tokens = int(getattr(raw, "prompt_tokens", 0) or 0)
        entry.completion_tokens = int(getattr(raw, "completion_tokens", 0) or 0)
        raw_cost = getattr(raw, "cost_usd", None)
        entry.cost_usd = float(raw_cost) if raw_cost is not None else None
        entry.wall_ms = int((time.perf_counter() - t0) * 1000)

        if schema is None:
            ledger.add(entry)
            return raw, notes

        try:
            instance = extract_json(raw)
        except Exception as exc:  # noqa: BLE001
            entry.ok = False
            entry.error = "unparseable: %s" % exc
            last_error = entry.error or ""
            notes.append(last_error)
            ledger.add(entry)
            current_user = (user + "\n\nYour previous reply was not valid JSON:\n"
                            + raw[-800:] + "\nReturn ONLY JSON matching the schema.")
            continue

        errors = validate_schema(instance, schema)
        if not errors:
            ledger.add(entry)
            return instance, notes

        entry.ok, entry.error = False, "schema violations"
        ledger.add(entry)
        last_error = "; ".join(errors[:5])
        notes.append(last_error)
        log.info("schema repair round %d: %s", attempt, last_error)
        current_user = (user + "\n\nYour JSON violated these rules:\n- "
                        + "\n- ".join(errors[:8]) + "\nReturn ONLY corrected JSON.")

    raise SchemaViolation("%s: schema ladder exhausted. Last error: %s" % (role, last_error))
