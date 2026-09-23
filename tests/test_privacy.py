"""POPIA: SA ID validation and redaction."""

import logging

import pytest

from lease_abstract.privacy import (
    RedactingFilter,
    RedactionMap,
    Redactor,
    is_valid_sa_id,
    luhn_ok,
    sa_id_date_ok,
)

VALID_IDS = ["8804125001088", "9109235112083", "7501015800089"]


@pytest.mark.parametrize("digits", VALID_IDS)
def test_luhn_accepts_valid_sa_ids(digits):
    assert luhn_ok(digits)
    assert is_valid_sa_id(digits)


def test_luhn_rejects_bad_checksum():
    bad = "8804125001087"  # last digit off by one
    assert not luhn_ok(bad)
    assert not is_valid_sa_id(bad)


def test_sa_id_rejects_impossible_birth_date():
    assert not sa_id_date_ok("8813325001088")  # month 13
    assert not is_valid_sa_id("8813325001088")


def test_sa_id_rejects_wrong_length_and_non_digits():
    assert not is_valid_sa_id("880412500108")
    assert not luhn_ok("88041250010A8")


def test_redactor_replaces_each_kind_with_stable_placeholder():
    text = (
        "Sipho Dlamini, Identity Number 9109235112083, cell 082 555 0147, "
        "email sipho.dlamini@example.co.za, Account Number 62012345678, Branch Code 250655."
    )
    safe, rmap = Redactor().redact(text)
    assert "9109235112083" not in safe and "082 555 0147" not in safe
    assert "sipho.dlamini@example.co.za" not in safe and "62012345678" not in safe
    assert "250655" not in safe
    assert {rmap.kinds[k] for k in rmap.entries} == {"ID", "PHONE", "EMAIL", "BANK", "BRANCH"}
    assert rmap.restore(safe) == text


def test_redactor_does_not_redact_13_digit_numbers_that_fail_luhn():
    safe, rmap = Redactor().redact("reference 1234567890123 only")
    assert safe == "reference 1234567890123 only" and len(rmap) == 0


def test_same_value_gets_same_placeholder():
    rmap = RedactionMap()
    assert rmap.add("ID", "9109235112083") == rmap.add("ID", "9109235112083") == "[ID_1]"
    assert rmap.add("ID", "8804125001088") == "[ID_2]"
    assert rmap.count("ID") == 2


def test_redacting_log_filter_strips_pii():
    logger = logging.getLogger("test.redact")
    logger.addFilter(RedactingFilter())
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("tenant id %s phone %s", "9109235112083", "082 555 0147")
    assert records and "9109235112083" not in records[0].getMessage()
    assert "[ID_1]" in records[0].getMessage()


def test_contains_pii_on_demo_leases(demo_texts):
    r = Redactor()
    assert all(r.contains_pii(t) for t in demo_texts.values())
    assert not r.contains_pii("The rent is R8500 per month, due on the 1st.")
