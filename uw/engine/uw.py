#!/usr/bin/env python3
"""MCA capacity underwriting engine. Policy V2.2, engine V3.0.

Code computes every number in the report from ledger rows. The LLM answers
only the questions this engine writes to questions.json (prompt: prompts/judge.md).
Answers are checked here: enums, question IDs, ledger hash, and every evidence
quote must appear verbatim in a transaction description or a supplied document.

Usage:
  python engine/uw.py LEDGER.json --out DIR [--judgments JUDGMENTS.json]

Writes DIR/questions.json, DIR/audit.json, DIR/report.md. Exit 0 on success,
1 on bad input or a failed self-check, 2 on usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from itertools import groupby
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

D = Decimal
ENGINE_VERSION = "3.0"
POLICY_VERSION = "V2.2"

# Policy V2.2 parameters. Changing any value is a policy change: bump POLICY_VERSION.
BUSINESS_DAYS_PER_MONTH = D(20)
WEEKS_PER_MONTH = D("4.333")
BIWEEKS_PER_MONTH = D("2.167")
FULL_MONTH_DAYS = 18
LIVE_WINDOW_BD = 10
FUNDING_WINDOW_BD = 7
UNATTACHED_WINDOW_CAL = 14
SERIES_MIN_DEBITS = 3
SUSTAIN_PAYMENTS = 3
CHANGE_THRESHOLD = D("0.10")
CURE_WINDOW_BD = 2
REFI_GAP_BD = 10
PAYBACK_FACTOR = D("1.4")
HOLDBACK_SHARE = D("0.60")
FLIGHT_SHARE = D("0.30")
FLIGHT_DAYS = 2
RETURN_MATCH_BD = 5  # recredit must follow its debit within this many business days
CHAIN_GAP_BD = 10  # re-presentments within this gap belong to one attempt chain
TOP_STREAMS = 6

INTEGRITY = ("Pass", "Pass with flag", "Unverified", "Break")  # best to worst
WORST_ORDER = ("Break", "Unverified", "Pass with flag", "Pass")
SUFFIX = {
    "Pass": "",
    "Pass with flag": " (FLAGGED)",
    "Unverified": " (UNVERIFIED DATA)",
    "Break": " (PROVISIONAL — INTEGRITY FAIL)",
}
CREDIT_TAGS = (
    "REV_PROCESSOR",
    "REV_ACH",
    "REV_WIRE",
    "REV_DEPOSIT",
    "REV_PAYER",
    "STRIP_FUNDING",
    "STRIP_TRANSFER",
    "STRIP_REFUND",
    "STRIP_OWNER",
    "STRIP_RECREDIT",
)
DEBIT_TAGS = (
    "MCA",
    "PAYROLL",
    "OWNER_DRAW",
    "RENT",
    "UTILITIES",
    "INSURANCE",
    "TAX",
    "DEBT_SERVICE",
    "DIRECT_COST",
    "TRANSFER_OUT",
    "OTHER",
)
HARD_STRIP = {"STRIP_TRANSFER", "STRIP_REFUND", "STRIP_RECREDIT", "STRIP_OWNER"}
OBLIGATION_ROWS = [
    ("PAYROLL", "Payroll"),
    ("OWNER_DRAW", "Owner Draws"),
    ("RENT", "Rent"),
    ("UTILITIES", "Utilities"),
    ("INSURANCE", "Insurance"),
    ("TAX", "Taxes"),
    ("DEBT_SERVICE", "Non-MCA Debt Service"),
    ("DIRECT_COST", "Direct Costs"),
]
AMBIGUOUS_RE = re.compile(r"^AMBIGUOUS_[A-Z0-9_]{1,30}$")
CADENCE_FACTOR = {
    "daily": BUSINESS_DAYS_PER_MONTH,
    "weekly": WEEKS_PER_MONTH,
    "biweekly": BIWEEKS_PER_MONTH,
}


def rx(*alts):
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b")


# Descriptor rules. They tag provisionally; the LLM answers questions about what they cannot settle.
RECREDIT = rx(r"RETURN(?:ED)?", "REVERSAL", "REVERSED", "RECREDIT", r"R\d\d")
REFUND = rx("REFUND", r"CHARGEBACK REV\w*")
TRANSFER = rx("TRANSFER", "XFER", "TFR", "TRNSFR")
OD_XFER = rx("OD PROTECTION", "OVERDRAFT PROTECTION", "OVERDRAFT TRANSFER")
EXPLICIT_FIN = rx(
    "LOAN",
    "MCA",
    "FINANCING",
    r"DISBURSE\w*",
    r"(?:CASH|MERCHANT) ADVANCE",
    r"ADVANCE (?:FUNDING|PROCEEDS|DISB\w*)",
)
WIRE = rx("WIRE", "FEDWIRE", "WT")
PROCESSOR = rx(
    "SQUARE",
    "SQ",
    "STRIPE",
    "CLOVER",
    "FISERV",
    "WORLDPAY",
    "TOAST",
    "SHOPIFY",
    "PAYPAL",
    "HEARTLAND",
    "ELAVON",
    "TSYS",
    "BANKCARD",
    r"MERCH(?:ANT)? (?:DEP|SETTLE|BNKCD)\w*",
)
PAYER = rx(
    "TREAS",
    "SSA",
    "MEDICARE",
    "MEDICAID",
    "HCCLAIMPMT",
    "BCBS",
    "AETNA",
    "HUMANA",
    "CIGNA",
    "UNITEDHEALTH",
    "UHC",
)
DEPOSIT = rx(
    "DEPOSIT",
    "MOBILE",
    "CHECK",
    "BRANCH",
    "CASH",
    "REMOTE",
    "ZELLE",
    "VENMO",
    "CASH APP",
)
FEE = rx(
    "NSF",
    "OVERDRAFT FEE",
    "OD FEE",
    "RETURNED ITEM FEE",
    r"INSUFFICIENT FUNDS?",
    "OVERDRAFT ITEM FEE",
)
DEBIT_RULES = [
    (
        "PAYROLL",
        rx(
            "PAYROLL",
            "ADP",
            "GUSTO",
            "PAYCHEX",
            "PAYCOR",
            "RIPPLING",
            "TRINET",
            "JUSTWORKS",
        ),
    ),
    (
        "TAX",
        rx(
            "IRS",
            "USATAXPYMT",
            "EFTPS",
            "TAX",
            "DEPT OF REVENUE",
            "COMPTROLLER",
            "FRANCHISE TAX",
        ),
    ),
    (
        "INSURANCE",
        rx(
            "INSURANCE",
            "INS PREM",
            "GEICO",
            "PROGRESSIVE",
            "STATE FARM",
            "HISCOX",
            r"NEXT INSUR\w*",
            "ALLSTATE",
            "TRAVELERS",
        ),
    ),
    (
        "UTILITIES",
        rx(
            "ELECTRIC",
            "ENERGY",
            "WATER",
            "GAS CO",
            "COMCAST",
            "SPECTRUM",
            "XFINITY",
            "VERIZON",
            "AT&T",
            "T-MOBILE",
            r"UTILIT\w*",
            "CON ED",
            "PG&E",
        ),
    ),
    ("RENT", rx("RENT", "LEASE", "PROPERTY MGMT", "PROPERTY MANAGEMENT", "REALTY")),
    ("DEBT_SERVICE", rx("LOAN PMT", "LOAN PAYMENT", "MORTGAGE", "SBA", "AUTO LOAN")),
]
MCA_WORD = rx(
    "FUNDING",
    "FUND",
    "CAPITAL",
    "ADV",
    "ADVANCE",
    "MERCHANT",
    "LENDING",
    "FINANCIAL",
    "FINANCE",
    "RTR",
    r"FACTOR\w*",
)
LEVY = rx("LEVY", "LIEN", r"GARNISH\w*")
T1 = rx(
    "STOP PAY",
    "STOP PAYMENT",
    "UNAUTHORIZED",
    "AUTH REVOKED",
    "NOT AUTH",
    "ACH BLOCK",
    "POSITIVE PAY",
    "R05",
    "R07",
    "R08",
    "R10",
    "R29",
)
T2_FINANCE_CODES = rx("R01", "R09")
RETURN_CODE = re.compile(r"\bR\d\d\b")
NOISE = set(
    "ACH DEBIT CREDIT PPD CCD WEB TEL POS PURCHASE PMT PAYMENT ID REF TRN CO ENTRY DESCR IND ORIG DES "
    "CHECKCARD ONLINE ELECTRONIC WITHDRAWAL EPAY EPAYMENT RECURRING XXXXXX".split()
)
GENERIC = set(
    "LLC INC CORP CO CAPITAL FUNDING FUND GROUP FINANCIAL FINANCE ADV ADVANCE MERCHANT SOLUTIONS "
    "SERVICES PARTNERS BUSINESS LENDING HOLDINGS THE OF AND USA".split()
)


class UWError(Exception):
    pass


def require(ok, msg):
    if not ok:
        raise UWError(msg)


def norm(desc):
    """Payee key: uppercase letters only, ACH noise words and reference numbers removed."""
    words = [
        w
        for w in re.sub(r"[^A-Z& ]", " ", desc.upper()).split()
        if w not in NOISE and len(w) > 1
    ]
    return " ".join(words[:4]) or "UNKNOWN"


def funder_tokens(name):
    return {
        w
        for w in re.sub(r"[^A-Z ]", " ", name.upper()).split()
        if len(w) >= 3 and w not in GENERIC
    }


def has_token(text, tokens):
    return any(re.search(rf"\b{re.escape(tok)}\b", text.upper()) for tok in tokens)


def qid(kind, ids):
    return f"Q-{kind}-" + hashlib.sha1("|".join(sorted(ids)).encode()).hexdigest()[:10]


class Cal:
    """Business days: Monday to Friday minus supplied holidays."""

    def __init__(self, holidays):
        self.h = {date.fromisoformat(x) for x in holidays}

    def is_bd(self, d):
        return d.weekday() < 5 and d not in self.h

    def add(self, d, n):
        step = 1 if n >= 0 else -1
        while n:
            d += timedelta(step)
            if self.is_bd(d):
                n -= step
        return d

    def diff(self, a, b):
        """Business days after a, up to and including b. 0 when b <= a."""
        n, d = 0, a
        while d < b:
            d += timedelta(1)
            n += self.is_bd(d)
        return n


@dataclass
class Txn:
    id: str
    acct: str
    date: date
    amt: Decimal
    dir: str
    desc: str
    bal: Decimal | None
    src: str
    seq: int
    norm: str = ""
    tag: str = ""
    tag_source: str = "rule"
    flags: list = field(default_factory=list)
    returned_by: str | None = None
    returns: str | None = None

    @property
    def month(self):
        return (self.date.year, self.date.month)


@dataclass
class Position:
    pid: str
    funder: str
    group: str
    txns: list
    cleared: list
    display: str = ""
    cadence: str = "PROVISIONAL"
    level: Decimal = D(0)
    cost: Decimal = D(0)
    status: str = ""
    prefile: bool = False
    live: bool = False
    terminated: str = ""
    events: list = field(default_factory=list)
    triggers: list = field(default_factory=list)
    fundings: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def usd(x):
    if x is None:
        return "—"
    q = x.quantize(D(1), ROUND_HALF_UP)
    if q == 0:
        return "$0"
    return f"-${-q:,}" if q < 0 else f"${q:,}"


def pct(x):
    return "—" if x is None else f"{(x * 100).quantize(D('0.1'), ROUND_HALF_UP)}%"


def mdy(d):
    return d.strftime("%m/%d/%y")


def mon(k):
    return date(k[0], k[1], 1).strftime("%b-%y")


def mean(xs):
    return sum(xs, D(0)) / len(xs) if xs else None


def gap_class(bd):
    return (
        "daily"
        if bd <= 2
        else "weekly" if bd <= 7 else "biweekly" if bd <= 12 else "irregular"
    )


def runs(items, same):
    out = []
    for x in items:
        if out and same(out[-1][0], x):
            out[-1].append(x)
        else:
            out.append([x])
    return out


def changed(a, b):
    return abs(b - a) > a * CHANGE_THRESHOLD


def split_concurrent(ts):
    """Same payee debited twice on one day means concurrent contracts.

    Tracks open only when a day has more debits than open tracks. Each debit joins the
    nearest-amount track not yet used that day, so a level change stays inside its track.
    """
    if max(Counter(t.date for t in ts).values()) == 1:
        return [ts]
    tracks = []
    for _, day in groupby(ts, key=lambda t: t.date):
        free = list(tracks)
        for t in sorted(day, key=lambda t: -t.amt):
            if not free:
                tracks.append([t])
                continue
            tr = min(free, key=lambda tr: abs(tr[-1].amt - t.amt))
            tr.append(t)
            free.remove(tr)
    return tracks


class Engine:
    def __init__(self, raw: bytes, judgments=None):
        self.sha = hashlib.sha256(raw).hexdigest()
        try:
            led = json.loads(raw)
        except json.JSONDecodeError as e:
            raise UWError(f"ledger: invalid JSON ({e})")
        self.notes = defaultdict(list)  # account_id -> Table 1 notes
        self.load(led)
        self.classify()
        self.pair_returns()
        self.build_groups()
        self.questions = self.make_questions()
        self.answers = self.read_judgments(judgments)
        self.apply_debit_answers()
        self.build_positions()
        self.gate_and_attribute()
        self.revenue()
        self.streams()
        self.obligations()
        self.capacity()
        self.peak()
        self.returns_log()
        self.liquidity()
        self.narrative()
        self.self_check()

    # ---- 1. load, coverage, integrity -------------------------------------------------------------
    def load(self, led):
        require(isinstance(led, dict), "ledger: top level must be an object")
        require(
            led.get("schema") == "uw-ledger/1", "ledger: schema must be 'uw-ledger/1'"
        )
        require(
            isinstance(led.get("accounts"), list) and led["accounts"],
            "ledger: accounts missing",
        )
        self.cal = Cal(led.get("holidays", []))
        self.owners = [o.upper() for o in led.get("owner_names", []) if o.strip()]
        self.owner_rx = rx(*map(re.escape, self.owners)) if self.owners else None
        self.docs = {d["doc_id"]: d for d in led.get("documents", [])}
        self.accts = {}
        for a in led["accounts"]:
            for k in ("account_id", "name", "last4", "integrity", "statements"):
                require(k in a, f"account: missing {k}")
            require(
                a["integrity"] in INTEGRITY,
                f"account {a['account_id']}: integrity {a['integrity']!r}",
            )
            st = sorted(
                (date.fromisoformat(s["start"]), date.fromisoformat(s["end"]))
                for s in a["statements"]
            )
            require(
                st and all(s <= e for s, e in st),
                f"account {a['account_id']}: bad statements",
            )
            self.accts[a["account_id"]] = dict(
                a,
                statements=st,
                period_mode=st[0][0].day > 5,
                flagged_months=set(a.get("flagged_months", [])),
            )
        self.txns, seen, self.dropped = [], {}, Counter()
        for i, r in enumerate(led.get("transactions", [])):
            for k in (
                "txn_id",
                "account_id",
                "date",
                "amount",
                "direction",
                "description",
            ):
                require(k in r, f"transaction {i}: missing {k}")
            require(
                r["account_id"] in self.accts,
                f"transaction {r['txn_id']}: unknown account",
            )
            require(
                r["direction"] in ("credit", "debit"),
                f"transaction {r['txn_id']}: bad direction",
            )
            try:
                amt = D(str(r["amount"]))
                bal = None if r.get("balance") in (None, "") else D(str(r["balance"]))
            except InvalidOperation:
                raise UWError(f"transaction {r['txn_id']}: bad amount or balance")
            require(amt > 0, f"transaction {r['txn_id']}: amount must be positive")
            sig = (r["account_id"], r["date"], amt, r["direction"], r["description"])
            if r["txn_id"] in seen:
                require(
                    seen[r["txn_id"]] == sig,
                    f"transaction {r['txn_id']}: same id, different content",
                )
                self.dropped[r["account_id"]] += 1
                continue
            seen[r["txn_id"]] = sig
            self.txns.append(
                Txn(
                    r["txn_id"],
                    r["account_id"],
                    date.fromisoformat(r["date"]),
                    amt,
                    r["direction"],
                    r["description"],
                    bal,
                    r.get("source_ref", ""),
                    i,
                )
            )
        require(self.txns, "ledger: no transactions")
        self.txns.sort(key=lambda t: (t.date, t.seq))
        self.by_id = {t.id: t for t in self.txns}
        self.end = self.txns[-1].date
        self.live_start = self.cal.add(self.end, -LIVE_WINDOW_BD)
        for a, n in self.dropped.items():
            self.notes[a].append(f"{n} duplicate transaction id(s) dropped")

        # Month keys and covered days. Period-mode accounts (cycle starts after day 5) use statement periods.
        covered, plen, self.acct_months = defaultdict(set), Counter(), defaultdict(dict)
        for aid, a in self.accts.items():
            for s, e in a["statements"]:
                if a["period_mode"]:
                    k = (e.year, e.month)
                    plen[k] = max(plen[k], (e - s).days + 1)
                    self.acct_months[aid][k] = (e - s).days + 1
                else:
                    d = s
                    while d <= e:
                        covered[(d.year, d.month)].add(d)
                        self.acct_months[aid].setdefault((d.year, d.month), set()).add(
                            d
                        )
                        d += timedelta(1)
        for t in self.txns:
            t_key = self.month_key(t)
            covered.setdefault(t_key, set())
        flagged = {
            tuple(map(int, m.split("-")))
            for a in self.accts.values()
            for m in a["flagged_months"]
        }
        self.months = sorted(set(covered) | set(plen))
        self.days = {
            k: max(len(covered.get(k, ())), plen.get(k, 0)) for k in self.months
        }
        self.counted = [
            k
            for k in self.months
            if self.days[k] >= FULL_MONTH_DAYS and k not in flagged
        ]
        self.worst = next(
            x
            for x in WORST_ORDER
            if any(a["integrity"] == x for a in self.accts.values())
        )

    def month_key(self, t):
        a = self.accts[t.acct]
        if a["period_mode"]:
            for s, e in a["statements"]:
                if s <= t.date <= e:
                    return (e.year, e.month)
        return t.month

    # ---- 2. provisional classification ------------------------------------------------------------
    def classify(self):
        for t in self.txns:
            t.norm, u = norm(t.desc), t.desc.upper()
            other_last4 = [b["last4"] for k, b in self.accts.items() if k != t.acct]
            if t.dir == "credit":
                t.tag = self.credit_rule(t, u, other_last4)
            else:
                t.tag = self.debit_rule(u)

    def credit_rule(self, t, u, other_last4):
        if RECREDIT.search(u):
            return "STRIP_RECREDIT"
        if REFUND.search(u):
            return "STRIP_REFUND"
        if TRANSFER.search(u) or OD_XFER.search(u):
            if any(l4 in u for l4 in other_last4):
                return "STRIP_TRANSFER"
            t.flags.append("unclear_transfer")
            return "REV_DEPOSIT"
        if self.owner_rx and self.owner_rx.search(u):
            return "STRIP_OWNER"
        for tag, r in (
            ("REV_PROCESSOR", PROCESSOR),
            ("REV_PAYER", PAYER),
            ("REV_WIRE", WIRE),
            ("REV_DEPOSIT", DEPOSIT),
        ):
            if r.search(u):
                return tag
        return "REV_ACH"

    def debit_rule(self, u):
        if FEE.search(u):
            return "FEE_NSF_OD"
        if TRANSFER.search(u) or OD_XFER.search(u):
            return "TRANSFER_OUT"
        if self.owner_rx and self.owner_rx.search(u):
            return "OWNER_DRAW"
        return next((tag for tag, r in DEBIT_RULES if r.search(u)), "OTHER")

    def pair_returns(self):
        """Pair each returned-item recredit with the debit it reversed: same account and amount, prior 5 bd."""
        for c in self.txns:
            if c.dir != "credit" or c.tag != "STRIP_RECREDIT":
                continue
            lo = self.cal.add(c.date, -RETURN_MATCH_BD)
            cands = [
                t
                for t in self.txns
                if t.dir == "debit"
                and t.acct == c.acct
                and t.amt == c.amt
                and lo <= t.date <= c.date
                and not t.returned_by
                and t.tag != "FEE_NSF_OD"
            ]
            if cands:
                d = max(
                    cands,
                    key=lambda t: (
                        len(set(t.norm.split()) & set(c.norm.split())),
                        t.date,
                        t.seq,
                    ),
                )
                d.returned_by, c.returns = c.id, d.id

    # ---- 3. debit groups and questions ------------------------------------------------------------
    def build_groups(self):
        self.groups = {}
        by = defaultdict(list)
        for t in self.txns:
            if t.dir == "debit" and t.tag in ("OTHER", "DEBT_SERVICE"):
                by[t.norm].append(t)
        for name, ts in by.items():
            series = split_concurrent(ts)
            cleared = [t for t in max(series, key=len) if not t.returned_by]
            gaps = [self.cal.diff(a.date, b.date) for a, b in zip(cleared, cleared[1:])]
            cadence = (
                Counter(map(gap_class, gaps)).most_common(1)[0][0]
                if gaps
                else "PROVISIONAL"
            )
            regular = len(cleared) >= SERIES_MIN_DEBITS and cadence in CADENCE_FACTOR
            # MCA remittances are fixed amounts: same-amount runs of 3+ cover >=80% of payments.
            all_cleared = [t for s in series for t in s if not t.returned_by]
            fixed = sum(
                len(r)
                for s in series
                for r in runs(
                    [t for t in s if not t.returned_by],
                    lambda f, x: not changed(f.amt, x.amt),
                )
                if len(r) >= SUSTAIN_PAYMENTS
            )
            regular = regular and fixed >= D("0.8") * len(all_cleared)
            word = bool(MCA_WORD.search(name))
            early = (
                0 < len(cleared) < SERIES_MIN_DEBITS
                and word
                and cleared[-1].date >= self.live_start
            )
            default_mca = (regular and (word or cadence == "daily")) or early
            self.groups[name] = dict(
                txns=ts,
                cleared=cleared,
                cadence=cadence,
                regular=regular,
                default_mca=default_mca,
                ask=len(ts) >= 3 or word or default_mca,
                mca=default_mca,
                funder=name,
                tag=ts[0].tag,
                source="default",
                terminated="",
            )

    def established_revenue(self):
        seen = defaultdict(set)
        for t in self.txns:
            if t.dir == "credit" and t.tag.startswith("REV_"):
                seen[t.norm].add((t.id, t.month))
        return {
            n for n, s in seen.items() if len(s) >= 3 and len({m for _, m in s}) >= 2
        }

    def candidates(self, tokens):
        """Funding candidates: wires, explicit financing text, 3x median deposit, or a funder name."""
        self.established = self.established_revenue()
        ordinary = [
            t.amt
            for t in self.txns
            if t.dir == "credit"
            and t.tag.startswith("REV_")
            and not WIRE.search(t.desc.upper())
            and not EXPLICIT_FIN.search(t.desc.upper())
        ]
        self.median = statistics.median(ordinary) if ordinary else None
        out = {}
        for t in self.txns:
            if t.dir != "credit" or t.tag in HARD_STRIP:
                continue
            u, why = t.desc.upper(), []
            if WIRE.search(u):
                why.append("wire")
            if EXPLICIT_FIN.search(u):
                why.append("explicit financing text")
            if self.median and t.amt >= 3 * self.median:
                why.append(
                    f"{(t.amt / self.median).quantize(D('0.1'))}x median deposit"
                )
            names = [f for f, toks in tokens.items() if has_token(u, toks)]
            if names:
                why.append("names funder " + ", ".join(sorted(names)))
            if why:
                out[t.id] = why
        return out

    def auto_gate(self, t, tokens):
        """Financing evidence the engine can verify alone (V2.2 gate conditions 1 and 3)."""
        u = t.desc.upper()
        m = EXPLICIT_FIN.search(u)
        if m:
            return {"kind": "bank_text", "quote": m.group(0), "by": "rule"}
        if t.norm not in self.established:
            for f, toks in tokens.items():
                if has_token(u, toks):
                    return {"kind": "named_funder_series", "quote": f, "by": "rule"}
        return None

    def make_questions(self):
        qs = []
        default_tokens = {
            g["funder"]: funder_tokens(g["funder"])
            for g in self.groups.values()
            if g["default_mca"] and g["regular"]
        }
        first_debits = sorted(
            (g["cleared"][0].date, n)
            for n, g in self.groups.items()
            if g["ask"] and g["cleared"]
        )
        for t_id, why in self.candidates(default_tokens).items():
            t = self.by_id[t_id]
            if self.auto_gate(t, default_tokens):
                continue
            hi = self.cal.add(t.date, FUNDING_WINDOW_BD)
            near = [
                f"debit series {n} starts {mdy(d)}"
                for d, n in first_debits
                if t.date <= d <= hi
            ]
            qs.append(
                dict(
                    question_id=qid("credit", [t.id]),
                    type="credit",
                    txn_ids=[t.id],
                    transactions=[self.txn_view(t)],
                    why=why + near,
                    default=t.tag,
                )
            )
        unclear = defaultdict(list)
        for t in self.txns:
            if "unclear_transfer" in t.flags:
                unclear[t.norm].append(t)
        for name, ts in unclear.items():
            qs.append(
                dict(
                    question_id=qid("credit", [t.id for t in ts]),
                    type="credit",
                    txn_ids=[t.id for t in ts],
                    transactions=[self.txn_view(t) for t in ts[:5]],
                    count=len(ts),
                    why=["transfer wording; sending account not supplied"],
                    default="REV_DEPOSIT",
                )
            )
        for name, g in sorted(self.groups.items()):
            if not g["ask"]:
                continue
            ts = g["txns"]
            qs.append(
                dict(
                    question_id=qid("debit", [t.id for t in ts]),
                    type="debit_group",
                    descriptor=name,
                    txn_ids=[t.id for t in ts],
                    count=len(ts),
                    cleared=len(g["cleared"]),
                    cadence=g["cadence"],
                    amounts=sorted({str(t.amt) for t in ts})[:8],
                    first=ts[0].date.isoformat(),
                    last=ts[-1].date.isoformat(),
                    sample_descriptions=sorted({t.desc for t in ts})[:3],
                    default="MCA" if g["default_mca"] else g["tag"],
                )
            )
        rev = defaultdict(D)
        for t in self.txns:
            if t.dir == "credit" and t.tag.startswith("REV_"):
                rev[f"{t.tag} {t.norm}"] += t.amt
        total = sum(rev.values(), D(0))
        top = sorted(rev.items(), key=lambda kv: -kv[1])[:5]
        qs.append(
            dict(
                question_id=qid("core", [self.sha]),
                type="core_operation",
                txn_ids=[],
                streams=[
                    dict(stream=k, share=pct(v / total) if total else "—")
                    for k, v in top
                ],
                default="text written by engine from Table 3",
            )
        )
        return qs

    def txn_view(self, t):
        return dict(
            txn_id=t.id,
            account=self.accts[t.acct]["last4"],
            date=t.date.isoformat(),
            amount=str(t.amt),
            direction=t.dir,
            description=t.desc,
        )

    # ---- 4. judgments (trust boundary) ------------------------------------------------------------
    def verify_quote(self, ev, texts, what):
        require(isinstance(ev, dict), f"{what}: evidence must be an object")
        quote = str(ev.get("quote", "")).strip()
        require(len(quote) >= 3, f"{what}: evidence quote too short")
        if ev.get("kind") == "document":
            doc = self.docs.get(ev.get("doc_id"))
            require(doc is not None, f"{what}: unknown doc_id {ev.get('doc_id')!r}")
            require(
                quote.upper() in doc["text"].upper(),
                f"{what}: quote not found in document {doc['doc_id']}",
            )
        else:
            require(
                all(quote.upper() in s.upper() for s in texts),
                f"{what}: quote not in transaction text",
            )
        return dict(
            kind=ev.get("kind"), quote=quote, doc_id=ev.get("doc_id"), by="judgment"
        )

    def read_judgments(self, j):
        if j is None:
            return {}
        require(
            isinstance(j, dict) and isinstance(j.get("answers"), list),
            "judgments: answers list missing",
        )
        require(
            j.get("ledger_sha256") == self.sha,
            "judgments: ledger_sha256 does not match this ledger",
        )
        qs = {q["question_id"]: q for q in self.questions}
        out = {}
        for a in j["answers"]:
            q = qs.get(a.get("question_id"))
            what = f"judgment {a.get('question_id')}"
            require(q is not None, f"{what}: unknown question id")
            require(a["question_id"] not in out, f"{what}: answered twice")
            if q["type"] == "core_operation":
                text = re.sub(r"\s+", " ", str(a.get("text", ""))).strip()
                require(
                    0 < len(text) <= 240, f"{what}: text must be 1 to 240 characters"
                )
                out[q["question_id"]] = dict(text=text)
                continue
            tag = a.get("tag")
            if tag == "unsure":
                continue
            texts = [self.by_id[i].desc for i in q["txn_ids"]]
            if q["type"] == "credit":
                require(tag in CREDIT_TAGS, f"{what}: tag {tag!r} not a credit tag")
                ans = dict(tag=tag, reason=str(a.get("reason", ""))[:300])
                if tag in ("STRIP_FUNDING", "STRIP_TRANSFER", "STRIP_OWNER"):
                    kinds = (
                        ("bank_text", "sender_identified", "document")
                        if tag == "STRIP_FUNDING"
                        else ("bank_text", "document")
                    )
                    ev = a.get("evidence") or {}
                    require(
                        ev.get("kind") in kinds,
                        f"{what}: {tag} needs evidence kind in {kinds}",
                    )
                    ans["evidence"] = self.verify_quote(ev, texts, what)
                    if tag == "STRIP_FUNDING" and ev["kind"] == "document":
                        doc = self.docs[ev["doc_id"]]["text"].replace(",", "")
                        for i in q["txn_ids"]:
                            amt = self.by_id[i].amt
                            require(
                                str(amt) in doc or str(amt.quantize(D(1))) in doc,
                                f"{what}: document does not state amount {amt}",
                            )
                out[q["question_id"]] = ans
            else:
                require(
                    tag in DEBIT_TAGS or bool(AMBIGUOUS_RE.match(str(tag))),
                    f"{what}: bad debit tag {tag!r}",
                )
                ans = dict(tag=tag, reason=str(a.get("reason", ""))[:300])
                if tag == "MCA":
                    funder = re.sub(
                        r"[^A-Za-z0-9 &.\-]", "", str(a.get("funder", ""))
                    ).strip()[:40]
                    require(funder, f"{what}: MCA answer needs funder")
                    ans["funder"] = funder
                if a.get("terminated"):
                    ev = dict(
                        a["terminated"], kind=a["terminated"].get("kind", "bank_text")
                    )
                    ans["terminated"] = self.verify_quote(
                        ev, [" ".join(t.desc for t in self.txns)], what
                    )
                out[q["question_id"]] = ans
        return out

    def apply_debit_answers(self):
        for q in self.questions:
            a = self.answers.get(q["question_id"])
            if q["type"] != "debit_group" or not a:
                continue
            g = self.groups[q["descriptor"]]
            g["source"] = "judgment"
            g["mca"] = a["tag"] == "MCA"
            g["funder"] = a.get("funder", g["funder"]).upper()
            g["tag"] = a["tag"]
            if a.get("terminated"):
                g["terminated"] = a["terminated"]["quote"]
            if not g["mca"]:
                for t in g["txns"]:
                    t.tag, t.tag_source = a["tag"], "judgment"

    # ---- 5. MCA positions, events, live status ----------------------------------------------------
    def build_positions(self):
        self.positions = []
        for name, g in sorted(self.groups.items()):
            if not g["mca"]:
                continue
            ts = g["txns"]
            for s in split_concurrent(ts):
                cleared = [t for t in s if not t.returned_by]
                p = Position(
                    f"P{len(self.positions) + 1}", g["funder"], name, s, cleared
                )
                p.terminated = g["terminated"]
                p.source = g["source"]
                self.analyse(p)
                for t in s:
                    t.tag = "MCA_" + re.sub(r"[^A-Z0-9]+", "_", p.funder).strip("_")
                    t.tag_source = g["source"]
                self.positions.append(p)
        names = Counter(p.funder for p in self.positions)
        seen = Counter()
        for p in sorted(self.positions, key=lambda p: (p.txns[0].date, p.pid)):
            seen[p.funder] += 1
            p.display = p.funder + (
                f" #{seen[p.funder]}" if names[p.funder] > 1 else ""
            )
        # Different-name refinance hints (4E).
        for p in self.positions:
            if p.prefile or not p.cleared:
                continue
            for o in self.positions:
                if (
                    o is not p
                    and o.cleared
                    and o.funder != p.funder
                    and o.cleared[-1].date < p.cleared[0].date
                    and self.cal.diff(o.cleared[-1].date, p.cleared[0].date)
                    <= REFI_GAP_BD
                ):
                    p.notes.append(f"Possible refi of {o.funder}")
                    if p.live and o.live:
                        p.notes.append("Refi overlap, both counted")
        self.positions.sort(key=lambda p: (not p.live, -p.cost, p.pid))

    def analyse(self, p):
        c = p.cleared
        gaps = [self.cal.diff(a.date, b.date) for a, b in zip(c, c[1:])]
        normal = int(statistics.median(gaps)) if gaps else None
        cadence = (
            Counter(map(gap_class, gaps)).most_common(1)[0][0]
            if gaps
            else "PROVISIONAL"
        )
        standard = len(c) >= SERIES_MIN_DEBITS and cadence in CADENCE_FACTOR
        trig = lambda kind, t: p.triggers.append(
            dict(
                trigger_id=f"{p.pid}-T{len(p.triggers) + 1}",
                position=p.pid,
                kind=kind,
                date=t.date,
                txn_id=t.id,
            )
        )
        if c:
            start_cov = min(self.accts[t.acct]["statements"][0][0] for t in p.txns)
            p.prefile = (
                normal is not None and self.cal.diff(start_cov, c[0].date) <= 2 * normal
            )
            trig("START", c[0])
        if standard:
            # Amount levels: a level change needs >10% for SUSTAIN_PAYMENTS payments.
            amount_runs = runs(c, lambda first, x: not changed(first.amt, x.amt))
            prev = None
            for i, r in enumerate(amount_runs):
                if len(r) >= SUSTAIN_PAYMENTS:
                    if prev and changed(prev[0].amt, r[0].amt):
                        kind = "AMOUNT UP" if r[0].amt > prev[0].amt else "AMOUNT DOWN"
                        self.event(
                            p,
                            kind,
                            r[0],
                            f"{usd(prev[0].amt)} to {usd(r[0].amt)}",
                            f"{len(prev)} at old level, {len(r)} at new; confirmed {mdy(r[2].date)}",
                        )
                        if kind == "AMOUNT UP":
                            trig(kind, r[0])
                    prev = r
                elif (
                    prev
                    and r[0].amt < prev[0].amt
                    and i + 1 < len(amount_runs)
                    and not changed(prev[0].amt, amount_runs[i + 1][0].amt)
                ):
                    self.event(
                        p,
                        "TEMP CUT",
                        r[0],
                        f"{usd(prev[0].amt)} to {usd(r[0].amt)}",
                        f"{len(r)} payment(s) then back to prior level",
                    )
            p.level = prev[0].amt if prev else max(t.amt for t in c)
            # Cadence: a change needs SUSTAIN_PAYMENTS consecutive gaps of the new class.
            classes = [(gap_class(g), c[i + 1]) for i, g in enumerate(gaps)]
            prev_cls = None
            for r in runs(classes, lambda first, x: first[0] == x[0]):
                if len(r) >= SUSTAIN_PAYMENTS and r[0][0] in CADENCE_FACTOR:
                    if prev_cls and r[0][0] != prev_cls:
                        self.event(
                            p,
                            "CADENCE CHANGE",
                            r[0][1],
                            f"{prev_cls.title()} to {r[0][0].title()}",
                            f"{len(r)} payments at new cadence",
                        )
                        trig("CADENCE CHANGE", r[0][1])
                    prev_cls = r[0][0]
            p.cadence = prev_cls or cadence
            for a, b, g in zip(c, c[1:], gaps):
                if g > 2 * normal:
                    self.event(
                        p,
                        "STOPPED",
                        a,
                        f"Last debit before {g} bd gap",
                        "no payoff debit seen",
                    )
                    self.event(
                        p,
                        "RESTARTED",
                        b,
                        f"{p.cadence.title()} {usd(b.amt)}",
                        "debits resume",
                    )
                    trig("RESTARTED", b)
            if self.cal.diff(c[-1].date, self.end) > 2 * normal:
                self.event(
                    p,
                    "STOPPED",
                    c[-1],
                    f"No debit for {self.cal.diff(c[-1].date, self.end)} bd",
                    "no payoff debit seen",
                )
            p.cost = p.level * CADENCE_FACTOR[p.cadence]
            p.status = "CONFIRMED"
        else:
            p.cadence = "PROVISIONAL"
            p.level = max((t.amt for t in (c or p.txns)), default=D(0))
            p.cost = p.level * BUSINESS_DAYS_PER_MONTH
            p.status = "PROBABLE"
            p.notes.append(
                f"Provisional cadence: {len(c)} cleared debit(s); stress cost = max debit x20"
            )
        p.live = bool(c) and c[-1].date >= self.live_start and not p.terminated
        if p.terminated:
            p.notes.append(f"Terminated per evidence: {p.terminated}")
        elif c and not p.live:
            p.notes.append(
                f"Not live: last cleared {mdy(c[-1].date)} before live window {mdy(self.live_start)}"
            )
        if not p.live:
            p.cost = D(0)
        p.events.sort(key=lambda e: e["date"])

    def event(self, p, kind, t, change, detail):
        p.events.append(
            dict(kind=kind, date=t.date, txn_id=t.id, change=change, detail=detail)
        )

    # ---- 6. financing gate and bidirectional attribution ------------------------------------------
    def gate_and_attribute(self):
        tokens = {
            p.funder: funder_tokens(p.funder)
            for p in self.positions
            if p.status == "CONFIRMED"
        }
        all_tokens = {p.funder: funder_tokens(p.funder) for p in self.positions}
        cand = self.candidates(all_tokens)
        # Apply credit judgments, then the gate. Rule-verifiable evidence outranks a judgment.
        self.gate = {}
        for q in self.questions:
            a = self.answers.get(q["question_id"])
            if q["type"] != "credit" or not a:
                continue
            for i in q["txn_ids"]:
                t = self.by_id[i]
                t.tag, t.tag_source = a["tag"], "judgment"
                if a["tag"] == "STRIP_FUNDING":
                    self.gate[i] = a["evidence"]
        for i in cand:
            t = self.by_id[i]
            g = self.auto_gate(t, tokens)
            if g:
                self.gate[i] = g
        for i, g in self.gate.items():
            t = self.by_id[i]
            t.tag, t.tag_source = "STRIP_FUNDING", g["by"]
            if g["kind"] == "sender_identified":
                self.notes[t.acct].append(
                    f"LLM-identified funder for {mdy(t.date)} {usd(t.amt)} credit "
                    f"('{g['quote']}'); verify before relying"
                )
        cand.update({i: cand.get(i, ["financing evidence"]) for i in self.gate})
        self.cand = cand

        triggers = [tr for p in self.positions for tr in p.triggers]
        pos = {p.pid: p for p in self.positions}
        credits = [t for t in self.txns if t.dir == "credit"]
        pairs = defaultdict(list)  # trigger_id -> scored credits
        self.searches = []
        for tr in triggers:
            lo = self.cal.add(tr["date"], -FUNDING_WINDOW_BD)
            found = []
            for c in credits:
                if lo <= c.date <= tr["date"]:
                    sc = self.score(c, pos[tr["position"]], tr)
                    if sc["points"] >= 1:
                        found.append(sc)
            found.sort(key=lambda s: (-s["points"], s["bd_gap"]))
            pairs[tr["trigger_id"]] = found
            self.searches.append(
                dict(
                    search_id=f"B-{tr['trigger_id']}",
                    direction="backward",
                    anchor=tr["trigger_id"],
                    window=[lo, tr["date"]],
                    accounts=list(self.accts),
                    credits_scanned=sum(lo <= c.date <= tr["date"] for c in credits),
                    candidates=found,
                    outcome="",
                )
            )
        # Proposals: best gated credit per trigger; ties or cross-position reuse become AMBIGUOUS.
        proposal = {}
        for tr in triggers:
            found = pairs[tr["trigger_id"]]
            s = next(x for x in self.searches if x["anchor"] == tr["trigger_id"])
            if not found:
                s["outcome"] = "searched; none qualifies"
                continue
            top = [f for f in found if f["points"] == found[0]["points"]]
            if len(top) > 1:
                s["outcome"] = "AMBIGUOUS: tied candidates " + ", ".join(
                    f["txn_id"] for f in top
                )
                continue
            best = top[0]
            if best["txn_id"] not in self.gate:
                s["outcome"] = (
                    f"best candidate {best['txn_id']} fails financing-evidence gate"
                )
                continue
            proposal[tr["trigger_id"]] = best
        by_credit = defaultdict(list)
        for tid, best in proposal.items():
            by_credit[best["txn_id"]].append(tid)
        trig_by_id = {tr["trigger_id"]: tr for tr in triggers}
        self.attached = {}
        for cid, tids in by_credit.items():
            owners = {trig_by_id[t]["position"] for t in tids}
            if len(owners) > 1:
                for t in tids:
                    s = next(x for x in self.searches if x["anchor"] == t)
                    s["outcome"] = f"AMBIGUOUS: {cid} also best for another position"
                continue
            keep = min(
                tids, key=lambda t: (-proposal[t]["points"], proposal[t]["bd_gap"])
            )
            for t in tids:
                s = next(x for x in self.searches if x["anchor"] == t)
                s["outcome"] = (
                    f"Attached {cid}"
                    if t == keep
                    else f"{cid} attached to {keep} instead"
                )
            self.attached[cid] = keep
            tr = trig_by_id[keep]
            pos[tr["position"]].fundings.append(
                dict(
                    trigger=tr,
                    credit=cid,
                    **{
                        k: proposal[keep][k]
                        for k in ("points", "confidence", "bd_gap", "basis")
                    },
                )
            )
        for p in self.positions:
            p.fundings.sort(key=lambda f: f["trigger"]["date"])
            if p.status == "PROBABLE" and p.fundings:
                p.status = "CONFIRMED (early match)"
        # Forward search from every candidate credit.
        self.forward = []
        for cid in sorted(cand, key=lambda i: (self.by_id[i].date, i)):
            c = self.by_id[cid]
            hi = self.cal.add(c.date, FUNDING_WINDOW_BD)
            hits = [tr for tr in triggers if c.date <= tr["date"] <= hi]
            ambiguous = any(
                s["outcome"].startswith("AMBIGUOUS") and cid in s["outcome"]
                for s in self.searches
            ) or any(
                s["outcome"].startswith("AMBIGUOUS")
                and s["candidates"]
                and s["candidates"][0]["txn_id"] == cid
                for s in self.searches
            )
            if cid in self.attached:
                outcome = "Attached"
            elif ambiguous:
                outcome = "Competing/ambiguous"
            elif not hits:
                outcome = "No qualifying debit trigger"
            elif cid not in self.gate:
                outcome = "No supported financing evidence"
            else:
                outcome = "Competing/ambiguous"
            if cid in self.gate and cid not in self.attached:
                near = any(
                    c.date <= tr["date"] <= c.date + timedelta(UNATTACHED_WINDOW_CAL)
                    for tr in triggers
                )
                disposition = "STRIP_FUNDING, unattached" + (
                    "" if near else " (Unattached funding)"
                )
                self.notes[c.acct].append(
                    f"{'Unattached funding' if not near else 'Funding not attached'}: "
                    f"{mdy(c.date)} {usd(c.amt)} stripped on {self.gate[cid]['kind']}"
                )
            elif cid in self.gate:
                disposition = "STRIP_FUNDING, attached"
            else:
                disposition = f"{c.tag}; unresolved funding candidate"
                if hits:
                    self.notes[c.acct].append(
                        f"Unresolved funding candidate {mdy(c.date)} {usd(c.amt)} "
                        f"kept as {c.tag}; True Revenue sensitivity {usd(c.amt)}"
                    )
            self.forward.append(
                dict(
                    search_id=f"F-{cid}",
                    direction="forward",
                    anchor=cid,
                    window=[c.date, hi],
                    reasons=cand[cid],
                    triggers=[tr["trigger_id"] for tr in hits],
                    outcome=outcome,
                    disposition=disposition,
                    gate=self.gate.get(cid),
                )
            )

    def score(self, c, p, tr):
        u, pts, basis = c.desc.upper(), 0, []
        if has_token(u, funder_tokens(p.funder)):
            pts += 3
            basis.append("+3 names funder")
        if WIRE.search(u) or EXPLICIT_FIN.search(u):
            pts += 2
            basis.append("+2 wire/explicit financing")
        if self.median and c.amt >= 3 * self.median:
            pts += 2
            basis.append("+2 >=3x median deposit")
        if 0 <= (tr["date"] - c.date).days <= 3:
            pts += 1
            basis.append("+1 within 3 calendar days")
        if c.norm in self.established:
            pts -= 3
            basis.append("-3 established customer pattern")
        conf = (
            "HIGH"
            if pts >= 5
            else "MED" if pts >= 3 else "LOW; unverified" if pts >= 1 else "Not found"
        )
        return dict(
            txn_id=c.id,
            points=pts,
            confidence=conf,
            bd_gap=self.cal.diff(c.date, tr["date"]),
            basis=basis,
        )

    # ---- 7. revenue -------------------------------------------------------------------------------
    def revenue(self):
        self.month_rows = {}
        for k in self.months:
            cs = [t for t in self.txns if t.dir == "credit" and self.month_key(t) == k]
            gross = sum((t.amt for t in cs), D(0))
            strips = defaultdict(D)
            for t in cs:
                if t.tag.startswith("STRIP_"):
                    strips[t.tag] += t.amt
            stripped = sum(strips.values(), D(0))
            top = max(strips.items(), key=lambda kv: kv[1])[0] if strips else None
            self.month_rows[k] = dict(
                gross=gross, stripped=stripped, top_strip=top, true=gross - stripped
            )
        tr = [self.month_rows[k]["true"] for k in self.counted]
        self.tor = mean(tr)
        self.last3 = mean(tr[-3:])
        self.basis = self.last3
        self.worst_month = (
            min(self.counted, key=lambda k: self.month_rows[k]["true"])
            if self.counted
            else None
        )

    def streams(self):
        groups = defaultdict(list)
        for t in self.txns:
            if t.dir == "credit" and t.tag.startswith("REV_"):
                groups[(t.tag, t.norm)].append(t)
        ranked = sorted(groups.items(), key=lambda kv: -sum(t.amt for t in kv[1]))
        top, rest = ranked[:TOP_STREAMS], ranked[TOP_STREAMS:]
        if rest:
            top.append(
                (
                    ("REV_OTHER", f"{len(rest)} other descriptors"),
                    [t for _, ts in rest for t in ts],
                )
            )
        total = sum((t.amt for _, ts in top for t in ts), D(0))
        self.stream_rows = []
        for (tag, name), ts in top:
            amt = sum((t.amt for t in ts), D(0))
            per_month = [
                sum((t.amt for t in ts if self.month_key(t) == k), D(0))
                for k in self.months
            ]
            m = mean(per_month)
            cv = (
                (D(statistics.pstdev(per_month)) / m).quantize(D("0.01")) if m else None
            )
            per = D(len(ts)) / max(1, len(self.months))
            cadence = (
                "daily" if per >= 15 else "weekly" if per >= D("3.5") else "irregular"
            )
            present = sum(1 for v in per_month if v > 0)
            self.stream_rows.append(
                dict(
                    name=f"{tag} {name}",
                    cadence=cadence,
                    count=len(ts),
                    avg=amt / len(ts),
                    total=amt,
                    cv=cv,
                    share=amt / total if total else None,
                    present=present,
                )
            )

    # ---- 8. obligations and capacity --------------------------------------------------------------
    def obligations(self):
        n = len(self.counted)
        debits = [
            t
            for t in self.txns
            if t.dir == "debit"
            and not t.returned_by
            and self.month_key(t) in self.counted
        ]
        self.ob_rows = []
        tags = [r for r in OBLIGATION_ROWS] + [
            (t, t) for t in sorted({t.tag for t in debits if AMBIGUOUS_RE.match(t.tag)})
        ]
        for tag, label in tags:
            ts = [t for t in debits if t.tag == tag]
            avg = sum((t.amt for t in ts), D(0)) / n if n else None
            names = Counter(t.norm for t in ts).most_common(2)
            basis = (
                ", ".join(f"{nm} {c / n:.1f}/mo" for nm, c in names)
                if ts and n
                else "none observed"
            )
            if tag == "OWNER_DRAW":
                basis = f"{basis}; excluded from total"
            self.ob_rows.append(
                dict(
                    tag=tag,
                    label=label,
                    avg=avg,
                    basis=basis,
                    ambiguous=bool(AMBIGUOUS_RE.match(tag)),
                )
            )
        self.total_ob = (
            sum(
                (
                    r["avg"]
                    for r in self.ob_rows
                    if r["tag"] != "OWNER_DRAW" and not r["ambiguous"]
                ),
                D(0),
            )
            if n
            else None
        )

    def capacity(self):
        self.stack = sum((p.cost for p in self.positions if p.live), D(0))
        b, s, o = self.basis, self.stack, self.total_ob
        w = self.month_rows[self.worst_month]["true"] if self.worst_month else None
        self.room = dict(
            A=b - s if b is not None else None,
            B=HOLDBACK_SHARE * b - s if b is not None else None,
            C=b - s - o if b is not None and o is not None else None,
            D=HOLDBACK_SHARE * w - s if w is not None else None,
        )
        r = self.room
        self.headline = (
            max(D(0), min(r["B"], r["C"])) if None not in (r["B"], r["C"]) else None
        )
        self.conservative = (
            max(D(0), min(r["C"], r["D"])) if None not in (r["C"], r["D"]) else None
        )
        if self.headline is None:
            self.binding = "Insufficient counted months"
        elif self.headline == 0:
            self.binding = "No headline room (Room B or C <= 0)"
        else:
            self.binding = (
                "Room B: 60% revenue holdback"
                if r["B"] <= r["C"]
                else "Room C: operating obligations"
            )
        if self.conservative == 0 and self.headline is not None:
            lim = (
                "Room C <= 0"
                if r["C"] <= r["D"]
                else f"Room D <= 0 (worst month {mon(self.worst_month)})"
            )
            self.binding += f"; CONSERVATIVE: {lim}"
        status = (
            "INSUFFICIENT DATA"
            if len(self.counted) < 2
            else "YES" if self.headline > 0 else "NO"
        )
        self.status = status + SUFFIX[self.worst]

    # ---- 9. peak load -----------------------------------------------------------------------------
    def peak(self):
        covered = set()
        for a in self.accts.values():
            for s, e in a["statements"]:
                covered |= {s + timedelta(i) for i in range((e - s).days + 1)}
        weeks = defaultdict(list)
        for p in self.positions:
            for t in p.cleared:
                weeks[t.date - timedelta(t.date.weekday())].append((t, p))
        eligible = {
            m: v
            for m, v in weeks.items()
            if all(m + timedelta(i) in covered for i in range(5))
        }
        self.peak_week = None
        if eligible:
            m = max(eligible, key=lambda m: (sum(t.amt for t, _ in eligible[m]), m))
            funders = sorted({p.display for _, p in eligible[m]})
            self.peak_week = dict(
                monday=m,
                weekly=sum((t.amt for t, _ in eligible[m]), D(0)),
                funders=funders,
                latest=m == max(eligible),
            )
        self.cur_weekly = self.stack / WEEKS_PER_MONTH

    # ---- 10. returns and liquidity ----------------------------------------------------------------
    def returns_log(self):
        returned = [t for t in self.txns if t.returned_by]
        chains = []
        for t in returned:
            ch = next(
                (
                    c
                    for c in chains
                    if c[-1].norm == t.norm
                    and c[-1].amt == t.amt
                    and self.cal.diff(c[-1].date, t.date) <= CHAIN_GAP_BD
                ),
                None,
            )
            ch.append(t) if ch else chains.append([t])
        self.t7 = []
        for ch in chains:
            first, last = ch[0], ch[-1]
            rc = self.by_id[last.returned_by]
            codes = " ".join(self.by_id[t.returned_by].desc.upper() for t in ch)
            is_mca = first.tag.startswith("MCA_")
            if T1.search(codes):
                tier = "T1"
            elif first.tag in ("PAYROLL", "RENT", "TAX", "INSURANCE") or (
                (is_mca or first.tag == "DEBT_SERVICE")
                and T2_FINANCE_CODES.search(codes)
            ):
                tier = "T2"
            else:
                tier = "T3"
            hi = self.cal.add(rc.date, CURE_WINDOW_BD)
            cure = next(
                (
                    t
                    for t in self.txns
                    if t.dir == "debit"
                    and not t.returned_by
                    and t.norm == first.norm
                    and t.amt >= first.amt
                    and rc.date <= t.date <= hi
                    and (t.date, t.seq) > (rc.date, rc.seq)
                ),
                None,
            )
            if is_mca and tier == "T1":
                cured = "N (MCA stop-pay)"
            elif cure and cure.bal is not None and cure.bal >= 0:
                cured = f"Y (re-presented {cure.date:%m/%d} cleared)"
            elif cure:
                cured = "N (re-presented; balance unknown)"
            else:
                cured = (
                    "N (returned "
                    + ", ".join(mdy(self.by_id[t.returned_by].date) for t in ch)
                    + ")"
                )
            code = RETURN_CODE.search(codes)
            self.t7.append(
                dict(
                    date=first.date,
                    who=first.norm,
                    amt=first.amt,
                    cls="A",
                    tier=tier,
                    desc=f"ACH Rev {code.group(0)}" if code else "Return",
                    cured=cured,
                    attempts=[t.id for t in ch],
                )
            )
        for t in self.txns:
            if (
                t.dir == "debit"
                and not t.returned_by
                and t.tag != "FEE_NSF_OD"
                and t.bal is not None
                and t.bal < 0 <= t.bal + t.amt
            ):
                self.t7.append(
                    dict(
                        date=t.date,
                        who=t.norm,
                        amt=t.amt,
                        cls="B",
                        tier="n/a",
                        desc="Paid into overdraft",
                        cured="n/a (paid by OD)",
                        attempts=[t.id],
                    )
                )
        self.t7.sort(key=lambda e: (e["date"], e["cls"]))

    def liquidity(self):
        eod = defaultdict(dict)  # account -> date -> end-of-day balance
        for t in self.txns:
            if t.bal is not None:
                eod[t.acct][t.date] = t.bal
        self.eod = eod
        self.od_days = {d for a in eod.values() for d, b in a.items() if b < 0}
        self.od_days |= {
            t.date
            for t in self.txns
            if (t.tag == "FEE_NSF_OD" and "OVERDRAFT" in t.desc.upper())
            or OD_XFER.search(t.desc.upper())
        }
        self.fees = [t for t in self.txns if t.tag == "FEE_NSF_OD"]
        self.thin = 3 * (self.stack / BUSINESS_DAYS_PER_MONTH)
        self.combined = {}
        if all(eod.get(a) for a in self.accts):
            start = max(min(eod[a]) for a in self.accts)
            d, last = start, {}
            while d <= self.end:
                for a in self.accts:
                    if d in eod[a]:
                        last[a] = eod[a][d]
                if self.cal.is_bd(d) and len(last) == len(self.accts):
                    self.combined[d] = sum(last.values(), D(0))
                d += timedelta(1)
        self.flights, used = [], set()
        for c in self.txns:
            if c.id not in self.cand:
                continue
            outs = [
                t
                for t in self.txns
                if t.dir == "debit"
                and t.acct == c.acct
                and t.id not in used
                and (t.date, t.seq) > (c.date, c.seq)
                and t.date <= c.date + timedelta(FLIGHT_DAYS)
            ]
            out = sum((t.amt for t in outs), D(0))
            if out > FLIGHT_SHARE * c.amt:
                used |= {t.id for t in outs}
                self.flights.append(
                    dict(date=c.date, inflow=c.amt, outflow=out, credit=c.id)
                )

    # ---- 11. narrative (deterministic except Core Operation) --------------------------------------
    def narrative(self):
        a_events = [e for e in self.t7 if e["cls"] == "A"]
        tiers = Counter(e["tier"] for e in a_events)
        uncured = sum(1 for e in a_events if not e["cured"].startswith("Y"))
        mca_ret = sum(
            1 for e in a_events if self.by_id[e["attempts"][0]].tag.startswith("MCA_")
        )
        levies = sum(
            1 for t in self.txns if t.dir == "debit" and LEVY.search(t.desc.upper())
        )
        will = (
            f"{len(a_events)} Class A return chain(s) (T1 {tiers['T1']}, T2 {tiers['T2']}, T3 {tiers['T3']}), "
            f"{uncured} uncured; {mca_ret} MCA payment return(s); {len(self.od_days)} overdraft day(s)."
        )
        if levies:
            will += f" {levies} levy/lien/garnishment debit(s) in bank text."
        if self.peak_week:
            pk = (
                f"Peak weekly {usd(self.peak_week['weekly'])} in week of {mdy(self.peak_week['monday'])} vs "
                f"current weekly {usd(self.cur_weekly)}."
            )
        else:
            pk = f"Observed peak unavailable (no fully covered week); current weekly {usd(self.cur_weekly)}."
        s, o, b = self.stack, self.total_ob, self.basis
        if len(self.counted) < 2:
            flip = f"Supply statements for at least 2 counted months (have {len(self.counted)})."
        elif self.headline > 0:
            flip = (
                f"HEADLINE falls to $0 if BASIS drops below {usd(max(s / HOLDBACK_SHARE, s + o))} "
                f"or Live Stack rises above {usd(min(HOLDBACK_SHARE * b, b - o))}."
            )
        else:
            flip = (
                f"HEADLINE turns positive when BASIS exceeds {usd(max(s / HOLDBACK_SHARE, s + o))} "
                f"at current stack and obligations, or Live Stack falls below {usd(min(HOLDBACK_SHARE * b, b - o))}."
            )
        core = next(
            (
                self.answers[q["question_id"]]["text"]
                for q in self.questions
                if q["type"] == "core_operation" and q["question_id"] in self.answers
            ),
            None,
        )
        if core is None:
            top = self.stream_rows[0] if self.stream_rows else None
            core = (
                f"Largest revenue stream is {top['name']} at {pct(top['share'])} of included revenue."
                if top
                else "No included revenue observed."
            )
        self.lines = dict(core=core, will=will, peak=pk, flip=flip)

    # ---- 12. invariants on unrounded values -------------------------------------------------------
    def self_check(self):
        checks = []

        def ok(name, cond):
            require(cond, f"self-check failed: {name}")
            checks.append(name)

        ok(
            "one final tag per transaction",
            all(t.tag for t in self.txns),
        )
        ok(
            "month accounting: gross - stripped = true",
            all(
                r["gross"] - r["stripped"] == r["true"]
                for r in self.month_rows.values()
            ),
        )
        ok(
            "streams total = sum of true revenue over all months",
            sum((r["total"] for r in self.stream_rows), D(0))
            == sum((r["true"] for r in self.month_rows.values()), D(0)),
        )
        ok(
            "every STRIP_FUNDING credit passed the evidence gate",
            all(t.id in self.gate for t in self.txns if t.tag == "STRIP_FUNDING"),
        )
        ok(
            "every trigger has a backward search",
            {tr["trigger_id"] for p in self.positions for tr in p.triggers}
            == {s["anchor"] for s in self.searches},
        )
        ok(
            "every funding candidate has a forward search and disposition",
            set(self.cand) == {f["anchor"] for f in self.forward}
            and all(f["disposition"] for f in self.forward),
        )
        ok(
            "no credit attached to two triggers",
            len(self.attached) == len(set(self.attached.values())),
        )
        ok(
            "attached credits are inside the 7 business-day window",
            all(
                self.cal.add(self.by_id[f["credit"]].date, FUNDING_WINDOW_BD)
                >= f["trigger"]["date"]
                >= self.by_id[f["credit"]].date
                for p in self.positions
                for f in p.fundings
            ),
        )
        ok(
            "live stack = sum of live position costs",
            self.stack == sum((p.cost for p in self.positions if p.live), D(0)),
        )
        ok(
            "non-live positions cost 0",
            all(p.cost == 0 for p in self.positions if not p.live),
        )
        ok(
            "no live cost removed by payoff estimate",
            all(p.cost > 0 for p in self.positions if p.live),
        )
        if self.headline is not None:
            ok(
                "HEADLINE = max(0, min(B, C))",
                self.headline == max(D(0), min(self.room["B"], self.room["C"])),
            )
        ok(
            "Class B events have tier n/a",
            all(e["tier"] == "n/a" for e in self.t7 if e["cls"] == "B"),
        )
        self.checks = checks

    # ---- 13. table rows and render ----------------------------------------------------------------
    def tables(self):
        dash = "—"
        t1 = []
        for aid, a in self.accts.items():
            ks = sorted(self.acct_months[aid])
            cov = f"{mon(ks[0])} to {mon(ks[-1])} ({len(ks)})" if ks else dash
            cnt = [k for k in ks if k in self.counted]
            partial = [
                f"{mon(k)} ({v if isinstance(v, int) else len(v)} days)"
                for k, v in sorted(self.acct_months[aid].items())
                if (v if isinstance(v, int) else len(v)) < FULL_MONTH_DAYS
            ]
            notes = (
                [f"Path A (Exparsed); source status {a['integrity']}"]
                + ([a["integrity_note"]] if a.get("integrity_note") else [])
                + self.notes[aid]
            )
            if aid == next(iter(self.accts)):
                open_q = [
                    q
                    for q in self.questions
                    if q["type"] != "core_operation"
                    and q["question_id"] not in self.answers
                ]
                if open_q:
                    notes.append(
                        f"{len(open_q)} judgment question(s) unanswered; engine defaults applied"
                    )
                notes += [
                    f"{p.display}: {n}"
                    for p in self.positions
                    for n in p.notes
                    if n.startswith("Provisional")
                ]
            t1.append(
                [
                    f"{a['name']} ...{a['last4']}",
                    cov,
                    f"{len(cnt)}: " + (", ".join(map(mon, cnt)) if cnt else "None"),
                    "Partial: " + ", ".join(partial) if partial else "None",
                    a["integrity"],
                    "; ".join(notes),
                ]
            )
        t2 = []
        for k in self.months:
            r = self.month_rows[k]
            strip = (
                f"{usd(r['stripped'])} ({r['top_strip']})"
                if r["top_strip"]
                else usd(r["stripped"])
            )
            t2.append(
                [
                    mon(k),
                    str(self.days[k]),
                    usd(r["gross"]),
                    strip,
                    usd(r["true"]),
                    "Yes" if k in self.counted else "No",
                ]
            )
        t2 += [
            ["TOR", dash, dash, dash, usd(self.tor), dash],
            ["Last-3 Avg", dash, dash, dash, usd(self.last3), dash],
            ["BASIS", dash, dash, dash, usd(self.basis), dash],
        ]
        t3 = [
            [
                r["name"],
                r["cadence"],
                f"{r['count']} items, avg {usd(r['avg'])}",
                usd(r["total"]) + (f" (CV {r['cv']})" if r["cv"] is not None else ""),
                f"{pct(r['share'])} of included revenue; in {r['present']} of {len(self.months)} months",
            ]
            for r in self.stream_rows
        ] or [["None", dash, dash, dash, dash]]
        t4 = []
        for p in self.positions:
            last = p.cleared[-1].date if p.cleared else None
            f = p.fundings[-1] if p.fundings else None
            fdate = (
                mdy(self.by_id[f["credit"]].date)
                if f
                else "Pre-file" if p.prefile else "Not found"
            )
            famt = usd(self.by_id[f["credit"]].amt) if f else dash
            notes = [p.status]
            for fx in p.fundings:
                c = self.by_id[fx["credit"]]
                notes.append(
                    f"{fx['confidence']} {fx['points']} pts: {mdy(c.date)} {usd(c.amt)} -> "
                    f"{fx['trigger']['kind']} {mdy(fx['trigger']['date'])}, {fx['bd_gap']} bd, "
                    f"gate {self.gate[c.id]['kind']}"
                )
            for s in self.searches:
                if s["anchor"] in {tr["trigger_id"] for tr in p.triggers} and s[
                    "outcome"
                ].startswith(("AMBIGUOUS", "best")):
                    c = self.by_id[s["candidates"][0]["txn_id"]]
                    notes.append(
                        f"Possible {mdy(c.date)} {usd(c.amt)} ({s['candidates'][0]['confidence']}); "
                        f"{s['outcome'].split(':')[0]}"
                    )
            if f and p.live:
                paid = sum(
                    (
                        t.amt
                        for t in p.cleared
                        if t.date >= self.by_id[f["credit"]].date
                    ),
                    D(0),
                )
                rem = self.by_id[f["credit"]].amt * PAYBACK_FACTOR - paid
                notes.append(
                    f"Est. remaining {usd(rem)} (1.4x model, unverified); counted live"
                )
            elif p.live:
                notes.append("Balance unknown, counted live")
            notes += [n for n in p.notes if not n.startswith("Provisional")]
            if p.cadence == "PROVISIONAL":
                notes.append("provisional stress cost max debit x20")
            cad = f"{p.cadence.title()} {usd(p.level)}"
            t4.append(
                [
                    p.display,
                    fdate,
                    famt,
                    cad,
                    mdy(last) if last else dash,
                    "Y" if p.live else "N",
                    "; ".join(notes),
                    usd(p.cost),
                ]
            )
            for e in p.events:
                t4.append(
                    [
                        f"↳ {mdy(e['date'])} {e['kind']}",
                        dash,
                        dash,
                        e["change"],
                        dash,
                        dash,
                        e["detail"],
                        dash,
                    ]
                )
        if not self.positions:
            t4.append(["None"] + [dash] * 7)
        hold = self.stack / self.basis if self.basis and self.basis > 0 else None
        t4 += [
            ["Total Live Stack"] + [dash] * 6 + [usd(self.stack)],
            ["Holdback % of Basis"] + [dash] * 6 + [pct(hold)],
        ]
        pw = self.peak_week
        cm, cw, cd = self.stack, self.cur_weekly, self.stack / BUSINESS_DAYS_PER_MONTH
        n_live = sum(p.live for p in self.positions)
        if pw:
            pm = pw["weekly"] * WEEKS_PER_MONTH
            mk = (pw["monday"].year, pw["monday"].month)
            rev = self.month_rows.get(mk, {}).get("true")
            detail = f"week of {mdy(pw['monday'])}; {len(pw['funders'])} positions; {', '.join(pw['funders'])}"
            if pw["latest"]:
                detail += "; Observed peak is latest full week"
            drop_detail = (
                f"Peak Holdback {pct(pm / rev) if rev else dash} of {mon(mk)} revenue"
            )
            if pw["weekly"] < cw:
                drop_detail += (
                    f"; Current exceeds observed peak by {usd(cw - pw['weekly'])}/wk"
                )
            t4b = [
                [
                    "Peak Handled",
                    usd(pm),
                    usd(pw["weekly"]),
                    usd(pm / BUSINESS_DAYS_PER_MONTH),
                    detail,
                ],
                [
                    "Current Live Stack",
                    usd(cm),
                    usd(cw),
                    usd(cd),
                    f"{n_live} live positions",
                ],
                [
                    "Drop Since Peak",
                    usd(pm - cm),
                    usd(pw["weekly"] - cw),
                    usd(pm / BUSINESS_DAYS_PER_MONTH - cd),
                    drop_detail,
                ],
            ]
        else:
            t4b = [
                [
                    "Peak Handled",
                    dash,
                    dash,
                    dash,
                    "No fully covered week with MCA debits",
                ],
                [
                    "Current Live Stack",
                    usd(cm),
                    usd(cw),
                    usd(cd),
                    f"{n_live} live positions",
                ],
                ["Drop Since Peak", dash, dash, dash, "Observed peak unavailable"],
            ]
        t5 = [
            [r["label"], usd(r["avg"]), r["basis"], "Yes" if r["ambiguous"] else "No"]
            for r in self.ob_rows
        ]
        t5 += (
            [["Total Average Obligations", usd(self.total_ob), dash, dash]]
            + [[f"Room {k}", usd(self.room[k]), dash, dash] for k in "ABC"]
            + [
                [
                    "Room D",
                    usd(self.room["D"]),
                    (
                        f"worst month {mon(self.worst_month)}"
                        if self.worst_month
                        else dash
                    ),
                    dash,
                ]
            ]
        )

        def tier(m):
            if m is None:
                return [dash] * 4
            return [
                usd(m),
                usd(m / WEEKS_PER_MONTH),
                usd(m / BUSINESS_DAYS_PER_MONTH),
                pct(m / self.basis) if self.basis and self.basis > 0 else dash,
            ]

        t6 = [
            ["HEADLINE (min B,C)"] + tier(self.headline),
            ["CONSERVATIVE (min C,D)"] + tier(self.conservative),
            ["Binding Constraint", self.binding, dash, dash, dash],
        ]
        t7 = [
            [
                mdy(e["date"]),
                e["who"],
                usd(e["amt"]),
                e["cls"],
                e["tier"],
                e["desc"],
                e["cured"],
            ]
            for e in self.t7
        ] or [["None"] + [dash] * 6]
        h = self.headline
        t8 = [
            [
                self.status,
                usd(h),
                usd(h / WEEKS_PER_MONTH) if h is not None else dash,
                usd(h / BUSINESS_DAYS_PER_MONTH) if h is not None else dash,
                self.binding,
            ]
        ]
        a_ev = [e for e in self.t7 if e["cls"] == "A"]
        tiers = Counter(e["tier"] for e in a_ev)
        od = sorted(self.od_days)
        low = min(
            ((b, d, a) for a, days in self.eod.items() for d, b in days.items()),
            default=None,
        )
        big = max(self.flights, key=lambda f: f["outflow"]) if self.flights else None
        fee_months = sorted({mon(t.month) for t in self.fees})
        t9 = [
            [
                "Overdraft days",
                str(len(od)),
                ", ".join(map(mdy, od[:6])) + (" ..." if len(od) > 6 else "") or "None",
            ],
            [
                "Returned/NSF debit events",
                str(len(a_ev)),
                f"Class A: T1 {tiers['T1']}, T2 {tiers['T2']}, T3 {tiers['T3']}",
            ],
            [
                "NSF/OD fees",
                f"{len(self.fees)}, {usd(sum((t.amt for t in self.fees), D(0)))}",
                ", ".join(fee_months) or "None",
            ],
            [
                "Days below THIN_BALANCE",
                (
                    str(sum(v < self.thin for v in self.combined.values()))
                    if self.combined
                    else dash
                ),
                f"threshold {usd(self.thin)}; combined end-of-day, business days",
            ],
            [
                "Lowest balance",
                usd(low[0]) if low else dash,
                (
                    f"{mdy(low[1])}, account ...{self.accts[low[2]]['last4']}"
                    if low
                    else "balances unavailable"
                ),
            ],
            [
                "FLIGHT events",
                str(len(self.flights)),
                (
                    f"largest: {mdy(big['date'])}, {usd(big['inflow'])} in, {usd(big['outflow'])} out"
                    if big
                    else "None"
                ),
            ],
        ]
        return [t1, t2, t3, t4, t4b, t5, t6, t7, t8, t9]

    def render(self):
        out = []
        for (title, header), rows in zip(SPEC, self.tables()):
            out += [
                f"### {title}",
                "",
                "| " + " | ".join(header) + " |",
                "| " + " | ".join([":---"] * len(header)) + " |",
            ]
            for r in rows:
                require(
                    len(r) == len(header),
                    f"{title}: row width {len(r)} != {len(header)}",
                )
                out.append("| " + " | ".join(cell(c) for c in r) + " |")
            out.append("")
            if title.startswith("Table 2 "):
                out += [f"**Core Operation:** {cell(self.lines['core'])}", ""]
            if title.startswith("Table 8 "):
                out += [
                    f"- **WILL-PAY READ:** {cell(self.lines['will'])}",
                    f"- **Peak MCA Load:** {cell(self.lines['peak'])}",
                    f"- **What Would Flip This:** {cell(self.lines['flip'])}",
                    "",
                    "Capacity test with return/OD exception log. Not a fund recommendation.",
                    "",
                ]
        return "\n".join(out)

    def audit(self):
        return dict(
            engine_version=ENGINE_VERSION,
            policy_version=POLICY_VERSION,
            ledger_sha256=self.sha,
            data_end=self.end,
            live_window_start=self.live_start,
            worst_integrity=self.worst,
            months=[
                dict(
                    month=mon(k),
                    days=self.days[k],
                    counted=k in self.counted,
                    **self.month_rows[k],
                )
                for k in self.months
            ],
            capacity=dict(
                tor=self.tor,
                last3=self.last3,
                basis=self.basis,
                live_stack=self.stack,
                total_obligations=self.total_ob,
                rooms=self.room,
                headline=self.headline,
                conservative=self.conservative,
                binding=self.binding,
                status=self.status,
            ),
            positions=[
                dict(
                    pid=p.pid,
                    display=p.display,
                    funder=p.funder,
                    status=p.status,
                    cadence=p.cadence,
                    level=p.level,
                    monthly_cost=p.cost,
                    live=p.live,
                    prefile=p.prefile,
                    terminated=p.terminated,
                    tag_source=p.source,
                    debit_ids=[t.id for t in p.txns],
                    cleared_ids=[t.id for t in p.cleared],
                    events=p.events,
                    triggers=p.triggers,
                    fundings=p.fundings,
                    notes=p.notes,
                )
                for p in self.positions
            ],
            backward_searches=self.searches,
            forward_searches=self.forward,
            peak_week=self.peak_week,
            returns=self.t7,
            flights=self.flights,
            transactions=[
                dict(
                    txn_id=t.id,
                    tag=t.tag,
                    tag_source=t.tag_source,
                    flags=t.flags,
                    returned_by=t.returned_by,
                )
                for t in self.txns
            ],
            questions_answered=sorted(self.answers),
            questions_open=sorted(
                q["question_id"]
                for q in self.questions
                if q["question_id"] not in self.answers
            ),
            narrative=self.lines,
            self_checks=self.checks,
        )


SPEC = [
    (
        "Table 1 — Coverage & Integrity",
        [
            "Account",
            "Months Covered",
            "Months Counted",
            "Missing/Partial",
            "Balance Reconstruction (Pass/Break)",
            "Notes",
        ],
    ),
    (
        "Table 2 — Monthly Revenue",
        [
            "Month",
            "Days Counted",
            "Gross Credits",
            "Stripped Inflows",
            "True Revenue",
            "Counted?",
        ],
    ),
    (
        "Table 3 — Primary Revenue-Streams Breakdown",
        [
            "Stream/Descriptor",
            "Cadence",
            "Volume/Frequency",
            "Total Inflow Amount [CV]",
            "Notes",
        ],
    ),
    (
        "Table 4 — Live Stack",
        [
            "Position/Funder",
            "Funding Date",
            "Funding Amount",
            "Cadence/Payment",
            "Last Debit",
            "Live?",
            "Notes",
            "Monthly Cost",
        ],
    ),
    ("Table 4b — Peak MCA Load", ["Metric", "Monthly", "Weekly", "Daily", "Detail"]),
    (
        "Table 5 — Obligations",
        ["Category", "Monthly Avg", "Basis (Counterparty/Evidence)", "Ambiguous?"],
    ),
    (
        "Table 6 — Payment Ceiling",
        ["Metric / Tier", "Monthly", "Weekly", "Daily", "% of Basis"],
    ),
    (
        "Table 7 — RETURN/OD/BOUNCE Log",
        [
            "Date",
            "Item / Counterparty",
            "Amount",
            "Class",
            "Tier",
            "Descriptor",
            "Cured (≤2bd)?",
        ],
    ),
    (
        "Table 8 — Conclusion",
        [
            "CAN THEY PAY",
            "Max Monthly Payment",
            "Max Weekly Payment",
            "Max Daily Payment",
            "Binding Constraint",
        ],
    ),
    ("Table 9 — Liquidity Stress", ["Metric", "Value", "Date/Detail"]),
]


def cell(s):
    """Sanitize one Markdown cell: no pipes, braces or line breaks; never empty."""
    s = re.sub(
        r"\s+", " ", str(s).replace("|", "/").replace("{", "(").replace("}", ")")
    ).strip()
    return s or "—"


def jsonable(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))


def legacy_gate(report_text):
    """Run the unchanged V2.2 report validator as a secondary format gate."""
    path = (
        Path(__file__).resolve().parent.parent / "legacy" / "validate_uw_report_v2_2.py"
    )
    spec = importlib.util.spec_from_file_location("legacy_validator", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.validate(mod.parse_report(report_text))
    except mod.ReportError as e:
        raise UWError(f"legacy report gate failed: {e}")
    return "PASS"


def run(ledger_path, out_dir, judgments_path=None):
    raw = Path(ledger_path).read_bytes()
    judgments = (
        json.loads(Path(judgments_path).read_text(encoding="utf-8"))
        if judgments_path
        else None
    )
    e = Engine(raw, judgments)
    report = e.render()
    audit = e.audit()
    audit["legacy_report_gate"] = legacy_gate(report)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    qdoc = dict(
        ledger_sha256=e.sha,
        policy_version=POLICY_VERSION,
        owner_names=e.owners,
        documents=list(e.docs.values()),
        questions=e.questions,
    )
    (out / "questions.json").write_text(
        json.dumps(qdoc, indent=2, default=jsonable), encoding="utf-8"
    )
    (out / "audit.json").write_text(
        json.dumps(audit, indent=2, default=jsonable), encoding="utf-8"
    )
    (out / "report.md").write_text(report, encoding="utf-8")
    return e


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ledger")
    ap.add_argument("--out", required=True)
    ap.add_argument("--judgments")
    args = ap.parse_args(argv)
    try:
        e = run(args.ledger, args.out, args.judgments)
    except (OSError, UWError, json.JSONDecodeError) as err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1
    open_q = len(e.questions) - len(e.answers)
    print(
        f"OK: {e.status}; HEADLINE {usd(e.headline)}/mo; {len(e.checks)} self-checks passed; "
        f"legacy report gate PASS; {open_q} question(s) open"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
