# Demo data (synthetic)

Everything in this folder is invented for testing and demonstration. No lease, person,
address or account here is real, and none comes from LeasEase users or any client.

- `leases/`: six synthetic South African residential leases, each written to exercise a
  specific compliance rule (the file name says which).
- `expected/`: hand-written gold abstracts, one per lease, used by `eval/run.py`.
- `expected_findings.yml`: the rule ids each lease should trigger.

Personal-information-shaped values exist only so the POPIA redactor has something to redact:
ID numbers pass the date and Luhn checks but use citizenship digit 9, which is never issued;
e-mail addresses use reserved `example.*` domains; phone numbers are invented (South Africa
has no reserved fictional range, so a coincidental match is possible).
