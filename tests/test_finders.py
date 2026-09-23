"""Primitive finders: South African money, dates, counts and percentages."""

from datetime import date

import pytest

from lease_abstract.extract.rules import (
    find_amounts,
    find_counts,
    find_dates,
    find_percentages,
    parse_amount,
    sentence_at,
    sentences,
    word_to_int,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("R 8 500,00", 8500.0),
        ("R8500", 8500.0),
        ("R8 500", 8500.0),
        ("ZAR 8,500", 8500.0),
        ("ZAR 15,500.00", 15500.0),
        ("R500,00", 500.0),
        ("R 6 500,00", 6500.0),
        ("R1 250 000,50", 1250000.5),
        ("R250", 250.0),
    ],
)
def test_amount_formats(text, expected):
    hits = find_amounts(f"rental of {text} per month")
    assert [h.value for h in hits] == [expected]
    assert hits[0].text.strip() == text


def test_amount_keeps_literal_text_and_offsets():
    text = "a deposit of R 17 000,00 (seventeen thousand rand)"
    hit = find_amounts(text)[0]
    assert text[hit.start : hit.end] == "R 17 000,00"


def test_percentage_is_not_an_amount():
    assert find_amounts("escalates by 6% per year") == []
    assert [h.value for h in find_percentages("escalates by 6% and 7,5 percent")] == [6.0, 7.5]


def test_parse_amount_edge_cases():
    assert parse_amount("8 500,00") == 8500.0
    assert parse_amount("8,500") == 8500.0
    assert parse_amount("8500.50") == 8500.5
    assert parse_amount("31,000.00") == 31000.0


@pytest.mark.parametrize(
    "text, expected",
    [
        ("01/03/2026", date(2026, 3, 1)),
        ("1 March 2026", date(2026, 3, 1)),
        ("1st day of March 2026", date(2026, 3, 1)),
        ("28 February 2027", date(2027, 2, 28)),
        ("2026-03-01", date(2026, 3, 1)),
        ("01-10-2026", date(2026, 10, 1)),
        ("01.10.2026", date(2026, 10, 1)),
        ("March 1, 2026", date(2026, 3, 1)),
        ("15 Jul 2026", date(2026, 7, 15)),
    ],
)
def test_date_formats(text, expected):
    hits = find_dates(f"commencing on {text} and")
    assert [h.value for h in hits] == [expected]


def test_impossible_dates_are_skipped_and_hits_sorted():
    hits = find_dates("from 31/02/2026 until 1 March 2026, signed 01/01/2026")
    assert [h.value for h in hits] == [date(2026, 3, 1), date(2026, 1, 1)]
    assert hits[0].start < hits[1].start


@pytest.mark.parametrize(
    "text, n, unit, kind",
    [
        ("twenty (20) business days", 20, "day", "business"),
        ("20 (twenty) business days", 20, "day", "business"),
        ("7 days", 7, "day", "calendar"),
        ("seven days", 7, "day", "calendar"),
        ("one calendar month", 1, "month", "calendar"),
        ("24 hours", 24, "hour", "calendar"),
        ("twenty-four hours", 24, "hour", "calendar"),
        ("10 working days", 10, "day", "business"),
        ("two weeks", 2, "week", "calendar"),
    ],
)
def test_count_formats(text, n, unit, kind):
    c = find_counts(f"on {text}' written notice")[0]
    assert (c.n, c.unit, c.kind) == (n, unit, kind)


def test_count_days_conversion():
    c = find_counts("one calendar month")[0]
    assert c.days == 30
    assert find_counts("two weeks")[0].days == 14


def test_word_to_int():
    assert word_to_int("twenty-four") == 24
    assert word_to_int("seventeen") == 17
    assert word_to_int("ninety nine") == 99
    assert word_to_int("dozen") is None


def test_sentences_and_sentence_at():
    text = "First sentence. Second one; Third here."
    assert sentences(text) == ["First sentence.", "Second one;", "Third here."]
    assert sentence_at(text, text.index("Second")) == "Second one;"
    assert sentence_at(text, len(text) - 1) == "Third here."
