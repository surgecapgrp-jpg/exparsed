#!/usr/bin/env python3
"""Tests for adapter.py: Exparsed ledger-v1 export -> normalized ledger -> engine."""

import copy
import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT))
import uw  # noqa: E402
import adapter  # noqa: E402

SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "sample_ledger.json").read_text())
# The real lgLedgerExport output, written by the page's own test (tests/contract.js).
GOLDEN = json.loads(
    (ROOT.parent / "tests" / "golden" / "ledger-v1.json").read_text(encoding="utf-8")
)


def to_export(led):
    """The sample ledger as Exparsed would export it: one file per account per statement."""
    last4 = {a["account_id"]: a["last4"] for a in led["accounts"]}
    files = []
    for a in led["accounts"]:
        for s in a["statements"]:
            rows = [
                t
                for t in led["transactions"]
                if t["account_id"] == a["account_id"]
                and s["start"] <= t["date"] <= s["end"]
            ]
            files.append(
                dict(
                    name=f"{a['account_id']}-{s['start'][:7]}.pdf",
                    accountLast4=last4[a["account_id"]],
                    period=dict(s),
                    status="verified",
                    rows=[
                        f"{t['date']}|{'dep' if t['direction'] == 'credit' else 'wd'}|"
                        f"{'' if t['direction'] == 'credit' else '-'}{t['amount']}|{t['balance'] or ''}|1|{t['description']}"
                        for t in rows
                    ],
                )
            )
    return dict(format="ledger-v1", files=files)


