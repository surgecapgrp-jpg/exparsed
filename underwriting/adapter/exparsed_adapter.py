#!/usr/bin/env python3
"""Convert an Exparsed `ledger-v1` export into the engine's normalized ledger (schemas/ledger.schema.json).

Format read from a real export (27 Oct 2026):
- files[]: one per source document, with accountLast4, period {start, end}, status, checks[], rows[].
- rows[]: "date|section|amount|balance|page|description" plus "|type" on printouts. Printouts list
  newest first. amount is signed (+credit / -debit); balance is the bank-printed running balance or
  empty. date "PENDING" marks unposted rows.
- computed[]: per-account arithmetic Exparsed derived from verified rows (kept as a cross-check only).

Usage: python adapter/exparsed_adapter.py EXPARSED_LEDGER.json [--owner "Jane Doe"] > normalized.json
exparsed.html calls page_run() through Pyodide.
"""

import argparse
import functools
import hashlib
import json
import sys
import traceback
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

# Exparsed file status -> V2.2 Table 1 verdict (see the export's own `note` for each status).
STATUS = {
    "verified": "Pass",
    "partial": "Unverified",
    "untestable": "Unverified",
    "breaks": "Break",
    "unparsed": "Unverified",
    "needs-ocr": "Unverified",
}
# Federal Reserve holidays. Saturday holidays are not observed by the Fed. Extend each year.
HOLIDAYS = [
    "2025-01-01",
    "2025-01-20",
    "2025-02-17",
    "2025-05-26",
    "2025-06-19",
    "2025-07-04",
    "2025-09-01",
    "2025-10-13",
    "2025-11-11",
    "2025-11-27",
    "2025-12-25",
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-05-25",
    "2026-06-19",
    "2026-09-07",
    "2026-10-12",
    "2026-11-11",
    "2026-11-26",
    "2026-12-25",
]


def fail(msg):
    sys.exit(f"adapter: {msg}")


def period(f):
    """Statement period, or the span of posted row dates when Exparsed found no printed period."""
    if f.get("period"):
        return dict(start=f["period"]["start"], end=f["period"]["end"])
    dates = sorted(line.split("|", 1)[0] for line in f["rows"] if not line.startswith("PENDING"))
    if not dates:
        fail(f"{f['name']}: no period and no posted rows")
    return dict(start=dates[0], end=dates[-1])


@functools.lru_cache(maxsize=2)
def normalized(ledger_text, owners=()):
    """ledger-v1 text -> engine ledger bytes. Cached: the page calls page_run twice per Run."""
    return json.dumps(convert(json.loads(ledger_text), list(owners))).encode()


