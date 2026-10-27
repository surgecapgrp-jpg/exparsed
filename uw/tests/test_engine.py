#!/usr/bin/env python3
"""Regression tests for engine/uw.py. Run: python -m unittest discover -s tests -v"""

import copy
import json
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import uw  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
LEDGER = json.loads((FIX / "sample_ledger.json").read_text())
JUDGMENTS = json.loads((FIX / "sample_judgments.json").read_text())


def raw(led):
    return json.dumps(led).encode()


def engine(led=None, judgments=None):
    """Run the engine and the unchanged V2.2 report validator on its output."""
    b = (FIX / "sample_ledger.json").read_bytes() if led is None else raw(led)
    e = uw.Engine(b, judgments)
    uw.legacy_gate(e.render())
    return e


def pos(e, funder):
    return [p for p in e.positions if p.funder.startswith(funder)]


def truncate(led, last):
    led = copy.deepcopy(led)
    led["transactions"] = [t for t in led["transactions"] if t["date"] <= last]
    for a in led["accounts"]:
        a["statements"] = [
            dict(s, end=min(s["end"], last))
            for s in a["statements"]
            if s["start"] <= last
        ]
    return led


def with_judgments(e_default, answers):
    return dict(ledger_sha256=e_default.sha, answers=answers)


def q(e, descriptor=None, kind=None):
    return next(
        x["question_id"]
        for x in e.questions
        if (descriptor and x.get("descriptor") == descriptor)
        or (kind and x["type"] == kind)
    )


class Sample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine()
        cls.j = engine(judgments=JUDGMENTS)

    def test_stack_is_exact_sum_of_live_costs(self):
        self.assertEqual(
            self.e.stack, D(525) * 20 + D(1200) * D("4.333") + D(900) * D("4.333")
        )

    def test_named_funder_wire_attaches_to_amount_up(self):
        p = pos(self.e, "RAPIDFUND")[0]
        self.assertEqual([ev["kind"] for ev in p.events], ["AMOUNT UP"])
        self.assertEqual(p.events[0]["date"].isoformat(), "2026-07-31")
        self.assertEqual(p.fundings[0]["trigger"]["kind"], "AMOUNT UP")
        self.assertEqual(self.e.by_id[p.fundings[0]["credit"]].amt, D(40000))

    def test_unknown_wire_is_not_stripped_without_evidence(self):
        wire = next(t for t in self.e.txns if "JKL" in t.desc)
        self.assertEqual(wire.tag, "REV_WIRE")
        self.assertFalse(pos(self.e, "CFG")[0].fundings)
        fwd = next(f for f in self.e.forward if f["anchor"] == wire.id)
        self.assertEqual(fwd["outcome"], "No supported financing evidence")

    def test_document_evidence_strips_and_attaches(self):
        wire = next(t for t in self.j.txns if "JKL" in t.desc)
        self.assertEqual(wire.tag, "STRIP_FUNDING")
        self.assertEqual(
            self.j.by_id[pos(self.j, "CFG")[0].fundings[0]["credit"]].id, wire.id
        )
        sep = self.j.month_rows[(2026, 9)]
        self.assertEqual(sep["true"], self.e.month_rows[(2026, 9)]["true"] - D(30000))

    def test_stopped_position_is_not_live(self):
        p = pos(self.e, "SUNCAP")[0]
        self.assertFalse(p.live)
        self.assertEqual(p.cost, 0)
        self.assertTrue(p.prefile)

    def test_varying_card_purchases_are_not_mca(self):
        self.assertFalse(pos(self.e, "HOME DEPOT"))

    def test_transfers_stripped_and_owner_draw_excluded(self):
        xfers = [
            t
            for t in self.e.txns
            if t.dir == "credit" and "TRANSFER FROM SAV" in t.desc
        ]
        self.assertTrue(xfers and all(t.tag == "STRIP_TRANSFER" for t in xfers))
        owner = next(r for r in self.e.ob_rows if r["tag"] == "OWNER_DRAW")
        self.assertEqual(owner["avg"], D(2000))
        self.assertEqual(
            self.e.total_ob,
            sum(
                r["avg"]
                for r in self.e.ob_rows
                if r["tag"] != "OWNER_DRAW" and not r["ambiguous"]
            ),
        )

    def test_payroll_return_is_one_cured_t2_chain(self):
        a = [ev for ev in self.e.t7 if ev["cls"] == "A"]
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["tier"], a[0]["cured"][:1]), ("T2", "Y"))
        self.assertTrue(any(ev["cls"] == "B" for ev in self.e.t7))

    def test_judgments_change_obligations(self):
        self.assertEqual(self.j.ob_rows[-1]["tag"], "AMBIGUOUS_CARD_PAYMENT")
        self.assertLess(self.j.headline, self.e.headline)

    def test_every_trigger_and_candidate_searched(self):
        triggers = {tr["trigger_id"] for p in self.e.positions for tr in p.triggers}
        self.assertEqual(triggers, {s["anchor"] for s in self.e.searches})
        self.assertEqual(set(self.e.cand), {f["anchor"] for f in self.e.forward})


class TrustBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = engine()
        cls.credit_q = q(cls.e, kind="credit")

    def reject(self, answers, msg):
        with self.assertRaisesRegex(uw.UWError, msg):
            uw.Engine(
                (FIX / "sample_ledger.json").read_bytes(),
                with_judgments(self.e, answers),
            )

    def test_fabricated_quote_rejected(self):
        self.reject(
            [
                dict(
                    question_id=self.credit_q,
                    tag="STRIP_FUNDING",
                    evidence=dict(kind="bank_text", quote="MCA FUNDING"),
                )
            ],
            "quote not in transaction text",
        )

    def test_funding_without_evidence_rejected(self):
        self.reject(
            [dict(question_id=self.credit_q, tag="STRIP_FUNDING")], "needs evidence"
        )

    def test_document_must_state_amount(self):
        led = copy.deepcopy(LEDGER)
        led["documents"][0][
            "text"
        ] = "CFG Merchant Solutions agreement funded via JKL Holdings."
        e = uw.Engine(raw(led))
        with self.assertRaisesRegex(uw.UWError, "does not state amount"):
            uw.Engine(
                raw(led),
                with_judgments(
                    e,
                    [
                        dict(
                            question_id=q(e, kind="credit"),
                            tag="STRIP_FUNDING",
                            evidence=dict(
                                kind="document",
                                doc_id="DOC-1",
                                quote="funded via JKL Holdings",
                            ),
                        )
                    ],
                ),
            )

    def test_unknown_question_and_wrong_ledger_rejected(self):
        self.reject(
            [dict(question_id="Q-credit-0000000000", tag="REV_WIRE")],
            "unknown question id",
        )
        with self.assertRaisesRegex(uw.UWError, "ledger_sha256"):
            uw.Engine(
                (FIX / "sample_ledger.json").read_bytes(),
                dict(ledger_sha256="x", answers=[]),
            )

    def test_bad_tag_rejected(self):
        self.reject(
            [dict(question_id=q(self.e, "SYSCO FOODS"), tag="REVENUE")], "bad debit tag"
        )

    def test_termination_needs_verbatim_evidence(self):
        self.reject(
            [
                dict(
                    question_id=q(self.e, "RAPIDFUND LLC"),
                    tag="MCA",
                    funder="RapidFund",
                    terminated=dict(quote="PAID IN FULL"),
                )
            ],
            "quote not in transaction text",
        )


class Scenarios(unittest.TestCase):
    def test_one_month_is_insufficient_data(self):
        e = engine(truncate(LEDGER, "2026-06-30"))
        self.assertTrue(e.status.startswith("INSUFFICIENT DATA"))

    def test_negative_drop_since_peak_with_provisional_cadence(self):
        e = engine(truncate(LEDGER, "2026-09-04"))
        cfg = pos(e, "CFG")[0]
        self.assertEqual((cfg.cadence, cfg.cost), ("PROVISIONAL", D(900) * 20))
        self.assertLess(e.peak_week["weekly"], e.cur_weekly)

    def test_duplicate_rows_dropped_and_conflicts_fail(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"].append(dict(led["transactions"][0]))
        self.assertEqual(sum(engine(led).dropped.values()), 1)
        led["transactions"][-1]["amount"] = "1.00"
        with self.assertRaisesRegex(uw.UWError, "same id, different content"):
            uw.Engine(raw(led))

    def test_same_funder_two_concurrent_contracts(self):
        led = copy.deepcopy(LEDGER)
        extra = [
            dict(t, txn_id=t["txn_id"] + "b", amount="200.00")
            for t in led["transactions"]
            if t["description"].startswith("RAPIDFUND") and t["date"] >= "2026-08-03"
        ]
        led["transactions"] += extra
        e = engine(led)
        names = sorted(p.display for p in pos(e, "RAPIDFUND"))
        self.assertEqual(names, ["RAPIDFUND LLC #1", "RAPIDFUND LLC #2"])

    def test_integrity_suffix_follows_worst_account(self):
        led = copy.deepcopy(LEDGER)
        led["accounts"][1]["integrity"] = "Break"
        self.assertTrue(engine(led).status.endswith("(PROVISIONAL — INTEGRITY FAIL)"))

    def test_terminated_position_drops_from_stack(self):
        led = copy.deepcopy(LEDGER)
        led["documents"].append(
            dict(
                doc_id="DOC-2",
                kind="payoff_letter",
                text="BlueOak ADV confirms the advance is paid in full as of 09/28/2026.",
            )
        )
        e0 = uw.Engine(raw(led))
        e = engine(
            led,
            with_judgments(
                e0,
                [
                    dict(
                        question_id=q(e0, "BLUEOAK ADV"),
                        tag="MCA",
                        funder="BlueOak ADV",
                        terminated=dict(
                            kind="document", doc_id="DOC-2", quote="paid in full"
                        ),
                    )
                ],
            ),
        )
        self.assertEqual(e.stack, e0.stack - D(1200) * D("4.333"))

    def test_explicit_loan_text_strips_without_judgment(self):
        led = copy.deepcopy(LEDGER)
        for t in led["transactions"]:
            if "JKL" in t["description"]:
                t["description"] = "SBA LOAN PROCEEDS DISBURSEMENT"
        e = engine(led)
        t = next(t for t in e.txns if "SBA LOAN" in t.desc)
        self.assertEqual((t.tag, e.gate[t.id]["kind"]), ("STRIP_FUNDING", "bank_text"))


class Schemas(unittest.TestCase):
    def test_fixtures_match_schemas(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        for doc, schema in (
            (LEDGER, "ledger.schema.json"),
            (JUDGMENTS, "judgments.schema.json"),
        ):
            jsonschema.validate(
                doc, json.loads((ROOT / "schemas" / schema).read_text())
            )


if __name__ == "__main__":
    unittest.main()
