"""CLI smoke tests and the offline eval runner."""

import json
import subprocess
import sys

import pytest

from lease_abstract.cli import main
from lease_abstract.loader import PDFSupportMissing, load_text

from .conftest import LEASES, ROOT, make_lease

L01 = str(LEASES / "01_compliant.txt")
L02 = str(LEASES / "02_non_interest_deposit.txt")
L03 = str(LEASES / "03_entry_any_time.txt")


def test_extract_text_output(capsys):
    assert main(["extract", L01]) == 0
    out = capsys.readouterr().out
    assert "Lease abstract: 01_compliant.txt" in out
    assert "rent" in out and "R8 500" in out and "[c4.1, rules, 0.90]" in out
    assert "8804125001088" in out or "has_id_number=True" in out


def test_extract_json_output(capsys):
    assert main(["extract", L01, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rent"]["value"]["amount_zar"] == 8500.0
    assert data["rent"]["source_clause_id"] == "c4.1"
    assert "clauses" not in data


def test_check_text_and_json(capsys):
    assert main(["check", L02]) == 0
    out = capsys.readouterr().out
    assert "violations: 3" in out and "RHA-5-3-D-INTEREST" in out
    assert main(["check", L02, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {f["rule_id"] for f in data["findings"] if f["status"] == "in_force" and f["category"] != "advisory"} >= {"RHA-5-3-D-INTEREST"}


def test_check_strict_exit_codes(capsys, tmp_path):
    assert main(["check", L01, "--strict"]) == 0
    assert main(["check", L02, "--strict"]) == 1
    # Only a pending-proclamation note: strict must still pass.
    p = tmp_path / "pending_only.txt"
    p.write_text(make_lease(access="6.1 The Landlord may enter the premises on 12 hours' notice to inspect them."), encoding="utf-8")
    assert main(["check", str(p), "--strict"]) == 0
    assert "[PENDING]" in capsys.readouterr().out


def test_summarise_both_audiences(capsys):
    assert main(["summarise", L03, "--for", "tenant"]) == 0
    tenant = capsys.readouterr().out
    assert main(["summarize", L03, "--for", "landlord"]) == 0
    landlord = capsys.readouterr().out
    assert "Summary for the tenant" in tenant and "Summary for the landlord" in landlord
    assert "R12 000" in tenant and "R12 000" in landlord


def test_cli_requires_audience_for_summarise():
    with pytest.raises(SystemExit):
        main(["summarise", L01])


def test_loader_reads_text_and_reports_missing_pdf_support(tmp_path):
    assert load_text(L01).startswith("RESIDENTIAL LEASE AGREEMENT")
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        with pytest.raises(PDFSupportMissing):
            load_text(tmp_path / "x.pdf")


def test_eval_runner_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "eval" / "run.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "TOTAL" in proc.stdout and "LEAK" not in proc.stdout
