"""Rule extraction against the demo corpus, and the citation contract."""

import json
from datetime import date

import pytest

from lease_abstract import Field, Pipeline
from lease_abstract.extract.pipeline import enforce_citations, locate
from lease_abstract.schema import Rent

from .conftest import EXPECTED, LEASE_FILES, make_lease

NAMES = [p.name for p in LEASE_FILES]


def test_six_demo_leases_exist():
    assert len(LEASE_FILES) == 6
    assert all((EXPECTED / f"{p.stem}.json").exists() for p in LEASE_FILES)


@pytest.mark.parametrize("name", NAMES)
def test_every_extracted_field_has_a_source_clause_and_verbatim_quote(demo_abstracts, name):
    a = demo_abstracts[name]
    present = [(n, f) for n, f in a.fields() if f.present]
    assert present, "nothing was extracted"
    for field_name, f in present:
        assert f.source_clause_id, f"{name}: {field_name} has no source_clause_id"
        assert a.clause(f.source_clause_id) is not None, f"{name}: {field_name} cites unknown clause"
        assert f.extracted_text, f"{name}: {field_name} has no quote"
        assert locate(a.clauses, f.extracted_text) is not None
        assert f.cited


@pytest.mark.parametrize("name", NAMES)
def test_parties_match_gold(demo_abstracts, name):
    gold = json.loads((EXPECTED / f"{name.removesuffix('.txt')}.json").read_text(encoding="utf-8"))
    a = demo_abstracts[name]
    for role in ("landlord", "tenant"):
        party = getattr(a, role).value
        assert party is not None
        assert party.name.casefold() == gold[role]["name"].casefold()
        assert party.kind == gold[role]["kind"]
        assert party.has_id_number == gold[role]["has_id_number"]
        assert party.registration_number == gold[role]["registration_number"]


@pytest.mark.parametrize("name", NAMES)
def test_money_and_term_match_gold(demo_abstracts, name):
    gold = json.loads((EXPECTED / f"{name.removesuffix('.txt')}.json").read_text(encoding="utf-8"))
    a = demo_abstracts[name]
    assert a.rent.value.amount_zar == gold["rent"]["amount_zar"]
    assert a.rent.value.due_day == gold["rent"]["due_day"]
    assert a.deposit.value.amount_zar == gold["deposit"]["amount_zar"]
    assert a.deposit.value.interest_bearing == gold["deposit"]["interest_bearing"]
    assert a.deposit.value.refund_days == gold["deposit"]["refund_days"]
    t = a.term.value
    assert t.kind == gold["term"]["kind"]
    assert (t.start.isoformat() if t.start else None) == gold["term"]["start"]
    assert (t.end.isoformat() if t.end else None) == gold["term"]["end"]
    assert t.months == gold["term"]["months"]


def test_party_name_stops_before_id_and_address():
    a = Pipeline().run(make_lease())
    assert a.landlord.value.name == "Thabo Nkosi"
    assert a.landlord.value.address == "1 Hill Street, Durban, 4001"
    assert a.tenant.value.name == "Zanele Mthembu"
    assert a.landlord.value.kind == "individual"


def test_juristic_landlord_keeps_pty_ltd_in_name():
    from .conftest import LANDLORD_JURISTIC

    a = Pipeline().run(make_lease(landlord=LANDLORD_JURISTIC))
    assert a.landlord.value.name == "Ocean Lettings (Pty) Ltd"
    assert a.landlord.value.kind == "juristic"
    assert a.landlord.value.registration_number == "2010/123456/07"


def test_fixed_term_is_not_flipped_by_month_to_month_continuation_clause():
    a = Pipeline().run(make_lease())
    assert a.term.value.kind == "fixed"
    assert a.term.value.start == date(2026, 3, 1) and a.term.value.end == date(2027, 2, 28)
    assert a.term.value.months == 12


def test_month_to_month_term_has_no_end():
    from .conftest import TERM_MONTHLY

    a = Pipeline().run(make_lease(term=TERM_MONTHLY))
    assert a.term.value.kind == "month_to_month"
    assert a.term.value.end is None
    assert a.notice.value.tenant_days == 30 and a.notice.value.landlord_days == 30


def test_deposit_months_equivalent_from_words_and_from_ratio():
    a = Pipeline().run(make_lease())
    assert a.deposit.value.months_equivalent == 2.0
    text = make_lease().replace(", equal to two (2) months' rental", "")
    a2 = Pipeline().run(text)
    assert a2.deposit.value.months_equivalent == 2.0  # 17 000 / 8 500


def test_rent_found_under_combined_heading(demo_abstracts):
    a = demo_abstracts["02_non_interest_deposit.txt"]
    assert a.rent.value.amount_zar == 9200.0
    assert a.escalation.value.pct == 7.5


def test_premises_defined_by_means_clause(demo_abstracts):
    p = demo_abstracts["05_juristic_no_cpa.txt"].premises.value
    assert p.address == "Unit 804, The Grayston, 120 Grayston Drive, Sandton, 2196"
    assert p.unit == "804"


def test_maintenance_lettered_items_are_cited_to_a_real_clause(demo_abstracts):
    a = demo_abstracts["01_compliant.txt"]
    m = a.maintenance
    assert len(m.value.landlord) == 3 and len(m.value.tenant) == 3
    assert a.clause(m.source_clause_id).text == m.extracted_text


def test_enforce_citations_drops_fabricated_quotes():
    a = Pipeline().run(make_lease())
    a.rent = Field(value=Rent(amount_zar=1.0), confidence=0.9, source_clause_id="c4.1", extracted_text="not in the lease", origin="llm")
    dropped = enforce_citations(a)
    assert dropped == ["rent"]
    assert not a.rent.present


def test_enforce_citations_repairs_wrong_clause_id():
    a = Pipeline().run(make_lease())
    a.rent.source_clause_id = "c99"
    assert enforce_citations(a) == []
    assert a.rent.source_clause_id == "c4.1"


def test_locate_is_whitespace_and_case_insensitive(demo_abstracts):
    a = demo_abstracts["01_compliant.txt"]
    c = locate(a.clauses, "  the MONTHLY rental is r 8 500,00 ")
    assert c is not None and c.id == "c4.1"
    assert locate(a.clauses, "") is None
