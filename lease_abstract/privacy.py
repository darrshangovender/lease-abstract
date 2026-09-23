"""PII redaction (POPIA).

A lease is full of personal information: ID numbers, phone numbers, email
addresses, bank accounts. None of it may leave the process in a model prompt
or a log line. :class:`Redactor` swaps each item for a stable placeholder
(``[ID_1]``, ``[PHONE_2]`` ...) and returns a :class:`RedactionMap` that can
put the originals back into the final, local-only output.

Lawful purpose (POPIA s11(1)(b)): the personal information is processed only
to the extent necessary to perform the lease abstraction the data subject
(landlord or tenant) has requested. It is not retained by this library.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

SA_ID_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")
PHONE_RE = re.compile(
    r"(?<![\w/])(?:\+27|0)(?:[\s-]?\d){9}(?![\w/])",
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BANK_RE = re.compile(
    r"(?i)(?:account\s*(?:number|no\.?|#)?|acc(?:ount)?\s*(?:no\.?|#)?|acc\.?)\s*[:\-]?\s*(\d[\d\s-]{6,15}\d)"
)
BRANCH_RE = re.compile(r"(?i)branch\s*(?:code)?\s*[:\-]?\s*(\d{6})(?!\d)")


def luhn_ok(digits: str) -> bool:
    """Standard Luhn check over a digit string (SA ID numbers use it)."""
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def sa_id_date_ok(digits: str) -> bool:
    """YYMMDD prefix must be a real calendar date."""
    if len(digits) != 13:
        return False
    yy, mm, dd = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    year = 2000 + yy if yy <= date.today().year % 100 else 1900 + yy
    try:
        date(year, mm, dd)
    except ValueError:
        return False
    return True


def is_valid_sa_id(digits: str) -> bool:
    return len(digits) == 13 and sa_id_date_ok(digits) and luhn_ok(digits)


@dataclass
class RedactionMap:
    """Placeholder -> original. ``restore`` reverses a redaction."""

    entries: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, kind: str, original: str) -> str:
        for ph, orig in self.entries.items():
            if orig == original and self.kinds[ph] == kind:
                return ph
        n = sum(1 for k in self.kinds.values() if k == kind) + 1
        ph = f"[{kind}_{n}]"
        self.entries[ph] = original
        self.kinds[ph] = kind
        return ph

    def restore(self, text: str) -> str:
        for ph, orig in sorted(self.entries.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(ph, orig)
        return text

    def count(self, kind: str) -> int:
        return sum(1 for k in self.kinds.values() if k == kind)


class Redactor:
    """Find and replace PII. Order matters: IDs before bank accounts before phones."""

    def __init__(self, validate_ids: bool = True) -> None:
        self.validate_ids = validate_ids

    def redact(self, text: str, rmap: RedactionMap | None = None) -> tuple[str, RedactionMap]:
        rmap = rmap if rmap is not None else RedactionMap()

        def sub_id(m: re.Match[str]) -> str:
            digits = m.group(1)
            if self.validate_ids and not is_valid_sa_id(digits):
                return m.group(0)
            return rmap.add("ID", digits)

        text = SA_ID_RE.sub(sub_id, text)
        text = EMAIL_RE.sub(lambda m: rmap.add("EMAIL", m.group(0)), text)

        def sub_bank(m: re.Match[str]) -> str:
            acct = m.group(1)
            return m.group(0).replace(acct, rmap.add("BANK", acct))

        text = BANK_RE.sub(sub_bank, text)
        text = BRANCH_RE.sub(
            lambda m: m.group(0).replace(m.group(1), rmap.add("BRANCH", m.group(1))), text
        )
        text = PHONE_RE.sub(lambda m: rmap.add("PHONE", m.group(0)), text)
        return text, rmap

    def contains_pii(self, text: str) -> bool:
        _, rmap = self.redact(text)
        return len(rmap) > 0


class RedactingFilter(logging.Filter):
    """Attach to any logger so PII never reaches a log sink."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self.redactor = redactor or Redactor()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted, _ = self.redactor.redact(msg)
        record.msg = redacted
        record.args = ()
        return True


def get_logger(name: str = "lease_abstract") -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
    return logger


__all__ = [
    "RedactingFilter",
    "RedactionMap",
    "Redactor",
    "get_logger",
    "is_valid_sa_id",
    "luhn_ok",
    "sa_id_date_ok",
]
