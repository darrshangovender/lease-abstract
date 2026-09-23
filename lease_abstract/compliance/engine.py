"""Run every rule over an abstract and collect a :class:`ComplianceReport`."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PField

from ..schema import LeaseAbstract
from .rules import SEVERITY_ORDER, ComplianceRule, Context, Finding
from .sa import all_rules


class ComplianceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = "lease"
    findings: list[Finding] = PField(default_factory=list)
    rules_evaluated: int = 0

    def violations(self) -> list[Finding]:
        """In-force violations and unfair practices. Never includes pending rules."""
        return [f for f in self.findings if f.is_violation]

    def pending(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "pending_proclamation"]

    def advisories(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "in_force" and f.category == "advisory"]

    def by_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def rule_ids(self) -> set[str]:
        return {f.rule_id for f in self.findings}

    @property
    def worst_severity(self) -> str:
        v = self.violations()
        if not v:
            return "none"
        return max(v, key=lambda f: SEVERITY_ORDER[f.severity]).severity


class ComplianceEngine:
    def __init__(self, rules: Sequence[ComplianceRule] | None = None) -> None:
        self.rules = list(rules) if rules is not None else all_rules()

    def run(self, abstract: LeaseAbstract, text: str | None = None) -> ComplianceReport:
        if text is None:
            text = "\n".join(
                f"{c.heading + ' ' if c.heading else ''}{c.text}".strip() for c in abstract.clauses
            )
        ctx = Context(abstract=abstract, clauses=list(abstract.clauses), text=text)
        findings: list[Finding] = []
        for rule in self.rules:
            findings.extend(rule.run(ctx))
        findings.sort(key=lambda f: (f.status != "in_force", -SEVERITY_ORDER[f.severity], f.rule_id))
        return ComplianceReport(
            source_name=abstract.source_name, findings=findings, rules_evaluated=len(self.rules)
        )


def check_lease(abstract: LeaseAbstract, text: str | None = None) -> ComplianceReport:
    return ComplianceEngine().run(abstract, text)


__all__ = ["ComplianceEngine", "ComplianceReport", "check_lease"]
