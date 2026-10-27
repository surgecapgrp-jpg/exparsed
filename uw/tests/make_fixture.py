#!/usr/bin/env python3
"""Build tests/fixtures/sample_ledger.json: a synthetic two-account merchant, Jun to Sep 2026.

Planted facts the tests assert:
- RAPIDFUND LLC: daily $450 from coverage start (Pre-file), AMOUNT UP to $525 on 07/31 after a
  07/29 $40,000 wire that names the funder.
- SUNCAP FUNDING: daily $300, stops 06/26 (non-live).
- BLUEOAK ADV: weekly $1,200 from 08/17 after a 08/12 $25,000 ACH naming BLUEOAK.
- CFG MERCHANT SOLUTIONS: weekly $900 from 09/03. The only nearby credit is a 09/01 $30,000 wire
  from JKL HOLDINGS with no financing evidence in bank text. DOC-1 is a funding agreement for it.
- GUSTO payroll returned R01 on 08/17 and re-presented 08/18; a check on 08/13 overdraws the account.
- Savings to operating transfers carry the savings last4 and must be stripped.
"""

import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

HOLIDAYS = ["2026-06-19", "2026-07-03", "2026-09-07"]
START, END = date(2026, 6, 1), date(2026, 9, 30)
H = {date.fromisoformat(h) for h in HOLIDAYS}


def bdays():
    d = START
    while d <= END:
        if d.weekday() < 5 and d not in H:
            yield d
        d += timedelta(1)


