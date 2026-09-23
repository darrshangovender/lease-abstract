"""Typed lease abstract.

Every extracted value is wrapped in a :class:`Field` that carries a confidence
score, the id of the clause it came from and the literal text it was read
from. Nothing in a :class:`LeaseAbstract` is allowed to be "just a value" —
if it has no citation it is not an extraction, it is a guess.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import ClassVar, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field as PField

T = TypeVar("T")

PartyKind = Literal["individual", "juristic", "unknown"]
TermKind = Literal["fixed", "month_to_month"]
ClauseCategory = Literal[
    "title",
    "parties",
    "premises",
    "term",
    "rent",
    "escalation",
    "deposit",
    "notice",
    "maintenance",
    "penalties",
    "access",
    "special",
    "privacy",
    "cpa",
    "other",
]


class Party(BaseModel):
    """A landlord or tenant. ID numbers never live here — only a flag."""

    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["landlord", "tenant"]
    kind: PartyKind = "unknown"
    registration_number: str | None = None
    has_id_number: bool = False
    address: str | None = None


class Premises(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    unit: str | None = None
    erf: str | None = None
    furnished: bool | None = None


class Term(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None
    months: int | None = None
    kind: TermKind | None = None


class Rent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_zar: float = PField(gt=0)
    due_day: int | None = PField(default=None, ge=1, le=31)
    method: str | None = None


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pct: float | None = PField(default=None, ge=0, le=100)
    amount_zar: float | None = PField(default=None, gt=0)
    anniversary: bool = True

    @model_validator(mode="after")
    def _one_of(self) -> Escalation:
        if self.pct is None and self.amount_zar is None:
            raise ValueError("escalation needs either pct or amount_zar")
        return self


class Deposit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_zar: float = PField(gt=0)
    months_equivalent: float | None = PField(default=None, gt=0)
    interest_bearing: bool | None = None
    refund_days: int | None = PField(default=None, ge=0)


class Notice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_days: int | None = PField(default=None, ge=0)
    landlord_days: int | None = PField(default=None, ge=0)
    tenant_unit: Literal["calendar", "business"] = "calendar"
    landlord_unit: Literal["calendar", "business"] = "calendar"


class Maintenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    landlord: list[str] = PField(default_factory=list)
    tenant: list[str] = PField(default_factory=list)


class Clause(BaseModel):
    """One segment of the lease with a stable id (``c1.2``, ``s3``, ``p7``)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    heading: str | None = None
    text: str = ""
    category: ClauseCategory = "other"
    parent_id: str | None = None
    page: int = 1
    label: str | None = None


class Field(BaseModel, Generic[T]):
    """A cited, scored extraction."""

    model_config = ConfigDict(extra="forbid")

    value: T | None = None
    confidence: float = PField(default=0.0, ge=0.0, le=1.0)
    source_clause_id: str | None = None
    extracted_text: str | None = None
    origin: Literal["rules", "llm", "none"] = "none"

    @property
    def present(self) -> bool:
        return self.value is not None

    @property
    def cited(self) -> bool:
        return self.value is None or (
            self.source_clause_id is not None and bool(self.extracted_text)
        )

    @classmethod
    def empty(cls) -> Field[T]:
        return cls()


class LeaseAbstract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = "lease"
    landlord: Field[Party] = PField(default_factory=Field)
    tenant: Field[Party] = PField(default_factory=Field)
    premises: Field[Premises] = PField(default_factory=Field)
    term: Field[Term] = PField(default_factory=Field)
    rent: Field[Rent] = PField(default_factory=Field)
    escalation: Field[Escalation] = PField(default_factory=Field)
    deposit: Field[Deposit] = PField(default_factory=Field)
    notice: Field[Notice] = PField(default_factory=Field)
    maintenance: Field[Maintenance] = PField(default_factory=Field)
    penalties: Field[list[str]] = PField(default_factory=Field)
    special_clauses: Field[list[str]] = PField(default_factory=Field)
    clauses: list[Clause] = PField(default_factory=list)
    redactions: int = 0

    FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "landlord",
        "tenant",
        "premises",
        "term",
        "rent",
        "escalation",
        "deposit",
        "notice",
        "maintenance",
        "penalties",
        "special_clauses",
    )

    def fields(self) -> Iterator[tuple[str, Field]]:
        for name in self.FIELD_NAMES:
            yield name, getattr(self, name)

    def missing(self) -> list[str]:
        return [name for name, f in self.fields() if not f.present]

    def clause(self, clause_id: str) -> Clause | None:
        for c in self.clauses:
            if c.id == clause_id:
                return c
        return None


__all__ = [
    "Clause",
    "ClauseCategory",
    "Deposit",
    "Escalation",
    "Field",
    "LeaseAbstract",
    "Maintenance",
    "Notice",
    "Party",
    "PartyKind",
    "Premises",
    "Rent",
    "Term",
    "TermKind",
]
