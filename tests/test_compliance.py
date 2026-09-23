"""Every compliance rule: one true positive and one true negative each, and the
guarantee that pending-proclamation rules are never reported as violations."""

import pytest

from lease_abstract import ComplianceEngine, Pipeline
from lease_abstract.compliance import (
    PENDING_NOTE,
    ComplianceRule,
    Finding,
    all_rules,
    cpa_applicability,
    rule_by_id,
)
from lease_abstract.compliance.rules import Context
from lease_abstract.schema import Party

from .conftest import (
    ACCESS_OK,
    DEPOSIT_OK,
    LANDLORD_JURISTIC,
    TERM_FIXED,
    TERM_MONTHLY,
    make_lease,
    pending_ids,
    report_for,
    violation_ids,
)


def test_compliant_base_lease_has_no_violations():
    r = report_for(make_lease())
    assert r.violations() == []
    assert r.pending() == []
    assert r.worst_severity == "none"
    assert r.rules_evaluated == len(all_rules()) == 15


# ---------------------------------------------------------------- RHA s5(3)(d)
def test_deposit_interest_violation_when_non_interest_account():
    dep = DEPOSIT_OK.replace(
        "5.2 The deposit shall be invested in an interest-bearing account at not less than the savings rate and the interest shall accrue to the Tenant.",
        "5.2 The deposit will be held in the Landlord's current account and will not earn interest.",
    )
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "RHA-5-3-D-INTEREST")
    assert f.severity == "high" and f.clause_id == "c5.1" and "5(3)(d)" in f.explanation


def test_deposit_interest_silent_is_low_severity_and_interest_bearing_is_clean():
    dep = "\n".join(line for line in DEPOSIT_OK.splitlines() if not line.startswith("5.2"))
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "RHA-5-3-D-INTEREST")
    assert f.severity == "low"
    assert "RHA-5-3-D-INTEREST" not in violation_ids(make_lease())


# ---------------------------------------------------------------- RHA s5(3)(e)-(g)
@pytest.mark.parametrize("days, severity", [(30, "high"), (21, "medium"), (14, "low")])
def test_deposit_refund_period_graded(days, severity):
    dep = DEPOSIT_OK.replace("within 7 (seven) days", f"within {days} days")
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "RHA-5-3-E-REFUND")
    assert f.severity == severity


def test_deposit_refund_within_7_days_is_clean():
    assert "RHA-5-3-E-REFUND" not in violation_ids(make_lease())


# ---------------------------------------------------------------- RHA s5(3) inspection
def test_joint_inspection_missing_entirely_is_medium():
    dep = "\n".join(line for line in DEPOSIT_OK.splitlines() if not line.startswith("5.3"))
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "RHA-5-3-INSPECTION")
    assert f.severity == "medium" and f.clause_id is None


def test_inspection_not_joint_is_low_and_joint_is_clean():
    dep = DEPOSIT_OK.replace(
        "5.3 The Landlord and Tenant shall jointly inspect the premises at the start and at the end of the lease and record defects in writing.",
        "5.3 The Landlord shall inspect the premises at the end of the lease.",
    )
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "RHA-5-3-INSPECTION")
    assert f.severity == "low" and f.clause_id == "c5.3"
    assert "RHA-5-3-INSPECTION" not in violation_ids(make_lease())


# ---------------------------------------------------------------- RHAA 2014 (pending)
def test_entry_without_notice_is_pending_note_plus_tribunal_unfair_practice():
    text = make_lease(access="6.1 The Landlord may enter the premises at any time without notice to inspect them.")
    r = report_for(text)
    assert "RHAA-2014-INSPECTION-NOTICE" in {f.rule_id for f in r.pending()}
    assert "RHAA-2014-INSPECTION-NOTICE" not in {f.rule_id for f in r.violations()}
    assert "UNFAIR-ENTRY-NO-NOTICE" in {f.rule_id for f in r.violations()}


def test_short_hours_notice_is_pending_only():
    text = make_lease(access="6.1 The Landlord may enter the premises on 12 hours' notice to inspect them.")
    assert pending_ids(text) == {"RHAA-2014-INSPECTION-NOTICE"}
    assert "UNFAIR-ENTRY-NO-NOTICE" not in violation_ids(text)


def test_24_hours_notice_and_negated_entry_are_clean():
    assert pending_ids(make_lease()) == set()
    negated = "6.1 The Landlord may not enter the premises at any time without notice, except in an emergency."
    assert pending_ids(make_lease(access=negated)) == set()
    assert "UNFAIR-ENTRY-NO-NOTICE" not in violation_ids(make_lease(access=negated))


