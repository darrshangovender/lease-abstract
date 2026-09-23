"""LLM gap-filler.

The model only ever sees **redacted** clause text and is asked for a strict
JSON object: for each requested field, a ``value`` matching the schema and an
``extracted_text`` quote. A response that fails validation gets exactly one
self-correction retry with the validation error attached. If that fails too
the field stays with the rules layer (or empty) — the model never gets a
third chance and never gets to answer without a quote.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic import Field as PField

from ..schema import (
    Clause,
    Deposit,
    Escalation,
    LeaseAbstract,
    Maintenance,
    Notice,
    Party,
    Premises,
    Rent,
    Term,
)

T = TypeVar("T")


class ModelClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class MockModel:
    """Scripted model for tests and the offline eval.

    ``script`` may be a single string (returned every call), a sequence of
    strings (returned in order, last one repeated) or a callable of the prompt.
    Every prompt is recorded on ``.prompts`` so tests can assert what the
    model was shown.
    """

    def __init__(self, script: str | Sequence[str] | Callable[[str], str] = "{}") -> None:
        self.script = script
        self.prompts: list[str] = []
        self._i = 0

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if callable(self.script):
            return self.script(prompt)
        if isinstance(self.script, str):
            return self.script
        out = self.script[min(self._i, len(self.script) - 1)]
        self._i += 1
        return out

    @property
    def calls(self) -> int:
        return len(self.prompts)


class Cited(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    value: T
    extracted_text: str = PField(min_length=1)


class LLMPayload(BaseModel):
    """What the model must return. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    landlord: Cited[Party] | None = None
    tenant: Cited[Party] | None = None
    premises: Cited[Premises] | None = None
    term: Cited[Term] | None = None
    rent: Cited[Rent] | None = None
    escalation: Cited[Escalation] | None = None
    deposit: Cited[Deposit] | None = None
    notice: Cited[Notice] | None = None
    maintenance: Cited[Maintenance] | None = None
    penalties: Cited[list[str]] | None = None
    special_clauses: Cited[list[str]] | None = None


class LLMExtractionError(RuntimeError):
    pass


FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_response(raw: str) -> dict[str, Any]:
    text = FENCE_RE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("response contains no JSON object")
    return json.loads(text[start : end + 1])


def schema_for(wanted: Sequence[str]) -> dict[str, Any]:
    full = LLMPayload.model_json_schema()
    props = {k: v for k, v in full["properties"].items() if k in wanted}
    return {"type": "object", "properties": props, "$defs": full.get("$defs", {})}


def build_prompt(clauses: Sequence[Clause], wanted: Sequence[str]) -> str:
    body = "\n".join(
        f"[{c.id}] {(c.heading + ': ') if c.heading else ''}{c.text}".strip() for c in clauses
    )
    return (
        "You are abstracting a South African residential lease.\n"
        "Personal information has been replaced with placeholders like [ID_1]; keep them as-is.\n"
        f"Fill ONLY these fields: {', '.join(wanted)}.\n"
        "Return one JSON object. For each field give {\"value\": <object matching the schema>, "
        "\"extracted_text\": <a verbatim quote from one clause that supports the value>}.\n"
        "If the lease does not state a field, omit it. Never invent values. Dates as YYYY-MM-DD.\n\n"
        f"JSON schema:\n{json.dumps(schema_for(wanted), separators=(',', ':'))}\n\n"
        f"Clauses:\n{body}\n\nJSON:"
    )


class LLMExtractor:
    def __init__(self, client: ModelClient, max_retries: int = 1) -> None:
        self.client = client
        self.max_retries = max_retries
        self.attempts = 0
        self.errors: list[str] = []

    def fill(self, clauses: Sequence[Clause], wanted: Sequence[str]) -> dict[str, Cited]:
        """Return validated ``{field_name: Cited}`` for the fields the model answered."""
        wanted = [w for w in wanted if w in LeaseAbstract.FIELD_NAMES]
        if not wanted:
            return {}
        prompt = build_prompt(clauses, wanted)
        self.attempts = 0
        self.errors = []
        for attempt in range(self.max_retries + 1):
            self.attempts += 1
            raw = self.client.complete(prompt)
            try:
                data = parse_response(raw)
                payload = LLMPayload.model_validate(data)
            except (ValueError, ValidationError) as exc:
                msg = str(exc)
                self.errors.append(msg)
                if attempt < self.max_retries:
                    prompt = (
                        prompt
                        + "\n\nYour previous response was rejected:\n"
                        + msg[:1500]
                        + "\nReturn ONLY a valid JSON object that matches the schema."
                    )
                continue
            out: dict[str, Cited] = {}
            for name in wanted:
                cited = getattr(payload, name)
                if cited is not None:
                    out[name] = cited
            return out
        return {}


__all__ = [
    "Cited",
    "LLMExtractionError",
    "LLMExtractor",
    "LLMPayload",
    "MockModel",
    "ModelClient",
    "build_prompt",
    "parse_response",
    "schema_for",
]
