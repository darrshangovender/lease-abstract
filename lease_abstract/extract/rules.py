"""Regex / heuristic extractors.

Two layers:

1. **Primitive finders** (``find_amounts``, ``find_dates`` ...) that turn South
   African formatting quirks (``R 8 500,00``, ``01/03/2026``, ``twenty (20)
   business days``) into typed values plus the literal text they came from.
2. **Field extractors** that walk the segmented clauses, pick the right clause
   by category, run the finders, and return a cited
   :class:`~lease_abstract.schema.Field`.

Everything here is deterministic and offline. The LLM layer only fills what
these leave empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..privacy import is_valid_sa_id
from ..schema import (
    Clause,
    ClauseCategory,
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
from ..segment import by_category, family_text

# --------------------------------------------------------------------------- #
# Primitive finders
# --------------------------------------------------------------------------- #

AMOUNT_RE = re.compile(
    r"(?:\bR|\bZAR)\s?(?P<num>\d{1,3}(?:[ ,]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)(?![\d%])"
)
DMY_RE = re.compile(r"\b(?P<d>\d{1,2})[/\-.](?P<m>\d{1,2})[/\-.](?P<y>\d{4})\b")
ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_ALT = "|".join(m[:3] + r"(?:" + m[3:] + r")?" if len(m) > 3 else m for m in MONTHS)
LONG_DATE_RE = re.compile(
    r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?(?P<mon>" + _MONTH_ALT + r")\s+(?P<y>\d{4})\b",
    re.IGNORECASE,
)
US_DATE_RE = re.compile(
    r"\b(?P<mon>" + _MONTH_ALT + r")\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s?(?:%|percent|per cent)", re.IGNORECASE)

_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUM = (
    r"(?:(?:" + "|".join(_TENS) + r")(?:[- ](?:" + "|".join(_UNITS) + r"))?|" + "|".join(_UNITS) + r")"
)
COUNT_RE = re.compile(
    r"\b(?:(?P<digits>\d+)\s*(?:\((?P<wordparen>[a-z][a-z\- ]*)\)\s*)?|(?P<word>"
    + _WORD_NUM
    + r")\s*(?:\((?P<digitparen>\d+)\)\s*)?)"
    r"(?P<kind>business|working|calendar|clear)?\s*(?P<unit>days?|months?|weeks?|hours?)\b",
    re.IGNORECASE,
)
DUE_DAY_RE = re.compile(
    r"\b(?:on\s+or\s+before\s+)?(?:the\s+)?(?P<day>\d{1,2}(?:st|nd|rd|th)|first|second|third|fourth|fifth|fifteenth|twentieth|last)"
    r"\s+(?:day\s+)?of\s+(?:each|every)\s+(?:calendar\s+)?month\b",
    re.IGNORECASE,
)
_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "fifteenth": 15,
    "twentieth": 20,
    "last": 31,
}
REG_NO_RE = re.compile(r"\b(\d{4}/\d{6}/\d{2})\b")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z(\"“])")


@dataclass(frozen=True)
class Hit:
    """A typed value plus the literal text it was read from."""

    value: object
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Count:
    n: int
    unit: str  # day | month | week | hour
    kind: str  # calendar | business
    text: str
    start: int
    end: int

    @property
    def days(self) -> float:
        return {"day": 1, "week": 7, "month": 30, "hour": 1 / 24}[self.unit] * self.n


def parse_amount(token: str) -> float:
    """``8 500,00`` -> 8500.0, ``8,500`` -> 8500.0, ``8500.50`` -> 8500.5."""
    token = token.strip()
    m = re.fullmatch(r"(.*?)[.,](\d{2})", token)
    whole, cents = (m.group(1), m.group(2)) if m else (token, "00")
    whole = re.sub(r"[ ,.]", "", whole)
    return float(f"{whole}.{cents}")


def find_amounts(text: str) -> list[Hit]:
    return [
        Hit(parse_amount(m.group("num")), m.group(0), m.start(), m.end())
        for m in AMOUNT_RE.finditer(text)
    ]


def _mk_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[Hit]:
    hits: list[Hit] = []
    for m in DMY_RE.finditer(text):
        d = _mk_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if d:
            hits.append(Hit(d, m.group(0), m.start(), m.end()))
    for m in ISO_RE.finditer(text):
        d = _mk_date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if d:
            hits.append(Hit(d, m.group(0), m.start(), m.end()))
    for rx in (LONG_DATE_RE, US_DATE_RE):
        for m in rx.finditer(text):
            mon = m.group("mon").lower()[:3]
            month = next(i + 1 for i, name in enumerate(MONTHS) if name.startswith(mon))
            d = _mk_date(int(m.group("y")), month, int(m.group("d")))
            if d:
                hits.append(Hit(d, m.group(0), m.start(), m.end()))
    hits.sort(key=lambda h: h.start)
    return hits


def find_percentages(text: str) -> list[Hit]:
    return [
        Hit(float(m.group("num").replace(",", ".")), m.group(0), m.start(), m.end())
        for m in PERCENT_RE.finditer(text)
    ]


def word_to_int(word: str) -> int | None:
    parts = re.split(r"[- ]", word.strip().lower())
    total = 0
    for p in parts:
        if p in _UNITS:
            total += _UNITS[p]
        elif p in _TENS:
            total += _TENS[p]
        else:
            return None
    return total


def find_counts(text: str) -> list[Count]:
    """``twenty (20) business days``, ``7 days``, ``one calendar month``, ``24 hours``."""
    out: list[Count] = []
    for m in COUNT_RE.finditer(text):
        if m.group("digits"):
            n = int(m.group("digits"))
        else:
            n = word_to_int(m.group("word"))
            if n is None:
                continue
        unit = m.group("unit").lower().rstrip("s")
        kind = "business" if (m.group("kind") or "").lower() in {"business", "working"} else "calendar"
        out.append(Count(n, unit, kind, m.group(0), m.start(), m.end()))
    return out


def find_day_counts(text: str) -> list[Count]:
    return [c for c in find_counts(text) if c.unit in {"day", "week", "month"}]


def find_id_numbers(text: str) -> list[Hit]:
    return [
        Hit(m.group(0), m.group(0), m.start(), m.end())
        for m in re.finditer(r"(?<!\d)\d{13}(?!\d)", text)
        if is_valid_sa_id(m.group(0))
    ]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def sentence_at(text: str, pos: int) -> str:
    """The sentence of ``text`` that contains offset ``pos``."""
    start = 0
    for m in SENTENCE_SPLIT_RE.finditer(text):
        if m.end() > pos:
            return text[start : m.start()].strip()
        start = m.end()
    return text[start:].strip()


# --------------------------------------------------------------------------- #
# Field extractors
# --------------------------------------------------------------------------- #

JURISTIC_RE = re.compile(
    r"\b(?:\(pty\)|pty|ltd|limited|proprietary|cc|npc|inc|incorporated|trust|holdings|properties|"
    r"lettings|investments|estates|rentals|developments|body corporate)\b",
    re.IGNORECASE,
)
ROLE_MARK_RE = re.compile(
    r"\(?[\"“']?(?:the\s+)?(?P<role>Landlord|Lessor|Tenant|Lessee)[\"”']?\)?", re.IGNORECASE
)
COLON_MARK_RE = re.compile(r"\b(?P<role>Landlord|Lessor|Tenant|Lessee)\s*:\s*", re.IGNORECASE)
IS_MARK_RE = re.compile(
    r"\b(?:the\s+)?(?P<role>Landlord|Lessor|Tenant|Lessee)\s+(?:is|being|means|shall be)\s+",
    re.IGNORECASE,
)
# A name ends at punctuation or at the words that introduce an address/ID —
# but "(Pty) Ltd" is part of a company name, not a parenthetical to cut at.
NAME_STOP_RE = re.compile(
    r"[,;]|\((?!pty|proprietary)|\s+(?:of|residing|represented|with|whose|trading|identity|id\b)\b",
    re.IGNORECASE,
)
ROLE_WORD_RE = re.compile(r"\b(?:landlord|lessor|tenant|lessee)\b", re.IGNORECASE)
ADDRESS_RE = re.compile(
    r"\b(?:residing at|of|with (?:its )?(?:registered|principal) (?:address|place of business|office) at)\s+"
    r"(?P<addr>\d[^;.]+?)"
    r"(?=[;.]|\s+\(|\s+and\b|\s+\"|,\s+(?:telephone|tel|cell|phone|email|e-mail|contactable)\b|$)",
    re.IGNORECASE,
)


def _field(value, text: str, clause: Clause, confidence: float) -> Field:
    return Field(
        value=value,
        confidence=confidence,
        source_clause_id=clause.id,
        extracted_text=text,
        origin="rules",
    )


def _clean_name(raw: str) -> str:
    raw = re.sub(r"\([^)]*(?:\d|identity|registration|id\b)[^)]*\)", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\b(?:identity|id)\s*(?:number|no\.?)\s*[:\-]?\s*\S+", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\bregistration\s*(?:number|no\.?)\s*[:\-]?\s*\S+", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\[(?:ID|PHONE|EMAIL|BANK|BRANCH)_\d+\]", " ", raw)
    raw = re.sub(r"^\W+|\W+$", "", raw.strip())
    raw = re.sub(r"\s{2,}", " ", raw)
    return raw.strip(" ,;:-")


def _party_kind(name: str, context: str) -> str:
    if JURISTIC_RE.search(name) or REG_NO_RE.search(context):
        return "juristic"
    if re.search(r"identity|\bid\b|\[ID_\d+\]|born on", context, re.IGNORECASE):
        return "individual"
    words = name.split()
    if 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words):
        return "individual"
    return "unknown"


def _name_from_span(span: str) -> str | None:
    """The party name at the start of ``span``: cleaned, cut at the first stop word."""
    cleaned = _clean_name(span)
    stop = NAME_STOP_RE.search(cleaned)
    name = _clean_name(cleaned[: stop.start()] if stop else cleaned)
    if len(name) < 2 or not name[0].isalpha() or not name[0].isupper():
        return None
    if ROLE_WORD_RE.search(name):
        return None
    return name


def _party_span(sentence: str, role: str) -> str | None:
    """The slice of ``sentence`` that describes ``role`` (name, ID, address ...)."""
    m = COLON_MARK_RE.search(sentence)
    if m and m.group("role").lower() == role.lower():
        return sentence[m.end() :]
    m = IS_MARK_RE.search(sentence)
    if m and m.group("role").lower() == role.lower():
        return sentence[m.end() :]
    for rm in ROLE_MARK_RE.finditer(sentence):
        if rm.group("role").lower() != role.lower():
            continue
        head = sentence[: rm.start()]
        # Cut back to the nearest boundary that introduces a party.
        boundary = max(
            (
                b.end()
                for b in re.finditer(
                    r"\bbetween\b|\band\b|[:;]|\bof the (?:first|second|one|other) part,?", head, re.I
                )
            ),
            default=0,
        )
        if _name_from_span(head[boundary:]):
            return head[boundary:]
    return None


def _party_from_sentence(sentence: str, role: str) -> Party | None:
    role_norm = "landlord" if role.lower() in {"landlord", "lessor"} else "tenant"
    span = _party_span(sentence, role)
    if span is None:
        return None
    # Do not read past the *next* party's marker in the same sentence.
    nxt = ROLE_MARK_RE.search(span)
    if nxt and nxt.group("role").lower() != role.lower():
        span = span[: nxt.start()]
    name = _name_from_span(span)
    if name is None:
        return None
    reg = REG_NO_RE.search(span)
    has_id = bool(
        find_id_numbers(span)
        or re.search(r"\[ID_\d+\]|identity\s*(?:number|no)|\bid\s*(?:number|no)", span, re.IGNORECASE)
    )
    addr = None
    am = ADDRESS_RE.search(span)
    if am:
        addr = am.group("addr").strip(" ,")
    return Party(
        name=name,
        role=role_norm,
        kind=_party_kind(name, span),  # type: ignore[arg-type]
        registration_number=reg.group(1) if reg else None,
        has_id_number=has_id,
        address=addr,
    )


def _party_clauses(clauses: list[Clause]) -> list[Clause]:
    primary = by_category(clauses, "parties") + by_category(clauses, "title")
    seen = {c.id for c in primary}
    return primary + [c for c in clauses[:8] if c.id not in seen]


def extract_party(clauses: list[Clause], role: str) -> Field[Party]:
    aliases = ("Landlord", "Lessor") if role == "landlord" else ("Tenant", "Lessee")
    for clause in _party_clauses(clauses):
        for sent in sentences(clause.text):
            for alias in aliases:
                if alias.lower() not in sent.lower():
                    continue
                party = _party_from_sentence(sent, alias)
                if party:
                    conf = 0.9 if clause.category == "parties" else 0.7
                    return _field(party, sent, clause, conf)
    return Field()


# An address ends at a parenthesis, a quoted defined term, a full stop, or the
# words that introduce what comes *with* the premises.
_ADDR_END = (
    r"(?=\s*\(|\s*[\"“](?:the\s+)?premises|[.;]|$"
    r"|,\s+(?:which|together|including|comprising|consisting|erf)\b)"
)
PREMISES_RE = re.compile(
    r"\b(?:premises|property|dwelling|flat|unit|house|apartment|cottage|townhouse)[\"”]?\s+"
    r"(?:known as|situated at|located at|described as|being|at|means|shall mean)\s+"
    r"(?P<addr>[^;]+?)" + _ADDR_END,
    re.IGNORECASE,
)
SITUATED_RE = re.compile(
    r"\b(?:situated|located)\s+at\s+(?P<addr>[^;]+?)" + _ADDR_END,
    re.IGNORECASE,
)


def extract_premises(clauses: list[Clause]) -> Field[Premises]:
    candidates = by_category(clauses, "premises") + [c for c in clauses if c.category != "premises"]
    for clause in candidates:
        for sent in sentences(clause.text):
            m = PREMISES_RE.search(sent) or SITUATED_RE.search(sent)
            if not m:
                continue
            addr = m.group("addr").strip(" ,")
            if len(addr) < 8 or not re.search(r"\d", addr):
                continue
            unit_m = re.search(r"\b(?:unit|flat|apartment|door)\s+(?:no\.?\s*)?([A-Za-z0-9]+)", addr, re.I)
            erf_m = re.search(r"\berf\s+(\d+)", sent, re.IGNORECASE)
            low = clause.text.lower()
            furnished = None
            if "unfurnished" in low:
                furnished = False
            elif "furnished" in low:
                furnished = True
            conf = 0.9 if clause.category == "premises" else 0.65
            return _field(
                Premises(address=addr, unit=unit_m.group(1) if unit_m else None,
                         erf=erf_m.group(1) if erf_m else None, furnished=furnished),
                sent, clause, conf,
            )
    return Field()


M2M_RE = re.compile(r"month[- ]to[- ]month|monthly (?:basis|tenancy)|periodic", re.IGNORECASE)
CONTINUATION_RE = re.compile(
    r"expir|continue|thereafter|renew|extend|roll|after the (?:end|termination)", re.IGNORECASE
)


def extract_term(clauses: list[Clause]) -> Field[Term]:
    candidates = by_category(clauses, "term") or [c for c in clauses if "commenc" in c.text.lower()]
    for clause in candidates:
        text = family_text(clauses, clause.id) or clause.text
        low = text.lower()
        dates = find_dates(text)
        months = None
        mm = re.search(r"\b(\d+)\s*(?:\([a-z]+\)\s*)?(?:calendar\s+)?months?\b", text, re.I)
        if mm:
            months = int(mm.group(1))
        else:
            for c in find_counts(text):
                if c.unit == "month":
                    months = c.n
                    break
        # "Month-to-month" inside an expiry/continuation sentence ("on expiry
        # the lease continues month-to-month") describes what happens *after*
        # the fixed term, not the term itself.
        m2m_sentences = [
            s for s in sentences(text) if M2M_RE.search(s)
        ]
        m2m_primary = any(not CONTINUATION_RE.search(s) for s in m2m_sentences)
        is_fixed = bool(re.search(r"\bfixed\b", low)) or len(dates) >= 2 or bool(months)
        kind = None
        if m2m_primary:
            kind = "month_to_month"
        elif is_fixed:
            kind = "fixed"
        elif m2m_sentences:
            kind = "month_to_month"
        start = end = None
        if dates:
            ordered = sorted({h.value for h in dates})  # type: ignore[type-var]
            start = ordered[0]
            end = ordered[-1] if len(ordered) > 1 and kind != "month_to_month" else None
        if start and end and months is None:
            months = round(((end - start).days + 1) / 30.4375)
        if not (start or months or kind):
            continue
        cite = sentence_at(text, dates[0].start) if dates else sentences(text)[0]
        source = clause
        if cite not in clause.text:
            source = next((c for c in clauses if cite in c.text), clause)
        return _field(Term(start=start, end=end, months=months, kind=kind), cite, source, 0.85)
    return Field()


METHOD_RE = re.compile(
    r"debit order|stop order|standing order|electronic funds transfer|\beft\b|bank transfer|cash", re.I
)


RENT_WORD_RE = re.compile(r"\brent(?:al)?\b", re.IGNORECASE)


def extract_rent(clauses: list[Clause]) -> Field[Rent]:
    # A heading like "RENTAL AND ESCALATION" lands in the escalation category;
    # a lease with no rent heading at all still says "rent" somewhere.
    pool = by_category(clauses, "rent") + by_category(clauses, "escalation")
    seen = {c.id for c in pool}
    pool += [
        c
        for c in clauses
        if c.id not in seen
        and c.category not in {"deposit", "penalties"}
        and RENT_WORD_RE.search(c.text)
    ]
    for clause in pool:
        text = family_text(clauses, clause.id) or clause.text
        amounts = [
            a
            for a in find_amounts(text)
            if RENT_WORD_RE.search(sentence_at(text, a.start))
            and not re.search(r"deposit|penalt|fee", sentence_at(text, a.start), re.I)
        ]
        if not amounts:
            continue
        hit = next(
            (a for a in amounts if re.search(r"per month|monthly|per calendar month|month", sentence_at(text, a.start), re.I)),
            amounts[0],
        )
        sent = sentence_at(text, hit.start)
        due = None
        dm = DUE_DAY_RE.search(text)
        if dm:
            tok = dm.group("day").lower()
            due = _ORDINALS.get(tok) or int(re.sub(r"\D", "", tok))
        meth = METHOD_RE.search(text)
        method = meth.group(0).lower().replace("eft", "EFT") if meth else None
        source = clause if sent in clause.text else next((c for c in clauses if sent in c.text), clause)
        return _field(Rent(amount_zar=hit.value, due_day=due, method=method), sent, source, 0.9)  # type: ignore[arg-type]
    return Field()


def extract_escalation(clauses: list[Clause]) -> Field[Escalation]:
    candidates = by_category(clauses, "escalation") + [
        c for c in by_category(clauses, "rent") if re.search(r"escalat|increase", c.text, re.I)
    ]
    for clause in candidates:
        text = family_text(clauses, clause.id) or clause.text
        pcts = find_percentages(text)
        amounts = [a for a in find_amounts(text) if re.search(r"escalat|increase", sentence_at(text, a.start), re.I)]
        if not pcts and not amounts:
            continue
        hit = pcts[0] if pcts else amounts[0]
        sent = sentence_at(text, hit.start)
        anniv = bool(re.search(r"anniversary|annually|each year|every year|per annum|every 12 months", text, re.I))
        source = clause if sent in clause.text else next((c for c in clauses if sent in c.text), clause)
        value = Escalation(pct=hit.value if pcts else None, amount_zar=None if pcts else hit.value, anniversary=anniv)  # type: ignore[arg-type]
        return _field(value, sent, source, 0.9)
    return Field()


INTEREST_YES_RE = re.compile(r"interest[- ]bearing|bear interest|earn interest|accrue[sd]? interest|savings rate|interest (?:shall|will|must) accrue", re.I)
INTEREST_NO_RE = re.compile(r"non[- ]interest|no interest|not (?:earn|bear|attract|accrue) (?:any )?interest|without interest|shall not accrue interest", re.I)
REFUND_RE = re.compile(r"refund|repay|repaid|return|paid back|pay back", re.I)


def extract_deposit(clauses: list[Clause], rent: Rent | None = None) -> Field[Deposit]:
    for clause in by_category(clauses, "deposit"):
        text = family_text(clauses, clause.id) or clause.text
        amounts = [a for a in find_amounts(text) if "deposit" in sentence_at(text, a.start).lower()]
        if not amounts:
            continue
        hit = amounts[0]
        sent = sentence_at(text, hit.start)
        months_eq = None
        me = re.search(r"(?:equal|equivalent)\s+to\s+(?P<n>\d+|[a-z]+)\s*(?:\(\d+\)\s*)?(?:\([a-z]+\)\s*)?months?", text, re.I)
        if me:
            tok = me.group("n")
            months_eq = float(tok) if tok.isdigit() else (float(word_to_int(tok)) if word_to_int(tok) else None)
        if months_eq is None and rent:
            months_eq = round(hit.value / rent.amount_zar, 2)  # type: ignore[operator]
        interest: bool | None = None
        if INTEREST_NO_RE.search(text):
            interest = False
        elif INTEREST_YES_RE.search(text):
            interest = True
        refund_days = None
        for c in find_day_counts(text):
            if REFUND_RE.search(sentence_at(text, c.start)):
                refund_days = int(c.days)
                break
        source = clause if sent in clause.text else next((c for c in clauses if sent in c.text), clause)
        value = Deposit(amount_zar=hit.value, months_equivalent=months_eq, interest_bearing=interest, refund_days=refund_days)  # type: ignore[arg-type]
        return _field(value, sent, source, 0.9)
    return Field()


NOTICE_SKIP_RE = re.compile(r"inspect|enter|access|remedy|rectif|expir|renew|arrear|overdue", re.I)
ACTOR_RE = re.compile(r"either party|both parties|tenant|lessee|landlord|lessor", re.I)


def extract_notice(clauses: list[Clause]) -> Field[Notice]:
    pool = by_category(clauses, "notice") + by_category(clauses, "term") + by_category(clauses, "cpa")
    seen: set[str] = set()
    tenant: tuple[int, str] | None = None
    landlord: tuple[int, str] | None = None
    cite: tuple[str, Clause] | None = None
    for clause in pool:
        if clause.id in seen:
            continue
        seen.add(clause.id)
        for sent in sentences(clause.text):
            if "notice" not in sent.lower() or NOTICE_SKIP_RE.search(sent):
                continue
            counts = [c for c in find_day_counts(sent) if c.unit != "hour"]
            if not counts:
                continue
            c = counts[0]
            am = ACTOR_RE.search(sent)
            actor = am.group(0).lower() if am else "either party"
            days, unit = int(c.days), c.kind
            if actor in {"either party", "both parties"}:
                tenant = tenant or (days, unit)
                landlord = landlord or (days, unit)
            elif actor in {"tenant", "lessee"}:
                tenant = tenant or (days, unit)
            else:
                landlord = landlord or (days, unit)
            cite = cite or (sent, clause)
    if cite is None:
        return Field()
    value = Notice(
        tenant_days=tenant[0] if tenant else None,
        landlord_days=landlord[0] if landlord else None,
        tenant_unit=tenant[1] if tenant else "calendar",  # type: ignore[arg-type]
        landlord_unit=landlord[1] if landlord else "calendar",  # type: ignore[arg-type]
    )
    return _field(value, cite[0], cite[1], 0.8)


ACTOR_SPLIT_RE = re.compile(r"(?=\bThe (?:Landlord|Tenant|Lessor|Lessee)\b)")


def _items(segment: str) -> list[str]:
    body = segment.split(":", 1)[1] if ":" in segment else segment
    parts = re.split(r";|\s\([a-z]\)\s|\s\d{1,2}\.\d\s", body)
    out = []
    for p in parts:
        p = re.sub(r"^\s*(?:and\s+)?", "", p.strip()).rstrip(".;, ")
        p = re.sub(r"^\(?[a-z]\)\s*", "", p)
        if len(p) > 3:
            out.append(p)
    return out


def extract_maintenance(clauses: list[Clause]) -> Field[Maintenance]:
    roots = [c for c in by_category(clauses, "maintenance") if c.parent_id is None or c.heading]
    if not roots:
        roots = by_category(clauses, "maintenance")
    if not roots:
        return Field()
    landlord: list[str] = []
    tenant: list[str] = []
    cite: tuple[str, Clause] | None = None
    covered: set[str] = set()
    for root in roots:
        if root.id in covered:
            continue
        text = family_text(clauses, root.id)
        covered |= {c.id for c in clauses if c.parent_id == root.id}
        for seg in ACTOR_SPLIT_RE.split(text):
            seg = seg.strip()
            if not seg:
                continue
            low = seg.lower()
            if low.startswith(("the landlord", "the lessor")):
                target = landlord
            elif low.startswith(("the tenant", "the lessee")):
                target = tenant
            else:
                continue
            items = _items(seg)
            if not items:
                continue
            target.extend(i for i in items if i not in target)
            if cite is None:
                cite = _cite_segment(seg, clauses)
    if cite is None:
        return Field()
    return _field(Maintenance(landlord=landlord, tenant=tenant), cite[0], cite[1], 0.8)


def _cite_segment(seg: str, clauses: list[Clause]) -> tuple[str, Clause] | None:
    """Cite the clause whose text opens ``seg``.

    ``seg`` may span a parent ("The Landlord is responsible for:") and its
    lettered children; the quote must be text that exists verbatim in *one*
    clause, or the citation check downstream will (rightly) throw it out.
    """
    first = sentences(seg)[0]
    for c in clauses:
        if c.text and first in c.text:
            return first, c
    for c in clauses:
        if c.text and seg.startswith(c.text):
            return c.text, c
    return None


PENALTY_RE = re.compile(r"penalt|interest (?:at|of|on)|late payment|forfeit|per day|admin(?:istration)? fee|cancellation fee", re.I)


def extract_penalties(clauses: list[Clause]) -> Field[list[str]]:
    pool = by_category(clauses, "penalties") or clauses
    found: list[tuple[str, Clause]] = []
    for clause in pool:
        for sent in sentences(clause.text):
            if PENALTY_RE.search(sent) and sent not in [f[0] for f in found]:
                found.append((sent, clause))
    if not found:
        return Field()
    return _field([s for s, _ in found], found[0][0], found[0][1], 0.75)


def extract_special(clauses: list[Clause]) -> Field[list[str]]:
    by_id = {c.id: c for c in clauses}
    labels: list[str] = []
    cite: tuple[str, Clause] | None = None
    for clause in by_category(clauses, "special"):
        heading = clause.heading
        if heading is None and clause.parent_id and by_id.get(clause.parent_id):
            heading = by_id[clause.parent_id].heading
        label = heading.title() if heading else sentences(clause.text)[0][:80]
        if label not in labels:
            labels.append(label)
        if cite is None and clause.text:
            cite = (sentences(clause.text)[0], clause)
    if not labels or cite is None:
        return Field()
    return _field(labels, cite[0], cite[1], 0.7)


class RuleExtractor:
    """Run every rule extractor and assemble a :class:`LeaseAbstract`."""

    def extract(self, clauses: list[Clause], source_name: str = "lease") -> LeaseAbstract:
        rent = extract_rent(clauses)
        return LeaseAbstract(
            source_name=source_name,
            landlord=extract_party(clauses, "landlord"),
            tenant=extract_party(clauses, "tenant"),
            premises=extract_premises(clauses),
            term=extract_term(clauses),
            rent=rent,
            escalation=extract_escalation(clauses),
            deposit=extract_deposit(clauses, rent.value),
            notice=extract_notice(clauses),
            maintenance=extract_maintenance(clauses),
            penalties=extract_penalties(clauses),
            special_clauses=extract_special(clauses),
            clauses=clauses,
        )


def category_of(clause: Clause) -> ClauseCategory:
    return clause.category


__all__ = [
    "Count",
    "Hit",
    "RuleExtractor",
    "extract_deposit",
    "extract_escalation",
    "extract_maintenance",
    "extract_notice",
    "extract_party",
    "extract_penalties",
    "extract_premises",
    "extract_rent",
    "extract_special",
    "extract_term",
    "find_amounts",
    "find_counts",
    "find_dates",
    "find_day_counts",
    "find_id_numbers",
    "find_percentages",
    "parse_amount",
    "sentence_at",
    "sentences",
    "word_to_int",
]
