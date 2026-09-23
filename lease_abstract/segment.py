"""Deterministic clause segmenter.

Real leases arrive in every shape: ``1.``/``1.1``/``(a)`` numbering, ALL-CAPS
section headings with no numbers at all, run-on paragraphs, and page-break
noise from PDF extraction. The segmenter turns all of those into a flat list
of :class:`~lease_abstract.schema.Clause` objects with stable ids:

* ``c<label>`` for numbered clauses (``c1``, ``c1.1``, ``c5.a``)
* ``s<n>``     for ALL-CAPS headings without a number
* ``p<n>``     for unnumbered paragraphs under a heading

Ids are derived from the document itself, so re-running on the same text
gives the same ids, and citations survive a re-run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import Clause, ClauseCategory

NUMBERED_RE = re.compile(r"^(?P<label>\d+(?:\.\d+)*)[.)]?\s+(?P<rest>\S.*)$")
LETTERED_RE = re.compile(r"^\((?P<label>[a-z]|[ivx]+|\d+)\)\s+(?P<rest>\S.*)$")
PAGE_BREAK_RE = re.compile(
    r"^(?:\f|-{2,}\s*page\s+\d+(?:\s+of\s+\d+)?\s*-{2,}|page\s+\d+\s+of\s+\d+|\[page\s*\d+\])\s*$",
    re.IGNORECASE,
)
# The execution block ("Signed at Durban on ...") belongs to no section; if it
# were parented to the last one, its date would leak into that clause's family.
EXECUTION_RE = re.compile(r"^(?:signed|dated|thus done and signed|signature|witness)", re.IGNORECASE)

# Keywords match on word boundaries; a trailing ``*`` allows any suffix
# (``terminat*`` hits "termination" and "terminate", while ``term`` does not).
CATEGORY_KEYWORDS: dict[ClauseCategory, tuple[str, ...]] = {
    "parties": ("parties", "landlord:", "tenant:", "lessor", "lessee", "between"),
    "premises": ("premises", "property", "dwelling", "situated at"),
    "term": ("duration", "term", "period", "commencement", "commenc*"),
    "rent": ("rental", "rent", "payment of rent"),
    "escalation": ("escalation", "escalat*", "increase*"),
    "deposit": ("deposit*",),
    "notice": ("notice*", "termination", "cancellation", "cancel*", "terminat*"),
    "maintenance": ("maintenance", "repair*", "upkeep"),
    "penalties": ("breach*", "penalt*", "late payment", "default", "arrear*"),
    "access": ("access", "inspection*", "inspect*", "entry", "enter*"),
    "special": (
        "special",
        "pets",
        "sublet*",
        "sub-let*",
        "use of the premises",
        "alteration*",
        "parking",
        "smoking",
    ),
    "privacy": ("popia", "personal information", "privacy", "protection of personal"),
    "cpa": ("consumer protection", "expiry", "renewal", "renew*"),
}


def _keyword_re(keyword: str) -> re.Pattern[str]:
    prefix = keyword.endswith("*")
    core = keyword.rstrip("*")
    tail = "" if prefix or not core[-1].isalnum() else r"\b"
    return re.compile(r"\b" + re.escape(core) + tail, re.IGNORECASE)


CATEGORY_PATTERNS: dict[ClauseCategory, tuple[re.Pattern[str], ...]] = {
    cat: tuple(_keyword_re(k) for k in words) for cat, words in CATEGORY_KEYWORDS.items()
}

# Order matters: the first category whose keyword hits the heading wins.
HEADING_PRIORITY: tuple[ClauseCategory, ...] = (
    "parties",
    "premises",
    "deposit",
    "rent",
    "escalation",
    "term",
    "notice",
    "maintenance",
    "penalties",
    "access",
    "privacy",
    "cpa",
    "special",
)

TITLE_WORDS = ("lease agreement", "agreement of lease", "rental agreement", "lease of residential")


def _is_caps_heading(line: str) -> bool:
    letters = [ch for ch in line if ch.isalpha()]
    if len(letters) < 3 or len(line) > 80:
        return False
    if not all(ch.isupper() for ch in letters):
        return False
    # A shouting sentence still ends in a full stop; a heading does not.
    return not line.rstrip().endswith((".", ";", ","))


def _is_title_heading(line: str) -> bool:
    words = line.split()
    if not 1 <= len(words) <= 6 or line.rstrip().endswith((".", ";", ",", ":")):
        return False
    return all(w[:1].isupper() or w.lower() in {"of", "and", "the", "to"} for w in words)


def _heading_category(heading: str) -> ClauseCategory | None:
    for cat in HEADING_PRIORITY:
        if any(rx.search(heading) for rx in CATEGORY_PATTERNS[cat]):
            return cat
    return None


def categorise(heading: str | None, text: str, parent_heading: str | None = None) -> ClauseCategory:
    """Pick a category from the heading first, then the parent heading, then the body text.

    Only a clause's *own* heading can make it the title; a section under the
    title still gets its own category.
    """
    if heading:
        hl = heading.lower()
        if any(t in hl for t in TITLE_WORDS) and len(hl) < 60:
            return "title"
        cat = _heading_category(heading)
        if cat is not None:
            return cat
    if parent_heading:
        cat = _heading_category(parent_heading)
        if cat is not None:
            return cat
    best: ClauseCategory = "other"
    best_hits = 0
    for cat in HEADING_PRIORITY:
        hits = sum(len(rx.findall(text)) for rx in CATEGORY_PATTERNS[cat])
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


@dataclass
class _Draft:
    id: str
    heading: str | None
    text_lines: list[str] = field(default_factory=list)
    parent_id: str | None = None
    page: int = 1
    label: str | None = None

    @property
    def text(self) -> str:
        return " ".join(line.strip() for line in self.text_lines).strip()


class Segmenter:
    """Split lease text into clauses. Stateless apart from per-call counters."""

    def __init__(self, min_clause_chars: int = 1) -> None:
        self.min_clause_chars = min_clause_chars

    def segment(self, text: str) -> list[Clause]:
        drafts: list[_Draft] = []
        seen_ids: dict[str, int] = {}
        section_n = 0
        para_n = 0
        page = 1
        paragraph_break = False
        current: _Draft | None = None
        # Most recent numbered draft at each depth, for parent lookup.
        last_by_depth: dict[int, _Draft] = {}
        # Most recent un-numbered CAPS section. Top-level numbered clauses hang
        # off it (if there is one) — never off the previous numbered clause,
        # otherwise every section becomes a descendant of section 1.
        last_section: _Draft | None = None

        def unique(base: str) -> str:
            n = seen_ids.get(base, 0)
            seen_ids[base] = n + 1
            return base if n == 0 else f"{base}-{n + 1}"

        def start(draft: _Draft) -> _Draft:
            nonlocal current
            drafts.append(draft)
            current = draft
            return draft

        for raw in text.replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if "\f" in raw or PAGE_BREAK_RE.match(line):
                page += 1
                paragraph_break = True
                continue
            if not line:
                paragraph_break = True
                continue

            m = NUMBERED_RE.match(line)
            if m:
                label, rest = m.group("label"), m.group("rest").strip()
                depth = label.count(".")
                parent = last_by_depth.get(depth - 1) if depth else None
                heading = rest if (_is_caps_heading(rest) or _is_title_heading(rest)) else None
                d = _Draft(
                    id=unique(f"c{label}"),
                    heading=heading,
                    parent_id=parent.id if parent else (last_section.id if last_section else None),
                    page=page,
                    label=label,
                )
                if heading is None:
                    d.text_lines.append(rest)
                start(d)
                last_by_depth[depth] = d
                for deeper in [k for k in last_by_depth if k > depth]:
                    del last_by_depth[deeper]
                paragraph_break = False
                continue

            m = LETTERED_RE.match(line)
            if m and current is not None:
                label, rest = m.group("label"), m.group("rest").strip()
                host = current
                # (a) items hang off the nearest numbered/section clause, not off a sibling (b).
                while host.label and re.fullmatch(r"[a-z]|[ivx]+", host.label) and host.parent_id:
                    host = next(d for d in drafts if d.id == host.parent_id)
                d = _Draft(
                    id=unique(f"{host.id}.{label}"),
                    heading=None,
                    parent_id=host.id,
                    page=page,
                    label=label,
                )
                d.text_lines.append(rest)
                start(d)
                paragraph_break = False
                continue

            if _is_caps_heading(line):
                section_n += 1
                d = _Draft(id=unique(f"s{section_n}"), heading=line, page=page)
                start(d)
                last_section = d
                last_by_depth = {}
                paragraph_break = False
                continue

            # Plain text line.
            if current is None:
                para_n += 1
                start(_Draft(id=unique(f"p{para_n}"), heading=None, page=page))
            elif paragraph_break and (current.text or EXECUTION_RE.match(line)):
                para_n += 1
                parent = current.parent_id if current.heading is None else current.id
                if EXECUTION_RE.match(line):
                    parent = None
                start(_Draft(id=unique(f"p{para_n}"), heading=None, parent_id=parent, page=page))
            assert current is not None
            current.text_lines.append(line)
            paragraph_break = False

        by_id = {d.id: d for d in drafts}
        clauses: list[Clause] = []
        for d in drafts:
            parent = by_id.get(d.parent_id) if d.parent_id else None
            parent_heading = parent.heading if parent else None
            if parent and parent_heading is None and parent.parent_id:
                grand = by_id.get(parent.parent_id)
                parent_heading = grand.heading if grand else None
            if d.heading is None and not d.text:
                continue
            if len(d.text) < self.min_clause_chars and d.heading is None:
                continue
            clauses.append(
                Clause(
                    id=d.id,
                    heading=d.heading,
                    text=d.text,
                    category=categorise(d.heading, d.text, parent_heading),
                    parent_id=d.parent_id,
                    page=d.page,
                    label=d.label,
                )
            )
        return clauses


def segment(text: str) -> list[Clause]:
    return Segmenter().segment(text)


def family_text(clauses: list[Clause], clause_id: str) -> str:
    """Text of a clause plus all of its descendants, in document order."""
    ids = {clause_id}
    changed = True
    while changed:
        changed = False
        for c in clauses:
            if c.parent_id in ids and c.id not in ids:
                ids.add(c.id)
                changed = True
    return " ".join(c.text for c in clauses if c.id in ids and c.text)


def by_category(clauses: list[Clause], category: ClauseCategory) -> list[Clause]:
    return [c for c in clauses if c.category == category]


__all__ = ["Segmenter", "by_category", "categorise", "family_text", "segment"]
