#!/usr/bin/env python3
"""Tests for adapter.py: Exparsed ledger-v1 export -> normalized ledger -> engine."""

import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT))
import uw  # noqa: E402
import adapter  # noqa: E402

SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "sample_ledger.json").read_text())


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