def page_run(ledger_text, judgments_text=None, owners=()):
    """Entry point for exparsed.html (Pyodide). Returns JSON text; never raises."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
    import uw

    try:
        r = uw.underwrite(normalized(ledger_text, tuple(owners)), json.loads(judgments_text) if judgments_text else None)
        return json.dumps(
            dict(ok=True, status=r.status, open_questions=r.open_questions, questions=r.questions, report=r.report, audit=r.audit),
            default=uw.jsonable,
        )
    except (uw.UWError, SystemExit) as err:
        return json.dumps(dict(ok=False, error=str(err)))
    except Exception as err:  # a bug or an export shape the adapter does not know: say where
        frame = traceback.extract_tb(err.__traceback__)[-1]
        return json.dumps(dict(ok=False, error=f"{type(err).__name__}: {err} ({Path(frame.filename).name}:{frame.lineno})"))

def convert(src, owners):
    if src.get("format") != "ledger-v1":
        fail(f"expected format ledger-v1, got {src.get('format')!r}")
    by_acct, unread = defaultdict(list), []
    for f in src["files"]:
        # V1.7 section 1: every supplied file stays in the inventory, read or not.
        if f.get("docKind"):
            unread.append(dict(name=f["name"], reason=f"{f['docKind']}; not a bank statement", statement=False))
            continue
        if not f.get("rows") or f.get("status") in ("needs-ocr", "unparsed"):
            unread.append(dict(name=f["name"], reason=f"Exparsed status {f.get('status', 'no rows')}", statement=True))
            continue
        # No printed account number: the file stands alone as its own account.
        by_acct[f.get("accountLast4") or f"file {f['name']}"].append(f)
    accounts, txns = [], []
    for last4, files in by_acct.items():
        verdicts = [STATUS.get(f["status"], "Unverified") for f in files]
        worst = next(
            v
            for v in ("Break", "Unverified", "Pass with flag", "Pass")
            if v in verdicts
        )
        notes, pending, zero, seen = [], 0, 0, Counter()
        for f in files:
            failed = [
                c["check"] for c in f.get("checks", []) if c.get("result") != "pass"
            ]
            notes.append(
                f"{f['name']}: Exparsed {f['status']}"
                + (f", failed: {', '.join(failed)}" if failed else "")
                + (
                    f", flags: {', '.join(f['provenance']['flags'])}"
                    if (f.get("provenance") or {}).get("flags")
                    else ""
                )
            )
            cols = f["columns"].split("|")
            if cols[:6] != ["date", "section", "amount", "balance", "page", "description"] or cols[6:] not in ([], ["type"]):
                fail(f"{f['name']}: unexpected columns {f['columns']}")
            # The description may itself hold "|": split the fixed columns from the left, type from the right.
            rows = []
            for line in f["rows"]:
                head = line.split("|", 5)
                desc = head[5]
                if len(cols) == 7 and "|" in desc:  # lgRowStr drops an empty type; it maps "|" in descriptions to "/"
                    desc = desc.rsplit("|", 1)[0]
                rows.append(dict(zip(cols[:5], head[:5]), description=desc))
            dated = [r["date"] for r in rows if r["date"] != "PENDING"]
            if dated and dated[0] > dated[-1]:
                rows.reverse()  # printouts list newest first; the engine wants posting order
            for r in rows:
                if r["date"] == "PENDING":
                    pending += 1
                    continue
                amt = Decimal(r["amount"])
                if amt == 0:
                    zero += 1
                    continue
                key = "|".join(
                    (last4, r["date"], r["amount"], r["balance"], r["description"])
                )
                seen[key] += 1
                txns.append(
                    dict(
                        txn_id=f"{last4}-"
                        + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:12],
                        account_id=last4,
                        date=r["date"],
                        amount=str(abs(amt)),
                        direction="credit" if amt > 0 else "debit",
                        description=r["description"],
                        balance=r["balance"] or None,
                        source_ref=f"{f['name']} p{r['page']}",
                    )
                )
        if pending:
            notes.append(f"{pending} pending row(s) excluded")
        if zero:
            notes.append(f"{zero} zero-amount row(s) excluded")
        notes += [
            n
            for c in src.get("computed", [])
            if c["account"] == last4
            for n in c.get("notes", [])
        ]
        accounts.append(
            dict(
                account_id=last4,
                # A file without a printed account number is labelled by its file name.
                name=last4[5:] if last4.startswith("file ") else "Account",
                last4="----" if last4.startswith("file ") else last4,
                integrity=worst,
                integrity_note="; ".join(notes),
                statements=[period(f) for f in files],
            )
        )
    if not accounts:
        fail("no statement files with rows")
    return dict(
        schema="uw-ledger/1",
        owner_names=owners,
        holidays=HOLIDAYS,
        sources_unread=unread,
        accounts=accounts,
        transactions=txns,
        documents=[],
        # Exparsed's own gross credits per month; the engine cross-checks its sums against them.
        exparsed_computed=[
            dict(account=c["account"], month=m["month"], gross_inflows=m["grossInflows"], partial=m.get("partial", False))
            for c in src.get("computed", [])
            for m in c.get("months", [])
            if "grossInflows" in m
        ],
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger")
    ap.add_argument("--owner", action="append", default=[])
    args = ap.parse_args()
    with open(args.ledger, encoding="utf-8") as fh:
        json.dump(convert(json.load(fh), args.owner), sys.stdout, indent=1)
