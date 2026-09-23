"""Plain-English summaries: both voices, every number preserved, polish guarded."""

import pytest

from lease_abstract import MockModel, Summariser, summarise
from lease_abstract.summary import NumberMismatchError, fmt_zar, numbers_in, polish

from .conftest import LEASE_FILES

NAMES = [p.name for p in LEASE_FILES]


def _abstract_numbers(a) -> set[str]:
    nums = set()
    r, d, e, n, t = a.rent.value, a.deposit.value, a.escalation.value, a.notice.value, a.term.value
    nums.add(f"{r.amount_zar:g}")
    nums.add(f"{d.amount_zar:g}")
    if d.refund_days is not None:
        nums.add(str(d.refund_days))
    if e is not None:
        nums.add(f"{e.pct:g}" if e.pct is not None else f"{e.amount_zar:g}")
    if n is not None:
        nums |= {str(x) for x in (n.tenant_days, n.landlord_days) if x is not None}
    if t is not None:
        if t.months:
            nums.add(str(t.months))
        if t.start:
            nums.add(str(t.start.year))
    return nums


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("audience", ["tenant", "landlord"])
def test_summary_preserves_every_number(demo_abstracts, demo_reports, name, audience):
    a = demo_abstracts[name]
    text = Summariser(a, demo_reports[name]).render(audience)
    found = numbers_in(text)
    for num in _abstract_numbers(a):
        assert num in found, f"{name}/{audience}: {num} missing from summary"
    assert "not legal advice" in text


def test_voices_differ_but_facts_do_not(demo_abstracts, demo_reports):
    s = Summariser(demo_abstracts["01_compliant.txt"], demo_reports["01_compliant.txt"])
    tenant, landlord = s.for_tenant(), s.for_landlord()
    assert "Your deposit" in tenant and "You hold a deposit" in landlord
    assert "You pay R8 500" in tenant and "The tenant pays R8 500" in landlord
    assert numbers_in(tenant)["8500"] == numbers_in(landlord)["8500"]


def test_summary_separates_violations_pending_and_advisories(demo_abstracts, demo_reports):
    text = Summariser(demo_abstracts["03_entry_any_time.txt"], demo_reports["03_entry_any_time.txt"]).for_landlord()
    assert "falls short of the law" in text and "UNFAIR-ENTRY-NO-NOTICE" in text
    assert "Suggested fix:" in text
    assert "Coming law (not yet in force" in text
    assert "RHAA-2014-INSPECTION-NOTICE" not in text.split("Coming law")[0]
    clean = Summariser(demo_abstracts["01_compliant.txt"], demo_reports["01_compliant.txt"]).for_tenant()
    assert "No breaches of current law were found" in clean


def test_fmt_zar_and_numbers_in():
    assert fmt_zar(8500) == "R8 500"
    assert fmt_zar(1250000.5) == "R1 250 000,50"
    assert numbers_in("R8 500 and 8500 and 7,5%") == {"8500": 2, "7,5": 1}


def test_polish_passes_when_numbers_survive():
    src = "Rent is R8 500 due on day 1. Deposit R17 000."
    out = polish(src, MockModel(lambda p: p.split("Do not add facts.\n\n", 1)[1].replace("Rent is", "The rent is")))
    assert out.startswith("The rent is R8 500")


def test_polish_raises_on_number_drift_and_summarise_falls_back(demo_abstracts, demo_reports):
    with pytest.raises(NumberMismatchError):
        polish("Rent is R8 500.", MockModel("Rent is R8 600."))
    a = demo_abstracts["01_compliant.txt"]
    template = summarise(a, demo_reports["01_compliant.txt"], "tenant")
    drifted = summarise(a, demo_reports["01_compliant.txt"], "tenant", model=MockModel("Everything is fine."))
    assert drifted == template


def test_polish_prompt_is_redacted():
    model = MockModel(lambda p: p.split("Do not add facts.\n\n", 1)[1])
    src = "Tenant ID 8804125001088, rent R8 500."
    out = polish(src, model)
    assert "8804125001088" not in model.prompts[0] and "[ID_1]" in model.prompts[0]
    assert "8804125001088" in out
