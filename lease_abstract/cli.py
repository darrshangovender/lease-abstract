"""Command-line interface.

    lease-abstract extract lease.txt [--json]
    lease-abstract check lease.txt [--json] [--strict]
    lease-abstract summarise lease.txt --for tenant|landlord
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compliance.engine import ComplianceEngine, ComplianceReport
from .extract.pipeline import Pipeline
from .loader import load_text
from .schema import LeaseAbstract
from .summary import Summariser, fmt_zar


def _run(path: str) -> tuple[LeaseAbstract, str]:
    text = load_text(path)
    abstract = Pipeline().run(text, source_name=Path(path).name)
    return abstract, text


def _print_abstract(a: LeaseAbstract) -> None:
    print(f"Lease abstract: {a.source_name}")
    print(f"  clauses: {len(a.clauses)}   redacted PII items: {a.redactions}")
    for name, f in a.fields():
        if not f.present:
            print(f"  {name:16} -")
            continue
        v = f.value
        if hasattr(v, "model_dump"):
            d = v.model_dump(exclude_none=True)
            for k in ("amount_zar",):
                if k in d:
                    d[k] = fmt_zar(d[k])
            shown = ", ".join(f"{k}={val}" for k, val in d.items())
        else:
            shown = "; ".join(str(x) for x in v) if isinstance(v, list) else str(v)
        if len(shown) > 110:
            shown = shown[:107] + "..."
        print(f"  {name:16} {shown}")
        print(f"  {'':16} [{f.source_clause_id}, {f.origin}, {f.confidence:.2f}]")


def _print_report(r: ComplianceReport) -> None:
    print(f"Compliance: {r.source_name}  ({r.rules_evaluated} rules)")
    v, p, adv = r.violations(), r.pending(), r.advisories()
    print(f"  violations: {len(v)}   pending-law notes: {len(p)}   advisories: {len(adv)}")
    for f in v:
        appl = "" if f.applicability == "applies" else f" (applicability: {f.applicability})"
        print(f"  [{f.severity.upper():6}] {f.rule_id}  {f.statute} {f.section}{appl}")
        print(f"           clause {f.clause_id}: {f.explanation}")
        print(f"           fix: {f.suggested_fix}")
    for f in p:
        print(f"  [PENDING] {f.rule_id}  {f.statute} {f.section}")
        print(f"           clause {f.clause_id}: {f.explanation}")
        print(f"           note: {f.note}")
    for f in adv:
        print(f"  [NOTE  ] {f.rule_id}: {f.explanation}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lease-abstract", description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("extract", help="extract a typed, cited abstract")
    e.add_argument("path")
    e.add_argument("--json", action="store_true", help="print the abstract as JSON")

    c = sub.add_parser("check", help="run the SA compliance rules")
    c.add_argument("path")
    c.add_argument("--json", action="store_true")
    c.add_argument("--strict", action="store_true", help="exit 1 if any in-force violation is found")

    s = sub.add_parser("summarise", aliases=["summarize"], help="plain-English summary")
    s.add_argument("path")
    s.add_argument("--for", dest="audience", choices=["tenant", "landlord"], required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    abstract, text = _run(args.path)

    if args.command == "extract":
        if args.json:
            print(abstract.model_dump_json(indent=2, exclude={"clauses"}))
        else:
            _print_abstract(abstract)
        return 0

    report = ComplianceEngine().run(abstract, text)
    if args.command == "check":
        if args.json:
            print(report.model_dump_json(indent=2))
        else:
            _print_report(report)
        return 1 if (args.strict and report.violations()) else 0

    print(Summariser(abstract, report).render(args.audience))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
