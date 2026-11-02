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


def run(led=None, judgments=None):
    """underwrite() through its interface. It also runs the unchanged V2.2 report validator."""
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
        self.assertEqual(self.j.audit["legacy_report_gate"], "PASS")

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
            "quote not in transaction text",
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
            uw.legacy_gate(bad)

    def test_explicit_loan_text_strips_without_judgment(self):
        led = copy.deepcopy(LEDGER)
        for t in led["transactions"]:
            if "JKL" in t["description"]:
                t["description"] = "SBA LOAN PROCEEDS DISBURSEMENT"
        r = run(led)
        self.assertEqual(tags(r, led, "SBA LOAN"), ["STRIP_FUNDING"])
        self.assertEqual(forward(r, ids(led, "SBA LOAN")[0])["gate"]["kind"], "bank_text")


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
        self.assertEqual(r["audit"]["legacy_report_gate"], "PASS")
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
