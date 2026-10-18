"""Regression tests for 0.1.1."""

import re
from pathlib import Path

import pytest

from lease_abstract.compliance import rule_by_id
from lease_abstract.privacy import Redactor, is_valid_sa_id

from .conftest import DEPOSIT_OK, make_lease, report_for

ROOT = Path(__file__).resolve().parents[1]

# --- statute citations (checked against Government Gazette 20726, 15 Dec 1999) ---------


def test_refund_rule_cites_the_paragraphs_that_set_the_7_14_21_day_periods():
    """It cited s5(3)(e)-(g); (e) and (f) are the joint inspections, not refunds.

    s5(3)(g): 14 days after deductions; (i): 7 days when nothing is owing;
    (k)-(m): 21 days when the tenant did not respond to the inspection request.
    """
    rule = rule_by_id("RHA-5-3-REFUND")
    assert rule.section == "s5(3)(g), (i) and (k)-(m)"
    for days, cites in [(30, ["s5(3)(i)", "s5(3)(g)", "s5(3)(k)-(m)"]),
                        (21, ["s5(3)(k)-(m)", "s5(3)(i)", "s5(3)(g)"]),
                        (14, ["s5(3)(i)"])]:
        dep = DEPOSIT_OK.replace("within 7 (seven) days", f"within {days} days")
        f = next(x for x in report_for(make_lease(deposit=dep)).violations()
                 if x.rule_id == "RHA-5-3-REFUND")
        for c in cites:
            assert c in f.explanation, (days, c)
        assert "5(3)(e)" not in f.explanation


def test_joint_inspection_rule_cites_paragraphs_e_and_f():
    assert rule_by_id("RHA-5-3-INSPECTION").section == "s5(3)(e)-(f)"


def test_entry_without_notice_cites_the_in_force_section_4_2():
    """RHA s4(2) (in force since 1999) already requires reasonable notice before inspection."""
    assert rule_by_id("UNFAIR-ENTRY-NO-NOTICE").section.startswith("s4(2);")


def test_lockout_cites_the_court_order_requirements_in_section_4():
    section = rule_by_id("UNFAIR-LOCKOUT").section
    assert "s4(3)(c)" in section and "s4(5)(d)(ii)" in section


# --- demo data must not contain issuable ID numbers ---------------------------------------


def _id_numbers(text: str) -> list[str]:
    return re.findall(r"(?<!\d)\d{13}(?!\d)", text)


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "demo" / "leases").glob("*.txt")) + sorted((ROOT / "tests").glob("*.py")),
    ids=lambda p: p.name,
)
def test_demo_and_test_id_numbers_cannot_belong_to_a_real_person(path):
    """Checksum-valid IDs with a real birth date and citizenship digit 0/1/2 could be someone's.

    Every valid-looking ID shipped in this repo uses citizenship digit 9, which is never
    issued, so it still exercises the date + Luhn checks without being a possible real ID.
    """
    for n in _id_numbers(path.read_text(encoding="utf-8")):
        if is_valid_sa_id(n):
            assert n[10] == "9", f"{path.name}: {n} has an issuable citizenship digit"


def test_non_issuable_demo_ids_are_still_redacted():
    safe, rmap = Redactor().redact("Tenant ID 8804125001989, landlord ID 9109235112984.")
    assert "8804125001989" not in safe and "9109235112984" not in safe
    assert len(rmap) == 2
