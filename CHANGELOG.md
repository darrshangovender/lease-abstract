# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.1] - 2026-10-14

### Fixed
- Wrong Rental Housing Act paragraph citations, checked against the Act as published in
  Government Gazette No. 20726 (15 December 1999). The deposit-refund rule cited
  s5(3)(e)-(g); (e) and (f) are the joint inspections. It now cites s5(3)(i) (7 days, nothing
  owing), s5(3)(g) (14 days, after deductions) and s5(3)(k)-(m) (21 days, tenant did not
  respond to the inspection request), in the rule and in every finding message. The joint
  inspection rule now cites s5(3)(e)-(f) instead of s5(3).
- `UNFAIR-ENTRY-NO-NOTICE` now cites RHA s4(2) (inspection only after reasonable notice, in
  force since 1999); `UNFAIR-LOCKOUT` now cites s4(3)(c) and s4(5)(d)(ii) (court order
  required).
- Demo leases and tests shipped checksum-valid SA ID numbers with real birth dates and an
  issuable citizenship digit, i.e. numbers that could belong to real people. Every one now
  uses citizenship digit 9 (never issued) with a recomputed check digit; the redaction tests
  still exercise the date and Luhn checks.
- README Python example read a `lease.txt` that does not exist; it now reads a demo lease.

### Changed
- Rule id `RHA-5-3-E-REFUND` renamed to `RHA-5-3-REFUND` (the "E" named the wrong paragraph).
- Ruff rule set widened to `E, F, W, I, B, UP` (E501 ignored, with the reason in
  `pyproject.toml`); lint is now a CI gate (it was `continue-on-error`).
- README: Results section labelled with what it measures, limitations for the unbundled LLM
  client and unchecked non-RHA citations, standard footer. Added `demo/README.md`,
  `CITATION.cff`, this changelog, `tests/test_regressions.py`.

## [0.1.0] - 2026-10-09

### Added
- Initial release: clause segmenter, rules-first extractors with citations, strict-JSON LLM
  gap-fill protocol with `MockModel`, POPIA redaction, RHA / RHAA (pending) / CPA s14 /
  Tribunal compliance rules, tenant and landlord summaries, CLI and offline eval.
