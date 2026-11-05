# exparsed handoff

State on 2026-11-05 at `main` commit `6323ae9`. Repo: https://github.com/surgecapgrp-jpg/exparsed (private).
This file replaces the 2026-10-26 handoff. The underwriting design detail is in `underwriting/docs/HANDOFF.md`,
and the policy compliance detail is in `underwriting/docs/V1_7_MATRIX.md`.

## 1. Summary

exparsed is one HTML page that reads bank statements, checks them against their own printed totals, and
underwrites the merchant for MCA capacity under policy V1.7.

| Part | State |
| :--- | :--- |
| Statement reader | In use. 140 of 244 Desktop-set files verify from text; 29 of 42 scans verify through Mac OCR. |
| Underwriting engine | Experiment. Policy V1.7 batches 1 to 4 merged. Run on 1 real ledger and 1 synthetic ledger. |
| Underwrite button and chat | Built and tested with a mocked browser run. Never run in real Chrome with real Pyodide and a real key. |
| UI | Surge Capital theme (PR #9, merged 2026-11-04). |
| Tests | 213 JS tests, 66 engine tests, 15 end-to-end page checks: all pass on `main`. |

The next step is a real Chrome run on 3 to 5 real merchant files (section 9, item 1).

## 2. Files in the repo

| Path | What it is |
| :--- | :--- |
| `exparsed.html` | The whole app: 10,782 lines, about 700 KB. Statement reader, ledger export, OCR, AI calls, underwriting panel, chat, and an embedded copy of the Python engine. |
| `mac_ocr_server.py`, `mac_ocr.swift` | Local OCR server on `127.0.0.1:8091` (Apple Vision). The Swift helper compiles on first start. |
| `underwriting/engine/uw.py` | The underwriting engine, 3,100 lines, Python standard library only. |
| `underwriting/adapter/exparsed_adapter.py` | Converts the page's `ledger-v1` export to the engine's ledger. `page_run()` is the entry point the page calls. Holds the holiday list. |
| `underwriting/checker/validate_report.py` | The V1.7 report checker. The engine runs it on every report and fails the run on any error. |
| `underwriting/prompts/judge.md` | System prompt for the judgment call. |
| `underwriting/schemas/` | `ledger.schema.json` (engine input) and `judgments.schema.json` (model output, also sent as the structured-output schema). |
| `underwriting/embed.py` | Copies engine, adapter, checker and prompt into `exparsed.html` between the `UW-EMBED` markers (lines 454 to 4200). |
| `underwriting/tests/` | `test_engine.py` (66 tests), `make_fixture.py`, `fixtures/sample_ledger.json` (321 rows, Jun to Sep 2026) and `fixtures/sample_judgments.json`. |
| `underwriting/docs/HANDOFF.md` | Engine design, contracts, trust boundary, interpretations 1 to 19. |
| `underwriting/docs/V1_7_MATRIX.md` | 150 V1.7 rules mapped to code, interpretations B1 to B21, effect of each batch on saved runs. |
| `tests/` | JS unit tests for the page (`run-node.js` or `run.sh`), `extract.py`, synthetic samples. |
| `DESIGN_REVIEW.md` | The 2026-11-02 architecture review. Changes 2 to 5 are done; change 1 is open. |
| `underwriting/legacy/` | Empty except a cache folder. Safe to delete. |
| `tests/families.js.removed` | Old payee-grouping tests. Not run. |

The repo holds no customer statements. The one real ledger used for testing sits outside the repo
(section 8).

## 3. Running it

| Task | Command or step |
| :--- | :--- |
| Open the app | Open `exparsed.html` in Chrome. Drop statement files on the page. Nothing is uploaded except model calls. |
| OCR server | Starts at login through `~/Library/LaunchAgents/local.exparsed.macocr.plist`. Manual: `python3 mac_ocr_server.py`. Check: `launchctl list \| grep exparsed`. |
| Keys | Settings > AI providers. One Claude key and model, one OpenRouter key and model. Held in memory only, lost on reload. |
| Underwrite | Underwrite button > Run. First run downloads Pyodide 0.27.2 (about 10 MB) from cdn.jsdelivr.net. |
| Page tests | `node tests/run-node.js` (213 pass) or `bash tests/run.sh` on macOS. |
| Engine tests | `cd underwriting && python3 -m unittest discover -s tests` (66 pass). |
| Engine CLI | `python3 underwriting/engine/uw.py underwriting/tests/fixtures/sample_ledger.json --out run/` |
| After an engine change | `python3 underwriting/embed.py`. Test `PageEmbed` fails until the page copy matches. |

## 4. Statement reader

The page reads text PDFs (pdf.js), CSV, OFX/QFX, Excel (SheetJS) and scanned PDFs (Mac OCR, or Claude or
OpenRouter vision). Each file gets one status:

| Status | Meaning |
| :--- | :--- |
| verified | Rows add up to the printed balances and totals |
| partial | Some figures check; at least one total or balance is missing or off |
| break | Rows do not add up to the statement's figures |
| needs-ocr | No text layer; rerun with OCR |
| not-statement | Application, ID, contract, credit report or similar |
| untestable | No balances or totals printed |

Read path, with current line numbers in `exparsed.html`:

1. `readFileContent` (9659) is the entry. `dispatchFile` (4716) picks a reader by file type.
2. `fileOcrNeed` (9037) and `lgDocKind` (7543) decide whether a PDF needs OCR or is not a statement.
3. `doOcrMac` (10435) posts scanned pages to the OCR server. Cloud OCR goes through `cloudOcrRead` (9096).
4. `lgAccountChildren` (9669) splits a file: `lgSplitAccounts` (7863) per account heading,
   `lgSplitStatements` (7894) per repeated "Page 1 of N".
5. `lgFileLedger` (8678) builds and caches the ledger through `lgBuild` (7415) and `lgChooseReading` (7405).
   Readers: `lgParseColumnar` (6060), `lgParsePrintout` (6741), `lgParseCards` (7956), `lgParseStackedRows` (7995).
6. Shared helpers: `lgCleanLine` (5910) repairs OCR and text damage; `lgSectionOf` (5702) maps headings.
7. `recFromContent` (9679) builds the record shown on the page.
8. `lgOwnRows` (8734) drops overlapping printouts of one account. `lgLedgerExport` (8742) builds `ledger-v1`.
   `lgComputed` (8842) adds ADB, negative days and gross inflows per month.
9. Dates go through `lgDateTok`, which checks the day against the month length (leap years included).
   `lgUSDate` reads through it, so "13/40/26" and "2/30/2026" give no date (PR #12).

Last measured results (2026-10-26, not rerun since):

| Set | Result |
| :--- | :--- |
| Desktop set, 244 files, text layer | 140 verified, 23 multi-account files split into 70 verified ledgers, 0 break, 42 needs-ocr, 23 untestable, 8 not-statement, 3 partial |
| The 42 needs-ocr files through Mac OCR | 29 verified, 3 files split into 9 verified statements, 6 partial, 3 not-statement, 1 break (`Bank_Statement_5`) |
| FUNDED set, about 7,300 files | Not rerun after the October fixes |

## 5. Underwriting

### 5.1 Design

Code computes every number. The model answers a short list of classification questions and never sees a
dollar total or writes a table.

```text
statements -> lgLedgerExport (ledger-v1 JSON)
  -> page_run(ledger)            engine run 1: questions.json + default-answer report
  -> model with judge.md         judgments.json (structured output)
  -> page_run(ledger, answers)   engine run 2: checks every answer, recomputes, renders 10 tables
  -> validate_report.py          must PASS, or the run fails
  -> panel shows report; downloads: report.md, audit.json, judgments.json
```

The engine rejects a whole answer file when: the ledger hash differs, a question ID is unknown or
repeated, a tag is outside the allowed list, a strip lacks evidence, a quote is not verbatim in the
transaction text or named document, or a closure quote is not on a transaction of that payee or one
naming its funder.

### 5.2 Policy V1.7 coverage

`ENGINE_VERSION` 3.4, `POLICY_VERSION` V1.7b4. The matrix tracks 150 rules:

| Status | Rows |
| :--- | ---: |
| Met before V1.7 work | 38 |
| Changed in batch 1 (statuses Y/N/U, STRIP_UNRESOLVED, 52/12 conversion) | 19 |
| Changed in batch 2 (debit-first sweep D1 to D5, WATCH rows, identity joins, ±30-day windows) | 33 |
| Changed in batch 3 (account coverage, missing-account requests, commingling, report checker) | 24 |
| Changed in batch 4 (fixes from the 2026-11-02 spec review) | 10 |
| Partial | 20 |
| Gap | 3 |
| Handled by the page | 3 |

Gaps: D6 (reverse consolidations, processor splits, off-bank deductions), L11 (contractual cost
separate from observed), L13 (contract or lender payoff tied to the position).

Partial rows, grouped: per-file source records (R1), ownership evidence (R2), trace IDs (R3), exception
records (R7), pending rows as observations (S3), account identity beyond last four (S5), dedupe crosswalk
(S7), alternative tags (T1), off-bank exposure (T7, C5), hidden collections behind failed attempts (D5),
generic descriptors (D7), same-day doubles (D8), variable adverse scenario (D11), non-wire new senders
(C2), LLM sender identity as proof (M9), same-name renewal (M14), full credit dispositions (A2),
execution order (H11), FLIGHT inflow scope (P15).

### 5.3 Pull request history

| PR | Merge commit | Content |
| :--- | :--- | :--- |
| #4 | `8944394` | Engine runs in the page through Pyodide; one key set for OCR, judgments and chat |
| #5 | `82df417` | Design review changes 2 to 5: `underwrite()` interface, cross-check of page figures, structured chat rows, test markers |
| #6 | `c356a90` | V1.7 batch 1 and the compliance matrix |
| #7 | `e0ccc2f` | V1.7 batch 2 |
| #8 | `9b9c96c` | V1.7 batch 3 |
| #9 | `00b35ed` | Surge Capital rebrand (UI only, 1 file) |
| #10 | `8db2a61` | V1.7 batch 4 |
| #11 | `b67f148` | This handoff |
| #12 | `6323ae9` | Impossible dates rejected; Underwrite exports raw text (ported from `deepen`) |

Rollback point before all underwriting work: `283bc50`.

### 5.4 Model calls

| Item | Detail |
| :--- | :--- |
| Code | `aiRequest` (9209), `aiParse` (9227), `aiCall` (9244), `uwJudgeOnce` (9274), `uwUnderwrite` (9287), `uwRun` (10720) |
| Provider pick | OCR has its own pick. Underwriting and chat share a second pick (Claude or OpenRouter). |
| Judgment call | Non-streaming, 16,000 max tokens, Claude system prompt cached. Claude gets `output_config.format`; OpenRouter gets `response_format`. A 400 retries once without the schema. |
| Rejected answers | The engine error goes back to the model once. A second rejection shows the engine-default report with a red status line. |
| Export | Underwrite calls `lgLedgerExport(list, {redact:false, compact:false})`, so the engine sees the printed text (ORIG ID included) whatever the Redact and Compact toggles say. The export buttons still follow the toggles. |
| Bad input | A ledger row with an impossible date stops the run with `bad date` and the transaction id. |
| Fallback | Claude requests carry server-side refusal fallback (`fallbacks: "default"`). |
| Chat | Tools run in the page: `search_rows`, `read_document`, `read_audit` (13 audit sections). Results capped at 60,000 characters; 8 tool rounds per turn. System prompt: `uwChatSystem` (9369). |

### 5.5 Results on saved runs

| Run | Status | HEADLINE monthly |
| :--- | :--- | ---: |
| Sample ledger, engine defaults | INSUFFICIENT DATA | $11,577 |
| Sample ledger, saved answers | INSUFFICIENT DATA | $5,217 |
| Real ledger, engine defaults | INSUFFICIENT DATA | $74,570 |
| Real ledger, saved answers | INSUFFICIENT DATA | $39,061 |

The real ledger (1 account, 3,069 rows, Sep 2025 to Oct 2026) was YES at $44,882 under policy V2.2.
V1.7 makes it INSUFFICIENT DATA for 3 reasons:

- 4 material U positions: Accord $14,054, DIB $8,753, Eminent $7,500 and MS Equities $7,045 per month
  have no collections in 30 covered business days and no closure proof.
- TD Convenience Checking ...1272 moves $101,390 out by transfer and was not supplied (REQUEST REQUIRED).
- CHK ...1563 has two-way transfers (VERIFY OWNERSHIP).

Transfers to NST Credit Line ...6298 ($75,672) now count as debt service, which cut HEADLINE from
$44,882 to $39,061.

## 6. Decisions on record

Signed off 2026-11-02:

| # | Decision |
| :--- | :--- |
| B2 | Changed: unresolved credits never block YES. They block NO only when adding them back would reverse it. |
| B3 | Kept: unverified cadence is U with STRESS = max cleared debit x20. |
| B8 | Kept: D4 nominates a new payee after a financing credit only if it repeats or shares a word with the sender. |
| B10 | Kept: an unanswered fixed daily, weekly or biweekly series becomes a WATCH row. |

Waiting for sign-off: B1, B4 to B7, B9, B11 to B21 in `underwriting/docs/V1_7_MATRIX.md`, and the 19
readings in `underwriting/docs/HANDOFF.md` section 4.1. B18 matters most: a material missing account
also turns a NO into INSUFFICIENT DATA, while the policy text only asks to stop a YES.

## 7. Verification

| Check | Result on `main` 6323ae9 |
| :--- | :--- |
| `node tests/run-node.js` | 213 passed, 0 failed |
| `python3 -m unittest discover -s tests` in `underwriting/` | 66 passed |
| Engine self-checks per run | 17 pass on the sample |
| Report checker on every rendered report | PASS |
| End-to-end page run (headless Chromium, real engine behind a local server, mocked Pyodide and model, 3-month CSV) | 15 of 15 |
| Real ledger gross credits per month against the page's `computed` figures | Equal to the cent, 13 of 13 months |
| `bash tests/run.sh` (macOS JavaScriptCore) | Not run since PR #4 |
| Real Chrome, real Pyodide, real Claude or OpenRouter key | Never run |

## 8. Locations outside the repo

| Item | Location |
| :--- | :--- |
| Mac working copy of the page | `/Users/springfunding/JuniMyAgentVault/03_Agent_Wiki/pdf-vision-ocr/exparsed.html`. Not a git checkout; copy files into a clone to push. Check it is not older than `main`. |
| Desktop test set, 244 files | `/Users/springfunding/Desktop/test files for exparsed` |
| FUNDED set, about 7,300 files, 5.3 GB | `/Users/springfunding/JuniMyAgentVault/02_Library_Reference/pdf-vision-ocr/test-statements/FUNDED` |
| OCR server log | `~/Library/Logs/mac_ocr_server.log` |
| Real test ledger and its saved answers | Uploaded to a Claude Code cloud session (`dce0c170-ledger.json`). Temporary; keep a private copy. |
| Batch-run harness (`serve.py`, `hook.js`, `supervise.py`, `inx*.py`) | Remote branch `batch-harness` (4 commits, 2026-10-27), never merged. |
| End-to-end harness (`engine_server.py`, `e2e.js`) | Cloud session scratchpad. Temporary; not in the repo. |

## 9. Open items, in order

1. **Live run.** Open `main`'s `exparsed.html` in Chrome, add a key, underwrite 3 to 5 real merchant files.
   Record Pyodide load time, page freeze, model cost, rejected answers. This is the one check never done.
2. **Holidays for 2027.** `HOLIDAYS` in `underwriting/adapter/exparsed_adapter.py` stops at 2026. Statements
   from January 2027 will count holidays as business days. Add the Federal Reserve 2027 dates.
3. **Rejected-answer fallback.** After two rejected answer files the page shows the engine-default report.
   The V3 handoff says not to publish defaults after a model failure. Fix: show the error and no report.
4. **Sign-offs.** B18 first, then the other open interpretations (section 6).
5. **Standards fixes from the 2026-11-02 review:**
   - Commingling cutoffs, the 3x median rule, cadence cutoffs and the thin-balance factor are inline numbers in `uw.py`; the repo rule asks for named constants.
   - The worst-status order is defined in 3 files.
   - `page_run` claims it never raises, but `import uw` sits outside its `try`.
   - The checker repeats the weekly and daily conversion and hard-codes 0.60 and 20.
6. **Design review change 1.** One model-call module for OCR, judgments and chat. Today the Anthropic
   headers are built twice and `prov==='claude'` branches repeat in 3 functions.
7. **V1.7 gaps D6, L11, L13** and the 20 partial rows (section 5.2).
8. **Stage manifest** from the V3 handoff: per-stage NOT_STARTED / NEEDS_REVIEW states with input and
   policy hashes. Not started and not tracked in the matrix.
9. **Statement reader:** the 9 partial files, the upside-down check in `Bank_Statement_5`, a FUNDED rerun.
10. **Performance.** Python runs on the page's main thread. CPython takes 0.4 s on the real ledger; Pyodide
    is 2 to 5 times slower. Move it to a Web Worker if the page freezes.
11. **Review queue.** Show open questions and Table 1 notes for an underwriter, who answers in the same
    judgments format.
12. **Pricing.** Deferred by request; not started.
13. **Unmerged branches.** 3 remote branches hold commits that are not in `main`. They share no history
    with `main`; each starts with its own copy of the 2026-10-26 import.
    - `batch-harness`: 1 real commit, `tests/batch/run.js` (236 lines) and `ocr.js` under node. Merge it so batch runs can be repeated.
    - `uw-engine`: 3 real commits, a local Python model server (replaced by Pyodide in PR #4) and Python 3.9 support. `main` needs Python 3.10+.
    - `deepen`: 6 real commits of refactors. Two fixes are ported (PR #12). Its newest-first day-end fix was not needed: `main` already reverses newest-first rows. The rest (parser script split, reader snapshots, one "needs OCR" rule) is optional.

    `design-review-fixes`, `handoff-2026-11-05`, `date-and-export-fixes`, `rebrand/surge-capital`, `underwriting-in-page` and `v17-batch1` to `v17-batch4` are merged and can be deleted.
14. **Desktop set rerun after PR #12.** The stricter date check drops any row whose printed date is impossible. Rerun the 244 files and compare against section 4.

## 10. Rules for the next engineer

- Run both test suites after every change. Run `python3 underwriting/embed.py` after any change under `underwriting/`.
- Keep DOM code out of `/* @test-begin NAME */` ... `/* @test-end */` regions; `tests/extract.py` stops when markers do not pair.
- A policy value changes only with a named constant, a `POLICY_VERSION` bump and underwriter sign-off.
- A new V1.7 behaviour gets a matrix row update and a test that fails on the old code.
- The engine decides numbers. The model only answers `questions.json`, and every quote it gives must be verbatim.
