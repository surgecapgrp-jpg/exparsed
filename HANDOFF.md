# exparsed handoff

State as of 2026-10-26. Repo: https://github.com/surgecapgrp-jpg/exparsed (private, branch `main`).

## What exparsed is

`exparsed.html` is one self-contained page (6,688 lines) that turns bank statements into a ledger.
It reads text PDFs (through pdf.js), CSV, OFX/QFX, Excel (SheetJS) and scanned PDFs (through the local
Mac OCR server). Each ledger is checked against the statement's own figures: opening balance plus
credits minus debits must equal the closing balance, and section totals must match the printed
summary. Files never leave the machine. Open the page in Chrome and drop files on it.

Each file gets one status:

| Status | Meaning |
|---|---|
| verified (✓ reconciled) | rows add up to the printed balances and totals |
| partial | some figures check, at least one total or balance is missing or off |
| break | the rows do not add up to the statement's figures |
| needs-ocr | the PDF has no text layer; run it again with the OCR server up |
| not-statement | application, ID, contract, credit report or similar |
| untestable | no balances or totals printed, so nothing to check against |

## Where things live

| Item | Location |
|---|---|
| Working copy of the page | `/Users/springfunding/JuniMyAgentVault/03_Agent_Wiki/pdf-vision-ocr/exparsed.html` |
| Backup before the Desktop-set fixes | same folder, `exparsed.before-desktop-breaks.html` |
| Unit tests (working copy) | `/Users/springfunding/JuniMyAgentVault/03_Agent_Wiki/pdf-vision-ocr/test-statements/tests/` |
| OCR server (working copy) | same folder, `mac_ocr_server.py` and `mac_ocr.swift` |
| OCR server autostart | `~/Library/LaunchAgents/local.exparsed.macocr.plist`, log at `~/Library/Logs/mac_ocr_server.log` |
| Desktop test set (244 files) | `/Users/springfunding/Desktop/test files for exparsed` |
| Large test set (about 7,300 files, 5.3 GB) | `/Users/springfunding/JuniMyAgentVault/02_Library_Reference/pdf-vision-ocr/test-statements/FUNDED` |
| This repo | GitHub only. The vault folder is not a git checkout; copy changed files into a clone to push. |

The repo holds no customer statements. `tests/samples/` has synthetic files only.

## Running it

- Page: open `exparsed.html` in Chrome.
- OCR server: the launch agent starts `mac_ocr_server.py` at login on `127.0.0.1:8091` and restarts it
  after a crash. Check it with `launchctl list | grep exparsed` (a PID in the first column means it is up).
  Manual start: `python3 mac_ocr_server.py`. First start compiles `mac_ocr.swift` into `mac_ocr`
  (git-ignored). Stop autostart: `launchctl bootout gui/$(id -u)/local.exparsed.macocr`.
- Unit tests: `bash tests/run.sh` in this repo, or `bash test-statements/tests/run.sh exparsed.html`
  in the vault folder. Uses macOS JavaScriptCore, no node needed. `node tests/run-node.js` also works.
  Current result: 231 passed, 0 failed.
- Run the unit tests after every change to `exparsed.html`.

## How the page reads a file

Entry is `readFileContent` (line 5642). Line numbers below are for the committed `exparsed.html`.

1. `dispatchFile` (927) picks a reader by file type. PDFs go through pdf.js page text.
2. `fileOcrNeed` (5223) and `lgDocKind` (3740) decide whether a PDF needs OCR or is not a statement.
   Split children (`f.splitFrom`) skip the needs-OCR test.
3. `doOcrMac` (6418) posts scanned pages to the OCR server and gets lines back.
4. `lgAccountChildren` (5652) splits one file into several ledgers:
   - `lgSplitAccounts` (4060): one ledger per account heading (Numerica "ID", "Account Number: …",
     share headings).
   - `lgSplitStatements` (4091): one ledger per statement when "Page 1 of N" repeats, for files that
     hold several months.
