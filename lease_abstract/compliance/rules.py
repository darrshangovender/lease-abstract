"""Compliance rule primitives.

A :class:`ComplianceRule` binds a statute + section to a check function.
Rules carry a ``status`` — ``in_force`` or ``pending_proclamation`` — and
the engine guarantees that a pending rule can only ever produce a finding
tagged ``pending_proclamation`` with the standing note attached. It cannot
be reported as a current-law violation.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..schema import Clause, ClauseCategory, LeaseAbstract

Severity = Literal["info", "low", "medium", "high"]
Status = Literal["in_force", "pending_proclamation"]
Category = Literal["violation", "unfair_practice", "advisory", "pending"]
Applicability = Literal["applies", "likely", "uncertain"]

PENDING_NOTE = (
    "Rental Housing Amendment Act 35 of 2014: widely reported as in force, but the gazette "
    "record still shows commencement 'to be proclaimed'. Build for it; do not assert it is in force."
)

SEVERITY_ORDER: dict[str, int] = {"info": 0, "low": 1, "medium": 2, "high": 3}


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    status: Status
    clause_id: str | None
    explanation: str
    suggested_fix: str
    statute: str = ""
    section: str = ""
    category: Category = "violation"
    applicability: Applicability = "applies"
    note: str | None = None

    @property
    def is_violation(self) -> bool:
        return self.status == "in_force" and self.category in {"violation", "unfair_practice"}


@dataclass
class Context:
    """Everything a check may look at."""

    abstract: LeaseAbstract
    clauses: list[Clause]
    text: str

    @property
    def low(self) -> str:
        return self.text.lower()

    def find_clause(
        self, pattern: str | re.Pattern[str], categories: Sequence[ClauseCategory] | None = None
    ) -> Clause | None:
        rx = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
        pool = [c for c in self.clauses if categories is None or c.category in categories]
        for c in pool + [c for c in self.clauses if c not in pool]:
            if rx.search(c.text) or (c.heading and rx.search(c.heading)):
                return c
        return None

    def clause_ids(self, categories: Sequence[ClauseCategory]) -> list[str]:
        return [c.id for c in self.clauses if c.category in categories]


CheckFn = Callable[["Context", "ComplianceRule"], list[Finding]]


@dataclass
class ComplianceRule:
    id: str
    statute: str
    section: str
    description: str
    severity: Severity
    status: Status
    check: CheckFn
    category: Category = "violation"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def finding(
        self,
        clause_id: str | None,
        explanation: str,
        suggested_fix: str,
        severity: Severity | None = None,
        applicability: Applicability = "applies",
    ) -> Finding:
        pending = self.status == "pending_proclamation"
        return Finding(
            rule_id=self.id,
            severity=severity or self.severity,
            status=self.status,
            clause_id=clause_id,
            explanation=explanation,
            suggested_fix=suggested_fix,
            statute=self.statute,
            section=self.section,
            category="pending" if pending else self.category,
            applicability=applicability,
            note=PENDING_NOTE if pending else None,
        )

    def run(self, ctx: Context) -> list[Finding]:
        out = []
        for f in self.check(ctx, self):
            if self.status == "pending_proclamation":
                # Belt and braces: a pending rule can never emit anything else.
                f = f.model_copy(
                    update={"status": "pending_proclamation", "category": "pending", "note": PENDING_NOTE}
                )
            out.append(f)
        return out


__all__ = [
    "Applicability",
    "Category",
    "CheckFn",
    "ComplianceRule",
    "Context",
    "Finding",
    "PENDING_NOTE",
    "SEVERITY_ORDER",
    "Severity",
    "Status",
]