class Adapter(unittest.TestCase):
    def test_round_trip_keeps_every_row_and_the_headline(self):
        led, skipped = adapter.convert(
            to_export(SAMPLE), SAMPLE["owner_names"], SAMPLE["business_name"]
        )
        self.assertEqual(skipped, [])
        key = lambda t: (
            t["date"],
            t["amount"],
            t["direction"],
            t["description"],
            t["balance"],
        )  # noqa: E731
        self.assertEqual(
            sorted(map(key, led["transactions"])),
            sorted(map(key, SAMPLE["transactions"])),
        )
        self.assertEqual(
            {a["last4"]: a["integrity"] for a in led["accounts"]},
            {"1234": "Pass", "5678": "Pass"},
        )
        led["holidays"], led["documents"] = (
            SAMPLE["holidays"],
            SAMPLE["documents"],
        )  # same inputs as the sample
        e = uw.Engine(json.dumps(led).encode())
        uw.legacy_gate(e.render())
        self.assertEqual(uw.usd(e.headline), "$17,578")

    def test_ids_are_stable_and_overlapping_files_dedupe(self):
        exp = to_export(SAMPLE)
        a, _ = adapter.convert(exp)
        b, _ = adapter.convert(copy.deepcopy(exp))
        self.assertEqual(
            [t["txn_id"] for t in a["transactions"]],
            [t["txn_id"] for t in b["transactions"]],
        )
        exp["files"].append(
            copy.deepcopy(exp["files"][0])
        )  # same statement loaded twice
        c, _ = adapter.convert(exp)
        e = uw.Engine(json.dumps(c).encode())
        self.assertEqual(len(e.txns), len(SAMPLE["transactions"]))

    def test_identical_rows_in_one_file_stay_separate(self):
        exp = dict(
            format="ledger-v1",
            files=[
                dict(
                    name="a.pdf",
                    accountLast4="1111",
                    status="verified",
                    period=dict(start="2026-06-01", end="2026-06-30"),
                    rows=["2026-06-02|wd|-10.00||1|FEE", "2026-06-02|wd|-10.00||1|FEE"],
                )
            ],
        )
        led, _ = adapter.convert(exp)
        self.assertEqual(len({t["txn_id"] for t in led["transactions"]}), 2)

    def test_status_pending_missing_account_and_skips(self):
        exp = dict(
            format="ledger-v1",
            files=[
                dict(
                    name="good.pdf",
                    accountLast4="1111",
                    status="partial",
                    period=dict(start="2026-06-01", end="2026-06-30"),
                    rows=[
                        "PENDING|wd|-5.00||1|HOLD",
                        "2026-06-03|dep|250.00|250.00|1|DEPOSIT",
                        "2026-06-04|wd|0.00||1|MEMO",
                    ],
                ),
                dict(
                    name="bad.pdf",
                    accountLast4="1111",
                    status="breaks",
                    period=None,
                    rows=["2026-07-02|wd|-20.00||2|ACH"],
                ),
                dict(
                    name="noacct.csv",
                    accountLast4=None,
                    status="verified",
                    period=None,
                    rows=["2026-06-05|dep|30.00||1|X"],
                ),
                dict(name="app.pdf", status="not-statement", rows=[]),
                dict(name="scan.pdf", status="needs-ocr", rows=[]),
            ],
        )
        led, skipped = adapter.convert(exp)
        self.assertEqual([n for n, _ in skipped], ["app.pdf", "scan.pdf"])
        acc = {a["account_id"]: a for a in led["accounts"]}
        self.assertEqual(acc["1111"]["integrity"], "Break")
        self.assertEqual(
            acc["1111"]["statements"][1], dict(start="2026-07-02", end="2026-07-02")
        )
        self.assertEqual(
            (acc["file:noacct.csv"]["last4"], acc["file:noacct.csv"]["integrity"]),
            ("0000", "Unverified"),
        )
        self.assertEqual(
            sorted((t["direction"], t["amount"]) for t in led["transactions"]),
            [("credit", "250.00"), ("credit", "30.00"), ("debit", "20.00")],
        )

    def test_real_page_export(self):
        led, skipped = adapter.convert(GOLDEN, ["Jane Doe"], "Acme LLC")
        self.assertEqual(skipped, [])
        self.assertEqual(len(led["transactions"]), 9)
        descs = {t["description"] for t in led["transactions"]}
        self.assertIn("DEBIT ZELLE TO jane@example.com Orig ID 1234567890", descs)
        refs = {t["source_ref"] for t in led["transactions"]}
        self.assertIn("chase.pdf p.2", refs)
        self.assertIn("checking.csv", refs)  # CSV rows carry no page
        accts = {a["account_id"]: a for a in led["accounts"]}
        self.assertEqual(accts["6789"]["integrity"], "Pass")
        self.assertEqual(accts["file:checking.csv"]["integrity"], "Unverified")
        again, _ = adapter.convert(GOLDEN, ["Jane Doe"], "Acme LLC")
        self.assertEqual(led, again)  # same export, same transaction ids
        e = uw.Engine(json.dumps(led).encode())
        self.assertIn("Table 9", e.render())

    def test_page_and_engine_agree_on_shared_figures(self):
        # Fed holidays: the page's lgFedHolidays wrote tests/golden/holidays.json
        golden = json.loads(
            (ROOT.parent / "tests" / "golden" / "holidays.json").read_text()
        )
        for year, days in golden.items():
            self.assertEqual(
                [d.isoformat() for d in adapter.fed_holidays(int(year))], days, year
            )
        # Day-end balances: every printed day-end the page reports (thinnestFive) is the
        # engine's end-of-day balance for that account and date. The CSV in the golden export
        # is newest first with two rows on 2026-01-07; the day closes at 2,900.00.
        led, _ = adapter.convert(GOLDEN)
        e = uw.Engine(json.dumps(led).encode())
        e.render()
        checked = 0
        for acct in GOLDEN["computed"]:
            aid = acct["account"].replace("unknown:", "file:")
            for day in acct["thinnestFive"]:
                if day["basis"] != "printed" or aid not in e.eod or not e.eod[aid]:
                    continue
                self.assertEqual(
                    e.eod[aid][date.fromisoformat(day["date"])],
                    Decimal(str(day["balance"])).quantize(Decimal("0.01")),
                    f"{aid} {day['date']}",
                )
                checked += 1
        self.assertGreaterEqual(checked, 3)

    def test_posting_order(self):
        newest = [
            "2026-01-08|c|10.00|130.00||x",
            "2026-01-07|d|-5.00|120.00||y",
            "2026-01-07|d|-5.00|125.00||z",
        ]
        rows = [r.split("|") for r in newest]
        self.assertEqual([r[3] for r in adapter.posting_order(rows)], ["125.00", "120.00", "130.00"])
        self.assertIs(adapter.posting_order(rows[::-1])[0], rows[::-1][0])  # already oldest first
        no_bal = [["2026-01-09", "c", "1.00", ""], ["2026-01-02", "c", "1.00", ""]]
        self.assertEqual(adapter.posting_order(no_bal)[0][0], "2026-01-02")

    def test_rejects_other_formats(self):
        with self.assertRaises(adapter.AdapterError):
            adapter.convert(SAMPLE)

    def test_fed_holidays(self):
        h = adapter.fed_holidays(2026)
        self.assertIn(date(2026, 6, 19), h)  # Juneteenth, Friday
        self.assertNotIn(
            date(2026, 7, 3), h
        )  # July 4 is a Saturday: the Fed stays open Friday
        self.assertIn(date(2026, 9, 7), h)  # Labor Day
        self.assertIn(date(2026, 11, 26), h)  # Thanksgiving
        self.assertIn(date(2023, 1, 2), adapter.fed_holidays(2023))  # Jan 1 is a Sunday
        self.assertEqual(len(h), 10)  # 11 minus July 4 (Saturday)


if __name__ == "__main__":
    unittest.main()