5. `lgFileLedger` (4868) builds and caches the ledger (`_ledgerKey`) by running `lgBuild` (3612),
   which tries the readers in order:
   - `lgParseColumnar` (2259): statements with sections (Deposits, Withdrawals, Checks, Fees) and a summary.
   - `lgParsePrintout` (2940): online printouts with a running balance. `lgJoinWrappedCents` (2925)
     first rejoins cents that wrapped to the next line.
   - `lgParseCards` (4153): card-style rows.
   - `lgParseStackedRows` (4192): phone-app screenshots with amount / date and payee / balance on three lines.
6. Helpers used by all readers:
   - `lgCleanLine` (2109): fixes OCR and text-layer damage ("124.20-SC", "L,204.00", marks glued to dates).
   - `lgSectionOf` (1901): maps a heading to a section key (dep, wd, chk, fee, ret, other).
   - `lgSummaryKey` (2030): maps a summary label to a total.
   - `lgFindPeriod` (1814): finds the statement period.
   - `lgNoActivity` (3830): detects statements with no transactions.
7. `recFromContent` (5662) turns the ledger into the record shown on the page.

## Test results on the Desktop set (244 files)

Text-layer run, after this round of fixes:

| Result | Files |
|---|---|
| verified | 140 |
| multi-account files split into separate ledgers | 23 files, 70 ledgers, all verified |
| break | 0 (52 at the start) |
| needs-ocr | 42 |
| untestable | 23 |
| not-statement | 8 |
| partial | 3 |
| split children counted under their parent | 5 |

OCR run on the 42 needs-ocr files:

| Result | Files |
|---|---|
| verified | 29 (21 at the start) |
| split into statements | 3 files, 9 statements, all verified |
| partial | 6 |
| not-statement | 3 |
| break | 1 (`Bank_Statement_5`) |

Full reruns after each fix showed no file that got worse.

## Fixes made in this round

- Multi-account files read every account as its own ledger (`lgSplitAccounts`, account-number headings,
  leading zeros stripped from the id).
- Multi-statement files split on a repeated "Page 1 of N" (`lgSplitStatements`).
- New headings: PAPER DEPOSITS, FEES AND SERVICE CHARGES, EXPLANATION OF SERVICE FEES, RETURNED CHECKS
  (`ret` counts as a credit).
- Share headings such as "CHECKING-E WENAT ID: 10" and hyphenated names ("NON-INTEREST").
- Two-line balances ("Beginning balance" / "on April 1, 2026 $x") and two unlabelled period dates.
- Wells Fargo "Totals $x $y" read as the deposit and withdrawal totals.
- Header balance prefers "Current Ledger Balance" over other "present"/"current" labels.
- KeyBank dashed dates ("6-30-26") give the period.
- OCR rows whose date was not read get the date of the next row in the same section, marked "[date not read]".
- "Balance Forward" accepted as the opening balance; dated balance lines no longer count as activity.
- Page number glued to a year ("10/16/20261") in card rows.
- Phone-app stacked layout (`lgParseStackedRows`); `13/14/15_October2026` verify through it.

Tests for these are E13 to E15 in `tests/edge.js`.

## Known open items

- `Bank_Statement_5`: OCR reads one check upside down ("9207/60/90 00087 $217.50"), so the check total
  is off. Fix would be in the OCR server (detect a rotated region) or a check-row repair in `lgCleanLine`.
- 6 OCR files and 3 text files are partial. Each is missing one total or balance; none was looked at
  file by file after the last run.
- `tests/README.md` mentions statement batches under `../test-statements/`. They hold customer documents
  and stay out of this repo.
- `tests/families.js.removed` holds old tests for payee grouping, which moved to the LLM step downstream.
  It is not run.
- The FUNDED set (about 7,300 files) was not rerun after this round. Many of its files are applications,
  IDs, credit reports and contracts.

## AI providers, underwriting and chat (2026-11-02, branch `underwriting-in-page`)

