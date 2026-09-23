"""Plain-English summaries, one for each side of the table.

Both summaries are generated from the same abstract and the same findings.
They differ in voice ("your deposit" vs "the deposit you hold") and in what
each party most needs to act on — never in the facts. An optional LLM polish
pass may rephrase, but every number in the deterministic text must survive
it unchanged; :func:`polish` diffs the numbers and raises if any went missing
or appeared from nowhere.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from typing import Literal

from .compliance.engine import ComplianceReport
from .compliance.rules import Finding
from .extract.llm import ModelClient
from .privacy import Redactor
from .schema import LeaseAbstract

Audience = Literal["tenant", "landlord"]


class NumberMismatchError(AssertionError):
    def __init__(self, missing: Counter, added: Counter) -> None:
        self.missing, self.added = missing, added
        super().__init__(f"polish changed numbers: missing={dict(missing)} added={dict(added)}")


def fmt_zar(amount: float) -> str:
    whole = int(amount)
    cents = round((amount - whole) * 100)
    grouped = f"{whole:,}".replace(",", " ")
    return f"R{grouped},{cents:02d}" if cents else f"R{grouped}"


def fmt_date(d: date | None) -> str:
    # Built by hand: strftime's %-d is not portable to Windows.
    return f"{d.day} {d.strftime('%B %Y')}" if d else "an unstated date"


def numbers_in(text: str) -> Counter:
    """Multiset of numbers, with SA thousand-grouping collapsed (``8 500`` == ``8500``)."""
    collapsed = re.sub(r"(?<=\d)[ ,](?=\d{3}\b)", "", text)
    return Counter(re.findall(r"\d+(?:[.,]\d+)?", collapsed))


def _plural(n: float, word: str) -> str:
    n_txt = f"{n:g}"
    return f"{n_txt} {word}{'' if n == 1 else 's'}"


def _months_phrase(months: float | None) -> str:
    if not months:
        return ""
    possessive = "month's" if months == 1 else "months'"
    return f" ({months:g} {possessive} rent)"


def _party_desc(abstract: LeaseAbstract, role: str) -> str:
    f = abstract.landlord if role == "landlord" else abstract.tenant
    if f.value is None:
        return f"the {role} (not identified in the lease)"
    kind = {"individual": "an individual", "juristic": "a company or other juristic person"}.get(
        f.value.kind, "of unknown type"
    )
    return f"{f.value.name} ({kind})"


def _severity_word(f: Finding) -> str:
    return {"high": "Serious", "medium": "Important", "low": "Minor", "info": "Note"}[f.severity]


class Summariser:
    def __init__(self, abstract: LeaseAbstract, report: ComplianceReport | None = None) -> None:
        self.abstract = abstract
        self.report = report or ComplianceReport(source_name=abstract.source_name)

    # ------------------------------------------------------------------ core
    def _core(self, aud: Audience) -> list[str]:
        a = self.abstract
        you_are = "tenant" if aud == "tenant" else "landlord"
        other = "landlord" if aud == "tenant" else "tenant"
        lines: list[str] = []
        title = a.premises.value.address if a.premises.value else "the premises"
        lines.append(f"Summary for the {you_are} - {title}")
        lines.append("")
        lines.append(f"Parties. You are {_party_desc(a, you_are)}. The {other} is {_party_desc(a, other)}.")

        t = a.term.value
        if t is None:
            lines.append("Term. The lease does not clearly state its duration.")
        elif t.kind == "month_to_month":
            lines.append(
                "Term. This is a month-to-month lease"
                + (f" starting on {fmt_date(t.start)}" if t.start else "")
                + ". It runs until one side gives notice."
            )
        else:
            span = f" from {fmt_date(t.start)} to {fmt_date(t.end)}" if t.start and t.end else ""
            months = f" of {_plural(t.months, 'month')}" if t.months else ""
            lines.append(f"Term. A fixed-term lease{months}{span}.")

        r = a.rent.value
        if r is None:
            lines.append("Rent. The rent amount could not be determined from the lease.")
        else:
            due = f", due on day {r.due_day} of each month" if r.due_day else ""
            method = f", paid by {r.method}" if r.method else ""
            verb = "You pay" if aud == "tenant" else "The tenant pays"
            lines.append(f"Rent. {verb} {fmt_zar(r.amount_zar)} per month{due}{method}.")
        e = a.escalation.value
        if e is not None:
            when = "on each anniversary of the lease" if e.anniversary else "as set out in the lease"
            by = f"{e.pct:g}%" if e.pct is not None else fmt_zar(e.amount_zar or 0)
            lines.append(f"Escalation. The rent increases by {by} {when}.")

        d = a.deposit.value
        if d is not None:
            amount = fmt_zar(d.amount_zar) + _months_phrase(d.months_equivalent)
            if aud == "tenant":
                base = f"Deposit. Your deposit of {amount} must be held in an interest-bearing account and the interest belongs to you (Rental Housing Act s5(3)(d))."
            else:
                base = f"Deposit. You hold a deposit of {amount}. You must keep it in an interest-bearing account at not less than the savings rate; the interest belongs to the tenant (Rental Housing Act s5(3)(d))."
            if d.interest_bearing is False:
                base += " The lease says otherwise - that clause is not enforceable against the tenant."
            if d.refund_days is not None:
                base += f" The lease says it will be refunded within {_plural(d.refund_days, 'day')} after the lease ends."
            base += " The law requires refund within 7 days where there is no damage and 14 days where deductions are made."
            lines.append(base)

        n = a.notice.value
        if n is not None:
            parts = []
            if n.tenant_days is not None:
                who = "You" if aud == "tenant" else "The tenant"
                parts.append(f"{who} may end the lease on {n.tenant_days} {n.tenant_unit} days' written notice")
            if n.landlord_days is not None:
                who = "your landlord" if aud == "tenant" else "you"
                parts.append(f"{who} may end it on {n.landlord_days} {n.landlord_unit} days' written notice")
            if parts:
                lines.append("Notice. " + "; ".join(parts) + ".")

        m = a.maintenance.value
        if m is not None and (m.landlord or m.tenant):
            mine, theirs = (m.tenant, m.landlord) if aud == "tenant" else (m.landlord, m.tenant)
            if mine:
                lines.append("Your maintenance duties. " + "; ".join(mine) + ".")
            if theirs:
                lines.append(f"The {other}'s maintenance duties. " + "; ".join(theirs) + ".")

        p = a.penalties.value
        if p:
            lines.append("Penalties. " + " ".join(p))
        s = a.special_clauses.value
        if s:
            lines.append("Special clauses to read carefully: " + ", ".join(s) + ".")
        return lines

    def _findings(self, aud: Audience) -> list[str]:
        lines: list[str] = []
        violations = self.report.violations()
        pending = self.report.pending()
        advisories = self.report.advisories()
        lines.append("")
        if violations:
            head = (
                "Where this lease falls short of the law (you can raise these with your landlord or the Rental Housing Tribunal):"
                if aud == "tenant"
                else "Where this lease falls short of the law (fix these before signing - a tenant can take them to the Rental Housing Tribunal):"
            )
            lines.append(head)
            for f in violations:
                lines.append(f"- {_severity_word(f)} [{f.rule_id}, {f.statute} {f.section}]: {f.explanation}")
                if aud == "landlord":
                    lines.append(f"  Suggested fix: {f.suggested_fix}")
                if f.applicability != "applies":
                    lines.append(
                        f"  Applicability is {f.applicability}: the Consumer Protection Act binds landlords who let in the ordinary course of business."
                    )
        else:
            lines.append("No breaches of current law were found in this lease.")
        if pending:
            lines.append("")
            lines.append("Coming law (not yet in force - the Rental Housing Amendment Act is still to be proclaimed):")
            for f in pending:
                lines.append(f"- {f.explanation}")
        if advisories:
            lines.append("")
            for f in advisories:
                lines.append(f"Note: {f.explanation}")
        lines.append("")
        lines.append("This summary is generated from the lease text and is not legal advice.")
        return lines

    def for_tenant(self) -> str:
        return "\n".join(self._core("tenant") + self._findings("tenant"))

    def for_landlord(self) -> str:
        return "\n".join(self._core("landlord") + self._findings("landlord"))

    def render(self, audience: Audience) -> str:
        return self.for_tenant() if audience == "tenant" else self.for_landlord()


def polish(text: str, model: ModelClient, redactor: Redactor | None = None) -> str:
    """Ask a model to smooth the prose. Every number must survive, or this raises."""
    redactor = redactor or Redactor()
    safe, rmap = redactor.redact(text)
    prompt = (
        "Rewrite the following lease summary in warm, plain English for a non-lawyer. "
        "Keep every number, amount, date, section reference and placeholder exactly as written. "
        "Do not add facts.\n\n" + safe
    )
    out = model.complete(prompt)
    out = rmap.restore(out)
    before, after = numbers_in(text), numbers_in(out)
    missing, added = before - after, after - before
    if missing or added:
        raise NumberMismatchError(missing, added)
    return out


def summarise(
    abstract: LeaseAbstract,
    report: ComplianceReport | None,
    audience: Audience,
    model: ModelClient | None = None,
) -> str:
    """Deterministic summary, optionally polished. Falls back to the template on number drift."""
    text = Summariser(abstract, report).render(audience)
    if model is None:
        return text
    try:
        return polish(text, model)
    except NumberMismatchError:
        return text


__all__ = [
    "NumberMismatchError",
    "Summariser",
    "fmt_date",
    "fmt_zar",
    "numbers_in",
    "polish",
    "summarise",
]