def test_oral_variation_binding_is_pending_and_no_oral_variation_is_clean():
    text = make_lease(extra="7.1 Any oral agreement between the parties shall be binding on both.")
    assert pending_ids(text) == {"RHAA-2014-WRITTEN-LEASE"}
    assert "RHAA-2014-WRITTEN-LEASE" not in violation_ids(text)
    clean = make_lease(extra="7.1 No oral variation of this lease shall be binding.")
    assert pending_ids(clean) == set()


def test_pending_findings_carry_the_standing_note_and_are_never_violations():
    text = make_lease(access="6.1 The Landlord may enter the premises at any time without notice to inspect them.")
    r = report_for(text)
    for f in r.pending():
        assert f.status == "pending_proclamation"
        assert f.category == "pending"
        assert f.note == PENDING_NOTE
        assert not f.is_violation
    assert not any(f.status == "pending_proclamation" for f in r.violations())


def test_pending_rule_cannot_emit_an_in_force_finding_even_if_its_check_tries():
    rogue = ComplianceRule(
        id="ROGUE",
        statute="x",
        section="y",
        description="",
        severity="high",
        status="pending_proclamation",
        check=lambda ctx, rule: [
            Finding(rule_id="ROGUE", severity="high", status="in_force", clause_id=None, explanation="", suggested_fix="", category="violation")
        ],
    )
    a = Pipeline().run(make_lease())
    r = ComplianceEngine(rules=[rogue]).run(a)
    assert len(r.findings) == 1 and r.violations() == []
    assert r.pending()[0].status == "pending_proclamation" and r.pending()[0].note == PENDING_NOTE


def test_amendment_act_rules_are_registered_as_pending():
    assert rule_by_id("RHAA-2014-INSPECTION-NOTICE").status == "pending_proclamation"
    assert rule_by_id("RHAA-2014-WRITTEN-LEASE").status == "pending_proclamation"
    in_force = [r for r in all_rules() if r.status == "in_force"]
    assert all(not r.statute.startswith("Rental Housing Amendment") for r in in_force)


# ---------------------------------------------------------------- CPA s14
def test_cpa_cancellation_missing_right_flagged_with_applicability():
    term = TERM_FIXED.replace(
        "3.2 The Tenant may cancel this lease on 20 (twenty) business days' written notice, subject to a reasonable cancellation penalty under section 14 of the Consumer Protection Act.",
        "3.2 The Tenant has no right to cancel this lease before the termination date.",
    )
    r = report_for(make_lease(term=term))
    f = next(x for x in r.violations() if x.rule_id == "CPA-14-CANCELLATION")
    assert f.applicability == "uncertain"
    r2 = report_for(make_lease(landlord=LANDLORD_JURISTIC, term=term))
    f2 = next(x for x in r2.violations() if x.rule_id == "CPA-14-CANCELLATION")
    assert f2.applicability == "likely"


def test_cpa_cancellation_notice_too_long_and_20bd_clean():
    term = TERM_FIXED.replace("20 (twenty) business days' written notice", "60 (sixty) days' written notice")
    assert "CPA-14-CANCELLATION" in violation_ids(make_lease(term=term))
    assert "CPA-14-CANCELLATION" not in violation_ids(make_lease())


def test_cpa_rules_do_not_apply_to_month_to_month():
    ids = violation_ids(make_lease(term=TERM_MONTHLY))
    assert not any(i.startswith("CPA-") for i in ids)


def test_cpa_expiry_notice_missing_and_present():
    term = "\n".join(line for line in TERM_FIXED.splitlines() if not line.startswith("3.3"))
    assert "CPA-14-EXPIRY-NOTICE" in violation_ids(make_lease(term=term))
    assert "CPA-14-EXPIRY-NOTICE" not in violation_ids(make_lease())


def test_cpa_auto_renewal_excluded_and_allowed():
    term = TERM_FIXED.replace(
        "3.4 On expiry the lease continues on a month-to-month basis unless the Tenant elects otherwise.",
        "3.4 This lease shall not be renewed or extended and the Tenant shall vacate on the expiry date.",
    )
    assert "CPA-14-AUTO-RENEWAL" in violation_ids(make_lease(term=term))
    assert "CPA-14-AUTO-RENEWAL" not in violation_ids(make_lease())


def test_cpa_applicability_heuristic():
    assert cpa_applicability(Party(name="X (Pty) Ltd", role="landlord", kind="juristic")) == "likely"
    assert cpa_applicability(Party(name="Jane Doe", role="landlord", kind="individual")) == "uncertain"
    assert cpa_applicability(Party(name="Jane Doe", role="landlord", kind="individual"), "lets in the ordinary course of business") == "likely"
    assert cpa_applicability(None) == "uncertain"