def build():
    rnd = random.Random(7)
    rows = []  # (date, account, direction, amount, description)

    def add(d, acct, direction, amt, desc):
        rows.append(
            (d, acct, direction, Decimal(str(amt)).quantize(Decimal("0.01")), desc)
        )

    for i, d in enumerate(bdays()):
        add(
            d,
            "OP",
            "credit",
            rnd.randint(130000, 190000) / 100,
            f"SQUARE INC DEP {d:%y%m%d}",
        )
        if d.weekday() == 4:
            add(d, "OP", "credit", 4000, "ACH CREDIT ACME DISTRIBUTING PPD ID 99887766")
        if i % 10 == 3:
            add(d, "OP", "credit", rnd.randint(50000, 110000) / 100, "MOBILE DEPOSIT")
        if d <= date(2026, 7, 30):
            add(d, "OP", "debit", 450, "RAPIDFUND LLC ACH DEBIT 0001234")
        else:
            add(d, "OP", "debit", 525, "RAPIDFUND LLC ACH DEBIT 0001234")
        if d <= date(2026, 6, 26):
            add(d, "OP", "debit", 300, "SUNCAP FUNDING DEBIT")
        if d.weekday() == 0 and d >= date(2026, 8, 17):
            add(d, "OP", "debit", 1200, "BLUEOAK ADV ACH DEBIT")
        if d.weekday() == 3 and d >= date(2026, 9, 3):
            add(d, "OP", "debit", 900, "CFG MERCHANT SOLUTIONS ACH DEBIT")
        if d.weekday() == 2:
            add(
                d,
                "OP",
                "debit",
                rnd.randint(150000, 210000) / 100,
                "SYSCO FOODS ACH DEBIT",
            )
        if rnd.random() < 0.35:
            add(
                d,
                "OP",
                "debit",
                rnd.randint(2000, 30000) / 100,
                f"POS PURCHASE HOME DEPOT {rnd.randint(1000, 9999)}",
            )
    payroll = [date(2026, 6, 5) + timedelta(14 * k) for k in range(9)]
    for d in payroll:
        if d == date(2026, 8, 14):
            continue
        add(d, "OP", "debit", 5500, "GUSTO PAYROLL ACH DEBIT")
    for m in (6, 7, 8, 9):
        first = next(d for d in bdays() if d.month == m)
        add(first, "OP", "debit", 4500, "ACH DEBIT OAKWOOD PROPERTY MGMT RENT")
        add(date(2026, m, 10), "OP", "debit", 650, "CITY ELECTRIC CO")
        add(date(2026, m, 12), "OP", "debit", 220, "COMCAST BUSINESS")
        add(date(2026, m, 15), "OP", "debit", 380, "NEXT INSURANCE PREM")
        add(date(2026, m, 21), "OP", "debit", 3000, "AMEX EPAYMENT")
        add(date(2026, m, 20), "OP", "debit", 2000, "ZELLE TO JANE DOE")
    add(date(2026, 6, 15), "OP", "debit", 2100, "IRS USATAXPYMT")
    add(date(2026, 9, 15), "OP", "debit", 2100, "IRS USATAXPYMT")
    add(date(2026, 7, 29), "OP", "credit", 40000, "WIRE IN RAPIDFUND LLC REF 55512")
    add(date(2026, 8, 12), "OP", "credit", 25000, "ACH CREDIT BLUEOAK ADV FUNDING")
    add(date(2026, 9, 1), "OP", "credit", 30000, "WIRE IN ORIG JKL HOLDINGS REF 777")
    add(date(2026, 7, 15), "OP", "credit", 5000, "ONLINE TRANSFER FROM SAV XXXXXX5678")
    add(date(2026, 7, 15), "SAV", "debit", 5000, "ONLINE TRANSFER TO CHK XXXXXX1234")
    add(date(2026, 8, 13), "OP", "debit", 98000, "CHECK 1043")
    add(date(2026, 8, 14), "OP", "debit", 5500, "GUSTO PAYROLL ACH DEBIT")
    add(date(2026, 8, 14), "OP", "debit", 35, "OVERDRAFT FEE")
    add(date(2026, 8, 17), "OP", "credit", 5500, "GUSTO PAYROLL RETURN R01")
    add(date(2026, 8, 17), "OP", "debit", 35, "NSF RETURNED ITEM FEE")
    add(date(2026, 8, 17), "OP", "credit", 15000, "ONLINE TRANSFER FROM SAV XXXXXX5678")
    add(date(2026, 8, 17), "SAV", "debit", 15000, "ONLINE TRANSFER TO CHK XXXXXX1234")
    add(date(2026, 8, 18), "OP", "debit", 5500, "GUSTO PAYROLL ACH DEBIT")
    for m in (6, 7, 8, 9):
        add(date(2026, m, 28), "SAV", "credit", 2.10, "INTEREST PAYMENT")

    order = {"credit": 0, "debit": 1}
    rows.sort(key=lambda r: (r[0], r[1], order[r[2]]))
    bal = {"OP": Decimal("15000.00"), "SAV": Decimal("40000.00")}
    txns = []
    for n, (d, acct, direction, amt, desc) in enumerate(rows, 1):
        bal[acct] += amt if direction == "credit" else -amt
        txns.append(
            dict(
                txn_id=f"T{n:05d}",
                account_id=acct,
                date=d.isoformat(),
                amount=str(amt),
                direction=direction,
                description=desc,
                balance=str(bal[acct]),
                source_ref=f"{acct}-{d:%Y%m}.pdf",
            )
        )
    stmts = [
        dict(
            start=f"2026-{m:02d}-01",
            end=(date(2026, m + 1, 1) - timedelta(1)).isoformat(),
        )
        for m in (6, 7, 8, 9)
    ]
    return dict(
        schema="uw-ledger/1",
        business_name="Sample Bistro LLC",
        owner_names=["Jane Doe"],
        holidays=HOLIDAYS,
        accounts=[
            dict(
                account_id="OP",
                name="Operating",
                last4="1234",
                integrity="Pass",
                statements=stmts,
            ),
            dict(
                account_id="SAV",
                name="Savings",
                last4="5678",
                integrity="Pass",
                statements=stmts,
            ),
        ],
        documents=[
            dict(
                doc_id="DOC-1",
                kind="funding_agreement",
                text="Merchant cash advance agreement between CFG Merchant Solutions and Sample Bistro LLC. "
                "Purchase price $30,000.00 disbursed by wire on 09/01/2026 via JKL Holdings, "
                "CFG's funding agent. Weekly remittance $900.",
            )
        ],
        transactions=txns,
    )


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "sample_ledger.json"
    out.write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
