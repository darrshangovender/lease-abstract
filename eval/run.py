"""Offline benchmark: extraction vs gold abstracts, findings vs expected findings.

    python eval/run.py            # prints the table
    python eval/run.py --json     # also writes eval/results.json

Runs the full pipeline with a :class:`MockModel` that answers ``{}`` (so the
LLM gap-fill path is exercised but never contributes), then scores:

* **Fields** - every leaf in ``demo/expected/<lease>.json`` (``rent.amount_zar``,
  ``term.kind`` ...) against the extracted abstract. Precision / recall are
  over leaves, so a wrong value costs both a false positive and a false
  negative and a missing value costs a false negative only.
* **Findings** - rule ids in ``ComplianceReport.violations()`` against
  ``demo/expected_findings.yml``. Pending-proclamation findings are scored
  separately and the run fails if one of them is ever reported as a violation.
* **Cited** - share of extracted fields that carry a ``source_clause_id`` and a
  quote that can be found in the lease. This must be 100%.

Exit status is 1 if any lease has a citation gap or a pending rule leaks into
violations; otherwise 0, whatever the scores.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402  (PyYAML is a dev dependency)

from lease_abstract import ComplianceEngine, MockModel, Pipeline  # noqa: E402
from lease_abstract.extract.pipeline import locate  # noqa: E402
from lease_abstract.schema import LeaseAbstract  # noqa: E402

LEASES = ROOT / "demo" / "leases"
EXPECTED = ROOT / "demo" / "expected"
EXPECTED_FINDINGS = ROOT / "demo" / "expected_findings.yml"


# --------------------------------------------------------------------------- #
# Flattening
# --------------------------------------------------------------------------- #


def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return " ".join(v.split()).casefold()
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return float(v)
    return str(v)


def flatten_gold(gold: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in gold.items():
        if name == "source":
            continue
        if isinstance(value, dict):
            for k, v in value.items():
                out[f"{name}.{k}"] = v
        else:
            out[name] = value
    return out


def flatten_abstract(a: LeaseAbstract, keys: list[str]) -> dict[str, Any]:
    """Project the abstract onto the gold's leaf keys."""
    out: dict[str, Any] = {}
    for key in keys:
        if key == "penalties_count":
            out[key] = len(a.penalties.value) if a.penalties.value is not None else None
            continue
        name, _, sub = key.partition(".")
        f = getattr(a, name)
        if f.value is None:
            out[key] = None
            continue
        if name == "maintenance":
            out[key] = len(getattr(f.value, sub.removesuffix("_items")))
            continue
        v = getattr(f.value, sub)
        out[key] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    def __add__(self, other: Score) -> Score:
        return Score(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn, self.misses + other.misses)


def score_fields(gold: dict[str, Any], pred: dict[str, Any]) -> Score:
    s = Score()
    for key, g in gold.items():
        p = pred.get(key)
        # A whole field expected absent (e.g. notice: null) counts once.
        if g is None:
            if p is not None:
                s.fp += 1
                s.misses.append(f"{key}: expected none, got {p!r}")
            continue
        if _norm(p) == _norm(g):
            s.tp += 1
        elif p is None:
            s.fn += 1
            s.misses.append(f"{key}: missing (want {g!r})")
        else:
            s.fp += 1
            s.fn += 1
            s.misses.append(f"{key}: got {p!r}, want {g!r}")
    return s


def score_sets(expected: set[str], predicted: set[str]) -> Score:
    s = Score()
    s.tp = len(expected & predicted)
    s.fp = len(predicted - expected)
    s.fn = len(expected - predicted)
    s.misses = [f"unexpected {r}" for r in sorted(predicted - expected)] + [
        f"missed {r}" for r in sorted(expected - predicted)
    ]
    return s


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


@dataclass
class LeaseResult:
    name: str
    fields: Score
    findings: Score
    pending_ok: bool
    cited: int
    extracted: int
    applicability_ok: bool


