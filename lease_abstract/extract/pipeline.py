"""Extraction pipeline: segment -> rules -> LLM gap-fill -> cite.

The contract that matters: **no field leaves this pipeline without a
citation**. Rules cite by construction. LLM answers are accepted only when
their ``extracted_text`` can be located verbatim (whitespace- and
case-insensitively) inside one of the clauses; anything that cannot be
located is discarded, not "kept with low confidence".
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import ValidationError

from ..privacy import RedactionMap, Redactor, get_logger
from ..schema import Clause, Field, LeaseAbstract
from ..segment import Segmenter
from .llm import LLMExtractor, ModelClient
from .rules import RuleExtractor

log = get_logger(__name__)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def locate(clauses: Sequence[Clause], extracted_text: str | None) -> Clause | None:
    """Find the clause that contains ``extracted_text`` (prefers exact, then a 40-char prefix)."""
    if not extracted_text:
        return None
    needle = _norm(extracted_text)
    if not needle:
        return None
    for c in clauses:
        if needle in _norm(c.text) or (c.heading and needle in _norm(c.heading)):
            return c
    if len(needle) > 40:
        prefix = needle[:40]
        for c in clauses:
            if prefix in _norm(c.text):
                return c
    return None


def _restore_value(value, rmap: RedactionMap):
    """Put redacted PII back into any strings inside a model value."""
    if not len(rmap):
        return value
    if hasattr(value, "model_dump"):
        data = json.loads(rmap.restore(value.model_dump_json()))
        return type(value).model_validate(data)
    if isinstance(value, list):
        return [rmap.restore(v) if isinstance(v, str) else v for v in value]
    if isinstance(value, str):
        return rmap.restore(value)
    return value


def enforce_citations(abstract: LeaseAbstract) -> list[str]:
    """Blank any field whose quote cannot be found. Returns the names that were dropped."""
    dropped: list[str] = []
    for name, f in abstract.fields():
        if not f.present:
            continue
        clause = locate(abstract.clauses, f.extracted_text)
        if clause is None:
            setattr(abstract, name, Field())
            dropped.append(name)
        elif f.source_clause_id != clause.id and abstract.clause(f.source_clause_id or "") is None:
            f.source_clause_id = clause.id
    return dropped


class Pipeline:
    def __init__(
        self,
        model: ModelClient | None = None,
        redactor: Redactor | None = None,
        segmenter: Segmenter | None = None,
        llm_confidence: float = 0.75,
        min_rule_confidence: float = 0.6,
    ) -> None:
        self.model = model
        self.redactor = redactor or Redactor()
        self.segmenter = segmenter or Segmenter()
        self.rules = RuleExtractor()
        self.llm_confidence = llm_confidence
        self.min_rule_confidence = min_rule_confidence
        self.last_llm_errors: list[str] = []
        self.last_gaps: list[str] = []
        self.last_filled: list[str] = []

    def run(self, text: str, source_name: str = "lease") -> LeaseAbstract:
        clauses = self.segmenter.segment(text)
        abstract = self.rules.extract(clauses, source_name=source_name)
        _, rmap = self.redactor.redact(text)
        abstract.redactions = len(rmap)
        self.last_llm_errors, self.last_gaps, self.last_filled = [], [], []

        if self.model is not None:
            gaps = [
                name
                for name, f in abstract.fields()
                if not f.present or f.confidence < self.min_rule_confidence
            ]
            self.last_gaps = gaps
            if gaps:
                self._fill_with_llm(abstract, clauses, gaps, rmap)

        dropped = enforce_citations(abstract)
        if dropped:
            log.info("dropped uncited fields: %s", ", ".join(dropped))
        return abstract

    def _fill_with_llm(
        self, abstract: LeaseAbstract, clauses: list[Clause], gaps: list[str], rmap: RedactionMap
    ) -> None:
        assert self.model is not None
        redacted = [
            c.model_copy(update={"text": self.redactor.redact(c.text, rmap)[0]}) for c in clauses
        ]
        llm = LLMExtractor(self.model)
        results = llm.fill(redacted, gaps)
        self.last_llm_errors = llm.errors
        for name, cited in results.items():
            quote = rmap.restore(cited.extracted_text)
            clause = locate(clauses, quote)
            if clause is None:
                log.info("LLM answer for %s discarded: quote not found in lease", name)
                continue
            try:
                value = _restore_value(cited.value, rmap)
            except ValidationError:
                continue
            setattr(
                abstract,
                name,
                Field(
                    value=value,
                    confidence=self.llm_confidence,
                    source_clause_id=clause.id,
                    extracted_text=quote,
                    origin="llm",
                ),
            )
            self.last_filled.append(name)


def abstract_lease(
    text: str, model: ModelClient | None = None, source_name: str = "lease"
) -> LeaseAbstract:
    return Pipeline(model=model).run(text, source_name=source_name)


__all__ = ["Pipeline", "abstract_lease", "enforce_citations", "locate"]
