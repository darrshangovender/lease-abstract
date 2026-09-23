"""Unfair-practice patterns for the provincial Rental Housing Tribunals.

The Rental Housing Act (s13, s15(1)(f)) lets each province regulate "unfair
practices" and gives the Tribunal power to rule on them. These patterns cover
the clauses that Tribunals consistently treat as unfair. They are reported as
``unfair_practice`` findings, not as breaches of a numbered statutory duty —
the remedy is a Tribunal complaint, not a criminal charge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract.rules import sentences
from .rules import ComplianceRule, Context, Finding

NEGATION_RE = re.compile(
    r"\b(?:may not|shall not|will not|must not|not entitled|is not permitted|no right|"
    r"except in (?:an? )?(?:genuine )?emergenc|only in (?:an? )?emergenc|save for emergenc)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UnfairPattern:
    id: str
    pattern: str
    description: str
    suggested_fix: str
    statute: str = "Rental Housing Act 50 of 1999"
    section: str = "s13(4)-(5) and s15(1)(f) read with the provincial Unfair Practice Regulations"
    negatable: bool = True


UNFAIR_PATTERNS: tuple[UnfairPattern, ...] = (
    UnfairPattern(
        id="UNFAIR-DEPOSIT-FORFEIT",
        pattern=r"(?:deposit[^.;]{0,120}\bforfeit|forfeit[^.;]{0,120}\bdeposit)",
        description="Deposit forfeited on breach rather than applied to proven damages/arrears.",
        suggested_fix=(
            "Replace with: the deposit may be applied only to the reasonable cost of repairing "
            "damage and to amounts actually owing, with the balance refunded under RHA s5(3)."
        ),
        negatable=False,
    ),
    UnfairPattern(
        id="UNFAIR-ENTRY-NO-NOTICE",
        pattern=(
            r"(?:enter|entry|access|inspect)[^.;]{0,100}"
            r"(?:at any time|at all reasonable and unreasonable times|without (?:any |prior |giving )?notice|at will|as (?:he|she|it) sees fit)"
        ),
        description="Landlord reserves a right to enter the premises without reasonable notice.",
        suggested_fix=(
            "Require reasonable written notice (the Amendment Act contemplates 24 hours) and "
            "entry at reasonable times, with an emergency exception."
        ),
    ),
    UnfairPattern(
        id="UNFAIR-REPAIR-WAIVER",
        pattern=(
            r"(?:(?:landlord|lessor)[^.;]{0,80}(?:no obligation|not (?:be )?(?:obliged|responsible|liable))[^.;]{0,80}(?:repair|maintain|habitab)"
            r"|(?:tenant|lessee)[^.;]{0,60}waive[^.;]{0,100}(?:repair|maintenance|habitab))"
        ),
        description="Tenant waives the landlord's obligation to maintain a habitable dwelling.",
        suggested_fix=(
            "Delete the waiver. The landlord's duty to provide and maintain a habitable dwelling "
            "cannot be contracted out of."
        ),
        negatable=False,
    ),
    UnfairPattern(
        id="UNFAIR-TRIBUNAL-WAIVER",
        pattern=r"(?:waive[^.;]{0,80}(?:tribunal|right to (?:approach|refer|lodge))|tribunal[^.;]{0,60}waive)",
        description="Clause purports to waive the tenant's right to approach the Rental Housing Tribunal.",
        suggested_fix="Delete. Access to the Tribunal is statutory and cannot be waived.",
        negatable=False,
    ),
    UnfairPattern(
        id="UNFAIR-LOCKOUT",
        pattern=(
            r"(?:change the locks|lock[- ]?out|disconnect[^.;]{0,40}(?:water|electricity|services|utilities)|"
            r"remove the tenant'?s? (?:belongings|possessions|goods)|evict[^.;]{0,40}without (?:a )?court order)"
        ),
        description="Self-help eviction: lock-out, utility disconnection or removal of goods without a court order.",
        suggested_fix=(
            "Delete. Eviction requires a court order under the Prevention of Illegal Eviction "
            "from and Unlawful Occupation of Land Act 19 of 1998; self-help remedies are unlawful."
        ),
        statute="Rental Housing Act 50 of 1999; PIE Act 19 of 1998",
        section="RHA s15(1)(f) read with the Unfair Practice Regulations; PIE s4 and s8",
    ),
)


def match_unfair(ctx: Context, pattern: UnfairPattern) -> tuple[str | None, str] | None:
    """Return ``(clause_id, sentence)`` for the first sentence that triggers ``pattern``."""
    rx = re.compile(pattern.pattern, re.IGNORECASE)
    for clause in ctx.clauses:
        for sent in sentences(clause.text):
            m = rx.search(sent)
            if not m:
                continue
            if pattern.negatable and NEGATION_RE.search(sent[: m.end()]):
                continue
            return clause.id, sent
    return None


def _make_check(pattern: UnfairPattern):
    def check(ctx: Context, rule: ComplianceRule) -> list[Finding]:
        hit = match_unfair(ctx, pattern)
        if hit is None:
            return []
        clause_id, sent = hit
        return [
            rule.finding(
                clause_id,
                f"{pattern.description} Clause reads: \"{sent[:200]}\"",
                pattern.suggested_fix,
            )
        ]

    return check


def tribunal_rules() -> list[ComplianceRule]:
    return [
        ComplianceRule(
            id=p.id,
            statute=p.statute,
            section=p.section,
            description=p.description,
            severity="high",
            status="in_force",
            check=_make_check(p),
            category="unfair_practice",
            tags=("tribunal",),
        )
        for p in UNFAIR_PATTERNS
    ]


__all__ = ["UNFAIR_PATTERNS", "UnfairPattern", "match_unfair", "tribunal_rules"]
