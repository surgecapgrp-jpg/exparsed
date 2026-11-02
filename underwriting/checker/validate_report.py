#!/usr/bin/env python3
"""V1.7 report checker: ten-table structure and report-visible accounting.

Started as the V2.2 validator. V1.7 changes:
- weekly = monthly x 12/52;
- Table 4 Live? accepts U with Monthly Cost "—", ordered Y, then U, then N;
- the binding line may end with "; material uncertainty: ..." or "; coverage: ...";
- INSUFFICIENT DATA is allowed with two or more counted months, because material uncertainty and
  missing accounts are not fully visible in the report;
- Table 7 Class accepts UNKNOWN (tier and cure n/a);
- Commingling and Additional Accounts lines appear exactly once, in order, between What Would
  Flip This and the capacity-test line, with their fixed status words.

Usage: python checker/validate_report.py report.md

Limits: This validator does NOT verify transaction-to-funder attribution,
statement completeness, independent matching, or unrounded audit math.
Those checks require the normalized source ledger and audit records.
"""

import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

SPEC = [
    ("Table 1 — Coverage & Integrity", ["Account", "Months Covered", "Months Counted", "Missing/Partial", "Balance Reconstruction (Pass/Break)", "Notes"]),
    ("Table 2 — Monthly Revenue", ["Month", "Days Counted", "Gross Credits", "Stripped Inflows", "True Revenue", "Counted?"]),
    ("Table 3 — Primary Revenue-Streams Breakdown", ["Stream/Descriptor", "Cadence", "Volume/Frequency", "Total Inflow Amount [CV]", "Notes"]),
    ("Table 4 — Live Stack", ["Position/Funder", "Funding Date", "Funding Amount", "Cadence/Payment", "Last Debit", "Live?", "Notes", "Monthly Cost"]),
    ("Table 4b — Peak MCA Load", ["Metric", "Monthly", "Weekly", "Daily", "Detail"]),
    ("Table 5 — Obligations", ["Category", "Monthly Avg", "Basis (Counterparty/Evidence)", "Ambiguous?"]),
    ("Table 6 — Payment Ceiling", ["Metric / Tier", "Monthly", "Weekly", "Daily", "% of Basis"]),
    ("Table 7 — RETURN/OD/BOUNCE Log", ["Date", "Item / Counterparty", "Amount", "Class", "Tier", "Descriptor", "Cured (≤2bd)?"]),
    ("Table 8 — Conclusion", ["CAN THEY PAY", "Max Monthly Payment", "Max Weekly Payment", "Max Daily Payment", "Binding Constraint"]),
    ("Table 9 — Liquidity Stress", ["Metric", "Value", "Date/Detail"]),
]

CENT = Decimal("0.01")
MONEY_RE = re.compile(r"(?<![\w\d])(-?\$?-?\d[\d,]*(?:\.\d{1,2})?)")
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}|\[(?:account name|Mon-YY|funder|category|counterparty|headLine|monthly|n\])", re.I)
MONTH_RE = re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}")

class ReportError(Exception):
    pass


def require(test, msg):
    if not test:
        raise ReportError(msg)


def parse_cells(line, width, title, row_type):
    require(line.startswith("| ") and line.endswith(" |"), f"{title}: malformed {row_type} line")
    require(line.count("|") == width + 1, f"{title}: {row_type} must have {width} cells")
    cells = [s.strip() for s in line[1:-1].split("|")]
    require(len(cells) == width, f"{title}: wrong {row_type} cell count")
    require(all(c and "\n" not in c and "\r" not in c for c in cells), f"{title}: empty/multiline cell")
    require(not any(PLACEHOLDER_RE.search(c) for c in cells), f"{title}: template placeholder remains")
    return cells