| Item | Where |
|---|---|
| Keys | Settings > AI providers: one Claude key and model, one OpenRouter key and model. Held in memory only, as before. |
| Provider per job | OCR keeps its own pick (Mac OCR, Claude, OpenRouter). Underwriting and chat share a second pick (Claude or OpenRouter). |
| Underwrite button | Opens a panel over the output pane. Run: ledger export > engine through Pyodide > judgments from the model > engine again > ten-table report. |
| Engine | `underwriting/` (Python). `underwriting/embed.py` copies it into the page between the `UW-EMBED` markers. |
| Model calls | `aiRequest` / `aiCall` in the AI CALLS section of the page (pure functions, tested in `tests/ai.js`). Non-streaming, 16,000 max tokens, Claude system prompt cached. |
| Chat | Same panel. Tools run in the page: `search_rows`, `read_document`, `read_audit`. |

- Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 reject forced `tool_choice`, so judgments use structured output (`output_config.format`).
- Claude requests to Opus 5.5, Opus 5, Sonnet 5.5 and Fable 5.1 carry server-side refusal fallback (`fallbacks: "default"`, beta header `server-side-fallback-2026-07-01`).
- First Run downloads Pyodide 0.27.2 (about 10 MB) from cdn.jsdelivr.net; Chrome caches it. Offline, Run fails with a message and chat still works.
- Python runs on the page's main thread. The real 3,069-row ledger takes 0.4 s in CPython; Pyodide is typically 2 to 5 times slower. Move it to a Web Worker if the page freezes noticeably.
- Tests: `node tests/run-node.js` gives 208 passed (21 in `tests/ai.js`). `python3 -m unittest discover -s underwriting/tests` gives 56 passed. `tests/run.sh` (JSC) was not run.
- `tests/extract.py` takes the regions marked `/* @test-begin NAME */` ... `/* @test-end */` in the page and stops when the markers do not pair up. Keep DOM code out of marked regions.
- Chat reads row objects from `uwChatData`; the export and chat share `lgOwnRows`, so both drop the same duplicate printout rows.
- Not verified: Pyodide loading in a real browser, and live Claude or OpenRouter calls. A headless-Chrome run with mocked Pyodide (the real engine behind a local server), mocked Claude endpoints and a 3-month CSV passed 15 of 15 checks.

## Test harness (`tests/harness/`)

- `run.py` serves the page with `hook.js` injected and runs headless Chrome workers (`--workers`,
  default 8). Python standard library only, no CDP. Weekly loop:
  - no flags: test the inbox `~/Desktop/test files for exparsed` (new failing files); one FAIL line per file.
  - `--corpus`: test the permanent corpus, FUNDED + REGRESSION under `test-statements/`.
  - `--promote`: copy the inbox into REGRESSION, test the corpus, save the baseline if nothing got worse.
    Then empty the inbox.
- `hook.js` calls the page's own `readFileContent`, `recFromContent` and `lgBuild` (the drop path,
  including the account split) and reports one result per ledger, with the failed checks.
  A run through `addFiles` (the real drop) gave the same status on the 3 files tried.
- Results go to `tests/harness/results/last.json` (git-ignored, it holds customer file names).
  `--save-baseline` (corpus runs only) stores a run as `baseline.json`; later runs print `WORSE` lines and exit 1, and list
  ledgers missing from the baseline as `NEW`.
- `--limit N` runs the first N files (not with `--corpus`). `--page PATH` tests another copy of the page.
- Baseline on 2026-11-11: 3,672 of 8,396 ledgers verified (not-statement excluded), 7,509 files.
- It binds a local port, so it runs outside the Claude Code sandbox (or set
  `sandbox.network.allowLocalBinding: true`).
- No OCR pass: scanned files report needs-ocr.

## Suggested next steps

1. Look at the 9 partial files, biggest bank groups first.
2. Fix the upside-down check in `Bank_Statement_5`.
3. Rerun the FUNDED set and compare against the last FUNDED results.
