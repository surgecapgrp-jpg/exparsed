#!/usr/bin/env python3
"""Regression tests for engine/uw.py. Run: python -m unittest discover -s tests -v"""

import copy
import importlib.util
import json
import sys
import unittest
from unittest import mock
from datetime import date
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


def run(led=None, judgments=None):
    """underwrite() through its interface. It also runs the V1.7 report checker."""
    return uw.underwrite((FIX / "sample_ledger.json").read_bytes() if led is None else raw(led), judgments)


def pos(r, funder):
    return [p for p in r.audit["positions"] if p["funder"].startswith(funder)]


def ids(led, text):
    return [t["txn_id"] for t in led["transactions"] if text in t["description"]]


def tags(r, led, text):
    want = set(ids(led, text))
    return [t["tag"] for t in r.audit["transactions"] if t["txn_id"] in want]


def month(r, key):
    return next(m for m in r.audit["months"] if m["key"] == key)


def forward(r, txn_id):
    return next(f for f in r.audit["forward_searches"] if f["anchor"] == txn_id)


def truncate(led, last):
    led = copy.deepcopy(led)
    led["transactions"] = [t for t in led["transactions"] if t["date"] <= last]
    for a in led["accounts"]:
        a["statements"] = [dict(s, end=min(s["end"], last)) for s in a["statements"] if s["start"] <= last]
    return led


def with_judgments(r_default, answers):
    return dict(ledger_sha256=r_default.questions["ledger_sha256"], answers=answers)


W = uw.WEEKS_PER_MONTH


def cents(x):
    return x.quantize(D("0.01"))


def drop(led, text, after):
    """Remove the debits matching `text` dated after `after`, to make a series go silent."""
    led = copy.deepcopy(led)
    led["transactions"] = [t for t in led["transactions"] if not (text in t["description"] and t["date"] > after)]
    return led


def known(r, answers):
    """The answers whose question ids exist for this ledger (the core question id follows the ledger hash)."""
    ids = {x["question_id"] for x in r.questions["questions"]}
    return [a for a in answers if a["question_id"] in ids]


def q(r, descriptor=None, kind=None):
    return next(
        x["question_id"]
        for x in r.questions["questions"]
        if (descriptor and x.get("descriptor") == descriptor) or (kind and x["type"] == kind)
    )


class Sample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = run()
        cls.j = run(judgments=JUDGMENTS)

    def test_report_is_rendered_from_the_audit(self):
        self.assertEqual(self.j.report, uw.render(self.j.audit))
        self.assertEqual(self.j.audit["report_gate"], "PASS")

    def test_stack_is_exact_sum_of_live_costs(self):
        self.assertEqual(
            self.e.audit["capacity"]["live_stack"], D(525) * 20 + D(1200) * W + D(900) * W
        )
        self.assertEqual(cents(D(1200) * W), D("5200.00"))  # V1.7: exactly 52/12, not 4.333

    def test_named_funder_wire_attaches_to_amount_up(self):
        p = pos(self.e, "RAPIDFUND")[0]
        self.assertEqual([ev["kind"] for ev in p["events"]], ["AMOUNT UP"])
        self.assertEqual(p["events"][0]["date"].isoformat(), "2026-07-31")
        self.assertEqual(p["fundings"][0]["trigger"]["kind"], "AMOUNT UP")
        self.assertEqual(p["fundings"][0]["credit_amount"], D(40000))

    def test_unanswered_wire_is_unresolved_not_funding(self):
        # V1.7: an unanswered candidate credit leaves revenue as STRIP_UNRESOLVED and is not called financing.
        self.assertEqual(tags(self.e, LEDGER, "JKL"), ["STRIP_UNRESOLVED"])
        self.assertFalse(pos(self.e, "CFG")[0]["fundings"])
        self.assertEqual(forward(self.e, ids(LEDGER, "JKL")[0])["outcome"], "No supported financing evidence")
        self.assertEqual(month(self.e, "2026-09")["unresolved"], D(30000))
        self.assertIn("STRIP_UNRESOLVED $30,000", self.e.report)

    def test_answered_wire_returns_to_revenue(self):
        r = run(judgments=with_judgments(self.e, [dict(question_id=q(self.e, kind="credit"), tag="REV_WIRE")]))
        self.assertEqual(tags(r, LEDGER, "JKL"), ["REV_WIRE"])
        self.assertEqual(month(r, "2026-09")["true"], month(self.e, "2026-09")["true"] + D(30000))

    def test_document_evidence_strips_and_attaches(self):
        self.assertEqual(tags(self.j, LEDGER, "JKL"), ["STRIP_FUNDING"])
        self.assertEqual(pos(self.j, "CFG")[0]["fundings"][0]["credit"], ids(LEDGER, "JKL")[0])
        self.assertEqual(month(self.j, "2026-09")["true"], month(self.e, "2026-09")["true"])
        self.assertEqual(month(self.j, "2026-09")["unresolved"], 0)

    def test_stopped_position_without_closure_is_u(self):
        # V1.7: silence is not closure. SunCap stops 06/26, 66 covered bd before coverage end.
        p = pos(self.e, "SUNCAP")[0]
        self.assertEqual((p["live_status"], p["live"], p["monthly_cost"]), ("U", False, 0))
        self.assertGreater(p["scenario_cost"], 0)
        self.assertTrue(p["material"])
        self.assertIn("Collections absent", p["status_basis"])
        self.assertTrue(any("funding may precede coverage (unproven)" in n for n in p["notes"]))
        self.assertNotIn("Pre-file", self.e.report)
        self.assertTrue(self.e.status.startswith("INSUFFICIENT DATA"))
        self.assertIn("SUNCAP FUNDING U scenario", self.e.audit["capacity"]["binding"])

    def test_varying_card_purchases_are_not_mca(self):
        self.assertFalse(pos(self.e, "HOME DEPOT"))

    def test_transfers_stripped_and_owner_draw_excluded(self):
        self.assertEqual(set(tags(self.e, LEDGER, "TRANSFER FROM SAV")), {"STRIP_TRANSFER"})
        rows = self.e.audit["obligations"]
        self.assertEqual(next(r for r in rows if r["tag"] == "OWNER_DRAW")["avg"], D(2000))
        self.assertEqual(
            self.e.audit["capacity"]["total_obligations"],
            sum(r["avg"] for r in rows if r["tag"] != "OWNER_DRAW" and not r["ambiguous"]),
        )

    def test_payroll_return_is_one_cured_t2_chain(self):
        a = [ev for ev in self.e.audit["returns"] if ev["cls"] == "A"]
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["tier"], a[0]["cured"][:1]), ("T2", "Y"))
        self.assertTrue(any(ev["cls"] == "B" for ev in self.e.audit["returns"]))

    def test_judgments_change_obligations(self):
        self.assertEqual(self.j.audit["obligations"][-1]["tag"], "AMBIGUOUS_CARD_PAYMENT")
        self.assertLess(self.j.audit["capacity"]["headline"], self.e.audit["capacity"]["headline"])

    def test_every_trigger_searched_and_every_strip_gated(self):
        a = self.j.audit
        triggers = {tr["trigger_id"] for p in a["positions"] for tr in p["triggers"]}
        self.assertEqual(triggers, {s["anchor"] for s in a["backward_searches"]})
        stripped = {t["txn_id"] for t in a["transactions"] if t["tag"] == "STRIP_FUNDING"}
        self.assertTrue(stripped)
        self.assertTrue(all(forward(self.j, i)["gate"] for i in stripped))


class TrustBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = run()
        cls.credit_q = q(cls.e, kind="credit")

    def reject(self, answers, msg):
        with self.assertRaisesRegex(uw.UWError, msg):
            run(judgments=with_judgments(self.e, answers))

    def test_fabricated_quote_rejected(self):
        self.reject(
            [dict(question_id=self.credit_q, tag="STRIP_FUNDING", evidence=dict(kind="bank_text", quote="MCA FUNDING"))],
            "quote not in transaction text",
        )

    def test_funding_without_evidence_rejected(self):
        self.reject([dict(question_id=self.credit_q, tag="STRIP_FUNDING")], "needs evidence")

    def test_document_must_state_amount(self):
        led = copy.deepcopy(LEDGER)
        led["documents"][0]["text"] = "CFG Merchant Solutions agreement funded via JKL Holdings."
        r = run(led)
        answer = dict(
            question_id=q(r, kind="credit"),
            tag="STRIP_FUNDING",
            evidence=dict(kind="document", doc_id="DOC-1", quote="funded via JKL Holdings"),
        )
        with self.assertRaisesRegex(uw.UWError, "does not state amount"):
            run(led, with_judgments(r, [answer]))

    def test_unknown_question_and_wrong_ledger_rejected(self):
        self.reject([dict(question_id="Q-credit-0000000000", tag="REV_WIRE")], "unknown question id")
        with self.assertRaisesRegex(uw.UWError, "ledger_sha256"):
            run(judgments=dict(ledger_sha256="x", answers=[]))

    def test_bad_tag_rejected(self):
        self.reject([dict(question_id=q(self.e, "SYSCO FOODS"), tag="REVENUE")], "bad debit tag")

    def test_termination_needs_verbatim_evidence(self):
        self.reject(
            [dict(question_id=q(self.e, "RAPIDFUND LLC"), tag="MCA", funder="RapidFund", terminated=dict(quote="PAID IN FULL"))],
            "closure quote not on a transaction of this position",
        )


