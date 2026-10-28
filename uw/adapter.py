#!/usr/bin/env python3
"""Convert an Exparsed ledger-v1 export (the "Ledger JSON" button, lgLedgerExport in exparsed.html)
into the engine's normalized ledger (schemas/ledger.schema.json).

Usage: python3 uw/adapter.py ledger.json [--owner "Jane Doe"] [--business "Acme LLC"] > normalized.json
"""

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# Exparsed ledger status -> V2.2 Table 1 verdict. Files with any other status are skipped.
INTEGRITY = {
    "verified": "Pass",
    "partial": "Pass with flag",
    "untestable": "Unverified",
    "breaks": "Break",
}
WORST = ("Break", "Unverified", "Pass with flag", "Pass")


class AdapterError(Exception):
    pass


def fed_holidays(year):
    """Federal Reserve holidays. A Sunday holiday moves to Monday; a Saturday one is not observed."""

    def nth(month, weekday, n):  # n-th weekday of a month; n=-1 is the last one
        if n > 0:
            d = date(year, month, 1)
            return d + timedelta((weekday - d.weekday()) % 7 + 7 * (n - 1))
        d = date(year, month + 1, 1) - timedelta(1)
        return d - timedelta((d.weekday() - weekday) % 7)

    fixed = [date(year, m, d) for m, d in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25))]
    moving = [
        nth(1, 0, 3),
        nth(2, 0, 3),
        nth(5, 0, -1),
        nth(9, 0, 1),
        nth(10, 0, 2),
        nth(11, 3, 4),
    ]
    return sorted(
        [d + timedelta(1) if d.weekday() == 6 else d for d in fixed if d.weekday() != 5]
        + moving
    )


def convert(src, owners=(), business=None):
    """Returns (normalized ledger, skipped files as [(name, reason)])."""
    if not isinstance(src, dict) or src.get("format") != "ledger-v1":
        raise AdapterError(
            "not an Exparsed ledger-v1 export (format field missing or different)"
        )
    accounts, txns, skipped = {}, [], []
    for f in src.get("files", []):
        name, status = f.get("name", "?"), f.get("status")
        if status not in INTEGRITY:
            skipped.append((name, f"status {status}"))
            continue
        rows = [r.split("|") for r in f.get("rows", [])]
        rows = [r for r in rows if len(r) >= 6 and r[0] != "PENDING"]
        if not rows:
            skipped.append((name, "no dated rows"))
            continue
        last4 = f.get("accountLast4")
        aid = last4 or "file:" + name
        a = accounts.setdefault(
            aid,
            dict(
                account_id=aid,
                name=f"Account ending {last4}" if last4 else name,
                last4=last4[-4:] if last4 else "0000",
                integrity="Pass",
                statements=[],
                notes=[] if last4 else ["no account number printed"],
            ),
        )
        per = f.get("period") or {}
        a["statements"].append(
            dict(
                start=per.get("start") or min(r[0] for r in rows),
                end=per.get("end") or max(r[0] for r in rows),
            )
        )
        verdict = INTEGRITY[status] if last4 else "Unverified"
        a["integrity"] = min(a["integrity"], verdict, key=WORST.index)
        a["notes"].append(f"{name}: Exparsed {status}")
        # n separates identical rows inside one file; the same row in two files keeps one id,
        # so the engine drops it as a duplicate (overlapping statements).
        seen = Counter()
        for date_, _section, amount, balance, page, desc, *_ in rows:
            try:
                amt = Decimal(amount)
            except InvalidOperation:
                raise AdapterError(f"{name}: bad amount {amount!r}")
            if amt == 0:
                continue
            key = f"{a['last4']}|{date_}|{amt}|{desc}"
            seen[key] += 1
            txns.append(
                dict(
                    txn_id=hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:12],
                    account_id=aid,
                    date=date_,
                    amount=str(abs(amt)),
                    direction="credit" if amt > 0 else "debit",
                    description=desc,
                    balance=balance or None,
                    source_ref=f"{name} p.{page}" if page else name,
                )
            )
    if not txns:
        raise AdapterError("no statement rows to underwrite (every file was skipped)")
    years = {int(t["date"][:4]) for t in txns}
    out_accounts = []
    for a in accounts.values():
        a["integrity_note"] = "; ".join(a.pop("notes"))
        out_accounts.append(a)
    led = dict(
        schema="uw-ledger/1",
        owner_names=list(owners),
        holidays=[
            d.isoformat()
            for y in range(min(years) - 1, max(years) + 1)
            for d in fed_holidays(y)
        ],
        accounts=out_accounts,
        transactions=txns,
        documents=[],
    )
    if business:
        led["business_name"] = business
    return led, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ledger")
    ap.add_argument("--owner", action="append", default=[])
    ap.add_argument("--business")
    args = ap.parse_args()
    try:
        with open(args.ledger, encoding="utf-8") as fh:
            led, skipped = convert(json.load(fh), args.owner, args.business)
    except (OSError, json.JSONDecodeError, AdapterError) as e:
        sys.exit(f"adapter: {e}")
    for n, why in skipped:
        print(f"adapter: skipped {n} ({why})", file=sys.stderr)
    json.dump(led, sys.stdout, indent=1)