def parse_report(text):
    lines = text.splitlines()
    heading_pat = re.compile(r"^### (Table \S+ — .+)$")
    headings = [(i, m.group(1)) for i, l in enumerate(lines) if (m := heading_pat.match(l))]
    require(len(headings) == 10, f"Expected 10 table titles; got {len(headings)}")
    require([h for _, h in headings] == [t for t, _ in SPEC], "Table titles or order changed")
    out = {}
    for j, (start, title) in enumerate(headings):
        width = len(SPEC[j][1])
        stop = headings[j+1][0] if j < len(headings)-1 else len(lines)
        section = lines[start+1:stop]
        first = next((k for k, line in enumerate(section) if line.strip()), None)
        require(first is not None, f"{title}: missing table")
        header = "| " + " | ".join(SPEC[j][1]) + " |"
        delim = "| " + " | ".join([":---"]*width) + " |"
        require(section[first] == header, f"{title}: header changed")
        require(len(section)>first+1 and section[first+1] == delim, f"{title}: delimiter changed")
        rows = []
        k = first + 2
        while k < len(section) and section[k].startswith("|"):
            rows.append(parse_cells(section[k],width,title,f"data row {len(rows)+1}"))
            k += 1
        require(len(rows)>0, f"{title}: no data rows")
        require(not any(x.startswith("|") for x in section[k:]), f"{title}: orphan table row")
        out[title] = rows
    for required in (
        "**Core Operation:**", "**WILL-PAY READ:**", "**Peak MCA Load:**",
        "**What Would Flip This:**",
        "Capacity test with return/OD exception log. Not a fund recommendation."
    ):
        require(required in text, f"Missing fixed output line: {required}")
    # V1.7: two more fixed lines, each once, between What Would Flip This and the capacity-test line.
    flip = text.index("**What Would Flip This:**")
    cap = text.index("Capacity test with return/OD exception log.")
    for label, starts in (
        ("- **Commingling:** Commingling Status: ", ("None", "Present — Low", "Present — Moderate", "Present — High")),
        ("- **Additional Accounts to Request:** ", ("COMPLETE OBSERVED", "REQUEST REQUIRED", "VERIFY OWNERSHIP")),
    ):
        require(text.count(label) == 1, f"V1.7 line must appear exactly once: {label.strip()}")
        at = text.index(label)
        require(flip < at < cap, f"V1.7 line out of place: {label.strip()}")
        require(text[at + len(label):].startswith(starts), f"V1.7 line has no valid status: {label.strip()}")
    require(
        text.index("- **Commingling:**") < text.index("- **Additional Accounts to Request:**"),
        "V1.7 lines out of order",
    )
    return out


def money(cell, label, allow_unknown=False):
    if cell == "—":
        if allow_unknown: return None
        raise ReportError(f"{label}: unexpected unknown amount")
    m = MONEY_RE.search(cell)
    require(m is not None, f"{label}: expected currency, got {cell!r}")
    value = m.group(1).replace("$", "").replace(",", "")
    try: return Decimal(value)
    except InvalidOperation: raise ReportError(f"{label}: invalid currency {cell!r}")


def rounded_equal(x, y, display_count=1):
    # Currency values may appear as rounded whole dollars.
    tolerance = max(CENT, Decimal("0.50") * display_count)
    return abs(x-y) <= tolerance


def unique(rows, names, col=0, title="table"):
    for name in names:
        require(sum(r[col] == name for r in rows) == 1, f"{title}: expected one {name}")