def run_one(path: Path, expected_findings: dict[str, Any]) -> LeaseResult:
    text = path.read_text(encoding="utf-8")
    gold = json.loads((EXPECTED / f"{path.stem}.json").read_text(encoding="utf-8"))
    pipeline = Pipeline(model=MockModel("{}"))
    abstract = pipeline.run(text, source_name=path.name)
    report = ComplianceEngine().run(abstract, text)

    g = flatten_gold(gold)
    p = flatten_abstract(abstract, list(g))
    fields = score_fields(g, p)

    exp = expected_findings.get(path.name, {}) or {}
    exp_viol = set(exp.get("violations") or [])
    exp_pend = set(exp.get("pending") or [])
    got_viol = {f.rule_id for f in report.violations()}
    got_pend = {f.rule_id for f in report.pending()}
    findings = score_sets(exp_viol, got_viol)
    pending_ok = got_pend == exp_pend and not (got_pend & got_viol)
    if not pending_ok:
        findings.misses.append(f"pending mismatch: got {sorted(got_pend)}, want {sorted(exp_pend)}")

    want_appl = exp.get("applicability")
    applicability_ok = True
    if want_appl:
        cpa = [f for f in report.violations() if f.rule_id.startswith("CPA-")]
        applicability_ok = bool(cpa) and all(f.applicability == want_appl for f in cpa)

    extracted = cited = 0
    for _, f in abstract.fields():
        if not f.present:
            continue
        extracted += 1
        clause = locate(abstract.clauses, f.extracted_text)
        if f.source_clause_id and clause is not None and abstract.clause(f.source_clause_id):
            cited += 1
    return LeaseResult(path.name, fields, findings, pending_ok, cited, extracted, applicability_ok)


def fmt_pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def render(results: list[LeaseResult]) -> str:
    lines = []
    head = (
        f"{'lease':32} | {'fields':>9} | {'field P':>7} | {'field R':>7} | "
        f"{'findings':>9} | {'find P':>7} | {'find R':>7} | {'pending':>7} | {'cited':>7}"
    )
    lines.append(head)
    lines.append("-" * len(head))
    for r in results:
        lines.append(
            f"{r.name:32} | {r.fields.tp:>3}/{r.fields.tp + r.fields.fn:<5} | {fmt_pct(r.fields.precision):>7} | "
            f"{fmt_pct(r.fields.recall):>7} | {r.findings.tp:>3}/{r.findings.tp + r.findings.fn:<5} | "
            f"{fmt_pct(r.findings.precision):>7} | {fmt_pct(r.findings.recall):>7} | "
            f"{'ok' if r.pending_ok else 'LEAK':>7} | {r.cited:>2}/{r.extracted:<4}"
        )
    tf = sum((r.fields for r in results), Score())
    tg = sum((r.findings for r in results), Score())
    cited = sum(r.cited for r in results)
    extracted = sum(r.extracted for r in results)
    lines.append("-" * len(head))
    lines.append(
        f"{'TOTAL':32} | {tf.tp:>3}/{tf.tp + tf.fn:<5} | {fmt_pct(tf.precision):>7} | {fmt_pct(tf.recall):>7} | "
        f"{tg.tp:>3}/{tg.tp + tg.fn:<5} | {fmt_pct(tg.precision):>7} | {fmt_pct(tg.recall):>7} | "
        f"{'ok' if all(r.pending_ok for r in results) else 'LEAK':>7} | {cited:>2}/{extracted:<4}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="lease-abstract offline benchmark")
    ap.add_argument("--json", action="store_true", help="also write eval/results.json")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every miss")
    args = ap.parse_args(argv)

    expected_findings = yaml.safe_load(EXPECTED_FINDINGS.read_text(encoding="utf-8")) or {}
    results = [run_one(p, expected_findings) for p in sorted(LEASES.glob("*.txt"))]

    print(render(results))
    print()
    misses = [(r.name, m) for r in results for m in r.fields.misses + r.findings.misses]
    if misses and (args.verbose or len(misses) <= 20):
        for name, m in misses:
            print(f"  {name}: {m}")
        print()
    bad_appl = [r.name for r in results if not r.applicability_ok]
    if bad_appl:
        print(f"  CPA applicability mismatch: {', '.join(bad_appl)}")

    if args.json:
        out = ROOT / "eval" / "results.json"
        out.write_text(
            json.dumps(
                [
                    {
                        "lease": r.name,
                        "fields": {"tp": r.fields.tp, "fp": r.fields.fp, "fn": r.fields.fn},
                        "findings": {"tp": r.findings.tp, "fp": r.findings.fp, "fn": r.findings.fn},
                        "pending_ok": r.pending_ok,
                        "cited": r.cited,
                        "extracted": r.extracted,
                        "misses": r.fields.misses + r.findings.misses,
                    }
                    for r in results
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {out}")

    leak = [r.name for r in results if not r.pending_ok]
    uncited = [r.name for r in results if r.cited != r.extracted]
    if leak or uncited or bad_appl:
        print(f"FAIL: pending-leak={leak} uncited={uncited} applicability={bad_appl}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
