"""Shared fixtures: the demo corpus and a small, fully compliant lease whose
clauses can be swapped one at a time to trigger exactly one rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from lease_abstract import ComplianceEngine, ComplianceReport, LeaseAbstract, Pipeline

ROOT = Path(__file__).resolve().parents[1]
LEASES = ROOT / "demo" / "leases"
EXPECTED = ROOT / "demo" / "expected"
LEASE_FILES = sorted(LEASES.glob("*.txt"))

LANDLORD_INDIVIDUAL = "Thabo Nkosi, of 1 Hill Street, Durban, 4001."
LANDLORD_JURISTIC = (
    "Ocean Lettings (Pty) Ltd, Registration Number 2010/123456/07, "
    "with its registered office at 5 Bay Road, Durban, 4001."
)

TERM_FIXED = """3.1 This lease is for a fixed term of 12 (twelve) months commencing on 1 March 2026 and terminating on 28 February 2027.
3.2 The Tenant may cancel this lease on 20 (twenty) business days' written notice, subject to a reasonable cancellation penalty under section 14 of the Consumer Protection Act.
3.3 The Landlord shall notify the Tenant of the expiry of this lease not more than 80 and not less than 40 business days before the termination date.
3.4 On expiry the lease continues on a month-to-month basis unless the Tenant elects otherwise."""

TERM_MONTHLY = """3.1 This is a month-to-month tenancy commencing on 1 March 2026.
3.2 Either party may terminate this lease on one calendar month's written notice."""

DEPOSIT_OK = """5.2 The deposit shall be invested in an interest-bearing account at not less than the savings rate and the interest shall accrue to the Tenant.
5.3 The Landlord and Tenant shall jointly inspect the premises at the start and at the end of the lease and record defects in writing.
5.4 The deposit and interest shall be refunded within 7 (seven) days of the end of the lease."""

ACCESS_OK = "6.1 The Landlord may enter the premises on 24 (twenty-four) hours' written notice at reasonable times, except in an emergency."

BASE = """RESIDENTIAL LEASE AGREEMENT

1. PARTIES
1.1 Landlord: {landlord}
1.2 Tenant: Zanele Mthembu, of 3 Palm Road, Durban, 4001.

2. PREMISES
2.1 The premises are the flat situated at 10 Ocean Drive, Durban, 4001.

3. DURATION
{term}

4. RENTAL
4.1 The monthly rental is R 8 500,00 payable in advance on the 1st day of each month by EFT.
4.2 The rental shall escalate by 6% on each anniversary of the commencement date.

5. DEPOSIT
5.1 The Tenant shall pay a deposit of R 17 000,00, equal to two (2) months' rental.
{deposit}

6. ACCESS
{access}

7. GENERAL
{extra}
"""


def make_lease(
    landlord: str = LANDLORD_INDIVIDUAL,
    term: str = TERM_FIXED,
    deposit: str = DEPOSIT_OK,
    access: str = ACCESS_OK,
    extra: str = "7.1 This lease is governed by South African law.",
) -> str:
    return BASE.format(landlord=landlord, term=term, deposit=deposit, access=access, extra=extra)


def report_for(text: str) -> ComplianceReport:
    abstract = Pipeline().run(text)
    return ComplianceEngine().run(abstract, text)


def violation_ids(text: str) -> set[str]:
    return {f.rule_id for f in report_for(text).violations()}


def pending_ids(text: str) -> set[str]:
    return {f.rule_id for f in report_for(text).pending()}


@pytest.fixture(scope="session")
def demo_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in LEASE_FILES}


@pytest.fixture(scope="session")
def demo_abstracts(demo_texts) -> dict[str, LeaseAbstract]:
    return {name: Pipeline().run(text, source_name=name) for name, text in demo_texts.items()}


@pytest.fixture(scope="session")
def demo_reports(demo_texts, demo_abstracts) -> dict[str, ComplianceReport]:
    return {
        name: ComplianceEngine().run(demo_abstracts[name], demo_texts[name]) for name in demo_texts
    }
