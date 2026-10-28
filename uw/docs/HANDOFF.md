# MCA Underwriting V3.0 Engineering Handoff (policy V2.2)

Status: Experiment. Tested on one synthetic ledger and 9 variants of it. Not yet run on a real Exparsed ledger.
Date: 27 October 2026.

## 1. What changed from the V2.2 package

The V2.2 package asked an LLM to do the whole underwriting job: dedupe rows, find debit series, search 7-business-day windows, score candidates, add up revenue and rooms, then type ten Markdown tables. A separate validator could only read the finished Markdown, with $0.50 of tolerance per number.

V3.0 keeps the V2.2 policy word for word and moves the work to where it can be checked:

| Work | V2.2 package | V3.0 package |
| :--- | :--- | :--- |
| Dedupe, coverage, month counting | LLM | `engine/uw.py` |
| Debit series, events, live status, stack | LLM | `engine/uw.py` |
| Backward and forward funding searches, scores | LLM | `engine/uw.py` |
| Revenue, obligations, Rooms A to D, HEADLINE | LLM | `engine/uw.py`, exact `Decimal` |
| Returns, overdrafts, liquidity, peak | LLM | `engine/uw.py` |
| Table rendering | LLM, checked after the fact | `engine/uw.py`, from one row builder |
| Ambiguous credits, unknown payees, funder names, Core Operation | LLM | LLM, through `prompts/judge.md` |
| Proof that a credit is financing | LLM judgment of "independent evidence" | Engine verifies the quote is verbatim in bank text or a supplied document |
| Report format check | `validate_uw_report_v2_2.py` | Same file, unchanged, run automatically after every render |
| Funding decision | Underwriter | Underwriter |

The LLM never sees a dollar total and never writes a table. It answers a short list of questions. On the sample ledger it gets 9 questions for 321 transactions.

## 2. Run flow

```text
Exparsed ledger.json
  -> adapter/exparsed_adapter.py          normalized ledger (schemas/ledger.schema.json)
  -> engine/uw.py --out run/              run/questions.json + a default-answer report
  -> LLM with prompts/judge.md            run/judgments.json (schemas/judgments.schema.json)
  -> engine/uw.py --judgments ... --out run/
       validates judgments, verifies quotes, recomputes everything
       writes run/audit.json and run/report.md
       runs legacy/validate_uw_report_v2_2.py on report.md (must PASS)
  -> underwriter reviews report.md and the open items in audit.json
```

Commands:

```bash
python engine/uw.py tests/fixtures/sample_ledger.json --out run/
python engine/uw.py tests/fixtures/sample_ledger.json --judgments tests/fixtures/sample_judgments.json --out run/
python -m unittest discover -s tests -v
```

Exit codes: 0 success, 1 bad input or failed self-check (message on stderr), 2 usage error. Python 3.9+ standard library only. `jsonschema` is optional and only used by one test.

## 3. Contracts

| File | Producer | Consumer | Checked by |
| :--- | :--- | :--- | :--- |
| `schemas/ledger.schema.json` | Exparsed adapter | engine | `Engine.load` re-checks every field in code |
| `questions.json` | engine | LLM | Question IDs are SHA-1 of their transaction IDs, so the same ledger always yields the same IDs |
| `schemas/judgments.schema.json` | LLM | engine | `Engine.read_judgments`: ledger hash, question IDs, enums, verbatim quotes, document amount |
| `audit.json` | engine | Exparsed UI, auditors | Every report number traces to transaction IDs here |
| `report.md` | engine | underwriter | `legacy/validate_uw_report_v2_2.py`, unchanged |

### 3.1 Trust boundary on LLM output

`read_judgments` rejects the whole judgments file when any of these fail:

- `ledger_sha256` differs from the ledger being run.
- A `question_id` is unknown or answered twice.
- A tag is outside the allowed list for that question type.
- `STRIP_FUNDING`, `STRIP_TRANSFER` or `STRIP_OWNER` arrives without evidence.
- An evidence `quote` is not a verbatim substring of the transaction description, or of the named document.
- A `document` used for `STRIP_FUNDING` does not state the credit's amount.
- A `terminated` claim has no verbatim quote.

Bank descriptions reach the LLM as data. Whatever text the LLM writes, only enums, short funder names and one 240-character Core Operation sentence reach the report, and `cell()` strips pipes, braces and line breaks from all of them.

### 3.2 What the engine decides alone

- Financing gate condition 1: the credit text matches explicit financing wording (`LOAN`, `MCA`, `FINANCING`, `DISBURSE*`, `CASH ADVANCE`, `MERCHANT ADVANCE`, `ADVANCE FUNDING/PROCEEDS`).
- Financing gate condition 3: the credit names the funder of a confirmed 3+ payment series, and its descriptor is not an established customer pattern.
- Conditions 2 and 4 (sender identity, documents) come only from judgments. `sender_identified` strips are listed in Table 1 Notes for human verification.

