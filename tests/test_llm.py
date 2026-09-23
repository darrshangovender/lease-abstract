"""LLM gap-fill: strict JSON, one retry, verbatim quotes, and no PII in prompts."""

import json

import pytest

from lease_abstract import MockModel, Pipeline, Redactor
from lease_abstract.extract.llm import LLMExtractor, build_prompt, parse_response
from lease_abstract.segment import segment

from .conftest import LEASE_FILES, make_lease

PII_SAMPLES = {
    "01_compliant.txt": ["8804125001088", "9109235112083", "082 555 0147", "sipho.dlamini@example.co.za", "62012345678"],
    "02_non_interest_deposit.txt": ["7603055017085", "031 303 2211", "10098765432"],
    "03_entry_any_time.txt": ["7908115023084", "8501175209088", "ayesha.p@example.com", "+27 83 444 9012"],
    "04_deposit_forfeit.txt": ["9306285115087", "8802145126083", "072 118 3390", "1234567890"],
    "05_juristic_no_cpa.txt": ["9504305081087", "62987654321"],
    "06_monthly_7day_notice.txt": ["7501015800089", "9104225301085", "076 200 4411", "lerato.m@example.org"],
}


@pytest.mark.parametrize("path", LEASE_FILES, ids=[p.name for p in LEASE_FILES])
def test_pii_never_reaches_model_prompts(path):
    model = MockModel("{}")
    # Force every field to be treated as a gap so the whole lease is sent.
    Pipeline(model=model, min_rule_confidence=1.0).run(path.read_text(encoding="utf-8"))
    assert model.calls >= 1
    redactor = Redactor()
    for prompt in model.prompts:
        for raw in PII_SAMPLES[path.name]:
            assert raw not in prompt, f"{raw} leaked into prompt"
        assert not redactor.contains_pii(prompt)
        assert "[ID_1]" in prompt


def test_parse_response_strips_fences_and_prose():
    raw = 'Sure!\n```json\n{"rent": {"value": {"amount_zar": 1}, "extracted_text": "x"}}\n```'
    assert parse_response(raw)["rent"]["value"]["amount_zar"] == 1
    with pytest.raises(ValueError):
        parse_response("no json here")


def test_invalid_response_gets_exactly_one_retry():
    model = MockModel(["not json", "{}"])
    llm = LLMExtractor(model)
    out = llm.fill(segment("1. RENT\n1.1 R100 per month."), ["rent"])
    assert out == {} and model.calls == 2 and llm.attempts == 2
    assert "rejected" in model.prompts[1]


def test_unknown_keys_and_missing_quote_are_rejected():
    model = MockModel([json.dumps({"rent": {"value": {"amount_zar": 100}}}), "{}"])
    llm = LLMExtractor(model)
    assert llm.fill(segment("1. RENT\n1.1 R100 per month."), ["rent"]) == {}
    assert llm.errors and "extracted_text" in llm.errors[0]


def test_llm_answer_accepted_only_when_quote_is_verbatim():
    text = make_lease().replace("4.1 The monthly rental is R 8 500,00 payable in advance on the 1st day of each month by EFT.", "4.1 Rent as agreed separately.")
    good = json.dumps({"rent": {"value": {"amount_zar": 8500}, "extracted_text": "Rent as agreed separately."}})
    a = Pipeline(model=MockModel(good)).run(text)
    assert a.rent.present and a.rent.origin == "llm" and a.rent.source_clause_id == "c4.1"

    bad = json.dumps({"rent": {"value": {"amount_zar": 8500}, "extracted_text": "invented quote"}})
    p = Pipeline(model=MockModel(bad))
    a2 = p.run(text)
    assert not a2.rent.present and "rent" in p.last_gaps and p.last_filled == []


def test_placeholders_in_model_output_are_restored_locally():
    text = make_lease(landlord="Thabo Nkosi, Identity Number 8804125001088, of 1 Hill Street, Durban, 4001.")
    model = MockModel(
        lambda prompt: json.dumps(
            {"special_clauses": {"value": ["ID on file: [ID_1]"], "extracted_text": "This lease is governed by South African law."}}
        )
    )
    a = Pipeline(model=model).run(text)
    assert a.special_clauses.value == ["ID on file: 8804125001088"]
    assert all("8804125001088" not in p for p in model.prompts)


def test_build_prompt_lists_only_requested_fields():
    prompt = build_prompt(segment("1. RENT\n1.1 R100."), ["rent", "deposit"])
    assert "Fill ONLY these fields: rent, deposit" in prompt
    assert '"escalation"' not in prompt
    assert "[c1.1] R100." in prompt
