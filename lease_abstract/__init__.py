"""lease-abstract: residential lease abstraction and compliance checking for South African rentals."""

from .compliance import ComplianceEngine, ComplianceReport, Finding, check_lease
from .extract import MockModel, Pipeline, abstract_lease
from .privacy import RedactionMap, Redactor
from .schema import (
    Clause,
    Deposit,
    Escalation,
    Field,
    LeaseAbstract,
    Maintenance,
    Notice,
    Party,
    Premises,
    Rent,
    Term,
)
from .segment import Segmenter, segment
from .summary import Summariser, summarise

__version__ = "0.1.0"

__all__ = [
    "Clause",
    "ComplianceEngine",
    "ComplianceReport",
    "Deposit",
    "Escalation",
    "Field",
    "Finding",
    "LeaseAbstract",
    "Maintenance",
    "MockModel",
    "Notice",
    "Party",
    "Pipeline",
    "Premises",
    "RedactionMap",
    "Redactor",
    "Rent",
    "Segmenter",
    "Summariser",
    "Term",
    "__version__",
    "abstract_lease",
    "check_lease",
    "segment",
    "summarise",
]