## 4. Policy

`engine/uw.py` lines 35 to 53 hold every V2.2 parameter as a named constant. Changing one is a policy change: bump `POLICY_VERSION` and get underwriting sign-off.

The three V2.2 overrides are enforced by self-checks that fail the run:

1. `every STRIP_FUNDING credit passed the evidence gate`.
2. `no live cost removed by payoff estimate`. The 1.4x payback appears only as a Notes estimate.
3. Peak Handled is the largest observed fully covered week. Negative Drop Since Peak renders as-is (test `test_negative_drop_since_peak_with_provisional_cadence`).

### 4.1 Interpretations that need underwriter sign-off

V2.2 leaves these points open. The engine picks one reading and states it here so it can be reviewed in one place.

| # | V2.2 text | Engine reading |
| ---: | :--- | :--- |
| 1 | "Detect MCA series" | Default MCA when a payee has 3+ cleared debits at daily/weekly/biweekly cadence, same-amount runs of 3+ cover 80% of them, and the name has a funder word or the cadence is daily. 1 to 2 debits qualify only with a funder word and a debit inside the live window. The LLM can overrule both. |
| 2 | Class B "debit paid into overdraft" | The debit that moves the balance from 0 or above to below 0. Later debits while overdrawn are not separate events. |
| 3 | FLIGHT "an inflow" | Funding candidates and STRIP_FUNDING credits only. Applying it to every deposit flags ordinary spending. |
| 4 | Peak week "5 business days of statement coverage" | Monday to Friday all inside a statement period. Holiday weeks stay eligible. |
| 5 | THIN_BALANCE and lowest balance | Thin days use combined end-of-day balance across accounts, business days only. Lowest balance is the lowest single-account end-of-day balance. |
| 6 | T3 "small discretionary debits" | Every Class A chain that is not T1 or T2. No dollar cutoff exists in V2.2. |
| 7 | "Pre-file requires evidence" | First cleared debit within 2 normal payment gaps of coverage start. |
| 8 | Mixed calendar and statement-period accounts | Days Counted is the larger of the two counts for that month label. |
| 9 | Balance field | Exparsed balance is the balance after that row. |
| 10 | Funding columns with several fundings | Columns show the latest attached funding. Earlier ones are listed in Notes. |
| 11 | Return pairing | A recredit matches a debit with the same account and amount in the prior 5 business days. Re-presentments within 10 business days form one chain. |
| 12 | Defaults for unanswered questions | Credits stay revenue and unknown payees stay OTHER (outside obligations). On the sample this shows HEADLINE $17,578 with no answers and $5,218 with answers. Recommendation: Exparsed should not show a report to an underwriter while any `debit_group` question is open. |

### 4.2 Not implemented

- PDF Path B extraction checks. Exparsed already extracts and reconciles; the adapter passes its status through.
- Reverse-consolidation disclosure by month.
- Same-name renewal after a gap is handled as STOPPED then RESTARTED inside one position, with a funding search on the restart. V2.2 4E describes the same outcome.
- A holiday calendar. The ledger must supply `holidays`; an empty list means none.

## 5. Integration into Exparsed

1. Fill `FIELDS` and `STATUS` in `adapter/exparsed_adapter.py` from one real `ledger.json`. Add the federal bank holiday list. Add funding agreements and payoff letters to `documents` when the merchant uploads them.
2. Call `Engine(raw_ledger_bytes)` and send `questions.json` plus `prompts/judge.md` to the LLM with `schemas/judgments.schema.json` as the structured-output schema.
3. Call `Engine(raw_ledger_bytes, judgments)`. Show `report.md`. Store `audit.json` with the ledger hash.
4. Show open questions and Table 1 notes as an underwriter review queue. An underwriter answer uses the same judgments format, so the LLM and the human use one path.

## 6. Verification

| Check | Result |
| :--- | :--- |
| `python -m unittest discover -s tests` | 24 tests pass |
| Legacy V2.2 validator on every report the tests render | PASS (run inside `engine()` in the tests) |
| Self-checks per run (unrounded) | 13 pass on the sample |
| Fixtures against JSON Schemas | Pass with `jsonschema` 4.26 |
| Real Exparsed ledger | Not run |

The tests cover the V2.2 regression list: unknown wire near a new debit (not stripped), documented financing (stripped and attached), amount-up trigger anchored to the first new payment, stopped position, two concurrent contracts from one funder, duplicate rows, conflicting duplicates, one-month data, integrity suffix, payoff only with evidence, negative peak drop with provisional cadence, payroll return cured within 2 business days, overdraft Class B, and five rejected-judgment cases.

## 7. Next action

Experiment: run the V2.2 LLM-only prompt and this engine on the same 10 real Exparsed ledgers. Compare true revenue, stripped funding, funding-to-debit matches, live stack and HEADLINE per ledger. Resolve each disagreement against the source rows, and get sign-off on the 12 readings in section 4.1 before broader use.
