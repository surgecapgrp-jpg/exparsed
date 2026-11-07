#!/usr/bin/env python3
"""MCA capacity underwriting engine. Policy V1.7 (batches 1 to 3 over the V2.2 engine), engine V3.3.

V1.7 batch 1 (docs/V1_7_MATRIX.md): unanswered candidate credits are STRIP_UNRESOLVED;
Table 4 status is Y/N/U and only closure evidence makes N; material U positions block YES and
unresolved credits block only a NO they could reverse (sign-off B2); weeks and biweeks per month are exactly 52/12 and 26/12;
Pre-file needs evidence, so the engine no longer infers it.

V1.7 batch 2: debit-first sweep (D1 name/ID, D2 cadence, D3 same amount under another
payee, D4 new payee after a financing credit, D5 returned attempts) with a disposition for
every nominated debit; unresolved finance-looking payees are WATCH rows (U); payee groups
merge into one position only on a shared originator ID or sequential continuity; backward
and forward searches add a +/-30 calendar-day INVESTIGATE window; monthly cadence; evidence
levels; completeness metrics.

V1.7 batch 3: calendar months for every account and 18 days per material account;
unreadable files inventoried; unprovided accounts from transfer text (REQUEST REQUIRED, VERIFY
OWNERSHIP) gate the verdict when material; commingling per account-month; credit-line transfers
are debt service; Class UNKNOWN returns; Commingling and Additional Accounts lines in Table 8.

Code computes every number in the report from ledger rows. The LLM answers
only the questions this engine writes to questions.json (prompt: prompts/judge.md).
Answers are checked here: enums, question IDs, ledger hash, and every evidence
quote must appear verbatim in a transaction description or a supplied document.

Usage:
  python engine/uw.py LEDGER.json --out DIR [--judgments JUDGMENTS.json]

Writes DIR/questions.json, DIR/audit.json, DIR/report.md. Exit 0 on success,
1 on bad input or a failed self-check, 2 on usage error.
"""

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
ENGINE_VERSION = "3.4"
POLICY_VERSION = "V1.7b11"

# Policy parameters (V2.2 values with the V1.7 changes marked). Changing any value is a policy change: bump POLICY_VERSION.
BUSINESS_DAYS_PER_MONTH = D(20)
WEEKS_PER_MONTH = D(52) / D(12)  # V1.7: exact, rounded only for display
BIWEEKS_PER_MONTH = D(26) / D(12)
FULL_MONTH_DAYS = 18
LIVE_WINDOW_BD = 10
PROLONGED_SILENCE_BD = 30  # V1.7: covered business days without collections before Y becomes U
MATERIAL_SHARE = D("0.05")  # V1.7: an uncertainty is material at >=5% of BASIS (operational policy)
FUNDING_WINDOW_BD = 7
UNATTACHED_WINDOW_CAL = 14
EXPANDED_WINDOW_CAL = 30  # V1.7: investigation only, never attaches funding
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
FIXED_SHARE = D("0.8")   # share of payments in same-amount runs that makes a series fixed-amount
LARGE_DEPOSIT_MULTIPLE = 3  # a credit at this multiple of the median deposit is unusual
# Sign-off B1 (2026-11-07): an unresolved candidate credit under this amount is not material and keeps its rule tag.
UNRESOLVED_FLOOR = D("2500")
SCORE_NEAR_CAL = 3  # funding credit within this many calendar days of its first debit scores +1
THIN_BALANCE_DAYS = 3  # THIN_BALANCE = this many business days of the live stack's daily cost
# Business-day gap between debits -> cadence: <=2 daily, <=7 weekly, <=12 biweekly, 18 to 25 monthly.
GAP_DAILY_BD, GAP_WEEKLY_BD, GAP_BIWEEKLY_BD, GAP_MONTHLY_BD = 2, 7, 12, (18, 25)
# Credits per month -> revenue-stream cadence in Table 3.
STREAM_DAILY_PER_MONTH, STREAM_WEEKLY_PER_MONTH = 15, D("3.5")
# Commingling severity per account-month: High above 10 items or 15% of gross; Moderate at 3 items or MATERIAL_SHARE.
COMMINGLING_HIGH_ITEMS, COMMINGLING_HIGH_SHARE, COMMINGLING_MODERATE_ITEMS = 10, D("0.15"), 3

INTEGRITY = ("Pass", "Pass with flag", "Unverified", "Break")  # best to worst
WORST_ORDER = INTEGRITY[::-1]
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
    "STRIP_UNRESOLVED",  # V1.7: excluded from revenue for lack of evidence; not a funding claim
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
# V1.7 execution order; the V3 handoff stage manifest reports one entry per stage.
STAGES = (
    "inventory/routes/coverage", "normalize/dedupe/reconcile", "account links and provisional tags",
    "debit-first MCA discovery", "credit-first funding discovery", "event/renewal discovery",
    "candidate-pair reconciliation", "finalized tags and position status",
    "revenue, costs, returns, liquidity, capacity", "MCA completeness audit", "render and validate ten tables",
)
CREDIT_DISPOSITIONS = ("ATTACHED", "FINANCING_UNATTACHED", "COMPETING", "CUSTOMER_SUPPORTED", "OTHER_SUPPORTED", "UNRESOLVED")
HARD_STRIP = {"STRIP_TRANSFER", "STRIP_REFUND", "STRIP_RECREDIT", "STRIP_OWNER"}
# V1.7 evidence level of a STRIP_FUNDING gate.
GATE_LEVEL = {
    "bank_text": "OBSERVED",
    "document": "CORROBORATED",
    "named_funder_series": "CORROBORATED",
    "sender_identified": "INFERRED",
}
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
    "monthly": D(1),
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
# V1.7 D1 also finds finance words run into a longer token (HEADWAYCAPITAL).
MCA_WORD_INSIDE = re.compile(r"CAPITAL|FUNDING|FINANC|LENDING|ADVANCE|MERCHANT")
ORIG_CO = re.compile(r"ORIG CO NAME:\s*(.*?)\s+ORIG ID")
# Printed IDs, masked or not: "ORIG ID: 1234567890", "ORIG ID **318418", "TRACE# **704849".
ORIG_ID = re.compile(r"ORIG ID:?\s*(\**[A-Z0-9]{4,})")
TRACE_ID = re.compile(r"TRACE(?:#|\s+(?:NO\.?|NUMBER))?:?\s*(\**[0-9]{4,})")
LEVY = rx("LEVY", "LIEN", r"GARNISH\w*")
# V1.7 section 9: masked account numbers in transfer text, financing accounts, possible personal use.
MASKED = re.compile(
    r"(?:\.{2,}|X{2,}|\*+)\s*(\d{4})\b|\b(?:CHK|CHECKING|SAV|SAVINGS|LOC|ACCT|ACCOUNT|LINE|CARD)\s*(?:NO\.?|#)?\s*(\d{4})\b"
)
FIN_ACCT = rx("LOC", "CREDIT LINE", "LINE OF CREDIT", "LOAN")
LINK_NOISE = re.compile(
    r"\b(?:ONLINE|REALTIME|REAL TIME|TRANSFER|XFER|TFR|TRNSFR|TO|FROM|ACH|ODP|OD|PROTECTION)\b"
)
P2P = rx("ZELLE", "VENMO", "CASH APP", "CASHAPP")
PERSONAL_HINT = rx(
    "GROCERY", "SUPERMARKET", "WHOLE FOODS", "TRADER JOE", "NETFLIX", "SPOTIFY", "HULU",
    "DISNEY PLUS", "AMAZON PRIME", "GYM", "SALON", "MORTGAGE", "HOA",
)
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
RETURN_CODE = re.compile(r"\bR\d\d\b")
NOISE = set(
    "ACH DEBIT CREDIT PPD CCD WEB TEL POS PURCHASE PMT PAYMENT ID REF TRN CO ENTRY DESCR IND ORIG DES "
    "CHECKCARD ONLINE ELECTRONIC WITHDRAWAL EPAY EPAYMENT RECURRING XXXXXX".split()
)
GENERIC = set(
    "LLC INC CORP CO CAPITAL FUNDING FUND GROUP FINANCIAL FINANCE ADV ADVANCE MERCHANT SOLUTIONS "
    "SERVICES PARTNERS BUSINESS LENDING HOLDINGS THE OF AND USA".split()
)


def policy_hash():
    """Hash of POLICY_VERSION and every policy number, name and word list; regex rules are named by pattern."""
    items = sorted(
        (k, v.pattern if isinstance(v, re.Pattern) else str(v))
        for k, v in globals().items()
        if k.isupper() and isinstance(v, (Decimal, int, str, tuple, dict, re.Pattern)) and k != "ENGINE_VERSION"
    )
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]


POLICY_HASH = policy_hash()


class UWError(Exception):
    pass


def require(ok, msg):
    if not ok:
        raise UWError(msg)


