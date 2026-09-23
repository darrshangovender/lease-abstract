"""South African residential-lease rules.

Statutes encoded here:

* Rental Housing Act 50 of 1999 (in force)
* Rental Housing Amendment Act 35 of 2014 (**pending proclamation** — see
  :data:`~lease_abstract.compliance.rules.PENDING_NOTE`)
* Consumer Protection Act 68 of 2008, s14 (in force; applicability depends on
  whether the landlord is a supplier acting in the ordinary course of business)
* Protection of Personal Information Act 4 of 2013 (in force; advisory)
* Common-law notice for periodic leases, as applied by the Rental Housing
  Tribunals (advisory position, not a numbered statutory duty)

Section references follow the project brief. Verify against the gazetted
text before relying on a citation in a dispute.
"""

from __future__ import annotations

import re

from ..extract.rules import find_counts, sentences
from ..schema import Party
from .rules import Applicability, ComplianceRule, Context, Finding
from .tribunal import NEGATION_RE, tribunal_rules

RHA = "Rental Housing Act 50 of 1999"
RHAA = "Rental Housing Amendment Act 35 of 2014"
CPA = "Consumer Protection Act 68 of 2008"
POPIA = "Protection of Personal Information Act 4 of 2013"

BUSINESS_DAYS_20_AS_CALENDAR = 28  # 20 business days is roughly four calendar weeks


# --------------------------------------------------------------------------- #
# Rental Housing Act 50 of 1999
# --------------------------------------------------------------------------- #


