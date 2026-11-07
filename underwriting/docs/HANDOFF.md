# MCA Underwriting V3.0 Engineering Handoff (policy V1.7, batches 1 to 4)

Status: Experiment. Tested on one synthetic ledger, its variants, and one real Exparsed ledger (1 account, 3,069 posted rows, Sep 2025 to Oct 2026).
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
| Report format check | `validate_uw_report_v2_2.py` | `checker/validate_report.py`, rewritten for V1.7, run automatically after every render |
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
       runs checker/validate_report.py (V1.7 report checker) on report.md (must PASS)
  -> underwriter reviews report.md and the open items in audit.json
```

Commands:

```bash
python engine/uw.py tests/fixtures/sample_ledger.json --out run/
python engine/uw.py tests/fixtures/sample_ledger.json --judgments tests/fixtures/sample_judgments.json --out run/
python -m unittest discover -s tests -v
```

Exit codes: 0 success, 1 bad input or failed self-check (message on stderr), 2 usage error. Python 3.10+ standard library only. `jsonschema` is optional and only used by one test.

## 3. Contracts

The engine's interface is one function: `underwrite(raw, judgments=None) -> Result`. `raw` is normalized ledger bytes; `judgments` answers an earlier run's questions on the same bytes. `Result` carries `questions` (the document the LLM answers), `audit`, `report`, `status` and `open_questions`. It raises `UWError` on bad input, rejected judgments or a failed self-check. `render(audit)` builds the report from the audit alone, so a figure the audit lacks cannot reach the report. The CLI, `page_run()` and the tests all go through `underwrite()`.

`audit["exparsed_crosscheck"]` compares the engine's gross credits per account and calendar month with Exparsed's `computed.months[].grossInflows`. Exparsed leaves out partial months. A mismatch adds a Table 1 note naming the month and both sums. Overdraft days are not compared: Exparsed counts business days with a negative carried balance, and the engine counts dates with a negative end-of-day balance, an overdraft fee or an overdraft transfer.

| File | Producer | Consumer | Checked by |
| :--- | :--- | :--- | :--- |
| `schemas/ledger.schema.json` | Exparsed adapter | engine | `_Engine.load` re-checks every field in code |
| `questions.json` | engine | LLM | Question IDs are SHA-1 of their transaction IDs, so the same ledger always yields the same IDs |
| `schemas/judgments.schema.json` | LLM | engine | `_Engine.read_judgments`: ledger hash, question IDs, enums, verbatim quotes, document amount |
| `audit.json` | engine | Exparsed UI, auditors | Every report number traces to transaction IDs here |
| `report.md` | engine | underwriter | `checker/validate_report.py` (V1.7 report checker) |

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

`engine/uw.py` lines 51 to 83 hold the policy parameters as named constants, including the commingling, 3x median, cadence and thin-balance cutoffs. `checker/validate_report.py` keeps its own copy of 4 of them; a test fails when the copies differ. Changing one is a policy change: bump `POLICY_VERSION` and get underwriting sign-off.

The three V2.2 overrides are enforced by self-checks that fail the run:

1. `every STRIP_FUNDING credit passed the evidence gate`.
2. `no live cost removed by payoff estimate`. The 1.4x payback appears only as a Notes estimate.
3. Report Peak Weekly = max(observed peak week, modeled current weekly), per V1.7 K3 (batch 4). Drop Since Peak is never negative; the checker rejects one.

### 4.1 Interpretations that need underwriter sign-off

Policy V1.7 is being adopted in batches. `docs/V1_7_MATRIX.md` maps every V1.7 rule to the engine, lists what batches 1 to 3 changed, and adds interpretations B1 to B21 for sign-off.

V2.2 leaves these points open. The engine picks one reading and states it here so it can be reviewed in one place.

| # | V2.2 text | Engine reading |
| ---: | :--- | :--- |
| 1 | "Detect MCA series" | Default MCA when a payee has 3+ cleared debits at daily/weekly/biweekly cadence, same-amount runs of 3+ cover 80% of them, and the name has a funder word or the cadence is daily. 1 to 2 debits qualify only with a funder word and a debit inside the live window. The LLM can overrule both. V1.7 batch 2: monthly cadence counts, finance words inside a token count, and unanswered finance-looking payees become WATCH rows (matrix B8 to B13). |
| 2 | Class B "debit paid into overdraft" | The debit that moves the balance from 0 or above to below 0. Later debits while overdrawn are not separate events. |
| 3 | FLIGHT "an inflow" | Funding candidates and STRIP_FUNDING credits of at least 3x the median deposit. On the real ledger, applying it to every candidate gave 155 events, mostly $300 inflows. |
| 4 | Peak week "5 business days of statement coverage" | At least 5 covered business days in the Mon to Sun week, on the accounts that carry MCA collections (V1.7 batches 3 and 4). Holiday weeks with 4 business days are skipped. |
| 5 | THIN_BALANCE and lowest balance | Thin days use combined end-of-day balance across accounts, business days only. Lowest balance is the lowest single-account end-of-day balance. |
| 6 | T3 "small discretionary debits" | Every Class A chain that is not T1 or T2. Since batch 4, every non-T1 return on MCA, loan, payroll, rent, tax or insurance is T2. |
| 7 | "Pre-file requires evidence" | V1.7 batch 1: no longer inferred. A first debit within 2 payment gaps of coverage start gets the note "funding may precede coverage (unproven)"; Funding Date shows Not found. |
| 8 | Mixed calendar and statement-period accounts | V1.7 batch 3: every account uses calendar months; Days Counted is the union of covered days, and each material account needs 18 (matrix B17). |
| 9 | Balance field | Exparsed balance is the balance after that row. |
| 10 | Funding columns with several fundings | Columns show the latest attached funding. Earlier ones are listed in Notes. |
| 11 | Return pairing | A recredit matches a debit with the same account and amount in the prior 5 business days. Re-presentments within 10 business days form one chain. |
| 12 | Defaults for unanswered questions | V1.7 batch 1: unanswered candidate credits become STRIP_UNRESOLVED (out of revenue, not called financing). Unknown payees stay OTHER (outside obligations). |
| 13 | Payment level for share-of-sales remittance (V2.2 assumes fixed payments) | A confirmed series where same-amount runs cover under 80% of payments is VARIABLE. Monthly cost = cleared debits in the last 20 business days. No amount events. The real ledger has two: DoorDash Capital and Rewards Network. |
| 14 | Concurrent contracts from one payee | Split only when 3+ days have same-day debits that differ by more than 10%. Same-amount doubles are catch-up payments. A split whose tracks are not fixed-amount stays one VARIABLE position. |
| 15 | Backward search on a Pre-file start | V1.7 batch 1: every START trigger is searched, since Pre-file is no longer inferred. |
| 16 | Descriptor change | V1.7 batch 2: payees given the same funder join only on a shared originator ID, sequential continuity, or open payment slots (matrix B12). `KAPITUS SERVICIN` joins `KAPITUS` on open slots. |
| 17 | "Large/unusual credits" for the forward search | 3x median deposit counts only for payers without an established pattern (3+ credits in 2+ months). Credits from a payee the business also pays are always candidates. |
| 18 | Statement-cycle grouping | Removed in V1.7 batch 3: revenue uses calendar posting months for every account. |
| 19 | Table 4 "Possible" notes | Shown for MED or HIGH leading candidates only. LOW candidates stay in `audit.json`. |

### 4.2 Not implemented

- PDF Path B extraction checks. Exparsed already extracts and reconciles; the adapter passes its status through.
- Reverse-consolidation disclosure by month.
- Same-name renewal after a gap is handled as STOPPED then RESTARTED inside one position, with a funding search on the restart. V2.2 4E describes the same outcome.
- A holiday calendar beyond 2027. `adapter/exparsed_adapter.py` carries Federal Reserve holidays for 2025 to 2027 and stops with an error on a later year; extend `HOLIDAYS` each year.

## 5. Integration into Exparsed

1. `adapter/exparsed_adapter.py` reads the Exparsed `ledger-v1` export: `files[].rows` pipe rows, newest first, pending rows dropped, file `status` mapped to the Table 1 verdict. Transaction IDs are SHA-1 of account, date, amount, printed balance and description, since the export has none. Add funding agreements and payoff letters to `documents` when the merchant uploads them.
2. `exparsed.html` runs the engine in the browser. The Underwrite button builds the `ledger-v1` export from the loaded files, loads Pyodide 0.27.2 from jsdelivr on first use, writes the embedded sources into its file system, and calls `page_run(ledger)`.
3. The page sends `questions.json` with `prompts/judge.md` as the system prompt to the provider picked under Settings > AI providers > Underwriting and chat. Claude gets `output_config.format` (JSON schema); OpenRouter gets `response_format`. A 400 on the schema retries once without it.
4. `page_run(ledger, judgments)` validates and applies the answers. If the engine rejects them, the page sends the engine's error back to the model once and applies the corrected file. A second rejection shows the reason and no report.
5. The panel shows `report.md` and offers the report, `audit.json` and the judgments as downloads.
6. Chat in the same panel uses the same key. The model reads ledger rows, extracted documents and audit sections through three local tools (`search_rows`, `read_document`, `read_audit`), so the 642 KB ledger is never sent whole. Tool results are capped at 60,000 characters; a turn stops after 8 tool rounds.
7. Open item: show open questions and Table 1 notes as an underwriter review queue. An underwriter answer can use the same judgments format, so the model and the human share one path.

## 6. Verification

| Check | Result |
| :--- | :--- |
| `python -m unittest discover -s tests` | 85 tests pass |
| V1.7 report checker on every report the tests render | PASS (run inside `underwrite()`) |
| Self-checks per run (unrounded) | 17 pass on the sample |
| Fixtures against JSON Schemas | Pass with `jsonschema` 4.26 |
| Real Exparsed ledger, gross credits per month | Equal to Exparsed `computed.months[].grossInflows` to the cent, 13 of 13 full months |
| Real Exparsed ledger, overdraft days | 5, equal to the sum of Exparsed `businessDaysNegative` |
| Real Exparsed ledger, V1.7 report checker | PASS |

The tests cover the V2.2 regression list: unknown wire near a new debit (not stripped), documented financing (stripped and attached), amount-up trigger anchored to the first new payment, stopped position, two concurrent contracts from one funder, duplicate rows, conflicting duplicates, one-month data, integrity suffix, payoff only with evidence, negative peak drop with provisional cadence, payroll return cured within 2 business days, overdraft Class B, and five rejected-judgment cases.

## 7. First real ledger (27 Oct 2026)

Exparsed `ledger-v1`, 1 account, 3,069 posted rows, 13 counted months. Claude answered the 81 questions with `prompts/judge.md`; the engine accepted all 81 and left 1 marked unsure.

| Item | Engine defaults | With judgments |
| :--- | ---: | ---: |
| MCA positions found | 5 (1 live) | 9 (4 live) |
| Live stack, monthly | $7,800 | $21,186 |
| BASIS | $165,616 | $137,284 |
| Total obligations | $31,885 | $71,215 (4 ambiguous rows shown, not summed) |
| HEADLINE monthly | $91,569 | $44,883 |

Defaults missed Kapitus, Rewards Network, DoorDash Capital and Accord because their names carry no funder keyword. They also counted $99,155 of Kapitus funding as revenue. The run produced readings 13 to 19 in section 4.1.

## 8. Next action

Experiment: run the V2.2 LLM-only prompt and this engine on the same 10 real Exparsed ledgers. Compare true revenue, stripped funding, funding-to-debit matches, live stack and HEADLINE per ledger. Resolve each disagreement against the source rows, and get sign-off on the 19 readings in section 4.1 before broader use.