def norm(desc):
    """Payee key: uppercase letters only, ACH noise words and reference numbers removed.

    NACHA-style text ("ORIG CO NAME:<payee> ORIG ID ...") keys on the originator name alone.
    """
    m = ORIG_CO.search(desc.upper())
    words = [
        w
        for w in re.sub(r"[^A-Z& ]", " ", m.group(1) if m else desc.upper()).split()
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
    orig_id: str = ""
    trace_id: str = ""
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
    live: bool = False  # live_status == "Y"
    live_status: str = ""  # V1.7 Table 4: Y active, N closed on evidence, U unresolved
    status_basis: str = ""
    scenario: Decimal | None = None  # U only: plausible monthly cost, never in the stack
    adverse: Decimal | None = None  # VARIABLE only: highest 20 bd of cleared debits, reported, never in the stack
    material: bool = False
    watch: bool = False  # V1.7 UNRESOLVED WATCH: finance-looking payee, MCA identity unproved
    groups: list = field(default_factory=list)
    evidence: str = ""  # V1.7 evidence level
    terminated: str = ""
    terminated_date: date | None = None  # bank_text closure only; documents carry no engine-readable date
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
        if bd <= GAP_DAILY_BD
        else "weekly" if bd <= GAP_WEEKLY_BD else "biweekly" if bd <= GAP_BIWEEKLY_BD
        else "monthly" if GAP_MONTHLY_BD[0] <= bd <= GAP_MONTHLY_BD[1] else "irregular"
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


def fixed_share(cleared):
    """Share of payments inside same-amount runs of SUSTAIN_PAYMENTS or more."""
    if not cleared:
        return D(0)
    n = sum(len(r) for r in runs(cleared, lambda f, x: not changed(f.amt, x.amt)) if len(r) >= SUSTAIN_PAYMENTS)
    return D(n) / len(cleared)


def split_concurrent(ts):
    """Same payee debited twice on one day means concurrent contracts.

    Tracks open only when a day has more debits than open tracks. Each debit joins the
    nearest-amount track not yet used that day, so a level change stays inside its track.
    """
    # Concurrency needs SUSTAIN_PAYMENTS days whose debits differ by more than CHANGE_THRESHOLD,
    # or (V1.7 D8) same-amount doubles on SUSTAIN_PAYMENTS consecutive debit days. An isolated
    # same-amount double, such as the day after a holiday, is a catch-up payment.
    amounts = defaultdict(list)
    for t in ts:
        amounts[t.date].append(t.amt)
    doubled_run = max((len(r) for r in runs(sorted(amounts), lambda f, d: (len(amounts[f]) > 1) == (len(amounts[d]) > 1)) if len(amounts[r[0]]) > 1), default=0)
    if sum(changed(min(a), max(a)) for a in amounts.values()) < SUSTAIN_PAYMENTS and doubled_run < SUSTAIN_PAYMENTS:
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


class _Engine:
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
        self.crosscheck_exparsed()
        self.streams()
        self.obligations()
        self.account_links()
        self.account_requests()
        self.commingling()
        self.capacity()
        self.peak()
        self.returns_log()
        self.liquidity()
        self.narrative()
        self.completeness_audit()
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
        self.computed = led.get("exparsed_computed", [])
        require(isinstance(self.computed, list), "ledger: exparsed_computed must be a list")
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
            try:
                day = date.fromisoformat(r["date"])
            except (TypeError, ValueError):
                raise UWError(f"transaction {r['txn_id']}: bad date {r['date']!r}") from None
            self.txns.append(
                Txn(
                    r["txn_id"],
                    r["account_id"],
                    day,
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
        self.live_start = self.cal.add(self.end, 1 - LIVE_WINDOW_BD)  # V1.7 P5: 10 bd counting the end day
        self.acct_end = {aid: max(e for _, e in a["statements"]) for aid, a in self.accts.items()}
        for a, n in self.dropped.items():
            self.notes[a].append(f"{n} duplicate transaction id(s) dropped")

        # V1.7: revenue uses calendar posting months for every account, whatever the statement cycle.
        covered, self.acct_months = defaultdict(set), defaultdict(dict)
        for aid, a in self.accts.items():
            for s, e in a["statements"]:
                d = s
                while d <= e:
                    covered[(d.year, d.month)].add(d)
                    self.acct_months[aid].setdefault((d.year, d.month), set()).add(d)
                    d += timedelta(1)
        for t in self.txns:
            covered.setdefault(t.month, set())
        flagged = {
            tuple(map(int, m.split("-")))
            for a in self.accts.values()
            for m in a["flagged_months"]
        }
        self.months = sorted(covered)
        self.days = {k: len(covered[k]) for k in self.months}
        # V1.7 section 1: a month counts only with >=18 covered days on every material account whose
        # statement span includes it. A union of other accounts cannot stand in for a missing one.
        credits = Counter()
        for t in self.txns:
            if t.dir == "credit":
                credits[t.acct] += t.amt
        total = sum(credits.values(), D(0))
        self.material_accts = [aid for aid in self.accts if total and credits[aid] >= MATERIAL_SHARE * total]
        self.month_gaps = {}
        for k in self.months:
            short = []
            for aid in self.material_accts:
                st = self.accts[aid]["statements"]
                lo, hi = st[0][0], st[-1][1]
                first, last = date(k[0], k[1], 1), date(k[0] + k[1] // 12, k[1] % 12 + 1, 1) - timedelta(1)
                n = len(self.acct_months[aid].get(k, ()))
                if lo <= last and hi >= first and n < FULL_MONTH_DAYS:
                    short.append(f"...{self.accts[aid]['last4']} {n} days")
            if short:
                self.month_gaps[k] = short
        self.counted = [
            k
            for k in self.months
            if self.days[k] >= FULL_MONTH_DAYS and k not in flagged and k not in self.month_gaps
        ]
        for k in self.months:
            if self.days[k] >= FULL_MONTH_DAYS and k in self.month_gaps:
                self.notes[self.material_accts[0]].append(
                    f"{mon(k)} not counted: " + ", ".join(self.month_gaps[k]) + " covered"
                )
        # V1.7 section 1: supplied files the extraction could not read stay in the inventory.
        self.unread = led.get("sources_unread", [])
        # V1.7 S3: pending rows are reported as observations and never enter totals.
        self.pending = led.get("pending_observations", [])
        self.sources = led.get("sources", [])
        self.crosswalk = led.get("duplicate_crosswalk", [])  # V1.7 S7  # V1.7 R1: per-file records from the adapter, reported as given
        for o in self.pending:
            require(o.get("account_id") in self.accts, f"pending observation: unknown account {o.get('account_id')!r}")
        require(isinstance(self.unread, list), "ledger: sources_unread must be a list")
        self.worst = next(
            x
            for x in WORST_ORDER
            if any(a["integrity"] == x for a in self.accts.values())
        )

    def month_key(self, t):
        return t.month

    # ---- 2. provisional classification ------------------------------------------------------------
    def classify(self):
        for t in self.txns:
            t.norm, u = norm(t.desc), t.desc.upper()
            m = ORIG_ID.search(u)
            t.orig_id = m.group(1) if m else ""
            m = TRACE_ID.search(u)
            t.trace_id = m.group(1) if m else ""
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
        if self.owner_rx and self.owner_rx.search(u):
            return "OWNER_DRAW"  # V1.7: a transfer to the owner is an owner/personal item
        if TRANSFER.search(u) or OD_XFER.search(u):
            # V1.7: a transfer paying a credit line or loan account is established non-MCA financing.
            return "DEBT_SERVICE" if FIN_ACCT.search(u) else "TRANSFER_OUT"
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
        # V1.7 D1 to D5 sweep every debit not already tagged by a supported rule; manual transfers included.
        for t in self.txns:
            if t.dir == "debit" and t.tag in ("OTHER", "DEBT_SERVICE", "TRANSFER_OUT"):
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
            regular = regular and fixed >= FIXED_SHARE * len(all_cleared)
            word = bool(MCA_WORD.search(name) or MCA_WORD_INSIDE.search(name))
            early = (
                0 < len(cleared) < SERIES_MIN_DEBITS
                and word
                and cleared[-1].date >= self.live_start
            )
            default_mca = (regular and (word or cadence == "daily")) or early
            passes = (["D1 finance word in payee"] if word else []) + (
                [f"D2 {cadence} cadence, {len(cleared)} cleared"] if regular else []
            ) + (
                ["D5 returned attempt"] if word and any(t.returned_by for t in ts) else []
            )
            self.groups[name] = dict(
                txns=ts,
                cleared=cleared,
                cadence=cadence,
                regular=regular,
                default_mca=default_mca,
                cleared_count=len(all_cleared),
                word=word,
                passes=passes,
                orig_ids={t.orig_id for t in ts if t.orig_id},
                ask=len(ts) >= 3 or word or default_mca,
                mca=default_mca,
                answered=False,
                funder=name,
                tag=ts[0].tag,
                source="default",
                terminated="",
            )
        self.sweep_links()

    def sweep_links(self):
        """V1.7 D3 and D4: payees linked to a default MCA series by amount, or to a financing credit by timing."""
        series = [g for g in self.groups.values() if g["default_mca"] and g["cleared"]]
        for name, h in self.groups.items():
            if h["default_mca"]:
                continue
            for g in series:
                level = Counter(t.amt for t in g["cleared"]).most_common(1)[0][0]
                lo = g["cleared"][0].date - timedelta(EXPANDED_WINDOW_CAL)
                hi = g["cleared"][-1].date + timedelta(EXPANDED_WINDOW_CAL)
                hit = [t for t in h["cleared"] if t.amt == level and lo <= t.date <= hi]
                # Sign-off B9 (2026-11-07): 2 same-amount debits link, however busy the payee. One never does.
                if len(hit) >= 2:
                    h["passes"].append(f"D3 same amount {usd(level)} as {g['funder']}")
                    h["ask"] = True
                    break
        fin = [
            t for t in self.txns
            if t.dir == "credit" and EXPLICIT_FIN.search(t.desc.upper()) and t.tag not in HARD_STRIP
        ]
        for name, h in self.groups.items():
            if h["default_mca"] or not h["cleared"]:
                continue
            first = h["txns"][0].date
            src = next((c for c in fin if c.date <= first <= c.date + timedelta(EXPANDED_WINDOW_CAL)), None)
            # A new payee after a financing credit is linked only by a repeating collection or a shared name.
            gaps = [self.cal.diff(a.date, b.date) for a, b in zip(h["cleared"], h["cleared"][1:])]
            repeating = gaps and all(gap_class(x) in ("daily", "weekly", "biweekly") for x in gaps)
            if src and (repeating or set(name.split()) & set(src.norm.split())):
                h["passes"].append(f"D4 first debit {(first - src.date).days} days after financing credit {mdy(src.date)}")
                h["ask"] = True

    def established_revenue(self):
        seen = defaultdict(set)
        for t in self.txns:
            if t.dir == "credit" and t.tag.startswith("REV_"):
                seen[t.norm].add((t.id, t.month))
        return {
            n for n, s in seen.items() if len(s) >= 3 and len({m for _, m in s}) >= 2
        }

    def candidates(self, tokens):
        """Funding candidates: wires, new senders on other rails, explicit financing text, 3x median deposit, or a funder name."""
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
            # V1.7 C2: a sender seen fewer than 3 times over 2 months on ACH, transfer, deposit or check.
            # Unclear transfers are asked about in their own question.
            elif t.tag in ("REV_ACH", "REV_DEPOSIT") and t.norm not in self.established and "unclear_transfer" not in t.flags:
                why.append("new sender (ACH, transfer, deposit or check)")
            if EXPLICIT_FIN.search(u):
                why.append("explicit financing text")
            # Size alone does not make a recurring customer payer's deposit unusual.
            if (
                self.median
                and t.amt >= LARGE_DEPOSIT_MULTIPLE * self.median
                and t.norm not in self.established
            ):
                why.append(
                    f"{(t.amt / self.median).quantize(D('0.1'))}x median deposit"
                )
            names = [f for f, toks in tokens.items() if has_token(u, toks)]
            if names:
                why.append("names funder " + ", ".join(sorted(names)))
            if t.norm in self.groups:
                why.append(f"same counterparty as debits to {t.norm}")
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
            ][:5]
            qs.append(
                dict(
                    question_id=qid("credit", [t.id]),
                    type="credit",
                    txn_ids=[t.id],
                    transactions=[self.txn_view(t)],
                    why=why + near,
                    default="STRIP_UNRESOLVED",
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
                    default="STRIP_UNRESOLVED",
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
                    cleared=g["cleared_count"],
                    cadence=g["cadence"],
                    amounts=sorted({str(t.amt) for t in ts})[:8],
                    first=ts[0].date.isoformat(),
                    last=ts[-1].date.isoformat(),
                    sample_descriptions=sorted({t.desc for t in ts})[:3],
                    why=g["passes"],
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
                    if ev["kind"] == "document":
                        ans["terminated"] = self.verify_quote(ev, [], what)
                    else:
                        # V1.7 L6: closure text must sit on one transaction of this payee or one naming its funder.
                        quote = str(ev.get("quote", "")).strip().upper()
                        own = {t.id for t in self.groups[q["descriptor"]]["txns"]}
                        tok = funder_tokens(ans.get("funder") or q["descriptor"])
                        hits = [
                            t for t in self.txns
                            if quote and quote in t.desc.upper() and (t.id in own or has_token(t.desc, tok))
                        ]
                        require(hits, f"{what}: closure quote not on a transaction of this position or naming its funder")
                        ans["terminated"] = self.verify_quote(ev, [hits[-1].desc], what)
                        ans["terminated"]["date"] = hits[-1].date
                out[q["question_id"]] = ans
        return out

    def apply_debit_answers(self):
        for q in self.questions:
            a = self.answers.get(q["question_id"])
            if q["type"] != "debit_group" or not a:
                continue
            g = self.groups[q["descriptor"]]
            g["source"] = "judgment"
            g["answered"] = True
            g["mca"] = a["tag"] == "MCA"
            g["funder"] = a.get("funder", g["funder"]).upper()
            g["tag"] = a["tag"]
            if a.get("terminated"):
                g["terminated"] = a["terminated"]["quote"]
                g["terminated_date"] = a["terminated"].get("date")
            if not g["mca"]:
                for t in g["txns"]:
                    t.tag, t.tag_source = a["tag"], "judgment"

    # ---- 5. MCA positions, events, live status ----------------------------------------------------
    def build_positions(self):
        self.positions, self.join_basis = [], {}
        # V1.7: a funder name alone never joins payee groups. Groups of one funder merge only on a
        # shared originator ID, or when one starts within REFI_GAP_BD after the other stops.
        by_funder = defaultdict(list)
        for name, g in sorted(self.groups.items(), key=lambda kv: (kv[1]["txns"][0].date, kv[0])):
            if g["mca"]:
                by_funder[g["funder"]].append((name, g))
        clusters = []
        for funder, groups in by_funder.items():
            mine = []
            for name, g in groups:
                into = next(
                    (
                        cl for cl in mine
                        if self.same_position(cl, g)
                    ),
                    None,
                )
                if into is None:
                    mine.append([(name, g)])
                else:
                    into.append((name, g))
            clusters += mine
        for members in clusters:
            name, g = members[0]
            ts = sorted(
                (t for _, m in members for t in m["txns"]),
                key=lambda t: (t.date, t.seq),
            )
            if len(members) > 1:
                g = dict(
                    g,
                    terminated=next(
                        (m["terminated"] for _, m in members if m["terminated"]), ""
                    ),
                    terminated_date=next(
                        (m.get("terminated_date") for _, m in members if m["terminated"]), None
                    ),
                )
            tracks = split_concurrent(ts)
            if len(tracks) > 1 and any(fixed_share([t for t in tr if not t.returned_by]) < FIXED_SHARE for tr in tracks):
                tracks = [ts]   # variable remittance (share of sales) looks concurrent but is one contract
            for s in tracks:
                cleared = [t for t in s if not t.returned_by]
                p = Position(
                    f"P{len(self.positions) + 1}", g["funder"], name, s, cleared
                )
                p.terminated, p.terminated_date = g["terminated"], g.get("terminated_date")
                p.source = g["source"]
                p.groups = [n for n, _ in members]
                self.analyse(p)
                for n, m in members[1:]:
                    first = next((t for t in s if t.norm == n), None)
                    if first:
                        self.event(p, "DESCRIPTOR CHANGE", first, f"{name} to {n}", self.join_basis.get(n, ""))
                p.events.sort(key=lambda e: e["date"])
                for t in s:
                    t.tag = "MCA_" + re.sub(r"[^A-Z0-9]+", "_", p.funder).strip("_")
                    t.tag_source = g["source"]
                self.positions.append(p)
        # V1.7 UNRESOLVED WATCH: an unanswered finance-looking payee stays visible as a U row.
        for name, g in sorted(self.groups.items()):
            # Finance-looking: a finance word, a D3/D4 link, or a fixed daily/weekly/biweekly series.
            finance = (
                g["word"]
                or any(x.startswith(("D3", "D4")) for x in g["passes"])
                or (g["regular"] and g["cadence"] in ("daily", "weekly", "biweekly"))
            )
            if g["mca"] or g["answered"] or not finance or not g["cleared"]:
                continue
            p = Position(
                f"W{sum(x.watch for x in self.positions) + 1}",
                name if funder_tokens(name) - {"UNKNOWN"} else "UNKNOWN MCA-STYLE",
                name,
                g["txns"],
                [t for t in g["txns"] if not t.returned_by],
                watch=True,
                groups=[name],
            )
            p.source = "default"
            self.analyse(p)
            p.status, p.triggers = "UNRESOLVED WATCH", []
            for t in g["txns"]:
                t.flags.append("watch")
            self.positions.append(p)
        names = Counter(p.funder for p in self.positions)
        seen = Counter()
        for p in sorted(self.positions, key=lambda p: (p.txns[0].date, p.pid)):
            seen[p.funder] += 1
            p.display = (
                f"Unknown MCA-style #{seen[p.funder]}"
                if p.funder == "UNKNOWN MCA-STYLE"
                else p.funder + (f" #{seen[p.funder]}" if names[p.funder] > 1 else "")
            )
        # Different-name refinance hints (4E).
        for p in self.positions:
            if not p.cleared or p.watch:
                continue
            for o in self.positions:
                if (
                    o is not p
                    and not o.watch
                    and o.cleared
                    and o.funder != p.funder
                    and o.cleared[-1].date < p.cleared[0].date
                    and self.cal.diff(o.cleared[-1].date, p.cleared[0].date)
                    <= REFI_GAP_BD
                ):
                    p.notes.append(f"Possible refi of {o.funder}")
                    if p.live and o.live:
                        p.notes.append("Refi overlap, both counted")
        rank = {"Y": 0, "U": 1, "N": 2}
        self.positions.sort(key=lambda p: (rank[p.live_status], -p.cost, p.pid))

    def same_position(self, cluster, g):
        """V1.7: same judged funder plus a shared originator ID, sequential continuity, or open cadence slots."""
        dates = {t.date for _, m in cluster for t in m["cleared"]}
        last = max(dates) if dates else None
        first = min(dates) if dates else None
        mine = [t.date for t in g["cleared"]]
        if any(m["orig_ids"] & g["orig_ids"] for _, m in cluster):
            why = "shared originator ID"
        elif mine and last and last < mine[0] and self.cal.diff(last, mine[0]) <= REFI_GAP_BD:
            why = "sequential continuity"
        elif mine and first and first <= mine[0] and mine[-1] <= last and not dates & set(mine):
            why = "debits fill open slots of the same funder's series"
        else:
            return False
        self.join_basis[next(n for n, x in self.groups.items() if x is g)] = why
        return True

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
        end = self.acct_end[(c or p.txns)[-1].acct]  # coverage end of the debit account
        observed = bool(c) and c[-1].date >= self.cal.add(end, 1 - LIVE_WINDOW_BD)
        variable = standard and fixed_share(c) < FIXED_SHARE
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
            # V1.7: Pre-file needs a source; nearness to coverage start is only a note.
            if normal is not None and self.cal.diff(start_cov, c[0].date) <= 2 * normal:
                p.notes.append("Debits start near coverage start; funding may precede coverage (unproven)")
            trig("START", c[0])
        if variable:
            # Share-of-sales remittance: cost is the cleared debits of 20 business days, not a level x factor.
            # The window ends at coverage end while collections are current, else at the last debit.
            w_end = end if observed else c[-1].date
            lo = self.cal.add(w_end, -int(BUSINESS_DAYS_PER_MONTH))
            recent = [t.amt for t in c if t.date > lo]
            p.cadence, p.status = "VARIABLE", "CONFIRMED"
            p.level = sum(recent, D(0)) / len(recent) if recent else D(0)
            p.cost = sum(recent, D(0))
            p.notes.append(f"Variable remittance: cost = cleared debits in the 20 bd to {mdy(w_end)}")
            # V1.7 D11: a separate adverse scenario, the highest 20 bd of cleared debits in the series.
            p.adverse = max(
                sum((x.amt for x in c if self.cal.add(t.date, -int(BUSINESS_DAYS_PER_MONTH)) < x.date <= t.date), D(0))
                for t in c
            )
            if p.adverse > p.cost:
                p.notes.append(f"Variable remittance: adverse scenario {usd(p.adverse)}/mo (highest 20 bd), not in stack")
            if self.cal.diff(c[-1].date, end) > 2 * normal:
                self.event(p, "STOPPED", c[-1], f"No debit for {self.cal.diff(c[-1].date, end)} bd",
                           "no payoff debit seen")
        elif standard:
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
                    if g <= REFI_GAP_BD:
                        # V1.7 M14: the same funder resuming within REFI_GAP_BD of the stop.
                        self.event(p, "PROBABLE RENEWAL", b, f"resumed {g} bd after the stop",
                                   "same funder within 10 bd; check for a new funding credit")
            if self.cal.diff(c[-1].date, end) > 2 * normal:
                self.event(
                    p,
                    "STOPPED",
                    c[-1],
                    f"No debit for {self.cal.diff(c[-1].date, end)} bd",
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
        self.set_status(p, end, observed)
        p.events.sort(key=lambda e: e["date"])

    def covered_bd(self, acct, after, end):
        """Business days after `after` through `end` that fall inside the account's statements."""
        spans = self.accts[acct]["statements"]
        return sum(
            1
            for i in range(1, (end - after).days + 1)
            if self.cal.is_bd(d := after + timedelta(i)) and any(s <= d <= e for s, e in spans)
        )

    def set_status(self, p, end, observed):
        """V1.7 Table 4 status. Only closure evidence makes N; silence or an estimated payoff never does."""
        c = p.cleared
        after = [t for t in c if p.terminated_date and t.date > p.terminated_date]
        if p.watch:
            st, basis = "U", "WATCH: MCA identity unproved (" + "; ".join(self.groups[p.group]["passes"]) + ")"
        elif p.terminated and not after:
            st, basis = "N", f"Closed per evidence: {p.terminated}"
        elif not c:
            st, basis = "U", "No cleared collection"
        elif p.cadence == "PROVISIONAL":
            st, basis = "U", f"Cadence unverified ({len(c)} cleared); STRESS scenario = max debit x20"
        elif observed:
            st, basis = "Y", f"Observed: cleared collection within {LIVE_WINDOW_BD} bd of coverage end"
        elif (silent := self.covered_bd(c[-1].acct, c[-1].date, end)) <= PROLONGED_SILENCE_BD:
            st, basis = "Y", f"Assumed open; collections absent {silent} covered bd; last sustained cost carried"
        else:
            st, basis = "U", f"Collections absent {silent} covered bd; no closure evidence"
        if after:
            basis += f"; closure text {mdy(p.terminated_date)} ignored: {len(after)} cleared debit(s) after it"
        p.live_status, p.status_basis, p.live = st, basis, st == "Y"
        if st == "U":
            p.scenario = p.cost  # last sustained (or STRESS) monthly cost, shown as a scenario only
        if st != "Y":
            p.cost = D(0)

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
            if q["type"] != "credit":
                continue
            for i in q["txn_ids"]:
                t = self.by_id[i]
                if not a:  # V1.7: unanswered candidate credits stay out of revenue, from UNRESOLVED_FLOOR up (B1)
                    if t.amt >= UNRESOLVED_FLOOR:
                        t.tag, t.tag_source = "STRIP_UNRESOLVED", "default"
                    continue
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
            # V1.7 expanded window: +/-30 calendar days outside the primary window, INVESTIGATE only.
            xlo, xhi = tr["date"] - timedelta(EXPANDED_WINDOW_CAL), tr["date"] + timedelta(EXPANDED_WINDOW_CAL)
            wide = [
                dict(sc, after_trigger=c.date > tr["date"])
                for c in credits
                if xlo <= c.date <= xhi and not (lo <= c.date <= tr["date"])
                and (sc := self.score(c, pos[tr["position"]], tr))["points"] >= 3
            ]
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
                    expanded_window=[xlo, xhi],
                    expanded=wide,
                    expanded_outcome=(
                        f"INVESTIGATE: {len(wide)} MED/HIGH credit(s); "
                        f"{sum(w['after_trigger'] for w in wide)} after the trigger (contradiction if funding)"
                        if wide
                        else "searched; none"
                    ),
                )
            )
        # Proposals: best gated credit per trigger; ties or cross-position reuse become AMBIGUOUS.
        proposal = {}
        for tr in triggers:
            found = pairs[tr["trigger_id"]]
            s = next(x for x in self.searches if x["anchor"] == tr["trigger_id"])
            if not found:
                s["outcome"] = s["outcome"] or "searched; none qualifies"
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
                        + (
                            "excluded from revenue (STRIP_UNRESOLVED; not called financing)"
                            if c.tag == "STRIP_UNRESOLVED"
                            else f"kept as {c.tag}; True Revenue sensitivity {usd(c.amt)}"
                        )
                    )
            wide = [
                tr["trigger_id"]
                for tr in triggers
                if abs((tr["date"] - c.date).days) <= EXPANDED_WINDOW_CAL and tr not in hits
            ]
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
                    v17_disposition=self.credit_disposition(c, outcome),
                    gate=self.gate.get(cid),
                    evidence=GATE_LEVEL[self.gate[cid]["kind"]] if cid in self.gate else "UNKNOWN",
                    expanded_triggers=wide,
                    expanded_outcome=f"INVESTIGATE: {len(wide)} trigger(s) within {EXPANDED_WINDOW_CAL} days" if wide else "searched; none",
                )
            )
        self.set_evidence()

    def credit_disposition(self, c, outcome):
        """V1.7 section 4 credit disposition."""
        if outcome == "Attached":
            return "ATTACHED"
        if c.id in self.gate:
            return "FINANCING_UNATTACHED" if outcome != "Competing/ambiguous" else "COMPETING"
        if outcome == "Competing/ambiguous":
            return "COMPETING"
        if c.tag == "STRIP_UNRESOLVED":
            return "UNRESOLVED"
        if c.tag.startswith("STRIP_"):
            return "OTHER_SUPPORTED"
        if c.tag_source == "judgment" or c.norm in self.established:
            return "CUSTOMER_SUPPORTED"
        return "UNRESOLVED"

    def set_evidence(self):
        """V1.7 evidence level per position: CORROBORATED > OBSERVED > INFERRED; WATCH is UNKNOWN."""
        for p in self.positions:
            gates = {self.gate[f["credit"]]["kind"] for f in p.fundings}
            if p.watch:
                p.evidence = "UNKNOWN"
            elif gates & {"bank_text", "document", "named_funder_series"} or (p.terminated and p.live_status == "N"):
                p.evidence = "CORROBORATED"
            elif any(self.groups[g]["word"] for g in p.groups):
                p.evidence = "OBSERVED"
            else:
                p.evidence = "INFERRED"

    def score(self, c, p, tr):
        u, pts, basis = c.desc.upper(), 0, []
        named = has_token(u, funder_tokens(p.funder))
        if named:
            pts += 3
            basis.append("+3 names funder")
        if EXPLICIT_FIN.search(u) or (WIRE.search(u) and (named or MCA_WORD_INSIDE.search(u))):
            # V1.7 M8: a wire scores only when it names the funder or carries finance wording.
            pts += 2
            basis.append("+2 explicit financing / finance wire")
        if self.median and c.amt >= LARGE_DEPOSIT_MULTIPLE * self.median:
            pts += 2
            basis.append(f"+2 >={LARGE_DEPOSIT_MULTIPLE}x median deposit")
        if 0 <= (tr["date"] - c.date).days <= SCORE_NEAR_CAL:
            pts += 1
            basis.append(f"+1 within {SCORE_NEAR_CAL} calendar days")
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
            cal_gap=(tr["date"] - c.date).days,
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
                gross=gross,
                stripped=stripped,
                top_strip=top,
                true=gross - stripped,
                unresolved=strips.get("STRIP_UNRESOLVED", D(0)),
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

    def crosscheck_exparsed(self):
        """Gross credits per account and calendar month against Exparsed's own computed figures.

        Both sides sum the same posted credits, so any difference means rows were dropped or
        doubled on the way here. A mismatch becomes a Table 1 note; the run continues.
        """
        compared, mismatches = 0, []
        for c in self.computed:
            a = self.accts.get(c.get("account"))
            if not a or c.get("partial"):
                continue  # Exparsed leaves a partial first day out of its sum
            k = tuple(map(int, c["month"].split("-")))
            ours = sum(
                (t.amt for t in self.txns if t.acct == c["account"] and t.dir == "credit" and t.month == k),
                D(0),
            )
            theirs = D(str(c["gross_inflows"]))
            compared += 1
            if ours != theirs:
                mismatches.append(dict(account=c["account"], month=c["month"], engine=ours, exparsed=theirs))
                self.notes[c["account"]].append(
                    f"Gross credits {mon(k)}: engine ${ours:,.2f}, Exparsed computed ${theirs:,.2f}; "
                    "rows were dropped or doubled before underwriting"
                )
        self.crosscheck = dict(months_compared=compared, mismatches=mismatches)

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
                "daily" if per >= STREAM_DAILY_PER_MONTH else "weekly" if per >= STREAM_WEEKLY_PER_MONTH else "irregular"
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

    def account_links(self):
        """V1.7 section 9: unprovided accounts named in transfer text, with flows, months and evidence."""
        mine = {a["last4"] for a in self.accts.values()}
        links, seen = {}, []
        for t in self.txns:
            u = t.desc.upper()
            if not (TRANSFER.search(u) or OD_XFER.search(u)) or t.returned_by:
                continue
            m = MASKED.search(u)
            digits = m and (m.group(1) or m.group(2))
            if digits in mine:
                continue  # a supplied account
            o = ORIG_CO.search(u)
            head = o.group(1) if o else re.split(r"\d|\*|TRANSACTION|REFERENCE|CONF|\.\.\.", u)[0]
            name = " ".join(re.sub(r"[^A-Z ]", " ", LINK_NOISE.sub(" ", head)).split()[:3])
            seen.append((t, digits, name))
        # A row without a printed number joins a numbered account with the same name.
        named = {nm: d for _, d, nm in seen if d and nm}
        for t, digits, name in seen:
            u = t.desc.upper()
            digits = digits or named.get(name)
            key = f"...{digits}" if digits else (name or "unidentified account")
            k = links.setdefault(
                key, dict(account=key, label=name, n_in=0, n_out=0, amt_in=D(0), amt_out=D(0), months=set(),
                          financing=False, txn_ids=[])
            )
            side = "in" if t.dir == "credit" else "out"
            k[f"n_{side}"] += 1
            k[f"amt_{side}"] += t.amt
            k["months"].add(t.month)
            k["financing"] |= bool(FIN_ACCT.search(u))
            k["txn_ids"].append(t.id)
        self.links = sorted(links.values(), key=lambda k: -(k["amt_in"] + k["amt_out"]))

    def account_requests(self):
        """REQUEST REQUIRED or VERIFY OWNERSHIP per linked account; material ones gate the verdict (G5)."""
        n = max(len(self.counted), 1)
        five = MATERIAL_SHARE * self.basis if self.basis and self.basis > 0 else D(0)
        self.requests = []
        for k in self.links:
            recurring = k["n_in"] + k["n_out"] >= 2
            monthly = (k["amt_in"] + k["amt_out"]) / n
            if not (recurring or k["financing"] or monthly >= five):
                continue
            kind = "VERIFY OWNERSHIP" if k["n_in"] and k["n_out"] else "REQUEST REQUIRED"
            ms = sorted(k["months"])
            why = ("financing account; " if k["financing"] else "") + (
                "two-way transfers" if kind == "VERIFY OWNERSHIP" else "recurring transfers" if recurring else "material transfer"
            )
            self.requests.append(
                dict(k, kind=kind, why=why, monthly=monthly, material=monthly >= five,
                     span=f"{mon(ms[0])} to {mon(ms[-1])}", months=[mkey(m) for m in ms])
            )
        self.coverage_block = [
            f"unprovided account {r['account']} moves {usd(r['monthly'])}/mo (could hold MCA payments or revenue)"
            for r in self.requests
            if r["material"]
        ] + [f"unreadable statement {u['name']}" for u in self.unread if u.get("statement", True)]

    def commingling(self):
        """V1.7 section 9: confirmed personal items per account-month, possible items reported apart."""
        gross = Counter()
        for t in self.txns:
            if t.dir == "credit":
                gross[(t.acct, t.month)] += t.amt
        conf, poss = defaultdict(list), []
        for t in self.txns:
            if t.returned_by:
                continue
            if t.tag in ("OWNER_DRAW", "STRIP_OWNER"):
                conf[(t.acct, t.month)].append(t)
            elif t.dir == "debit" and t.tag in ("OTHER", "TRANSFER_OUT") and (
                P2P.search(t.desc.upper()) or PERSONAL_HINT.search(t.desc.upper())
            ):
                poss.append(t)

        def severity(items, share):
            if len(items) > COMMINGLING_HIGH_ITEMS or (share is not None and share > COMMINGLING_HIGH_SHARE):
                return "High"
            if len(items) >= COMMINGLING_MODERATE_ITEMS or (share is not None and share >= MATERIAL_SHARE):
                return "Moderate"
            return "Low"

        rows = []
        for (aid, k), items in sorted(conf.items()):
            amt = sum((t.amt for t in items), D(0))
            share = amt / gross[(aid, k)] if gross[(aid, k)] else None
            rows.append(dict(account=aid, month=mkey(k), count=len(items), amount=amt, share=share,
                             severity=severity(items, share)))
        order = ["Low", "Moderate", "High"]
        worst = max(rows, key=lambda r: (order.index(r["severity"]), r["amount"]), default=None)
        self.comm = dict(
            rows=rows,
            status=f"Present — {worst['severity']}" if worst else "None",
            confirmed=sum(r["count"] for r in rows),
            confirmed_amount=sum((r["amount"] for r in rows), D(0)),
            worst=worst,
            possible=len(poss),
            possible_amount=sum((t.amt for t in poss), D(0)),
        )

    def rooms(self, b, w, s):
        """Rooms A-D, HEADLINE and CONSERVATIVE for a BASIS, worst-month True Revenue and stack."""
        o = self.total_ob
        r = dict(
            A=b - s if b is not None else None,
            B=HOLDBACK_SHARE * b - s if b is not None else None,
            C=b - s - o if b is not None and o is not None else None,
            D=HOLDBACK_SHARE * w - s if w is not None else None,
        )
        headline = max(D(0), min(r["B"], r["C"])) if None not in (r["B"], r["C"]) else None
        conservative = max(D(0), min(r["C"], r["D"])) if None not in (r["C"], r["D"]) else None
        return r, headline, conservative

    def capacity(self):
        self.stack = sum((p.cost for p in self.positions if p.live), D(0))
        w = self.month_rows[self.worst_month]["true"] if self.worst_month else None
        self.room, self.headline, self.conservative = self.rooms(self.basis, w, self.stack)
        r = self.room
        if self.headline is None:
            self.binding = "Insufficient counted months"
        elif self.headline == 0:
            self.binding = "No headline room (Room B or C <= 0): " + " and ".join(
                f"Room {x}" for x in "BC" if r[x] <= 0
            ) + " <= 0"
        else:
            self.binding = (
                "Room B: 60% revenue holdback"
                if r["B"] <= r["C"]
                else "Room C: operating obligations"
            )
        if self.conservative is not None and self.headline is not None:
            # V1.7 V10: Room C if C<=D, else Room D and the worst month.
            lim = "Room C" if r["C"] <= r["D"] else f"Room D (worst month {mon(self.worst_month)})"
            self.binding += f"; CONSERVATIVE: {lim}" + (" <= 0" if self.conservative == 0 else "")
        self.readiness()
        if self.uncertain_block:
            self.binding += "; material uncertainty: " + "; ".join(self.uncertain_block)
        if self.coverage_block and self.headline is not None:
            self.binding += "; coverage: " + "; ".join(self.coverage_block)
        # Sign-off B18: a missing account or unreadable statement can only hide more MCA payments,
        # which lower HEADLINE, so it blocks YES and leaves a NO standing (V1.7 section 9).
        status = (
            "INSUFFICIENT DATA"
            if len(self.counted) < 2 or self.uncertain_block or (self.coverage_block and self.headline > 0)
            else "YES" if self.headline > 0 else "NO"
        )
        self.status = status + SUFFIX[self.worst]

    def readiness(self):
        """V1.7 rules 6 and 7: test each U position and the unresolved credits against the verdict.

        Material = could change the verdict or the binding room, or moves >= 5% of BASIS. A material U
        position blocks YES. Unresolved credits are already out of BASIS, so they only block a NO they
        could reverse. Their sensitivity is still reported.
        """
        self.uncertain, self.uncertain_block = [], []
        if self.headline is None or len(self.counted) < 2:
            return

        def view(b, w, s):
            r, hl, _ = self.rooms(b, w, s)
            return (hl > 0, "zero" if hl == 0 else "B" if r["B"] <= r["C"] else "C"), hl

        w = self.month_rows[self.worst_month]["true"]
        base, _ = view(self.basis, w, self.stack)
        five = MATERIAL_SHARE * self.basis if self.basis > 0 else D(0)
        u = [p for p in self.positions if p.live_status == "U"]
        for p in u:
            flips, hl = view(self.basis, w, self.stack + p.scenario)
            p.material = p.scenario >= five or flips != base
            self.uncertain.append(
                dict(kind="U position", ref=p.display, monthly=p.scenario, headline_if=hl, material=p.material)
            )
        # Sign-off B7 (2026-11-07): each U position is tested alone; immaterial ones are not summed.
        unres = sum((self.month_rows[k]["unresolved"] for k in self.months), D(0))
        if unres:
            alt = {k: self.month_rows[k]["true"] + self.month_rows[k]["unresolved"] for k in self.counted}
            b2 = mean([alt[k] for k in self.counted][-3:])
            flips, hl = view(b2, min(alt.values()), self.stack)
            material = abs(b2 - self.basis) >= five or flips != base
            self.uncertain.append(
                dict(kind="unresolved credits", ref="STRIP_UNRESOLVED", amount=unres, basis_if=b2, headline_if=hl,
                     material=material, reverses_no=not base[0] and flips[0])
            )
        if base[0]:
            # Sign-off B2 (2026-11-02): unresolved credits are already out of BASIS, so adding them back can
            # only raise capacity. They never block YES; material U positions do.
            self.uncertain_block = [
                f"{x['ref']} U scenario {usd(x['monthly'])}/mo" for x in self.uncertain if x["material"] and "monthly" in x
            ]
        else:
            self.uncertain_block = [
                f"unresolved credits {usd(x['amount'])} could reverse NO" for x in self.uncertain if x.get("reverses_no")
            ]

    # ---- 9. peak load -----------------------------------------------------------------------------
    def peak(self):
        # V1.7 K2: eligible weeks need 5 covered business days on the accounts that carry MCA collections.
        coll = {t.acct for p in self.positions if not p.watch for t in p.cleared} or set(self.accts)
        covered = set()
        for aid in coll:
            for s, e in self.accts[aid]["statements"]:
                covered |= {s + timedelta(i) for i in range((e - s).days + 1)}
        weeks = defaultdict(list)
        for p in self.positions:
            if p.watch:  # identity unproved: not an observed MCA collection
                continue
            for t in p.cleared:
                weeks[t.date - timedelta(t.date.weekday())].append((t, p))
        eligible = {
            m: v
            for m, v in weeks.items()
            if sum(self.cal.is_bd(d := m + timedelta(i)) and d in covered for i in range(7)) >= 5
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
            elif is_mca or first.tag in ("DEBT_SERVICE", "PAYROLL", "RENT", "TAX", "INSURANCE"):
                tier = "T2"  # V1.7 K7: involuntary essential return, R01/R09 included
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
            if (is_mca or first.tag == "DEBT_SERVICE") and tier == "T1":
                cured = "N (MCA/loan stop-pay)"
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
        # V1.7 K6, sign-off B21 (2026-11-07): a return credit with no matching debit is a Class A return.
        # The debit is unknown, so it may be essential: T1 by code, else T2, and never cured.
        for c in self.txns:
            u = c.desc.upper()
            if c.dir == "credit" and c.tag == "STRIP_RECREDIT" and not c.returns and (RETURN_CODE.search(u) or "RETURN" in u):
                code = RETURN_CODE.search(u)
                self.t7.append(
                    dict(date=c.date, who=c.norm, amt=c.amt, cls="A", tier="T1" if T1.search(u) else "T2",
                         desc=(f"ACH Rev {code.group(0)}; " if code else "") + "return credit, debit not found",
                         cured="N (debit not found)", attempts=[c.id])
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
        self.thin = THIN_BALANCE_DAYS * (self.stack / BUSINESS_DAYS_PER_MONTH)
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
            if c.id not in self.cand or not self.median or c.amt < 3 * self.median:
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
        pw = self.peak_week
        if pw and pw["weekly"] >= self.cur_weekly:
            pk = f"Peak weekly {usd(pw['weekly'])} in week of {mdy(pw['monday'])} vs current weekly {usd(self.cur_weekly)}."
        else:
            seen = f"observed peak {usd(pw['weekly'])} in week of {mdy(pw['monday'])}" if pw else "no fully covered week"
            pk = f"Peak weekly {usd(self.cur_weekly)} is the modeled current floor ({seen}); current weekly {usd(self.cur_weekly)}."
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
        if self.uncertain_block or self.coverage_block:
            flip = "Resolve " + "; ".join(self.uncertain_block + self.coverage_block) + ". " + flip
        # V1.7 section 7: outflows kept out of obligations are disclosed with their effect on Room C.
        out = [r for r in self.ob_rows if (r["tag"] == "OWNER_DRAW" or r["ambiguous"]) and r["avg"]]
        if out and self.room["C"] is not None:
            extra = sum((r["avg"] for r in out), D(0))
            flip += (
                f" Excluded outflows ({', '.join(r['label'] for r in out)}) average {usd(extra)}/mo; "
                f"counting them sets Room C to {usd(self.room['C'] - extra)}."
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
        c = self.comm
        comm = f"Commingling Status: {c['status']}; " + (
            f"{c['confirmed']} confirmed item(s), {usd(c['confirmed_amount'])}; worst {kmon(c['worst']['month'])} "
            f"{c['worst']['count']} item(s) {usd(c['worst']['amount'])}"
            + (f" ({pct(c['worst']['share'])} of gross credits)" if c["worst"]["share"] is not None else "")
            if c["worst"]
            else "0 confirmed items in the supplied accounts"
        ) + f"; possible: {c['possible']} P2P or consumer item(s), {usd(c['possible_amount'])}; not proof of personal use."
        if self.requests:
            kinds = {r["kind"] for r in self.requests}
            more = len(self.requests) - 5
            acc = ("REQUEST REQUIRED" if "REQUEST REQUIRED" in kinds else "VERIFY OWNERSHIP") + "; " + "; ".join(
                f"{i}) {r['account']}" + (f" ({r['label']})" if r["label"] and r["label"] not in r["account"] else "")
                + f": {r['kind']}, {r['why']}; in {r['n_in']} / {usd(r['amt_in'])}, out {r['n_out']} / {usd(r['amt_out'])}; "
                f"{r['span']}; full statements for underwriting months"
                for i, r in enumerate(self.requests[:5], 1)
            ) + (f"; {more} more in audit.json" if more > 0 else "")
        else:
            acc = "COMPLETE OBSERVED; no unprovided account implicated by the supplied rows."
        self.lines = dict(core=core, will=will, peak=pk, flip=flip, commingling=comm, accounts=acc)

    # ---- 11b. V1.7 section 10 completeness audit --------------------------------------------------
    def completeness_audit(self):
        owner = {}
        for p in self.positions:
            for t in p.txns:
                owner.setdefault(t.id, []).append(p.pid)
        self.debit_owner = owner
        self.debit_dispositions = []
        for name, g in sorted(self.groups.items()):
            if not (g["passes"] or g["mca"]):
                continue
            pids = sorted({p.pid for p in self.positions if name in p.groups})
            if pids:
                kind = "WATCH" if any(p.watch for p in self.positions if p.pid in pids) else "POSITION"
                disp = f"{kind} {', '.join(pids)}"
            else:
                disp = f"NON-MCA {g['tag']} ({g['source']})"
            self.debit_dispositions.append(
                dict(group=name, txn_ids=[t.id for t in g["txns"]], passes=g["passes"], disposition=disp)
            )
        cleared = lambda d: [t for t in self.txns if t.dir == d and not t.returned_by]
        # V1.7 A2: every cleared credit gets one disposition. Candidates take their forward-search result;
        # the rest are customer revenue (processor, payer, recurring sender or answered) or a strip.
        fwd_of = {f["anchor"]: f["v17_disposition"] for f in self.forward}
        self.credit_dispositions = [
            dict(txn_id=t.id, disposition=fwd_of.get(t.id) or (
                "CUSTOMER_SUPPORTED" if t.tag in ("REV_PROCESSOR", "REV_PAYER") else self.credit_disposition(t, None)))
            for t in cleared("credit")
        ]
        fwd = Counter(f["v17_disposition"] for f in self.forward)
        self.completeness = dict(
            credits_scanned=len(cleared("credit")),
            debits_scanned=len(cleared("debit")),
            candidate_credits=len(self.cand),
            candidate_debit_groups=len(self.debit_dispositions),
            positions=sum(not p.watch for p in self.positions),
            watch=sum(p.watch for p in self.positions),
            material_u=sum(p.material for p in self.positions),
            unmatched_finance_credits=fwd["FINANCING_UNATTACHED"],
            unresolved_credits=fwd["UNRESOLVED"],
            closed_with_proof=sum(p.live_status == "N" for p in self.positions),
            requested_missing_accounts=sum(r["kind"] == "REQUEST REQUIRED" for r in self.requests),
        )

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
            "every cleared credit has one V1.7 disposition",
            sorted(d["txn_id"] for d in self.credit_dispositions)
            == sorted(t.id for t in self.txns if t.dir == "credit" and not t.returned_by)
            and all(d["disposition"] in CREDIT_DISPOSITIONS for d in self.credit_dispositions),
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
            "status is Y, N or U; N only with closure evidence; U carries a scenario",
            all(
                (p.live_status != "N" or bool(p.terminated))
                and (p.live_status == "U") == (p.scenario is not None)
                and p.live == (p.live_status == "Y")
                for p in self.positions
            ),
        )
        ok(
            "every nominated debit group has a disposition; no debit in two positions",
            all(d["disposition"] for d in self.debit_dispositions)
            and all(len(v) == 1 for v in self.debit_owner.values()),
        )
        ok(
            "every trigger and candidate credit has an expanded-window disposition",
            all(s["expanded_outcome"] for s in self.searches) and all(f["expanded_outcome"] for f in self.forward),
        )
        ok(
            "no YES while a material U position is open",
            not (self.status.startswith("YES") and any(x["material"] and "monthly" in x for x in self.uncertain)),
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
    def exceptions(self):
        """V1.7 R7: one EXCEPTION record per unresolved item, built from the findings already made."""
        sev = lambda m: "MATERIAL" if m else "MINOR"
        by_display = {p.display: p for p in self.positions}
        out = []
        for u in getattr(self, "uncertain", []):  # readiness() skips it when no HEADLINE is computed
            if u["kind"] == "U position":
                p = by_display[u["ref"]]
                out.append(dict(type="U POSITION", source_tx_ids=[t.id for t in p.txns],
                                why_unresolved="no collection in the live window and no closure proof",
                                possible_effect_on_capacity=f"HEADLINE {usd(u['headline_if'])} if its {usd(u['monthly'])}/mo scenario is live",
                                required_evidence="statements through today, a payoff letter or the contract",
                                severity=sev(u["material"])))
            else:
                out.append(dict(type="UNRESOLVED CREDITS",
                                source_tx_ids=[t.id for t in self.txns if t.tag == "STRIP_UNRESOLVED"],
                                why_unresolved="candidate credits without customer or financing evidence",
                                possible_effect_on_capacity=f"HEADLINE {usd(u['headline_if'])} if {usd(u['amount'])} is revenue",
                                required_evidence="invoices, remittance detail or the sender's identity",
                                severity=sev(u["material"])))
        for r in self.requests:
            out.append(dict(type=r["kind"], source_tx_ids=r["txn_ids"],
                            why_unresolved=f"account {r['account']} not supplied ({r['why']})",
                            possible_effect_on_capacity=f"{usd(r['monthly'])}/mo moves through it; could hold MCA payments or revenue",
                            required_evidence=f"full statements for {r['account']}, {r['span']}",
                            severity=sev(r["material"])))
        for u in self.unread:
            if u.get("statement", True):
                out.append(dict(type="UNREADABLE SOURCE", source_tx_ids=[],
                                why_unresolved=f"{u['name']}: {u['reason']}",
                                possible_effect_on_capacity="its transactions are not in any figure",
                                required_evidence="a readable copy or OCR", severity="MATERIAL"))
        for q in self.questions:
            if q["question_id"] not in self.answers:
                out.append(dict(type="OPEN QUESTION", source_tx_ids=q["txn_ids"],
                                why_unresolved=f"{q['type']} question {q['question_id']} unanswered; engine default applied",
                                possible_effect_on_capacity="the default is the conservative reading",
                                required_evidence="an answer in the judgments file", severity="MINOR"))
        return out

    def stages(self, exceptions):
        """V3 handoff stage manifest for V1.7 execution-order stages 1 to 10 (11 is added after rendering).

        Each stage reports counts, the material items a person must review, and hashes chained from the
        ledger: a stage's input hash is the previous stage's output hash. NEEDS_REVIEW marks evidence
        uncertainty; the run itself completed (a failed run raises UWError and returns no audit).
        """
        material = defaultdict(list)
        stage_of = {"UNREADABLE SOURCE": 1, "REQUEST REQUIRED": 3, "VERIFY OWNERSHIP": 3,
                    "UNRESOLVED CREDITS": 5, "U POSITION": 8}
        for x in exceptions:
            if x["severity"] == "MATERIAL" and x["type"] in stage_of:
                material[stage_of[x["type"]]].append(x["type"])
        if self.worst in ("Break", "Unverified"):
            material[2].append(f"integrity {self.worst}")
        competing = sum(f["v17_disposition"] == "COMPETING" for f in self.forward)
        if competing:
            material[7].append("COMPETING")
        if getattr(self, "uncertain_block", None) or self.coverage_block:
            material[9].append("verdict held by uncertainty or coverage")
        events = Counter(e["kind"] for p in self.positions for e in p.events)
        status = Counter(p.live_status for p in self.positions if not p.watch)
        counts = {
            1: dict(accounts=len(self.accts), statements=sum(len(a["statements"]) for a in self.accts.values()),
                    unread=len(self.unread)),
            2: dict(transactions=len(self.txns), duplicate_ids_dropped=sum(self.dropped.values()),
                    pending=len(self.pending)),
            3: dict(tags=dict(Counter(t.tag for t in self.txns)), account_requests=len(self.requests)),
            4: dict(debit_groups=len(self.groups), nominated=len(self.debit_dispositions),
                    positions=sum(not p.watch for p in self.positions), watch=sum(p.watch for p in self.positions)),
            5: dict(candidates=len(self.cand), financing_gated=len(self.gate)),
            6: dict(events=dict(events)),
            7: dict(backward_searches=len(self.searches), forward_searches=len(self.forward),
                    attached=len(self.attached), competing=competing),
            8: dict(Y=status["Y"], U=status["U"], N=status["N"]),
            9: dict(headline=self.headline, basis=self.basis, stack=self.stack, status=self.status),
            10: dict(self.completeness, self_checks=len(self.checks)),
        }
        # What each output hash covers: the counts plus the stage's own results, so a changed tag,
        # position or room changes the hash even when the counts do not.
        detail = {
            1: sorted(self.accts), 2: [t.id for t in self.txns], 3: [(t.id, t.tag) for t in self.txns],
            4: sorted((p.pid, [t.id for t in p.txns]) for p in self.positions), 5: sorted(self.cand),
            6: sorted((p.pid, e["kind"], e["txn_id"]) for p in self.positions for e in p.events),
            7: sorted(self.attached.items()), 8: sorted((p.pid, p.live_status, p.cost) for p in self.positions),
            9: [self.headline, self.conservative, self.basis, self.stack, self.status], 10: self.checks,
        }
        out, prev = [], self.sha
        for k, name in enumerate(STAGES[:10], 1):
            digest = stage_hash([counts[k], detail[k]])
            out.append(dict(stage=k, name=name, status="NEEDS_REVIEW" if material[k] else "COMPLETE",
                            input_hash=prev, policy_hash=POLICY_HASH, output_hash=digest, counts=counts[k],
                            unresolved=sorted(set(material[k]))))
            prev = digest
        return out

    def audit(self):
        """Every fact the report shows, plus the provenance behind it. render() reads only this."""
        exceptions = self.exceptions()
        searches_by_trigger = defaultdict(list)
        for s in self.searches:
            searches_by_trigger[s["anchor"]].append(s)

        def position(p):
            fundings = [
                dict(
                    f,
                    credit_date=self.by_id[f["credit"]].date,
                    credit_amount=self.by_id[f["credit"]].amt,
                    gate=self.gate[f["credit"]]["kind"],
                )
                for f in p.fundings
            ]
            possible = [
                dict(
                    date=self.by_id[s["candidates"][0]["txn_id"]].date,
                    amount=self.by_id[s["candidates"][0]["txn_id"]].amt,
                    confidence=s["candidates"][0]["confidence"],
                    outcome=s["outcome"].split(":")[0],
                )
                for tr in p.triggers
                for s in searches_by_trigger[tr["trigger_id"]]
                if s["outcome"].startswith(("AMBIGUOUS", "best"))
                and s["candidates"][0]["points"] >= 3
            ]
            latest = fundings[-1] if fundings else None
            return dict(
                pid=p.pid,
                display=p.display,
                funder=p.funder,
                status=p.status,
                cadence=p.cadence,
                level=p.level,
                monthly_cost=p.cost,
                live=p.live,
                live_status=p.live_status,
                status_basis=p.status_basis,
                scenario_cost=p.scenario,
                adverse_cost=p.adverse,
                material=p.material,
                watch=p.watch,
                groups=p.groups,
                evidence=p.evidence,
                terminated=p.terminated,
                tag_source=p.source,
                last_debit=p.cleared[-1].date if p.cleared else None,
                paid_since_latest_funding=(
                    sum((t.amt for t in p.cleared if t.date >= latest["credit_date"]), D(0))
                    if latest
                    else None
                ),
                debit_ids=[t.id for t in p.txns],
                cleared_ids=[t.id for t in p.cleared],
                events=p.events,
                triggers=p.triggers,
                fundings=fundings,
                possible_fundings=possible,
                notes=p.notes,
            )

        low = min(
            ((b, d, a) for a, days in self.eod.items() for d, b in days.items()),
            default=None,
        )
        return dict(
            engine_version=ENGINE_VERSION,
            policy_version=POLICY_VERSION,
            ledger_sha256=self.sha,
            data_end=self.end,
            live_window_start=self.live_start,
            worst_integrity=self.worst,
            accounts=[
                dict(
                    account_id=aid,
                    name=a["name"],
                    last4=a["last4"],
                    integrity=a["integrity"],
                    months=[
                        dict(key=mkey(k), days=v if isinstance(v, int) else len(v))
                        for k, v in sorted(self.acct_months[aid].items())
                    ],
                    notes=[f"Path A (Exparsed); source status {a['integrity']}"]
                    + ([a["integrity_note"]] if a.get("integrity_note") else [])
                    + self.notes[aid],
                )
                for aid, a in self.accts.items()
            ],
            months=[
                dict(
                    key=mkey(k),
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
                uncertainty=self.uncertain,
                coverage_block=self.coverage_block,
                worst_month=mkey(self.worst_month) if self.worst_month else None,
            ),
            streams=self.stream_rows,
            positions=[position(p) for p in self.positions],
            backward_searches=self.searches,
            forward_searches=self.forward,
            pending_observations=self.pending,
            sources=self.sources,
            duplicate_crosswalk=self.crosswalk,
            exceptions=exceptions,
            stages=self.stages(exceptions),
            credit_dispositions=self.credit_dispositions,
            peak_week=self.peak_week,
            obligations=self.ob_rows,
            returns=self.t7,
            flights=self.flights,
            liquidity=dict(
                od_days=sorted(self.od_days),
                fees=[dict(txn_id=t.id, date=t.date, amount=t.amt) for t in self.fees],
                thin=self.thin,
                days_below_thin=(
                    sum(v < self.thin for v in self.combined.values())
                    if self.combined
                    else None
                ),
                lowest=(
                    dict(balance=low[0], date=low[1], last4=self.accts[low[2]]["last4"])
                    if low
                    else None
                ),
            ),
            exparsed_crosscheck=self.crosscheck,
            debit_dispositions=self.debit_dispositions,
            account_requests=self.requests,
            commingling=self.comm,
            sources_unread=self.unread,
            material_accounts=self.material_accts,
            month_gaps={mkey(k): v for k, v in self.month_gaps.items()},
            completeness=self.completeness,
            transactions=[
                dict(
                    txn_id=t.id,
                    sequence=t.seq,
                    source_ref=t.src,
                    orig_id=t.orig_id,
                    trace_id=t.trace_id,
                    tag=t.tag,
                    tag_source=t.tag_source,
                    flags=t.flags,
                    returned_by=t.returned_by,
                )
                for t in self.txns
            ],
            questions=[
                dict(question_id=q["question_id"], type=q["type"], answered=q["question_id"] in self.answers)
                for q in self.questions
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

    def questions_doc(self):
        return dict(
            ledger_sha256=self.sha,
            policy_version=POLICY_VERSION,
            owner_names=self.owners,
            documents=list(self.docs.values()),
            questions=self.questions,
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


def stage_hash(x):
    return hashlib.sha256(json.dumps(x, default=jsonable, sort_keys=True).encode()).hexdigest()[:16]


def jsonable(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))


def report_gate(report_text):
    """Run checker/validate_report.py (V1.7 report checker) on the rendered report."""
    path = (
        Path(__file__).resolve().parent.parent / "checker" / "validate_report.py"
    )
    spec = importlib.util.spec_from_file_location("report_checker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.validate(mod.parse_report(report_text))
    except mod.ReportError as e:
        raise UWError(f"report check failed: {e}")
    return "PASS"


def mkey(k):
    return f"{k[0]}-{k[1]:02d}"


def kmon(key):
    """'2026-06' -> 'Jun-26'."""
    return mon((int(key[:4]), int(key[5:7])))


def tables(a):
    """The ten report tables as rows of cells, built from the audit alone."""
    dash = "—"
    cap, months = a["capacity"], a["months"]
    counted = {m["key"] for m in months if m["counted"]}
    true_by_key = {m["key"]: m["true"] for m in months}
    positions = a["positions"]
    t1 = []
    for i, acct in enumerate(a["accounts"]):
        ks = [m["key"] for m in acct["months"]]
        cov = f"{kmon(ks[0])} to {kmon(ks[-1])} ({len(ks)})" if ks else dash
        cnt = [k for k in ks if k in counted]
        partial = [
            f"{kmon(m['key'])} ({m['days']} days)"
            for m in acct["months"]
            if m["days"] < FULL_MONTH_DAYS
        ]
        notes = list(acct["notes"])
        if i == 0:
            open_q = [q for q in a["questions"] if q["type"] != "core_operation" and not q["answered"]]
            if open_q:
                notes.append(f"{len(open_q)} judgment question(s) unanswered; engine defaults applied")
            notes += [
                f"{'Unreadable' if u.get('statement', True) else 'Not a statement'}: {u['name']} ({u.get('reason', 'not extracted')})"
                for u in a["sources_unread"]
            ]
            notes += [
                f"Unprovided account {r['account']}: {r['kind']}" + (" (material)" if r["material"] else "")
                for r in a["account_requests"]
            ]
            unres = [m for m in months if m["unresolved"]]
            if unres:
                notes.append(
                    f"STRIP_UNRESOLVED {usd(sum(m['unresolved'] for m in unres))} in {len(unres)} month(s): "
                    "excluded from revenue for lack of evidence, not called financing"
                )
            notes += [
                f"{x['ref']}: U scenario {usd(x['monthly'])}/mo would set HEADLINE {usd(x['headline_if'])}"
                + (" (material)" if x["material"] else "")
                for x in cap["uncertainty"]
                if "monthly" in x
            ]
            notes += [
                f"{p['display']}: {n}"
                for p in positions
                for n in p["notes"]
                if n.startswith("Provisional")
            ]
        t1.append(
            [
                f"{acct['name']} ...{acct['last4']}",
                cov,
                f"{len(cnt)}: " + (", ".join(map(kmon, cnt)) if cnt else "None"),
                "Partial: " + ", ".join(partial) if partial else "None",
                acct["integrity"],
                "; ".join(notes),
            ]
        )
    t2 = [
        [
            m["month"],
            str(m["days"]),
            usd(m["gross"]),
            (f"{usd(m['stripped'])} ({m['top_strip']}" + (f"; unresolved {usd(m['unresolved'])}" if m["unresolved"] and m["top_strip"] != "STRIP_UNRESOLVED" else "") + ")")
            if m["top_strip"]
            else usd(m["stripped"]),
            usd(m["true"]),
            "Yes" if m["counted"] else "No",
        ]
        for m in months
    ]
    t2 += [
        ["TOR", dash, dash, dash, usd(cap["tor"]), dash],
        ["Last-3 Avg", dash, dash, dash, usd(cap["last3"]), dash],
        ["BASIS", dash, dash, dash, usd(cap["basis"]), dash],
    ]
    t3 = [
        [
            r["name"],
            r["cadence"],
            f"{r['count']} items, avg {usd(r['avg'])}",
            usd(r["total"]) + (f" (CV {r['cv']})" if r["cv"] is not None else ""),
            f"{pct(r['share'])} of included revenue; in {r['present']} of {len(months)} months",
        ]
        for r in a["streams"]
    ] or [["None", dash, dash, dash, dash]]
    t4 = []
    for p in positions:
        f = p["fundings"][-1] if p["fundings"] else None
        fdate = mdy(f["credit_date"]) if f else "Not found"
        st = p["live_status"]
        notes = [p["status"], p["evidence"], p["status_basis"]]
        for fx in p["fundings"]:
            notes.append(
                f"{fx['confidence']} {fx['points']} pts: {mdy(fx['credit_date'])} {usd(fx['credit_amount'])} -> "
                f"{fx['trigger']['kind']} {mdy(fx['trigger']['date'])}, {fx['bd_gap']} bd, gate {fx['gate']}"
            )
        for c in p["possible_fundings"]:
            notes.append(f"Possible {mdy(c['date'])} {usd(c['amount'])} ({c['confidence']}); {c['outcome']}")
        if st == "U":
            notes.append(
                f"SCENARIO {usd(p['scenario_cost'])}/mo, not in stack" + ("; material" if p["material"] else "")
            )
        if f and st != "N":
            rem = f["credit_amount"] * PAYBACK_FACTOR - p["paid_since_latest_funding"]
            notes.append(f"SCENARIO est. remaining {usd(rem)} (1.4x model); not closure evidence")
        notes += [n for n in p["notes"] if not n.startswith("Provisional")]
        t4.append(
            [
                p["display"],
                fdate,
                usd(f["credit_amount"]) if f else dash,
                f"{p['cadence'].title()} {usd(p['level'])}",
                mdy(p["last_debit"]) if p["last_debit"] else dash,
                st,
                "; ".join(notes),
                dash if st == "U" else usd(p["monthly_cost"]),
            ]
        )
        for e in p["events"]:
            t4.append([f"↳ {mdy(e['date'])} {e['kind']}", dash, dash, e["change"], dash, dash, e["detail"], dash])
    if not positions:
        t4.append(["None"] + [dash] * 7)
    stack, basis = cap["live_stack"], cap["basis"]
    hold = stack / basis if basis and basis > 0 else None
    t4 += [
        ["Total Live Stack"] + [dash] * 6 + [usd(stack)],
        ["Holdback % of Basis"] + [dash] * 6 + [pct(hold)],
    ]
    pw = a["peak_week"]
    cw, cd = stack / WEEKS_PER_MONTH, stack / BUSINESS_DAYS_PER_MONTH
    current = ["Current Live Stack", usd(stack), usd(cw), usd(cd), f"{sum(p['live'] for p in positions)} Y positions" + (f"; {sum(p['live_status'] == 'U' for p in positions)} U not in stack" if any(p["live_status"] == "U" for p in positions) else "")]
    # V1.7 K3: Report Peak Weekly = max(Observed Peak Weekly, Modeled Current Weekly).
    if pw and pw["weekly"] >= cw:
        pk, mk = pw["weekly"], mkey((pw["monday"].year, pw["monday"].month))
        detail = f"observed week of {mdy(pw['monday'])}; {len(pw['funders'])} positions; {', '.join(pw['funders'])}"
        if pw["latest"]:
            detail += "; Observed peak is latest full week"
    else:
        pk, mk = cw, max(counted, default=None)
        detail = "modeled current floor (stack/(52/12)); " + (
            f"observed peak {usd(pw['weekly'])}/wk in week of {mdy(pw['monday'])}" if pw else "no fully covered week with MCA debits"
        )
    pm = pk * WEEKS_PER_MONTH
    rev = true_by_key.get(mk) if mk in counted else None
    drop_detail = f"Peak Holdback {pct(pm / rev)} of {kmon(mk)} revenue" if rev else "Peak Holdback unavailable (no counted month)"
    t4b = [
        ["Peak Handled", usd(pm), usd(pk), usd(pm / BUSINESS_DAYS_PER_MONTH), detail],
        current,
        ["Drop Since Peak", usd(pm - stack), usd(pk - cw), usd(pm / BUSINESS_DAYS_PER_MONTH - cd), drop_detail],
    ]
    t5 = [[r["label"], usd(r["avg"]), r["basis"], "Yes" if r["ambiguous"] else "No"] for r in a["obligations"]]
    t5 += (
        [["Total Average Obligations", usd(cap["total_obligations"]), dash, dash]]
        + [[f"Room {k}", usd(cap["rooms"][k]), dash, dash] for k in "ABC"]
        + [["Room D", usd(cap["rooms"]["D"]), f"worst month {kmon(cap['worst_month'])}" if cap["worst_month"] else dash, dash]]
    )

    def tier(m):
        if m is None:
            return [dash] * 4
        return [
            usd(m),
            usd(m / WEEKS_PER_MONTH),
            usd(m / BUSINESS_DAYS_PER_MONTH),
            pct(m / basis) if basis and basis > 0 else dash,
        ]

    t6 = [
        ["HEADLINE (min B,C)"] + tier(cap["headline"]),
        ["CONSERVATIVE (min C,D)"] + tier(cap["conservative"]),
        ["Binding Constraint", cap["binding"], dash, dash, dash],
    ]
    t7 = [
        [mdy(e["date"]), e["who"], usd(e["amt"]), e["cls"], e["tier"], e["desc"], e["cured"]]
        for e in a["returns"]
    ] or [["None"] + [dash] * 6]
    h = cap["headline"]
    t8 = [
        [
            cap["status"],
            usd(h),
            usd(h / WEEKS_PER_MONTH) if h is not None else dash,
            usd(h / BUSINESS_DAYS_PER_MONTH) if h is not None else dash,
            cap["binding"],
        ]
    ]
    liq = a["liquidity"]
    a_ev = [e for e in a["returns"] if e["cls"] == "A"]
    tiers = Counter(e["tier"] for e in a_ev)
    od, low, flights = liq["od_days"], liq["lowest"], a["flights"]
    big = max(flights, key=lambda f: f["outflow"]) if flights else None
    fee_months = sorted({mon((f["date"].year, f["date"].month)) for f in liq["fees"]})
    t9 = [
        ["Overdraft days", str(len(od)), ", ".join(map(mdy, od[:6])) + (" ..." if len(od) > 6 else "") or "None"],
        ["Returned/NSF debit events", str(len(a_ev)), f"Class A: T1 {tiers['T1']}, T2 {tiers['T2']}, T3 {tiers['T3']}; UNKNOWN {sum(e['cls'] == 'UNKNOWN' for e in a['returns'])}"],
        ["NSF/OD fees", f"{len(liq['fees'])}, {usd(sum((f['amount'] for f in liq['fees']), D(0)))}", ", ".join(fee_months) or "None"],
        [
            "Days below THIN_BALANCE",
            str(liq["days_below_thin"]) if liq["days_below_thin"] is not None else dash,
            f"threshold {usd(liq['thin'])}; combined end-of-day, business days",
        ],
        ["Lowest balance", usd(low["balance"]) if low else dash, f"{mdy(low['date'])}, account ...{low['last4']}" if low else "balances unavailable"],
        [
            "FLIGHT events",
            str(len(flights)),
            f"largest: {mdy(big['date'])}, {usd(big['inflow'])} in, {usd(big['outflow'])} out" if big else "None",
        ],
    ]
    return [t1, t2, t3, t4, t4b, t5, t6, t7, t8, t9]


def render(a):
    """Ten-table Markdown report from the audit. A figure the audit lacks cannot reach the report."""
    lines, out = a["narrative"], []
    for (title, header), rows in zip(SPEC, tables(a)):
        out += [
            f"### {title}",
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join([":---"] * len(header)) + " |",
        ]
        for r in rows:
            require(len(r) == len(header), f"{title}: row width {len(r)} != {len(header)}")
            out.append("| " + " | ".join(cell(c) for c in r) + " |")
        out.append("")
        if title.startswith("Table 2 "):
            out += [f"**Core Operation:** {cell(lines['core'])}", ""]
        if title.startswith("Table 8 "):
            out += [
                f"- **WILL-PAY READ:** {cell(lines['will'])}",
                f"- **Peak MCA Load:** {cell(lines['peak'])}",
                f"- **What Would Flip This:** {cell(lines['flip'])}",
                f"- **Commingling:** {cell(lines['commingling'])}",
                f"- **Additional Accounts to Request:** {cell(lines['accounts'])}",
                "",
                "Capacity test with return/OD exception log. Not a fund recommendation.",
                "",
            ]
    return "\n".join(out)


@dataclass
class Result:
    questions: dict  # the questions document the LLM answers (prompts/judge.md)
    audit: dict  # every fact behind the report; Decimal and date values, see jsonable()
    report: str  # ten-table Markdown, already passed through checker/validate_report.py
    status: str  # Table 8 CAN THEY PAY value
    open_questions: int


def underwrite(raw, judgments=None):
    """The engine's interface. raw: normalized ledger bytes (schemas/ledger.schema.json).

    judgments: answers to an earlier run's questions on the same bytes, or None for engine defaults.
    Raises UWError on bad input, rejected judgments or a failed self-check.
    """
    e = _Engine(raw, judgments)
    audit = e.audit()
    report = render(audit)
    audit["report_gate"] = report_gate(report)
    last = audit["stages"][-1]["output_hash"]
    audit["stages"].append(dict(stage=11, name=STAGES[10], status="COMPLETE", input_hash=last, policy_hash=POLICY_HASH,
                                output_hash=stage_hash(report), counts=dict(report_gate=audit["report_gate"]), unresolved=[]))
    return Result(e.questions_doc(), audit, report, e.status, len(audit["questions_open"]))


def run(ledger_path, out_dir, judgments_path=None):
    raw = Path(ledger_path).read_bytes()
    judgments = (
        json.loads(Path(judgments_path).read_text(encoding="utf-8"))
        if judgments_path
        else None
    )
    r = underwrite(raw, judgments)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "questions.json").write_text(
        json.dumps(r.questions, indent=2, default=jsonable), encoding="utf-8"
    )
    (out / "audit.json").write_text(
        json.dumps(r.audit, indent=2, default=jsonable), encoding="utf-8"
    )
    (out / "report.md").write_text(r.report, encoding="utf-8")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ledger")
    ap.add_argument("--out", required=True)
    ap.add_argument("--judgments")
    args = ap.parse_args(argv)
    try:
        r = run(args.ledger, args.out, args.judgments)
    except (OSError, UWError, json.JSONDecodeError) as err:
        print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(
        f"OK: {r.status}; HEADLINE {usd(r.audit['capacity']['headline'])}/mo; "
        f"{len(r.audit['self_checks'])} self-checks passed; report check PASS; "
        f"{r.open_questions} question(s) open"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