def check_deposit_interest(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    dep = ctx.abstract.deposit
    if dep.value is None:
        return []
    if dep.value.interest_bearing is False:
        return [
            rule.finding(
                dep.source_clause_id,
                "The lease states the deposit will not earn interest. Section 5(3)(d) requires the "
                "landlord to invest the deposit in an interest-bearing account at not less than the "
                "bank's savings rate, with the interest accruing to the tenant.",
                "Amend the deposit clause: 'The deposit shall be invested in an interest-bearing "
                "account with a financial institution at a rate not less than the rate applicable "
                "to a savings account, and the interest shall accrue to the Tenant. The Landlord "
                "shall provide written proof of the interest on request.'",
            )
        ]
    if dep.value.interest_bearing is None:
        return [
            rule.finding(
                dep.source_clause_id,
                "The lease is silent on whether the deposit earns interest. Section 5(3)(d) applies "
                "regardless, but the tenant has no contractual record of the right.",
                "State expressly that the deposit is held in an interest-bearing account at not less "
                "than the savings rate, that interest accrues to the tenant, and that written proof "
                "is available on request.",
                severity="low",
            )
        ]
    return []


def check_deposit_refund(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    dep = ctx.abstract.deposit
    if dep.value is None or dep.value.refund_days is None:
        return []
    days = dep.value.refund_days
    if days > 21:
        return [
            rule.finding(
                dep.source_clause_id,
                f"The lease allows {days} days to refund the deposit. Section 5(3)(e)-(g) requires "
                "refund of the deposit plus interest within 7 days where there is no damage, 14 days "
                "where deductions are made, and 21 days where the tenant did not attend the outgoing "
                "inspection.",
                "Change the refund period to 7 days (no deductions) / 14 days (with an itemised "
                "statement of deductions), and 21 days only where the tenant fails to attend the "
                "outgoing inspection.",
            )
        ]
    if days > 14:
        return [
            rule.finding(
                dep.source_clause_id,
                f"The lease allows {days} days to refund the deposit. That period is only permitted "
                "where the tenant failed to attend the outgoing inspection (s5(3)(g)); otherwise the "
                "limit is 7 days (no damage) or 14 days (with deductions).",
                "Tie the 21-day period expressly to the tenant's non-attendance at the outgoing "
                "inspection and state the 7/14-day periods for the ordinary cases.",
                severity="medium",
            )
        ]
    if days > 7:
        return [
            rule.finding(
                dep.source_clause_id,
                f"The lease allows {days} days to refund the deposit. That is within the 14-day limit "
                "for refunds with deductions, but where there is no damage the deposit and interest "
                "must be refunded within 7 days (s5(3)(e)).",
                "State the 7-day period for the no-deduction case explicitly.",
                severity="low",
            )
        ]
    return []


JOINT_INSPECTION_RE = re.compile(
    r"(?:joint(?:ly)?[^.;]{0,80}inspect|inspect[^.;]{0,80}(?:joint|together|both parties|in the presence of))",
    re.IGNORECASE,
)


def check_joint_inspection(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    if JOINT_INSPECTION_RE.search(ctx.text):
        return []
    clause = ctx.find_clause(r"inspect", categories=["access", "deposit"])
    if clause is None and "inspect" in ctx.low:
        clause = ctx.find_clause(r"inspect")
    if clause is not None:
        return [
            rule.finding(
                clause.id,
                "The lease mentions an inspection but not a joint incoming and outgoing inspection "
                "by landlord and tenant together, which section 5(3) requires.",
                "Add: 'The Landlord and Tenant shall jointly inspect the premises before the Tenant "
                "moves in and again at the end of the lease, and record any defects in writing.'",
                severity="low",
            )
        ]
    return [
        rule.finding(
            None,
            "The lease makes no provision for the joint incoming and outgoing inspection required "
            "by section 5(3). Without a recorded incoming inspection the landlord cannot later prove "
            "damage against the deposit.",
            "Add a clause providing for a joint inspection at the start and end of the lease with "
            "a written, signed defects list.",
            severity="medium",
        )
    ]


# --------------------------------------------------------------------------- #
# Rental Housing Amendment Act 35 of 2014 (pending proclamation)
# --------------------------------------------------------------------------- #

ENTRY_RE = re.compile(r"\b(?:enter|entry|access|inspect)", re.IGNORECASE)
NO_NOTICE_RE = re.compile(
    r"at any time|at all times|without (?:any |prior |giving )?notice|at will", re.IGNORECASE
)


def check_inspection_notice(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    for clause in ctx.clauses:
        for sent in sentences(clause.text):
            if not ENTRY_RE.search(sent):
                continue
            m = NO_NOTICE_RE.search(sent)
            if m and not NEGATION_RE.search(sent[: m.end()]):
                return [
                    rule.finding(
                        clause.id,
                        "The landlord may enter without notice. The Amendment Act requires the "
                        "landlord to give the tenant 24 hours' written notice before an inspection "
                        f"or entry. Clause reads: \"{sent[:200]}\"",
                        "Require at least 24 hours' written notice and entry at reasonable times, "
                        "with an emergency exception.",
                    )
                ]
            short = [c for c in find_counts(sent) if c.unit == "hour" and c.n < 24]
            if short and not NEGATION_RE.search(sent):
                return [
                    rule.finding(
                        clause.id,
                        f"The lease requires only {short[0].n} hours' notice before the landlord enters. "
                        "The Amendment Act requires 24 hours' written notice.",
                        "Change the notice period to at least 24 hours in writing.",
                    )
                ]
    return []


ORAL_RE = re.compile(
    r"\b(?:oral|verbal)\b[^.;]{0,80}\b(?:binding|valid|enforceable|effective)\b", re.IGNORECASE
)


def check_written_lease(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    for clause in ctx.clauses:
        for sent in sentences(clause.text):
            m = ORAL_RE.search(sent)
            if m and not re.search(r"\b(?:not|no|neither|nor)\b", sent[: m.end()], re.IGNORECASE):
                return [
                    rule.finding(
                        clause.id,
                        "The lease treats oral variations as binding. The Amendment Act makes a "
                        f"written lease mandatory. Clause reads: \"{sent[:200]}\"",
                        "Provide that no variation is binding unless reduced to writing and signed "
                        "by both parties.",
                    )
                ]
    return []


# --------------------------------------------------------------------------- #
# Consumer Protection Act 68 of 2008, s14
# --------------------------------------------------------------------------- #

BUSINESS_RE = re.compile(
    r"ordinary course of (?:its |his |her |their )?business|letting agent|managing agent|"
    r"estate agent|rental agent|property management",
    re.IGNORECASE,
)


def cpa_applicability(landlord: Party | None, text: str = "") -> Applicability:
    """CPA s14 binds a *supplier* — a juristic landlord or anyone letting in the ordinary course of business."""
    if landlord is not None and landlord.kind == "juristic":
        return "likely"
    if BUSINESS_RE.search(text):
        return "likely"
    return "uncertain"


def _is_fixed_term(ctx: Context) -> bool:
    term = ctx.abstract.term.value
    if term is None:
        return bool(re.search(r"fixed[- ]term|for a period of", ctx.low)) and not re.search(
            r"month[- ]to[- ]month", ctx.low
        )
    return term.kind == "fixed"


TENANT_CANCEL_20BD_RE = re.compile(
    r"(?:tenant|lessee|consumer)[^.;]{0,160}(?:cancel|terminat)[^.;]{0,160}(?:20|twenty)[^.;]{0,25}business days",
    re.IGNORECASE,
)


def check_cpa_cancellation(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    if not _is_fixed_term(ctx):
        return []
    appl = cpa_applicability(ctx.abstract.landlord.value, ctx.text)
    notice = ctx.abstract.notice.value
    clause_id = ctx.abstract.notice.source_clause_id
    if notice is None or notice.tenant_days is None:
        if TENANT_CANCEL_20BD_RE.search(ctx.text):
            return []
        ids = ctx.clause_ids(["notice", "term"])
        return [
            rule.finding(
                clause_id or (ids[0] if ids else None),
                "This is a fixed-term lease with no right for the tenant to cancel early. CPA s14(2)(b) "
                "lets the consumer cancel a fixed-term agreement on 20 business days' written notice, "
                "subject to a reasonable cancellation penalty (s14(3)).",
                "Add: 'The Tenant may cancel this lease at any time on 20 (twenty) business days' "
                "written notice, subject to a reasonable cancellation penalty as contemplated in "
                "section 14(3) of the Consumer Protection Act.'",
                applicability=appl,
            )
        ]
    too_long = (notice.tenant_unit == "business" and notice.tenant_days > 20) or (
        notice.tenant_unit == "calendar" and notice.tenant_days > BUSINESS_DAYS_20_AS_CALENDAR
    )
    if too_long:
        unit = "business" if notice.tenant_unit == "business" else "calendar"
        return [
            rule.finding(
                clause_id,
                f"The tenant must give {notice.tenant_days} {unit} days' notice to cancel. CPA s14(2)(b) "
                "caps the consumer's notice at 20 business days.",
                "Reduce the tenant's cancellation notice to 20 business days (a reasonable "
                "cancellation penalty may still be charged).",
                applicability=appl,
            )
        ]
    return []


EXPIRY_NOTICE_RE = re.compile(
    r"(?:40|forty)[^.;]{0,20}(?:and|to|-|–)[^.;]{0,10}(?:80|eighty)[^.;]{0,20}business days|"
    r"(?:not (?:more|later) than 80|not less than 40|between 40 and 80)[^.;]{0,30}business days|"
    r"(?:40|forty)[^.;]{0,15}business days[^.;]{0,120}(?:expir|end of the lease|terminat)",
    re.IGNORECASE,
)


def check_cpa_expiry_notice(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    if not _is_fixed_term(ctx):
        return []
    if EXPIRY_NOTICE_RE.search(ctx.text):
        return []
    appl = cpa_applicability(ctx.abstract.landlord.value, ctx.text)
    ids = ctx.clause_ids(["cpa", "term"])
    return [
        rule.finding(
            ids[0] if ids else None,
            "The lease does not record the landlord's duty to notify the tenant of the impending "
            "expiry. CPA s14(2)(b)(i) requires written notice not more than 80 nor less than 40 "
            "business days before the end of a fixed term, including any material changes proposed.",
            "Add: 'The Landlord shall give the Tenant written notice of the expiry of this lease, and "
            "of any proposed changes, not more than 80 and not less than 40 business days before the "
            "termination date.'",
            applicability=appl,
        )
    ]


NO_RENEWAL_RE = re.compile(
    r"(?:shall|will|may) not (?:be )?(?:renew|continue|extend|roll)|no (?:right of |automatic |further )?(?:renewal|extension)|"
    r"(?:expire|terminate)[^.;]{0,40}automatically[^.;]{0,80}(?:vacate|not be (?:renewed|extended))",
    re.IGNORECASE,
)


def check_cpa_auto_renewal(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    if not _is_fixed_term(ctx):
        return []
    for clause in ctx.clauses:
        for sent in sentences(clause.text):
            m = NO_RENEWAL_RE.search(sent)
            if m and "unless" not in sent.lower():
                return [
                    rule.finding(
                        clause.id,
                        "The lease excludes continuation after expiry. CPA s14(2)(d) provides that on "
                        "expiry a fixed-term agreement continues on a month-to-month basis unless the "
                        f"consumer elects otherwise. Clause reads: \"{sent[:200]}\"",
                        "Replace with: 'On expiry this lease shall continue on a month-to-month basis "
                        "on the same terms unless the Tenant elects otherwise or the parties agree a "
                        "new fixed term.'",
                        applicability=cpa_applicability(ctx.abstract.landlord.value, ctx.text),
                    )
                ]
    return []


# --------------------------------------------------------------------------- #
# Periodic (month-to-month) notice — common-law position applied by Tribunals
# --------------------------------------------------------------------------- #


def check_monthly_notice(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    term = ctx.abstract.term.value
    notice = ctx.abstract.notice.value
    if term is None or term.kind != "month_to_month" or notice is None:
        return []
    shortest = None
    for days, unit in ((notice.tenant_days, notice.tenant_unit), (notice.landlord_days, notice.landlord_unit)):
        if days is None:
            continue
        cal = days if unit == "calendar" else round(days * 7 / 5)
        shortest = cal if shortest is None else min(shortest, cal)
    if shortest is None or shortest >= 30:
        return []
    return [
        rule.finding(
            ctx.abstract.notice.source_clause_id,
            f"A month-to-month lease may be ended on {shortest} days' notice. The accepted position "
            "for a periodic monthly tenancy is one full calendar month's notice; the Rental Housing "
            "Tribunals treat materially shorter notice as an unfair practice.",
            "Change the notice period to one calendar month, given in writing before the first day "
            "of the month.",
        )
    ]


# --------------------------------------------------------------------------- #
# POPIA
# --------------------------------------------------------------------------- #


def check_popia(ctx: Context, rule: ComplianceRule) -> list[Finding]:
    n = ctx.abstract.redactions
    if n == 0:
        return []
    ids = ctx.clause_ids(["parties", "privacy"])
    return [
        rule.finding(
            ids[0] if ids else None,
            f"The lease contains {n} item(s) of personal information (ID numbers, contact details, "
            "bank details). POPIA requires a lawful purpose for processing them (s9-s11). This tool "
            "redacted every item before any model call and from its logs; the lawful purpose is "
            "performance of the abstraction the parties requested.",
            "Keep the personal information to what the lease needs, state the purpose for which it "
            "is collected, and restrict who may access the signed document.",
        )
    ]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

SA_RULES: list[ComplianceRule] = [
    ComplianceRule(
        id="RHA-5-3-D-INTEREST",
        statute=RHA,
        section="s5(3)(d)",
        description="Deposit held in an interest-bearing account at not less than the savings rate; interest to tenant.",
        severity="high",
        status="in_force",
        check=check_deposit_interest,
    ),
    ComplianceRule(
        id="RHA-5-3-E-REFUND",
        statute=RHA,
        section="s5(3)(e)-(g)",
        description="Deposit plus interest refunded within 7 / 14 / 21 days.",
        severity="high",
        status="in_force",
        check=check_deposit_refund,
    ),
    ComplianceRule(
        id="RHA-5-3-INSPECTION",
        statute=RHA,
        section="s5(3)",
        description="Joint incoming and outgoing inspection.",
        severity="medium",
        status="in_force",
        check=check_joint_inspection,
    ),
    ComplianceRule(
        id="RHAA-2014-INSPECTION-NOTICE",
        statute=RHAA,
        section="s5 (inserting s4B) - 24 hours' written notice before inspection",
        description="Landlord must give 24 hours' written notice before entering to inspect.",
        severity="medium",
        status="pending_proclamation",
        check=check_inspection_notice,
    ),
    ComplianceRule(
        id="RHAA-2014-WRITTEN-LEASE",
        statute=RHAA,
        section="s5 (amending s5(1)) - written lease mandatory",
        description="Lease must be reduced to writing.",
        severity="low",
        status="pending_proclamation",
        check=check_written_lease,
    ),
    ComplianceRule(
        id="CPA-14-CANCELLATION",
        statute=CPA,
        section="s14(2)(b)(ii) and s14(3)",
        description="Consumer may cancel a fixed-term agreement on 20 business days' notice.",
        severity="medium",
        status="in_force",
        check=check_cpa_cancellation,
    ),
    ComplianceRule(
        id="CPA-14-EXPIRY-NOTICE",
        statute=CPA,
        section="s14(2)(b)(i)",
        description="Supplier must notify expiry 40-80 business days before the end of a fixed term.",
        severity="low",
        status="in_force",
        check=check_cpa_expiry_notice,
    ),
    ComplianceRule(
        id="CPA-14-AUTO-RENEWAL",
        statute=CPA,
        section="s14(2)(d)",
        description="Fixed-term agreement continues month-to-month on expiry unless the consumer elects otherwise.",
        severity="medium",
        status="in_force",
        check=check_cpa_auto_renewal,
    ),
    ComplianceRule(
        id="COMMON-LAW-MONTHLY-NOTICE",
        statute="Common law (periodic lease), as applied by the Rental Housing Tribunals",
        section="RHA s13 and s15(1)(f) (unfair practice)",
        description="Month-to-month tenancy requires one calendar month's notice.",
        severity="medium",
        status="in_force",
        check=check_monthly_notice,
        category="unfair_practice",
    ),
    ComplianceRule(
        id="POPIA-PII",
        statute=POPIA,
        section="s9-s11 (lawful processing, minimality, consent/justification)",
        description="Personal information in the lease must be processed for a documented lawful purpose.",
        severity="info",
        status="in_force",
        check=check_popia,
        category="advisory",
    ),
]


def all_rules() -> list[ComplianceRule]:
    return list(SA_RULES) + tribunal_rules()


def rule_by_id(rule_id: str) -> ComplianceRule:
    for r in all_rules():
        if r.id == rule_id:
            return r
    raise KeyError(rule_id)


__all__ = ["SA_RULES", "all_rules", "cpa_applicability", "rule_by_id"]