# ---------------------------------------------------------------- periodic notice
def test_monthly_notice_short_is_unfair_and_one_month_is_clean():
    short = TERM_MONTHLY.replace("one calendar month's written notice", "7 (seven) days' written notice")
    r = report_for(make_lease(term=short))
    f = next(x for x in r.violations() if x.rule_id == "COMMON-LAW-MONTHLY-NOTICE")
    assert f.category == "unfair_practice" and "7 days" in f.explanation
    assert "COMMON-LAW-MONTHLY-NOTICE" not in violation_ids(make_lease(term=TERM_MONTHLY))
    assert "COMMON-LAW-MONTHLY-NOTICE" not in violation_ids(make_lease())


# ---------------------------------------------------------------- POPIA
def test_popia_advisory_only_when_pii_present():
    r = report_for(make_lease(landlord="Thabo Nkosi, Identity Number 8804125001088, of 1 Hill Street, Durban, 4001."))
    assert {f.rule_id for f in r.advisories()} == {"POPIA-PII"}
    assert "POPIA-PII" not in {f.rule_id for f in r.violations()}
    assert report_for(make_lease()).advisories() == []


# ---------------------------------------------------------------- Tribunal patterns
def test_unfair_deposit_forfeit():
    dep = DEPOSIT_OK + "\n5.5 Should the Tenant commit any breach, the deposit shall be forfeited in full to the Landlord."
    r = report_for(make_lease(deposit=dep))
    f = next(x for x in r.violations() if x.rule_id == "UNFAIR-DEPOSIT-FORFEIT")
    assert f.clause_id == "c5.5" and f.severity == "high"
    assert f.category == "unfair_practice"
    assert "Unfair Practice" in f.section
    assert "UNFAIR-DEPOSIT-FORFEIT" not in violation_ids(make_lease())


def test_unfair_repair_waiver():
    extra = "7.1 The Tenant waives any claim against the Landlord for repairs and accepts the premises as is."
    assert "UNFAIR-REPAIR-WAIVER" in violation_ids(make_lease(extra=extra))
    assert "UNFAIR-REPAIR-WAIVER" not in violation_ids(make_lease())


def test_unfair_tribunal_waiver():
    extra = "7.1 The Tenant waives the right to refer any dispute to the Rental Housing Tribunal."
    assert "UNFAIR-TRIBUNAL-WAIVER" in violation_ids(make_lease(extra=extra))
    assert "UNFAIR-TRIBUNAL-WAIVER" not in violation_ids(make_lease())


def test_unfair_lockout_and_negated_lock_clause():
    extra = "7.1 On default the Landlord may change the locks and disconnect the electricity without a court order."
    assert "UNFAIR-LOCKOUT" in violation_ids(make_lease(extra=extra))
    negated = "7.1 The Tenant shall not change the locks without the Landlord's consent."
    assert "UNFAIR-LOCKOUT" not in violation_ids(make_lease(extra=negated))


def test_report_ordering_and_helpers():
    text = make_lease(
        deposit=DEPOSIT_OK.replace("within 7 (seven) days", "within 30 days"),
        access="6.1 The Landlord may enter the premises at any time without notice.",
    )
    r = report_for(text)
    statuses = [f.status for f in r.findings]
    assert statuses == sorted(statuses, key=lambda s: s != "in_force")  # in-force first
    assert r.worst_severity == "high"
    assert r.by_severity("high") and r.rule_ids() >= {"RHA-5-3-E-REFUND", "RHAA-2014-INSPECTION-NOTICE"}


def test_context_find_clause_prefers_requested_categories():
    a = Pipeline().run(make_lease())
    ctx = Context(abstract=a, clauses=list(a.clauses), text=make_lease())
    assert ctx.find_clause("inspect", categories=["deposit"]).id == "c5.3"
    assert ctx.clause_ids(["rent"]) == ["c4", "c4.1", "c4.2"]


def test_demo_corpus_findings_match_expected(demo_reports):
    import yaml

    from .conftest import ROOT

    expected = yaml.safe_load((ROOT / "demo" / "expected_findings.yml").read_text(encoding="utf-8"))
    for name, exp in expected.items():
        r = demo_reports[name]
        assert {f.rule_id for f in r.violations()} == set(exp["violations"]), name
        assert {f.rule_id for f in r.pending()} == set(exp["pending"]), name


def test_access_ok_constant_is_really_clean():
    assert "at any time" not in ACCESS_OK