def validate(t):
    t1 = t[SPEC[0][0]]
    for row in t1:
        if row[0] == "None": continue
        require(row[4] in ("Pass", "Unverified", "Pass with flag", "Break"), "Table 1: invalid status")
    severities = [r[4] for r in t1 if r[0] != "None"]
    worst = next((x for x in ("Break", "Unverified", "Pass with flag", "Pass") if x in severities), None)

    t2 = t[SPEC[1][0]]
    unique(t2,["TOR","Last-3 Avg","BASIS"],title="Table 2")
    require([r[0] for r in t2[-3:]] == ["TOR","Last-3 Avg","BASIS"], "Table 2: summary row order")
    months = [r for r in t2[:-3] if r[0] != "None"]
    revenue_total = Decimal(0)
    for r in months:
        require(bool(MONTH_RE.match(r[0])), f"Table 2: invalid month {r[0]}")
        require(r[5] in ("Yes","No"),f"Table 2: counted? {r[5]}")
        if r[1].isdigit() and r[5]=="Yes":
            require(int(r[1])>=18,f"Table 2 {r[0]} has fewer than 18 covered days")
        gross = money(r[2], f"Table 2 {r[0]} gross", True)
        stripped = money(r[3], f"Table 2 {r[0]} stripped", True)
        true = money(r[4], f"Table 2 {r[0]} true", True)
        if None not in (gross, stripped, true):
            require(rounded_equal(gross-stripped,true,3), f"Table 2: accounting break in {r[0]}")
            revenue_total += true
    basis = money(t2[-1][4],"BASIS",True)
    last3 = money(t2[-2][4],"Last-3 Avg",True)
    if basis is not None and last3 is not None:
        require(rounded_equal(basis,last3,2),"BASIS must equal Last-3 Avg")
    counted = [money(r[4],f"{r[0]} true",True) for r in months if r[5] == "Yes"]
    if counted and all(v is not None for v in counted):
        tor = money(t2[-3][4],"TOR",True)
        expected_tor = sum(counted, Decimal(0))/len(counted)
        require(tor is not None and rounded_equal(tor,expected_tor,2),"TOR mismatch")
        sorted_counted = sorted((r[0],money(r[4],f"{r[0]} true",False)) for r in months if r[5]=="Yes")
        # Sort month labels by calendar order rather than lexical month abbreviations.
        from datetime import datetime
        sorted_counted.sort(key=lambda x: datetime.strptime(x[0],"%b-%y"))
        final = [v for _,v in sorted_counted[-3:]]
        expected_last3 = sum(final,Decimal(0))/len(final)
        require(last3 is not None and rounded_equal(last3,expected_last3,2),"Last-3 Avg mismatch")

    t3=t[SPEC[2][0]]
    stream_vals=[money(r[3],"Table 3 stream",True) for r in t3 if r[0]!="None"]
    if months and all(money(r[4],"revenue",True) is not None for r in months) and all(v is not None for v in stream_vals):
        require(rounded_equal(sum(stream_vals,Decimal(0)), revenue_total, max(len(stream_vals),len(months))),"Table 3 revenue total does not reconcile")

    t4=t[SPEC[3][0]]
    unique(t4,["Total Live Stack","Holdback % of Basis"],title="Table 4")
    require([r[0] for r in t4[-2:]] == ["Total Live Stack","Holdback % of Basis"],"Table 4: summary order")
    for s in t4[-2:]:
        require(s[1:7] == ["—"]*6,"Table 4: summary columns 2-7 must be —")
    live_sum = Decimal(0)
    seen=set()
    prior_funder=None
    prev_live=False
    non_live_seen=0
    event_dates=[]
    for r in t4[:-2]:
        name=r[0]
        if name=="None":
            require(r[1:]==["—"]*7,"Table 4: malformed None row")
            continue
        if name.startswith("↳"):
            require(prior_funder is not None,"Table 4: orphan event")
            require(r[1]==r[2]==r[4]==r[5]==r[7]=="—","Table 4: event fields must be —")
            m = re.search(r"\d{2}/\d{2}/\d{2}",name)
            require(m is not None,"Table 4: undated event")
            from datetime import datetime
            date=datetime.strptime(m.group(0),"%m/%d/%y")
            require(not event_dates or date>=event_dates[-1],"Table 4: events out of order")
            event_dates.append(date)
        else:
            require(name not in seen,"Table 4: duplicate funder")
            seen.add(name)
            prior_funder=name
            event_dates=[]
            require(r[5] in ("Y","U","N"),"Table 4: invalid live status")
            rank={"Y":0,"U":1,"N":2}[r[5]]
            require(rank>=non_live_seen,"Table 4: rows not ordered Y, U, N")
            non_live_seen=rank
            if r[5]=="U":
                require(r[7]=="—","Table 4: U row must have Monthly Cost —")
            elif r[5]=="Y":
                require(r[4]!="—" and r[4]!="Not found","Table 4: live funder has no last debit")
                monthly=money(r[7],f"Table 4 {name} monthly",True)
                if monthly is not None: live_sum+=monthly
            else:
                require(money(r[7],f"Table 4 {name} monthly",False)==0,"Table 4: non-live cost is not zero")
            require(r[1] in ("Pre-file","Not found","—") or bool(DATE_RE.match(r[1])),"Table 4: invalid funding date")
    stack=money(t4[-2][7],"Total Live Stack",True)
    if stack is not None and all(money(r[7],"Live cost",True) is not None for r in t4[:-2] if r[0] not in ("None",) and not r[0].startswith("↳") and r[5]=="Y"):
        require(rounded_equal(live_sum,stack,max(1,len(seen))),"Table 4: stack sum mismatch")
    hold = t4[-1][7]
    if stack is not None and basis is not None and basis>0 and hold!="—":
        p = money(hold,"Holdback %")
        require(abs(p-(stack/basis*100))<=Decimal("1"),"Table 4: holdback percentage mismatch")

    t4b=t[SPEC[4][0]]
    unique(t4b,["Peak Handled","Current Live Stack","Drop Since Peak"],title="Table 4b")
    require([r[0] for r in t4b]==["Peak Handled","Current Live Stack","Drop Since Peak"],"Table 4b: wrong row order")
    current=money(t4b[1][1],"Table 4b current",True)
    if stack is not None and current is not None:
        require(rounded_equal(stack,current,2),"Table 4b current does not equal stack")
    for r in t4b:
        monthly=money(r[1],f"Table 4b {r[0]} monthly",True)
        weekly=money(r[2],f"Table 4b {r[0]} weekly",True)
        daily=money(r[3],f"Table 4b {r[0]} daily",True)
        if monthly is not None and weekly is not None:
            require(abs(weekly-monthly*12/52) <= Decimal("0.62"),f"Table 4b {r[0]} weekly conversion mismatch")
        if monthly is not None and daily is not None:
            require(abs(daily-monthly/Decimal("20")) <= Decimal("0.53"),f"Table 4b {r[0]} daily conversion mismatch")
    for j in (1,2,3):
        p=money(t4b[0][j],"peak",True)
        c=money(t4b[1][j],"current",True)
        d=money(t4b[2][j],"drop",True)
        if None not in (p,c,d):
            require(rounded_equal(p-c,d,3),f"Table 4b: drop mismatch at column {j}")
            # V2.2: Observed historical peak may be lower than modeled current.
            # A negative drop is valid and must reconcile.

    t5=t[SPEC[5][0]]
    room_names=["Total Average Obligations","Room A","Room B","Room C","Room D"]
    unique(t5,room_names,title="Table 5")
    require([r[0] for r in t5[-5:]]==room_names,"Table 5: wrong summary order")
    operating_total = Decimal(0)
    complete = True
    for r in t5[:-5]:
        if r[0] == "None":
            continue
        v = money(r[1],f"Obligation {r[0]}",True)
        if "owner draw" in r[0].lower():
            require("excluded from total" in r[2].lower(),"Table 5: Owner Draws must be marked excluded")
            continue  # Owner draws can be positive, but are NOT in the total.
        if r[3] == "Yes" or r[0].startswith("AMBIGUOUS_"):
            continue
        require(r[3] == "No",f"Table 5: invalid ambiguity {r[3]}")
        if v is None:
            complete = False
        else:
            operating_total += v
    obligations = money(t5[-5][1],"Total Average Obligations",True)
    if complete and obligations is not None:
        require(rounded_equal(operating_total,obligations,max(1,len(t5)-5)),
                "Table 5: obligations sum includes excluded or ambiguous debit")

    rooms={r[0]:money(r[1],r[0],True) for r in t5[-4:]}
    if basis is not None and stack is not None:
        for room, expected in (("Room A",basis-stack),("Room B",Decimal("0.60")*basis-stack)):
            if rooms[room] is not None:
                require(rounded_equal(rooms[room],expected,3),f"Table 5: {room} mismatch")
        if obligations is not None and rooms["Room C"] is not None:
            require(rounded_equal(rooms["Room C"],basis-stack-obligations,max(3,len(t5))),"Table 5: Room C mismatch")
        if counted and all(v is not None for v in counted) and rooms["Room D"] is not None:
            expected_d=Decimal("0.60")*min(counted)-stack
            require(rounded_equal(rooms["Room D"],expected_d,3),"Table 5: Room D mismatch")

    t6=t[SPEC[6][0]]
    require([r[0] for r in t6]==["HEADLINE (min B,C)","CONSERVATIVE (min C,D)","Binding Constraint"],"Table 6: wrong row order")
    headline=money(t6[0][1],"HEADLINE",True)
    conservative=money(t6[1][1],"CONSERVATIVE",True)
    if headline is not None and rooms["Room B"] is not None and rooms["Room C"] is not None:
        require(rounded_equal(headline,max(Decimal(0),min(rooms["Room B"],rooms["Room C"])),3),"HEADLINE formula mismatch")
    if conservative is not None and rooms["Room C"] is not None and rooms["Room D"] is not None:
        require(rounded_equal(conservative,max(Decimal(0),min(rooms["Room C"],rooms["Room D"])),3),"CONSERVATIVE formula mismatch")
    if headline is not None:
        if headline == 0:
            expected_binding="No headline room (Room B or C <= 0)"
        elif rooms["Room B"] is not None and rooms["Room C"] is not None:
            expected_binding="Room B: 60% revenue holdback" if rooms["Room B"] <= rooms["Room C"] else "Room C: operating obligations"
        else:
            expected_binding=None
        if expected_binding is not None:
            require(t6[2][1] == expected_binding or t6[2][1].startswith(tuple(expected_binding+x for x in ("; CONSERVATIVE:", "; material uncertainty:", "; coverage:"))),"Table 6: wrong binding constraint")
    for r in t6[:2]:
        m=money(r[1],f"Table 6 {r[0]} monthly",True)
        w=money(r[2],f"Table 6 {r[0]} weekly",True)
        d=money(r[3],f"Table 6 {r[0]} daily",True)
        if m is not None and w is not None:
            require(abs(w-m*12/52) <= Decimal("0.62"),f"Table 6 {r[0]} weekly conversion mismatch")
        if m is not None and d is not None:
            require(abs(d-m/Decimal("20")) <= Decimal("0.53"),f"Table 6 {r[0]} daily conversion mismatch")
        pct=r[4]
        if basis is not None and basis>0 and m is not None and pct!="—":
            percent=money(pct,"Payment % of Basis")
            require(abs(percent-m/basis*100)<=Decimal("0.25"),f"Table 6 {r[0]} % Basis mismatch")

    t7=t[SPEC[7][0]]
    for r in t7:
        if r[0]=="None":continue
        require(bool(DATE_RE.match(r[0])),"Table 7: invalid event date")
        require(r[3] in ("A","B","UNKNOWN","—"),"Table 7: invalid class")
        if r[3] == "UNKNOWN":
            require(r[4] == "n/a" and r[6] == "n/a","Table 7: UNKNOWN class needs tier and cure n/a")
        require(r[4] in ("T1","T2","T3","n/a","—"),"Table 7: invalid tier")
        if r[3] == "B":
            require(r[4] == "n/a","Table 7: Class B cannot have return severity tier")
            require(r[6] == "n/a (paid by OD)","Table 7: Class B cure must be n/a (paid by OD)")

    t8=t[SPEC[8][0]]
    require(len(t8)==1,"Table 8: expected one conclusion row")
    for j in (1,2,3):
        a=money(t6[0][j],f"Table 6 HEADLINE {j}",True)
        b=money(t8[0][j],f"Table 8 {j}",True)
        require((a is None and b is None) or (a is not None and b is not None and rounded_equal(a,b,2)),"Table 8 differs from HEADLINE")
    require(t8[0][4]==t6[2][1],"Table 8 binding constraint differs from Table 6")
    require(any(t8[0][0].startswith(x) for x in ("YES","NO","INSUFFICIENT DATA")),"Table 8: bad conclusion status")
    suffixes={"Pass":"", "Pass with flag":" (FLAGGED)", "Unverified":" (UNVERIFIED DATA)", "Break":" (PROVISIONAL — INTEGRITY FAIL)"}
    if worst:
        declared=t8[0][0]
        prefix=next((p for p in ("YES","NO","INSUFFICIENT DATA") if declared.startswith(p)),None)
        require(prefix is not None, "Table 8: invalid capacity status")
        require(declared == prefix+suffixes[worst],"Table 8: incorrect data-status suffix")
    if len(counted) < 2 and counted is not None:
        require(t8[0][0].startswith("INSUFFICIENT DATA"),"Table 8: fewer than two counted months requires INSUFFICIENT DATA")
    elif headline is not None and len(counted)>=2 and not t8[0][0].startswith("INSUFFICIENT DATA"):
        require(t8[0][0].startswith("YES" if headline>0 else "NO"),"Table 8: capacity decision disagrees with HEADLINE")

    t9=t[SPEC[9][0]]
    required=["Overdraft days","Returned/NSF debit events","NSF/OD fees","Days below THIN_BALANCE","Lowest balance","FLIGHT events"]
    require([r[0] for r in t9]==required,"Table 9: fixed metric rows changed")
    class_a=sum(1 for r in t7 if r[3]=="A")
    if t9[1][1] != "—":
        count_match=re.match(r"^\s*(\d+)",t9[1][1])
        require(count_match is not None,"Table 9: class A event count is missing")
        require(int(count_match.group(1)) == class_a,"Table 9: Class A count differs from Table 7")


def main():
    if len(sys.argv)!=2:
        print("Usage: python validate_uw_report.py report.md",file=sys.stderr)
        return 2
    try:
        text=Path(sys.argv[1]).read_text(encoding="utf-8")
        validate(parse_report(text))
    except (OSError,ReportError) as e:
        print(f"FAIL: {e}",file=sys.stderr)
        return 1
    print("PASS: 10-table schema and report-visible accounting checks.")
    print("NOT VERIFIED: source-ledger truth, bidirectional funding evidence, unrounded audit calculations.")
    return 0

if __name__=="__main__":
    sys.exit(main())