class Scenarios(unittest.TestCase):
    def test_one_month_is_insufficient_data(self):
        self.assertTrue(run(truncate(LEDGER, "2026-06-30")).status.startswith("INSUFFICIENT DATA"))

    def test_provisional_cadence_is_u_with_stress_scenario(self):
        r = run(truncate(LEDGER, "2026-09-04"))
        cfg = pos(r, "CFG")[0]
        # V1.7: an unverified cadence gets a STRESS scenario only, so the position is U and out of the stack.
        self.assertEqual((cfg["cadence"], cfg["live_status"], cfg["monthly_cost"]), ("PROVISIONAL", "U", 0))
        self.assertEqual(cfg["scenario_cost"], D(900) * 20)

    def test_impossible_date_is_a_clear_error(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"][0]["date"] = "2026-13-40"
        with self.assertRaisesRegex(uw.UWError, "bad date '2026-13-40'"):
            run(led)

    def test_duplicate_rows_dropped_and_conflicts_fail(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"].append(dict(led["transactions"][0]))
        self.assertIn("1 duplicate transaction id(s) dropped", run(led).audit["accounts"][0]["notes"])
        led["transactions"][-1]["amount"] = "1.00"
        with self.assertRaisesRegex(uw.UWError, "same id, different content"):
            run(led)

    def test_same_funder_two_concurrent_contracts(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"] += [
            dict(t, txn_id=t["txn_id"] + "b", amount="200.00")
            for t in led["transactions"]
            if t["description"].startswith("RAPIDFUND") and t["date"] >= "2026-08-03"
        ]
        self.assertEqual(sorted(p["display"] for p in pos(run(led), "RAPIDFUND")), ["RAPIDFUND LLC #1", "RAPIDFUND LLC #2"])

    def test_integrity_suffix_follows_worst_account(self):
        led = copy.deepcopy(LEDGER)
        led["accounts"][1]["integrity"] = "Break"
        self.assertTrue(run(led).status.endswith("(PROVISIONAL — INTEGRITY FAIL)"))

    def test_terminated_position_drops_from_stack(self):
        led = copy.deepcopy(LEDGER)
        led["documents"].append(
            dict(doc_id="DOC-2", kind="payoff_letter", text="BlueOak ADV confirms the advance is paid in full as of 09/28/2026.")
        )
        r0 = run(led)
        answer = dict(
            question_id=q(r0, "BLUEOAK ADV"),
            tag="MCA",
            funder="BlueOak ADV",
            terminated=dict(kind="document", doc_id="DOC-2", quote="paid in full"),
        )
        r = run(led, with_judgments(r0, [answer]))
        self.assertEqual(cents(r.audit["capacity"]["live_stack"]), cents(r0.audit["capacity"]["live_stack"] - D(1200) * W))
        self.assertEqual(pos(r, "BLUEOAK")[0]["live_status"], "N")

    def test_silence_up_to_30_covered_bd_is_assumed_open(self):
        led = drop(LEDGER, "RAPIDFUND", "2026-09-09")  # last debit 09/09: 15 bd before 09/30
        p = pos(run(led), "RAPIDFUND")[0]
        self.assertEqual((p["live_status"], p["monthly_cost"]), ("Y", D(525) * 20))
        self.assertIn("Assumed open; collections absent 15 covered bd", p["status_basis"])
        p = pos(run(drop(LEDGER, "RAPIDFUND", "2026-08-14")), "RAPIDFUND")[0]  # 31 bd of silence
        self.assertEqual((p["live_status"], p["monthly_cost"], p["scenario_cost"]), ("U", 0, D(525) * 20))

    def test_closing_the_material_u_position_allows_yes(self):
        led = copy.deepcopy(LEDGER)
        led["documents"].append(dict(doc_id="DOC-3", kind="payoff_letter", text="SunCap Funding: balance paid in full 06/26/2026."))
        r0 = run(led)
        sun = q(r0, "SUNCAP FUNDING")
        answers = [a for a in known(r0, JUDGMENTS["answers"]) if a["question_id"] != sun] + [
            dict(question_id=sun, tag="MCA", funder="SunCap Funding",
                 terminated=dict(kind="document", doc_id="DOC-3", quote="paid in full"))
        ]
        r = run(led, with_judgments(r0, answers))
        self.assertEqual(pos(r, "SUNCAP")[0]["live_status"], "N")
        self.assertEqual(r.status, "YES")
        # Sign-off B2: the unanswered $30,000 wire stays out of BASIS and does not block YES.
        jkl = q(r0, kind="credit")
        r = run(led, with_judgments(r0, [a for a in answers if a["question_id"] != jkl]))
        self.assertEqual(tags(r, led, "JKL"), ["STRIP_UNRESOLVED"])
        self.assertEqual(r.status, "YES")
        self.assertTrue(any(x["kind"] == "unresolved credits" for x in r.audit["capacity"]["uncertainty"]))

    def test_no_stands_when_uncertainty_cannot_reverse_it(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"] += [
            dict(t, txn_id=t["txn_id"] + "x", amount="40000.00") for t in led["transactions"] if "OAKWOOD PROPERTY" in t["description"]
        ]
        r0 = run(led)
        r = run(led, with_judgments(r0, known(r0, JUDGMENTS["answers"])))
        self.assertEqual(r.audit["capacity"]["headline"], 0)
        self.assertEqual(pos(r, "SUNCAP")[0]["live_status"], "U")
        self.assertEqual(r.status, "NO")

    def test_report_gate_rejects_a_costed_u_row(self):
        r = run()
        row = next(l for l in r.report.splitlines() if "| U |" in l)
        bad = r.report.replace(row, row[: row.rindex("| —")] + "| $5 |")
        with self.assertRaisesRegex(uw.UWError, "U row must have Monthly Cost"):
            uw.report_gate(bad)

    def test_explicit_loan_text_strips_without_judgment(self):
        led = copy.deepcopy(LEDGER)
        for t in led["transactions"]:
            if "JKL" in t["description"]:
                t["description"] = "SBA LOAN PROCEEDS DISBURSEMENT"
        r = run(led)
        self.assertEqual(tags(r, led, "SBA LOAN"), ["STRIP_FUNDING"])
        self.assertEqual(forward(r, ids(led, "SBA LOAN")[0])["gate"]["kind"], "bank_text")


def add_debits(led, desc, amount, dates, prefix):
    led = copy.deepcopy(led)
    led["transactions"] += [
        dict(txn_id=f"{prefix}{i}", account_id="OP", date=d, amount=amount, direction="debit", description=desc, balance=None)
        for i, d in enumerate(dates)
    ]
    return led


def disposition(r, group):
    return next(d for d in r.audit["debit_dispositions"] if d["group"] == group)


class V17Batch2(unittest.TestCase):
    """V1.7 debit-first sweep, WATCH rows, position identity, expanded windows, evidence, completeness."""

    def test_unanswered_finance_payee_is_a_watch_row(self):
        led = add_debits(LEDGER, "ACME CAPITAL GROUP ACH DEBIT", "750.00", ["2026-07-06", "2026-07-20"], "AC")
        r = run(led)
        w = pos(r, "ACME CAPITAL GROUP")[0]
        self.assertEqual((w["watch"], w["live_status"], w["evidence"], w["monthly_cost"]), (True, "U", "UNKNOWN", 0))
        self.assertIn("WATCH: MCA identity unproved (D1 finance word in payee)", w["status_basis"])
        self.assertTrue(disposition(r, "ACME CAPITAL GROUP").get("disposition").startswith("WATCH"))
        # An answer settles it: OTHER removes the WATCH row.
        r2 = run(led, with_judgments(r, [dict(question_id=q(r, "ACME CAPITAL GROUP"), tag="OTHER")]))
        self.assertFalse(pos(r2, "ACME CAPITAL GROUP"))
        self.assertEqual(disposition(r2, "ACME CAPITAL GROUP")["disposition"], "NON-MCA OTHER (judgment)")

    def test_d3_same_amount_under_a_generic_descriptor(self):
        led = add_debits(LEDGER, "ACH DEBIT WEB PMT 88213", "525.00", ["2026-09-08", "2026-09-15", "2026-09-22"], "G")
        r = run(led)
        w = next(p for p in r.audit["positions"] if p["watch"])
        self.assertEqual(w["display"], "Unknown MCA-style #1")
        self.assertIn("D3 same amount $525 as RAPIDFUND LLC", w["status_basis"])

    def test_same_funder_name_alone_does_not_merge_overlapping_groups(self):
        led = add_debits(LEDGER, "RAPID FUND SERVICING", "300.00", ["2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"], "RS")
        r0 = run(led)
        answers = [
            dict(question_id=q(r0, "RAPID FUND SERVICING"), tag="MCA", funder="RapidFund LLC"),
            dict(question_id=q(r0, "RAPIDFUND LLC"), tag="MCA", funder="RapidFund LLC"),
        ]
        r = run(led, with_judgments(r0, answers))
        self.assertEqual(sorted(p["display"] for p in pos(r, "RAPIDFUND")), ["RAPIDFUND LLC #1", "RAPIDFUND LLC #2"])

    def test_descriptor_change_with_continuity_merges(self):
        led = copy.deepcopy(LEDGER)
        for t in led["transactions"]:
            if t["description"].startswith("BLUEOAK") and t["date"] >= "2026-09-01":
                t["description"] = "BLUE OAK SERVICING ACH"
        r0 = run(led)
        answers = [
            dict(question_id=q(r0, "BLUEOAK ADV"), tag="MCA", funder="BlueOak ADV"),
            dict(question_id=q(r0, "BLUE OAK SERVICING"), tag="MCA", funder="BlueOak ADV"),
        ]
        p = pos(run(led, with_judgments(r0, answers)), "BLUEOAK")
        self.assertEqual(len(p), 1)
        ev = [e for e in p[0]["events"] if e["kind"] == "DESCRIPTOR CHANGE"]
        self.assertEqual(ev[0]["detail"], "sequential continuity")

    def test_expanded_window_lists_out_of_window_credit_without_attaching(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"].append(
            dict(txn_id="X1", account_id="OP", date="2026-07-08", amount="40000.00", direction="credit",
                 description="WIRE IN RAPIDFUND LLC REF 55400", balance=None)
        )
        r = run(led)
        s = next(s for s in r.audit["backward_searches"] if s["anchor"] == pos(r, "RAPIDFUND")[0]["triggers"][-1]["trigger_id"])
        self.assertIn("X1", [c["txn_id"] for c in s["expanded"]])
        self.assertTrue(s["expanded_outcome"].startswith("INVESTIGATE"))
        self.assertEqual(pos(r, "RAPIDFUND")[0]["fundings"][-1]["credit_amount"], D(40000))
        self.assertEqual(pos(r, "RAPIDFUND")[0]["fundings"][-1]["credit"], ids(LEDGER, "WIRE IN RAPIDFUND")[0])

    def test_monthly_cadence_costs_one_payment(self):
        led = add_debits(LEDGER, "NORTHSTAR FUNDING ACH", "2000.00", ["2026-06-15", "2026-07-15", "2026-08-14", "2026-09-15"], "NS")
        p = pos(run(led), "NORTHSTAR FUNDING")[0]
        self.assertEqual((p["cadence"], p["live_status"], p["monthly_cost"]), ("monthly", "Y", D(2000)))

    def test_credit_dispositions_and_evidence_levels(self):
        e, j = run(), run(judgments=JUDGMENTS)
        jkl = ids(LEDGER, "JKL")[0]
        self.assertEqual(forward(e, jkl)["v17_disposition"], "UNRESOLVED")
        self.assertEqual((forward(j, jkl)["v17_disposition"], forward(j, jkl)["evidence"]), ("ATTACHED", "CORROBORATED"))
        self.assertEqual(pos(j, "RAPIDFUND")[0]["evidence"], "CORROBORATED")

    def test_completeness_metrics_count_every_cleared_row(self):
        r = run()
        c = r.audit["completeness"]
        tx = {t["txn_id"]: t for t in LEDGER["transactions"]}
        returned = {t["txn_id"] for t in r.audit["transactions"] if t["returned_by"]}
        self.assertEqual(c["debits_scanned"], sum(t["direction"] == "debit" and i not in returned for i, t in tx.items()))
        self.assertEqual(c["positions"] + c["watch"], len(r.audit["positions"]))
        self.assertIn("every nominated debit group has a disposition; no debit in two positions", r.audit["self_checks"])


def add_rows(led, rows, prefix):
    led = copy.deepcopy(led)
    led["transactions"] += [
        dict(txn_id=f"{prefix}{i}", account_id=acct, date=d, amount=amt, direction=dr, description=desc, balance=None)
        for i, (acct, d, amt, dr, desc) in enumerate(rows)
    ]
    return led


class V17Batch3(unittest.TestCase):
    """V1.7 accounts, coverage, commingling, missing-account requests, UNKNOWN returns, report checker."""

    def transfers(self, amount):
        months = ["2026-06-10", "2026-07-10", "2026-08-10", "2026-09-10"]
        rows = [("OP", d, amount, "debit", "ONLINE TRANSFER TO CHK ...4455") for d in months]
        rows.append(("OP", "2026-08-20", "100.00", "credit", "ONLINE TRANSFER FROM CHK ...4455"))
        return add_rows(LEDGER, rows, "TR")

    def test_material_unprovided_account_blocks_the_verdict(self):
        r = run(self.transfers("5000.00"))
        req = r.audit["account_requests"][0]
        self.assertEqual((req["account"], req["kind"], req["material"]), ("...4455", "VERIFY OWNERSHIP", True))
        self.assertTrue(r.status.startswith("INSUFFICIENT DATA"))
        self.assertIn("coverage: unprovided account ...4455", r.audit["capacity"]["binding"])
        self.assertIn("- **Additional Accounts to Request:** VERIFY OWNERSHIP; 1) ...4455", r.report)

    def test_small_unprovided_account_is_listed_without_blocking(self):
        r = run(self.transfers("50.00"))
        self.assertFalse(r.audit["account_requests"][0]["material"])
        self.assertEqual(r.audit["capacity"]["coverage_block"], [])

    def test_supplied_account_transfer_is_not_a_request(self):
        self.assertIn("- **Additional Accounts to Request:** COMPLETE OBSERVED", run().report)

    def test_transfer_to_credit_line_is_debt_service(self):
        led = add_rows(LEDGER, [("OP", "2026-07-15", "800.00", "debit", "ONLINE TRANSFER TO NST CREDIT LINE 6298")], "CL")
        r = run(led)
        self.assertEqual(tags(r, led, "NST CREDIT LINE"), ["DEBT_SERVICE"])
        self.assertTrue(r.audit["account_requests"][0]["financing"])

    def test_owner_draws_are_confirmed_commingling(self):
        c = run().audit["commingling"]
        self.assertEqual((c["status"], c["confirmed"], c["confirmed_amount"]), ("Present — Low", 4, D(8000)))
        self.assertIn("Commingling Status: Present — Low; 4 confirmed item(s), $8,000", run().report)

    def test_commingling_severity_thresholds(self):
        led = add_rows(LEDGER, [("OP", f"2026-07-{d:02d}", "100.00", "debit", "ONLINE TRANSFER TO JANE DOE") for d in range(6, 17)], "OW")
        c = run(led).audit["commingling"]
        self.assertEqual(c["worst"]["month"], "2026-07")
        self.assertEqual((c["worst"]["count"], c["status"]), (12, "Present — High"))  # 11 new + the July draw

    def test_unreadable_statement_blocks_and_documents_do_not(self):
        led = copy.deepcopy(LEDGER)
        led["sources_unread"] = [dict(name="OP-202610.pdf", reason="Exparsed status needs-ocr", statement=True)]
        r = run(led)
        self.assertIn("coverage: unreadable statement OP-202610.pdf", r.audit["capacity"]["binding"])
        self.assertIn("Unreadable: OP-202610.pdf (Exparsed status needs-ocr)", r.report)
        led["sources_unread"] = [dict(name="application.pdf", reason="application; not a bank statement", statement=False)]
        r = run(led)
        self.assertEqual(r.audit["capacity"]["coverage_block"], [])
        self.assertIn("Not a statement: application.pdf", r.report)

    def test_union_of_accounts_cannot_hide_a_short_material_account(self):
        led = copy.deepcopy(LEDGER)
        op = next(a for a in led["accounts"] if a["account_id"] == "OP")
        op["statements"] = [s if s["start"] != "2026-08-01" else dict(s, end="2026-08-09") for s in op["statements"]]
        led["transactions"] = [t for t in led["transactions"] if not (t["account_id"] == "OP" and "2026-08-10" <= t["date"] <= "2026-08-31")]
        r = run(led)
        self.assertFalse(month(r, "2026-08")["counted"])
        self.assertEqual(month(r, "2026-08")["days"], 31)  # SAV still covers the whole month
        self.assertTrue(r.audit["month_gaps"]["2026-08"][0].endswith(" 9 days"))
        self.assertIn("Aug-26 not counted", r.report)

    def test_cycle_statements_still_use_calendar_months(self):
        led = copy.deepcopy(LEDGER)
        for a in led["accounts"]:
            a["statements"] = [dict(start="2026-06-01", end="2026-06-14"), dict(start="2026-06-15", end="2026-07-14"),
                               dict(start="2026-07-15", end="2026-08-14"), dict(start="2026-08-15", end="2026-09-14"),
                               dict(start="2026-09-15", end="2026-09-30")]
        r, base = run(led), run()
        self.assertEqual([m["key"] for m in r.audit["months"]], [m["key"] for m in base.audit["months"]])
        self.assertEqual([m["true"] for m in r.audit["months"]], [m["true"] for m in base.audit["months"]])

    def test_unpaired_return_credit_is_class_unknown(self):
        led = add_rows(LEDGER, [("OP", "2026-08-19", "612.00", "credit", "RETURN ITEM R01 ACME SUPPLY")], "RU")
        ev = [e for e in run(led).audit["returns"] if e["cls"] == "UNKNOWN"]
        self.assertEqual((len(ev), ev[0]["tier"], ev[0]["cured"]), (1, "n/a", "n/a"))

    def test_checker_policy_numbers_match_the_engine(self):
        # The checker keeps its own copy so it stays a separate check; this catches the two drifting apart.
        spec = importlib.util.spec_from_file_location("chk", ROOT / "checker" / "validate_report.py")
        chk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(chk)
        names = ("HOLDBACK_SHARE", "BUSINESS_DAYS_PER_MONTH", "WEEKS_PER_MONTH", "WORST_ORDER")
        self.assertEqual([getattr(chk, n) for n in names], [getattr(uw, n) for n in names])

    def test_checker_needs_both_v17_lines_once_and_in_order(self):
        rep = run().report
        line = next(l for l in rep.splitlines() if l.startswith("- **Commingling:**"))
        with self.assertRaisesRegex(uw.UWError, "exactly once"):
            uw.report_gate(rep.replace(line + "\n", ""))
        with self.assertRaisesRegex(uw.UWError, "exactly once"):
            uw.report_gate(rep.replace(line, line + "\n" + line))
        with self.assertRaisesRegex(uw.UWError, "no valid status"):
            uw.report_gate(rep.replace("Commingling Status: Present — Low", "Commingling Status: Some"))


class SignOffB18(unittest.TestCase):
    """Sign-off B18 (2026-11-06): a missing or unreadable statement blocks YES only, as V1.7 section 9 says."""

    def no_ledger(self):
        # Rent tripled: HEADLINE is 0 with the saved answers (see test_no_stands_when_uncertainty_cannot_reverse_it).
        led = copy.deepcopy(LEDGER)
        led["transactions"] += [
            dict(t, txn_id=t["txn_id"] + "x", amount="40000.00") for t in led["transactions"] if "OAKWOOD PROPERTY" in t["description"]
        ]
        return led

    def answered(self, led):
        r0 = run(led)
        return run(led, with_judgments(r0, known(r0, JUDGMENTS["answers"])))

    def test_material_missing_account_leaves_a_no_standing(self):
        months = ["2026-06-10", "2026-07-10", "2026-08-10", "2026-09-10"]
        led = add_rows(self.no_ledger(), [("OP", d, "5000.00", "debit", "ONLINE TRANSFER TO CHK ...4455") for d in months], "TR")
        r = self.answered(led)
        self.assertTrue(r.audit["account_requests"][0]["material"])
        self.assertEqual(r.status, "NO")
        self.assertIn("coverage: unprovided account ...4455", r.audit["capacity"]["binding"])
        self.assertIn("- **Additional Accounts to Request:** REQUEST REQUIRED; 1) ...4455", r.report)

    def test_unreadable_statement_leaves_a_no_standing(self):
        led = self.no_ledger()
        led["sources_unread"] = [dict(name="OP-202610.pdf", reason="Exparsed status needs-ocr", statement=True)]
        r = self.answered(led)
        self.assertEqual(r.status, "NO")
        self.assertIn("coverage: unreadable statement OP-202610.pdf", r.audit["capacity"]["binding"])


class CreditCoverage(unittest.TestCase):
    """V1.7 C2 and A2: new senders on every rail are candidates; every cleared credit gets a disposition."""

    def question_for(self, r, txn_id):
        return next((x for x in r.questions["questions"] if x["type"] == "credit" and txn_id in x["txn_ids"]), None)

    def test_new_ach_sender_is_a_funding_candidate(self):
        led = add_rows(LEDGER, [("OP", "2026-07-14", "900.00", "credit", "ACH CREDIT NORTHWIND HOLDINGS")], "NW")
        q = self.question_for(run(led), "NW0")
        self.assertIsNotNone(q)
        self.assertIn("new sender (ACH, transfer, deposit or check)", q["why"])

    def test_established_customer_is_not_a_candidate(self):
        rows = [("OP", f"2026-0{m}-15", "900.00", "credit", "ACH CREDIT NORTHWIND HOLDINGS") for m in (6, 7, 8)]
        self.assertIsNone(self.question_for(run(add_rows(LEDGER, rows, "NW")), "NW0"))

    def test_every_cleared_credit_has_one_disposition(self):
        r = run(None, JUDGMENTS)
        returned = {t["txn_id"] for t in r.audit["transactions"] if t.get("returned_by")}
        cleared = [t["txn_id"] for t in LEDGER["transactions"] if t["direction"] == "credit" and t["txn_id"] not in returned]
        got = {d["txn_id"]: d["disposition"] for d in r.audit["credit_dispositions"]}
        self.assertEqual(sorted(got), sorted(cleared))
        self.assertEqual(len(r.audit["credit_dispositions"]), len(cleared))
        by_desc = {t["txn_id"]: t["description"] for t in LEDGER["transactions"]}
        square = next(i for i in cleared if by_desc[i].startswith("SQUARE INC DEP"))
        self.assertEqual(got[square], "CUSTOMER_SUPPORTED")
        self.assertIn("ATTACHED", got.values())
        self.assertLessEqual(set(got.values()), {"ATTACHED", "FINANCING_UNATTACHED", "COMPETING", "CUSTOMER_SUPPORTED", "OTHER_SUPPORTED", "UNRESOLVED"})


def business_days(start, end):
    cal = uw.Cal(LEDGER["holidays"])
    d, out = date.fromisoformat(start), []
    while d <= date.fromisoformat(end):
        if cal.is_bd(d):
            out.append(d.isoformat())
        d = date.fromordinal(d.toordinal() + 1)
    return out


class DebitSide(unittest.TestCase):
    """V1.7 D8, M14, D11 (open item 7, debit-side batch)."""

    def daily(self, name, start, end, amount, doubles=()):
        rows = [("OP", d, amount, "debit", f"{name} ACH DEBIT") for d in business_days(start, end)]
        rows += [("OP", d, amount, "debit", f"{name} ACH DEBIT") for d in doubles]
        return rows

    def test_sustained_same_amount_doubles_are_two_positions(self):
        days = business_days("2026-07-01", "2026-09-30")
        led = add_rows(LEDGER, self.daily("NOVA CAPITAL", "2026-07-01", "2026-09-30", "250.00", doubles=days[-20:]), "NV")
        self.assertEqual(len(pos(run(led), "NOVA CAPITAL")), 2)

    def test_isolated_same_amount_doubles_are_catch_up(self):
        # Doubles the day after each holiday: one position, as on the real ledger.
        led = add_rows(LEDGER, self.daily("NOVA CAPITAL", "2026-06-01", "2026-09-30", "250.00",
                                          doubles=["2026-06-22", "2026-07-06", "2026-09-08"]), "NV")
        self.assertEqual(len(pos(run(led), "NOVA CAPITAL")), 1)

    def test_restart_within_ten_business_days_is_a_probable_renewal(self):
        rows = self.daily("NOVA CAPITAL", "2026-06-01", "2026-07-31", "250.00")
        rows += self.daily("NOVA CAPITAL", "2026-08-10", "2026-09-30", "300.00")  # 5 bd gap
        p = pos(run(add_rows(LEDGER, rows, "NV")), "NOVA CAPITAL")
        self.assertEqual(len(p), 1)
        self.assertIn("PROBABLE RENEWAL", [e["kind"] for e in p[0]["events"]])

    def test_restart_after_a_long_gap_is_not_called_a_renewal(self):
        rows = self.daily("NOVA CAPITAL", "2026-06-01", "2026-07-15", "250.00")
        rows += self.daily("NOVA CAPITAL", "2026-08-17", "2026-09-30", "250.00")  # 22 bd gap
        p = pos(run(add_rows(LEDGER, rows, "NV")), "NOVA CAPITAL")
        kinds = [e["kind"] for x in p for e in x["events"]]
        self.assertNotIn("PROBABLE RENEWAL", kinds)

    def test_variable_remittance_reports_an_adverse_scenario(self):
        june, later = business_days("2026-06-01", "2026-06-30"), business_days("2026-07-01", "2026-09-30")
        rows = [("OP", d, "400.00" if i % 2 == 0 else "380.00", "debit", "NOVA CAPITAL ACH DEBIT") for i, d in enumerate(june)]
        rows += [("OP", d, "150.00" if i % 2 == 0 else "170.00", "debit", "NOVA CAPITAL ACH DEBIT") for i, d in enumerate(later)]
        led = add_rows(LEDGER, rows, "NV")
        r0 = run(led)
        qid = next(x["question_id"] for x in r0.questions["questions"] if x.get("descriptor", "").startswith("NOVA CAPITAL"))
        p = pos(run(led, with_judgments(r0, [dict(question_id=qid, tag="MCA", funder="Nova Capital")])), "NOVA CAPITAL")[0]
        self.assertEqual((p["cadence"], p["live_status"]), ("VARIABLE", "Y"))
        self.assertEqual(p["monthly_cost"], D("3200.00"))  # last 20 bd of September
        self.assertEqual(p["adverse_cost"], D("7800.00"))  # 20 bd of June: 10 x $400 + 10 x $380
        self.assertTrue(any("adverse scenario $7,800/mo" in n for n in p["notes"]))


class Records(unittest.TestCase):
    """V1.7 R1, R3, R7, S3, S7 (open item 7, records batch): audit records only, no verdict change."""

    def test_transaction_record_carries_trace_id_sequence_and_source(self):
        desc = "ORIG CO NAME:ACME ORIG ID **318418 SEC:CCD TRACE# **704849 EED:260715"
        led = add_rows(LEDGER, [("OP", "2026-07-15", "120.00", "credit", desc)], "TR")
        led["transactions"][-1]["source_ref"] = "jul.pdf p2"
        rec = next(t for t in run(led).audit["transactions"] if t["txn_id"] == "TR0")
        self.assertEqual((rec["trace_id"], rec["orig_id"], rec["source_ref"]), ("**704849", "**318418", "jul.pdf p2"))
        self.assertIsInstance(rec["sequence"], int)

    def ledger_v1(self):
        return {
            "format": "ledger-v1",
            "computed": [],
            "files": [
                {
                    "name": "a.pdf",
                    "accountLast4": "9805",
                    "status": "verified",
                    "checks": [{"check": "balance", "result": "pass"}, {"check": "totals", "result": "fail"}],
                    "provenance": {"flags": []},
                    "period": {"start": "2026-06-01", "end": "2026-07-31"},
                    "columns": "date|section|amount|balance|page|description",
                    "rows": ["PENDING|pending|-5.00||1|(PENDING) ACME FEE"]
                    + [f"2026-0{m}-{d:02d}|dep|1000.00||1|ACH CREDIT ACME" for m in (6, 7) for d in range(1, 29)],
                }
            ],
        }

    def page(self, src):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        r = json.loads(exparsed_adapter.page_run(json.dumps(src)))
        self.assertTrue(r["ok"], r.get("error"))
        return r["audit"]

    def test_pending_rows_are_kept_as_non_cleared_observations(self):
        a = self.page(self.ledger_v1())
        self.assertEqual(a["pending_observations"],
                         [dict(account_id="9805", amount="-5.00", description="(PENDING) ACME FEE", source_ref="a.pdf p1 r1")])
        self.assertEqual(len(a["transactions"]), 56)

    def test_crosswalk_keeps_identical_rows_and_names_their_source_rows(self):
        src = self.ledger_v1()
        src["files"][0]["rows"].append("2026-07-28|dep|1000.00||2|ACH CREDIT ACME")  # printed twice on 07/28
        src["files"][0]["rowsOmitted"] = "3 rows on dates covered by b.pdf (same transactions; omitted)"
        a = self.page(src)
        g = a["duplicate_crosswalk"]
        self.assertEqual([len(x["txn_ids"]) for x in g], [2])
        self.assertEqual(sorted(x["source_ref"] for x in a["transactions"] if x["txn_id"] in g[0]["txn_ids"]),
                         ["a.pdf p1 r57", "a.pdf p2 r58"])
        self.assertEqual(a["sources"][0]["rows_omitted"], "3 rows on dates covered by b.pdf (same transactions; omitted)")

    def test_unresolved_items_become_exception_records(self):
        a = run().audit
        ex = a["exceptions"]
        u = next(x for x in ex if x["type"] == "U POSITION")
        suncap = pos(run(), "SUNCAP")[0]
        self.assertEqual(u["source_tx_ids"], suncap["debit_ids"])
        self.assertEqual(u["severity"], "MATERIAL")
        self.assertIn("HEADLINE $5,577", u["possible_effect_on_capacity"])  # sample: $11,577 falls by SunCap's $6,000 scenario
        credit = next(x for x in ex if x["type"] == "UNRESOLVED CREDITS")
        self.assertEqual(credit["severity"], "MATERIAL")
        self.assertEqual(sum(x["type"] == "OPEN QUESTION" for x in ex), 9)
        self.assertLessEqual({k for x in ex for k in x},
                             {"type", "source_tx_ids", "why_unresolved", "possible_effect_on_capacity", "required_evidence", "severity"})

    def test_every_file_has_a_source_record(self):
        src = self.ledger_v1()
        src["files"].append({"name": "scan.pdf", "status": "needs-ocr", "rows": []})
        a = self.page(src)
        self.assertEqual(a["sources"], [
            dict(source_id="a.pdf", account_id="9805", period=dict(start="2026-06-01", end="2026-07-31"),
                 extraction_status="verified", checks_passed=["balance"], checks_failed=["totals"],
                 rows=56, pending=1, zero=0, flags=[], rows_omitted=None),
            dict(source_id="scan.pdf", account_id=None, period=None, extraction_status="needs-ocr",
                 checks_passed=[], checks_failed=[], rows=0, pending=0, zero=0, flags=[], rows_omitted=None),
        ])


class StageManifest(unittest.TestCase):
    """V3 handoff: one manifest entry per V1.7 execution-order stage, with hashes, counts and review state."""

    NAMES = [
        "inventory/routes/coverage", "normalize/dedupe/reconcile", "account links and provisional tags",
        "debit-first MCA discovery", "credit-first funding discovery", "event/renewal discovery",
        "candidate-pair reconciliation", "finalized tags and position status",
        "revenue, costs, returns, liquidity, capacity", "MCA completeness audit", "render and validate ten tables",
    ]

    def test_eleven_stages_in_policy_order_with_review_state(self):
        st = run().audit["stages"]
        self.assertEqual([s["name"] for s in st], self.NAMES)
        by = {s["stage"]: s for s in st}
        self.assertEqual(by[8]["status"], "NEEDS_REVIEW")  # SunCap is a material U position on the sample
        self.assertIn("U POSITION", by[8]["unresolved"])
        self.assertEqual((by[6]["status"], by[11]["status"]), ("COMPLETE", "COMPLETE"))
        self.assertTrue(all(s["status"] in ("COMPLETE", "NEEDS_REVIEW") for s in st))

    def test_hashes_chain_from_the_ledger_and_track_policy(self):
        a = run().audit
        st = a["stages"]
        self.assertEqual(st[0]["input_hash"], a["ledger_sha256"])
        self.assertEqual([s["input_hash"] for s in st[1:]], [s["output_hash"] for s in st[:-1]])
        self.assertEqual(st, run().audit["stages"])  # same ledger, same manifest
        with mock.patch.object(uw, "HOLDBACK_SHARE", D("0.50")):
            self.assertNotEqual(uw.policy_hash(), st[0]["policy_hash"])
        answered = run(None, JUDGMENTS).audit["stages"]
        self.assertEqual(answered[0]["output_hash"], st[0]["output_hash"])  # answers do not touch inventory
        self.assertNotEqual(answered[2]["output_hash"], st[2]["output_hash"])  # they re-tag transactions


class V17Batch4(unittest.TestCase):
    """V1.7 fixes from the 2026-11 spec review: peak floor, closure evidence, return tiers, wires, windows, binding."""

    def bigcap(self):
        # A $3,000 daily MCA: 3 debits in the week of 08/31, 4 in the Labor Day week of 09/07.
        days = ["2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
        return run(add_debits(LEDGER, "BIGCAP FUNDING ACH DEBIT", "3000.00", days, "BIG"))

    def test_holiday_week_is_not_eligible_for_peak(self):
        # K2: the week of 09/07 has 4 business days (Labor Day), so its $12,000 of BIGCAP cannot be the peak.
        self.assertNotEqual(self.bigcap().audit["peak_week"]["monday"].isoformat(), "2026-09-07")

    def test_report_peak_is_floored_at_modeled_current(self):
        # K3: Report Peak Weekly = max(observed, stack/(52/12)); the drop is never negative.
        r = self.bigcap()
        cw = r.audit["capacity"]["live_stack"] / W
        self.assertLess(r.audit["peak_week"]["weekly"], cw)
        row = next(l for l in r.report.splitlines() if l.startswith("| Peak Handled"))
        self.assertIn("modeled current floor", row)
        self.assertIn(uw.usd(cw), row)
        drop_row = next(l for l in r.report.splitlines() if l.startswith("| Drop Since Peak"))
        self.assertNotIn("-", drop_row.split("|")[2])

    def test_live_window_is_ten_business_days_with_the_end_day(self):
        # P5: 09/17 to 09/30 is the window; a last debit on 09/16 is the 11th business day back.
        p = pos(run(drop(LEDGER, "RAPIDFUND", "2026-09-16")), "RAPIDFUND")[0]
        self.assertIn("Assumed open; collections absent 10 covered bd", p["status_basis"])
        p = pos(run(drop(LEDGER, "RAPIDFUND", "2026-09-17")), "RAPIDFUND")[0]
        self.assertTrue(p["status_basis"].startswith("Observed"))

    def test_bank_closure_text_must_belong_to_the_position(self):
        led = add_rows(LEDGER, [("OP", "2026-08-20", "1.00", "credit", "SYSCO FOODS PAID IN FULL"),
                                ("OP", "2026-09-30", "1.00", "credit", "RAPIDFUND LLC PAYOFF PAID IN FULL")], "CL")
        r0 = run(led)
        ans = lambda quote: [dict(question_id=q(r0, "RAPIDFUND LLC"), tag="MCA", funder="RapidFund",
                                  terminated=dict(quote=quote))]
        with self.assertRaisesRegex(uw.UWError, "closure quote not on a transaction"):
            run(led, with_judgments(r0, ans("SYSCO FOODS PAID")))
        self.assertEqual(pos(run(led, with_judgments(r0, ans("PAYOFF PAID IN FULL"))), "RAPIDFUND")[0]["live_status"], "N")

    def test_collections_after_bank_closure_text_keep_the_position_open(self):
        led = add_rows(LEDGER, [("OP", "2026-09-01", "1.00", "credit", "RAPIDFUND LLC PAYOFF QUOTE PAID IN FULL")], "CL")
        r0 = run(led)
        a = [dict(question_id=q(r0, "RAPIDFUND LLC"), tag="MCA", funder="RapidFund", terminated=dict(quote="PAID IN FULL"))]
        p = pos(run(led, with_judgments(r0, a)), "RAPIDFUND")[0]
        self.assertEqual(p["live_status"], "Y")
        self.assertIn("closure text 09/01/26 ignored", p["status_basis"])

    def returned(self, desc, code, then=None):
        rows = [("OP", "2026-08-04", "800.00", "debit", desc), ("OP", "2026-08-05", "800.00", "credit", f"{desc} RETURN {code}")]
        if then:
            rows.append(("OP", "2026-08-06", "800.00", "debit", desc))
        led = add_rows(LEDGER, rows, "RT")
        for t in led["transactions"]:
            if t["txn_id"].startswith("RT"):
                t["balance"] = "5000.00"
        return next(ev for ev in run(led).audit["returns"] if ev["who"].startswith(desc[:6]))

    def test_finance_return_is_t2_whatever_the_code(self):
        # K7: an involuntary finance return is T2, R01/R09 included but not required.
        self.assertEqual(self.returned("SBA EIDL LOAN PMT", "R02")["tier"], "T2")

    def test_loan_stop_pay_is_never_cured(self):
        # K8: stop-pay MCA/loan never cured, even with a cleared re-presentment.
        ev = self.returned("SBA EIDL LOAN PMT", "R08", then=True)
        self.assertEqual((ev["tier"], ev["cured"][:1]), ("T1", "N"))

    def test_plain_wire_gets_no_finance_points(self):
        # M8: +2 needs explicit finance terms or a finance-origin wire.
        led = add_rows(LEDGER, [("OP", "2026-07-30", "9000.00", "credit", "WIRE IN ORIG ACME CUSTOMER REF 9")], "WR")
        cands = [c for b in run(led).audit["backward_searches"] for c in b["candidates"] if c["txn_id"] == "WR0"]
        self.assertTrue(cands)
        self.assertFalse(any("financ" in x for c in cands for x in c["basis"]))

    def test_binding_names_the_conservative_room(self):
        # V10: Conservative binding is Room C if C<=D, else Room D and the worst month, stated every time.
        self.assertIn("; CONSERVATIVE: Room ", run().audit["capacity"]["binding"])


class RealDataShapes(unittest.TestCase):
    """Behaviors found on the first real Exparsed ledger (27 Oct 2026), rebuilt on synthetic rows."""

    def rapid_rows(self, led):
        return [t for t in led["transactions"] if t["description"].startswith("RAPIDFUND")]

    def test_orig_co_name_keys_on_payee(self):
        self.assertEqual(uw.norm("ORIG CO NAME:Forward Financin ORIG ID **948598 DESC DATE: CO ENTRY"), "FORWARD FINANCIN")

    def test_same_amount_doubles_are_catch_up_payments(self):
        led = copy.deepcopy(LEDGER)
        led["transactions"] += [
            dict(t, txn_id=t["txn_id"] + "c")
            for t in self.rapid_rows(led)
            if t["date"] in ("2026-08-04", "2026-08-11", "2026-08-18")
        ]
        self.assertEqual(len(pos(run(led), "RAPIDFUND")), 1)

    def test_share_of_sales_remittance_is_one_variable_position(self):
        led = copy.deepcopy(LEDGER)
        for i, t in enumerate(self.rapid_rows(led)):
            t["amount"] = f"{100 + (i * 37) % 400}.00"
            if i % 3 == 0:
                led["transactions"].append(dict(t, txn_id=t["txn_id"] + "v", amount=f"{20 + i % 50}.00"))
        r0 = run(led)
        self.assertFalse(pos(r0, "RAPIDFUND"))  # variable amounts are not MCA by default
        r = run(led, with_judgments(r0, [dict(question_id=q(r0, "RAPIDFUND LLC"), tag="MCA", funder="RapidFund")]))
        p = pos(r, "RAPIDFUND")
        self.assertEqual(len(p), 1)
        lo = uw.Cal(led["holidays"]).add(r.audit["data_end"], -20)
        by_id = {t["txn_id"]: t for t in led["transactions"]}
        recent = sum(D(by_id[i]["amount"]) for i in p[0]["cleared_ids"] if by_id[i]["date"] > lo.isoformat())
        self.assertEqual((p[0]["cadence"], p[0]["monthly_cost"]), ("VARIABLE", recent))

    def test_adapter_reads_ledger_v1(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        src = {
            "format": "ledger-v1",
            "computed": [],
            "files": [
                {
                    "name": "a.pdf",
                    "accountLast4": "9805",
                    "status": "verified",
                    "checks": [],
                    "provenance": {"flags": []},
                    "period": {"start": "2026-06-01", "end": "2026-06-30"},
                    "columns": "date|section|amount|balance|page|description|type",
                    "rows": [
                        "PENDING|pending|-5.00|90.00|1|(PENDING) X|Fee",
                        "2026-06-03|debit|-40.00|60.00|1|RENT|Rent",
                        "2026-06-02|credit|100.00|100.00|1|SQUARE|Deposit",
                    ],
                }
            ],
        }
        out = exparsed_adapter.convert(src, [])
        self.assertEqual(
            [(t["date"], t["direction"], t["amount"]) for t in out["transactions"]],
            [("2026-06-02", "credit", "100.00"), ("2026-06-03", "debit", "40.00")],
        )
        self.assertEqual(out["accounts"][0]["integrity"], "Pass")
        uw.underwrite(raw(out))

    def one_file_src(self, start, end):
        return {
            "format": "ledger-v1",
            "computed": [],
            "files": [
                {
                    "name": "y.pdf",
                    "accountLast4": "4321",
                    "status": "verified",
                    "checks": [],
                    "provenance": None,
                    "period": {"start": start, "end": end},
                    "columns": "date|section|amount|balance|page|description",
                    "rows": [f"{start}|dep|100.00|100.00|1|ACH CREDIT ACME"],
                }
            ],
        }

    def test_2027_federal_reserve_holidays_are_not_business_days(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        cal = uw.Cal(exparsed_adapter.convert(self.one_file_src("2027-01-01", "2027-12-31"), [])["holidays"])
        # Federal Reserve 2027: Sunday July 4 moves to Monday; Saturday June 19 and December 25 are not observed.
        closed = ["2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-07-05",
                  "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25"]
        self.assertEqual([d for d in closed if cal.is_bd(date.fromisoformat(d))], [])
        self.assertTrue(cal.is_bd(date(2027, 6, 18)) and cal.is_bd(date(2027, 12, 24)))

    def test_statement_in_a_year_without_holidays_is_a_clear_error(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        r = json.loads(exparsed_adapter.page_run(json.dumps(self.one_file_src("2027-12-01", "2028-01-31"))))
        self.assertEqual(r["ok"], False)
        self.assertIn("no Federal Reserve holidays for 2028", r["error"])

    def test_page_run_returns_an_error_when_the_engine_cannot_load(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        with mock.patch.dict(sys.modules, {"uw": None}):  # None makes `import uw` raise ImportError
            r = json.loads(exparsed_adapter.page_run(json.dumps(self.statement_src())))
        self.assertEqual(r["ok"], False)
        self.assertIn("engine did not load", r["error"])

    def statement_src(self, computed=()):
        # A sectioned statement: 6 columns, oldest first, no balances.
        rows = [f"2026-0{m}-{d:02d}|dep|1000.00||1|ACH CREDIT ACME" for m in (6, 7) for d in range(1, 29)]
        rows.append("2026-07-10|chk|-0.00||2|CHECK 101")
        return {
            "format": "ledger-v1",
            "computed": list(computed),
            "files": [
                {
                    "name": "s.pdf",
                    "accountLast4": "1234",
                    "status": "partial",
                    "checks": [],
                    "provenance": None,
                    "period": {"start": "2026-06-01", "end": "2026-07-31"},
                    "columns": "date|section|amount|balance|page|description",
                    "rows": rows,
                }
            ],
        }

    def test_page_run_reads_statement_rows_and_reports_errors(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        src = self.statement_src()
        r = json.loads(exparsed_adapter.page_run(json.dumps(src)))
        self.assertTrue(r["ok"], r.get("error"))
        self.assertTrue(r["status"].startswith("YES (UNVERIFIED DATA)"))
        self.assertIn("1 zero-amount row(s) excluded", r["report"])
        self.assertEqual(r["audit"]["report_gate"], "PASS")
        bad = json.loads(exparsed_adapter.page_run(json.dumps(src), json.dumps({"ledger_sha256": "x", "answers": []})))
        self.assertEqual((bad["ok"], "ledger_sha256" in bad["error"]), (False, True))
        src["files"][0]["rows"][0] = "2026-06-01|dep|abc||1|BROKEN"
        broken = json.loads(exparsed_adapter.page_run(json.dumps(src)))
        self.assertEqual(broken["ok"], False)
        self.assertRegex(broken["error"], r"^InvalidOperation: .*\(exparsed_adapter\.py:\d+\)$")

    def test_exparsed_computed_gross_is_cross_checked(self):
        sys.path.insert(0, str(ROOT / "adapter"))
        import exparsed_adapter

        months = [
            {"month": "2026-06", "partial": False, "grossInflows": 28000.00},
            {"month": "2026-07", "partial": False, "grossInflows": 27900.00},
        ]
        r = json.loads(exparsed_adapter.page_run(json.dumps(self.statement_src([{"account": "1234", "months": months}]))))
        check = r["audit"]["exparsed_crosscheck"]
        self.assertEqual((check["months_compared"], [m["month"] for m in check["mismatches"]]), (2, ["2026-07"]))
        self.assertIn("Gross credits Jul-26: engine $28,000.00, Exparsed computed $27,900.00", r["report"])


class PageEmbed(unittest.TestCase):
    def test_page_carries_current_engine_sources(self):
        sys.path.insert(0, str(ROOT))
        import embed

        page = embed.PAGE.read_text(encoding="utf-8")
        self.assertEqual(embed.embedded(page), embed.block(), "page copy is stale: run python underwriting/embed.py")


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
