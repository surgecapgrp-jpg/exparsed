# exparsed handoff

Code state on 2026-11-07 at `main` commit `10c0fe4` (PR #24, the last code change). Later commits that only
edit this file are not listed. Repo: https://github.com/surgecapgrp-jpg/exparsed (private).
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
| Tests | 215 JS tests, 85 engine tests, 15 end-to-end page checks: all pass on `main`. |

The next step is a real Chrome run on 3 to 5 real merchant files (section 9, item 1).

## 2. Files in the repo

| Path | What it is |
| :--- | :--- |
| `exparsed.html` | The whole app: 10,941 lines, about 700 KB. Statement reader, ledger export, OCR, AI calls, underwriting panel, chat, and an embedded copy of the Python engine. |
| `mac_ocr_server.py`, `mac_ocr.swift` | Local OCR server on `127.0.0.1:8091` (Apple Vision). The Swift helper compiles on first start. |
| `underwriting/engine/uw.py` | The underwriting engine, 3,185 lines, Python standard library only. |
| `underwriting/adapter/exparsed_adapter.py` | Converts the page's `ledger-v1` export to the engine's ledger. `page_run()` is the entry point the page calls. Holds the Federal Reserve holiday list for 2025 to 2027; a later year stops the run with an error. |
| `underwriting/checker/validate_report.py` | The V1.7 report checker. The engine runs it on every report and fails the run on any error. |
| `underwriting/prompts/judge.md` | System prompt for the judgment call. |
| `underwriting/schemas/` | `ledger.schema.json` (engine input) and `judgments.schema.json` (model output, also sent as the structured-output schema). |
| `underwriting/embed.py` | Copies engine, adapter, checker and prompt into `exparsed.html` between the `UW-EMBED` markers (lines 454 to 4352). |
| `underwriting/tests/` | `test_engine.py` (85 tests), `make_fixture.py`, `fixtures/sample_ledger.json` (321 rows, Jun to Sep 2026) and `fixtures/sample_judgments.json`. |
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
| Page tests | `node tests/run-node.js` (215 pass) or `bash tests/run.sh` on macOS. |
| Engine tests | `cd underwriting && python3 -m unittest discover -s tests` (85 pass). |
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

1. `readFileContent` (9818) is the entry. `dispatchFile` (4874) picks a reader by file type.
2. `fileOcrNeed` (9195) and `lgDocKind` (7701) decide whether a PDF needs OCR or is not a statement.
3. `doOcrMac` (10594) posts scanned pages to the OCR server. Cloud OCR goes through `cloudOcrRead` (9254).
4. `lgAccountChildren` (9828) splits a file: `lgSplitAccounts` (8021) per account heading,
   `lgSplitStatements` (8052) per repeated "Page 1 of N".
5. `lgFileLedger` (8836) builds and caches the ledger through `lgBuild` (7573) and `lgChooseReading` (7563).
   Readers: `lgParseColumnar` (6218), `lgParsePrintout` (6899), `lgParseCards` (8114), `lgParseStackedRows` (8153).
6. Shared helpers: `lgCleanLine` (6068) repairs OCR and text damage; `lgSectionOf` (5860) maps headings.
7. `recFromContent` (9838) builds the record shown on the page.
8. `lgOwnRows` (8892) drops overlapping printouts of one account. `lgLedgerExport` (8900) builds `ledger-v1`.
   `lgComputed` (9000) adds ADB, negative days and gross inflows per month.
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

`ENGINE_VERSION` 3.4, `POLICY_VERSION` V1.7b8. The matrix tracks 150 rules:

| Status | Rows |
| :--- | ---: |
| Met before V1.7 work | 38 |
| Changed in batch 1 (statuses Y/N/U, STRIP_UNRESOLVED, 52/12 conversion) | 19 |
| Changed in batch 2 (debit-first sweep D1 to D5, WATCH rows, identity joins, ±30-day windows) | 33 |
| Changed in batch 3 (account coverage, missing-account requests, commingling, report checker) | 24 |
| Changed in batch 4 (fixes from the 2026-11-02 spec review) | 10 |
| Changed in B5 (credit coverage C2, A2; PR #20) | 2 |
| Changed in B6 (debit side D8, M14, D11; PR #22) | 3 |
| Changed in B7 (records R1, R3, R7, S3, S7; PR #24) | 5 |
| Partial | 10 |
| Gap | 3 |
| Handled by the page | 3 |

Gaps: D6 (reverse consolidations, processor splits, off-bank deductions), L11 (contractual cost
separate from observed), L13 (contract or lender payoff tied to the position).

Partial rows, grouped: ownership evidence (R2), account identity beyond last four (S5), alternative tags (T1), off-bank exposure (T7, C5), hidden collections behind failed attempts (D5),
generic descriptors (D7), LLM sender identity as proof (M9),
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
| #13 | `28e2ce7` | Handoff update after #11 and #12 |
| #14 | `715f07a` | 2027 holidays, no report after twice-rejected answers, standards fixes (open items 2, 3, 5) |
| #15 | `ff1d4e9` | Handoff update after #14 |
| #16 | `f4ec5f5` | Sign-off B18: missing accounts block YES only (policy V1.7b5) |
| #17 | `f2eee77` | Handoff update after #16 |
| #18 | `d32d1cd` | One address and header builder per AI provider (open item 6) |
| #19 | `5b4add4` | Handoff update after #18 |
| #20 | `1995141` | V1.7 C2 and A2: new senders on every rail, a disposition per credit (policy V1.7b6) |
| #21 | `9411411` | Handoff update after #20 |
| #22 | `2395260` | V1.7 D8, M14, D11: concurrent doubles, same-funder renewals, adverse scenario (policy V1.7b7) |
| #23 | `318d906` | Handoff update after #22 |
| #24 | `10c0fe4` | V1.7 R1, R3, R7, S3, S7: source, transaction and exception records (policy V1.7b8) |
| #25 | `d5c4885` | Handoff update after #24 (handoff-only PRs after this one are not listed) |

Rollback point before all underwriting work: `283bc50`.

### 5.4 Model calls

| Item | Detail |
| :--- | :--- |
| Code | `aiRequest` (9367), `aiParse` (9385), `aiCall` (9402), `uwJudgeOnce` (9432), `uwUnderwrite` (9445), `uwRun` (10879) |
| Provider pick | OCR has its own pick. Underwriting and chat share a second pick (Claude or OpenRouter). |
| Judgment call | Non-streaming, 16,000 max tokens, Claude system prompt cached. Claude gets `output_config.format`; OpenRouter gets `response_format`. A 400 retries once without the schema. |
| Rejected answers | The engine error goes back to the model once. A second rejection shows the error and no report. |
| Export | Underwrite calls `lgLedgerExport(list, {redact:false, compact:false})`, so the engine sees the printed text (ORIG ID included) whatever the Redact and Compact toggles say. The export buttons still follow the toggles. |
| Bad input | A ledger row with an impossible date stops the run with `bad date` and the transaction id. |
| Fallback | Claude requests carry server-side refusal fallback (`fallbacks: "default"`). |
| Chat | Tools run in the page: `search_rows`, `read_document`, `read_audit` (13 audit sections). Results capped at 60,000 characters; 8 tool rounds per turn. System prompt: `uwChatSystem` (9528). |

### 5.5 Results on saved runs

| Run | Status | HEADLINE monthly |
| :--- | :--- | ---: |
| Sample ledger, engine defaults | INSUFFICIENT DATA | $11,577 |
| Sample ledger, saved answers | INSUFFICIENT DATA | $5,217 |
| Real ledger, engine defaults | INSUFFICIENT DATA | $74,570 |
| Real ledger, saved answers | INSUFFICIENT DATA | $39,061 |

Since V1.7b6 (PR #20) the saved real-ledger answers leave 1 question open: ADP TAX 03/09/26 $168.50, a new
sender, stays out of Mar-26 revenue. Mar-26 is not a BASIS month, so HEADLINE does not move.
Since V1.7b7 (PR #22) Table 4 notes show an adverse scenario for variable remitters: with saved answers,
REWARDS NETWORK $6,434/mo (highest 20 bd) against $3,374 in the stack. The stack uses the observed figure.
Since V1.7b8 (PR #24) the audit carries `sources`, `pending_observations`, `duplicate_crosswalk` and
`exceptions`, and reads originator IDs printed without a colon (2,057 on the real ledger). With saved
answers the KAPITUS descriptor change now joins on a shared originator ID; HEADLINE does not move.

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

Signed off 2026-11-06:

| # | Decision |
| :--- | :--- |
| B18 | Changed (PR #16, policy V1.7b5): a material missing account or an unreadable statement blocks YES only. A NO stands, because hidden MCA payments can only lower HEADLINE. The account stays under REQUEST REQUIRED and the binding line names it. |

Signed off 2026-11-07:

| # | Decision |
| :--- | :--- |
| B22 | Kept (PR #22, policy V1.7b7): same-amount same-day doubles count as a second schedule only on 3 consecutive debit days. A single double, such as the day after a holiday, is a catch-up payment. |

Waiting for sign-off: B1, B4 to B7, B9, B11 to B17, B19 to B21 in `underwriting/docs/V1_7_MATRIX.md`, and
the 19 readings in `underwriting/docs/HANDOFF.md` section 4.1.

## 7. Verification

| Check | Result on `main` 10c0fe4 |
| :--- | :--- |
| `node tests/run-node.js` | 215 passed, 0 failed |
| `python3 -m unittest discover -s tests` in `underwriting/` | 85 passed |
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
   On hold since 2026-11-06 by request. A cloud session cannot do it: cdn.jsdelivr.net is blocked, it has no key, and the merchant files are on the Mac.
2. **Holidays.** Done in PR #14: the 9 Federal Reserve 2027 dates are in `HOLIDAYS`. A statement period
   that reaches a year with no dates now stops with "no Federal Reserve holidays for YYYY". Add the 2028 dates before
   statements that run into January 2028 arrive.
3. **Rejected-answer fallback.** Done in PR #14: a second rejection shows "Engine stopped: answers rejected
   twice (...); no report" and clears any earlier report.
4. **Sign-offs.** B18 done in PR #16. The other open interpretations remain (section 6).
5. **Standards fixes from the 2026-11-02 review.** Done in PR #14. The engine's inline numbers are named
   constants at the top of `uw.py`. The adapter uses `uw.WORST_ORDER`. `import uw` sits inside `page_run`'s
   `try`. The checker keeps its own named copy of 4 policy numbers, and a test fails when they differ from the
   engine's. Report and audit output is byte-identical on the 4 saved runs.
6. **Design review change 1.** Done in PR #18, smallest version: a `providers` test region holds one address
   and one header builder per provider (`anthropicHeaders`, `openrouterHeaders`), used by OCR, model lists,
   judgments and chat. The 3 `prov==='claude'` branches in `aiRequest`, `aiParse` and `aiToolResults` stay: each
   builds a different provider's message shape. Streaming OCR and non-streaming judgments keep separate request code.
7. **V1.7 gaps D6, L11, L13** and the partial rows (section 5.2). B5 (PR #20) closed C2 and A2; B6 (PR #22)
   closed D8, M14 and D11; B7 (PR #24) closed R1, R3, R7, S3 and S7; 10 partial rows remain. Next: the document-based
   gaps (L11, L13, D6), which need the page to pass documents to the engine. P15 and M9 need sign-off first.
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

    `design-review-fixes`, `handoff-2026-11-05`, `date-and-export-fixes`, `handoff-update`, `tdd-open-items`, `handoff-pr14`, `b18-block-yes-only`, `handoff-pr16`, `model-call-module`, `handoff-pr18`, `v17-credit-coverage`, `handoff-pr20`, `v17-debit-side`, `handoff-pr22`, `v17-records`, `handoff-pr24`, `rebrand/surge-capital`, `underwriting-in-page` and `v17-batch1` to `v17-batch4` are merged and can be deleted.
14. **Desktop set rerun after PR #12.** The stricter date check drops any row whose printed date is impossible. Rerun the 244 files and compare against section 4.

## 10. Rules for the next engineer

- Run both test suites after every change. Run `python3 underwriting/embed.py` after any change under `underwriting/`.
- Keep DOM code out of `/* @test-begin NAME */` ... `/* @test-end */` regions; `tests/extract.py` stops when markers do not pair.
- A policy value changes only with a named constant, a `POLICY_VERSION` bump and underwriter sign-off.
- A new V1.7 behaviour gets a matrix row update and a test that fails on the old code.
- The engine decides numbers. The model only answers `questions.json`, and every quote it gives must be verbatim.
- Update this file in the same PR as the code change: header commit, PR table row, test counts, line numbers.
  A docs-only PR afterwards is then not needed.
