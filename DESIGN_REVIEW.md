# exparsed design review, after #4

Date: 2 November 2026. Scope: `exparsed.html` (10,122 lines), `mac_ocr_server.py`, `underwriting/`, `tests/`, at commit `195252c`.

## Answer

The two core modules are deep and worth keeping as they are: the statement reader behind `lgFileLedger(f)` and the underwriting engine behind `Engine(raw, judgments)`. The problems sit at five seams around them. Each one has a duplicate, a leak or a fragile test surface. Ranked by leverage per hour:

| # | Change | Deletes | Size | Risk |
| ---: | :--- | :--- | :--- | :--- |
| 1 | One model-call module with two provider adapters, used by OCR, judgments and chat | `anthropicHeaders`, the provider branches in `aiRequest`, `PROVIDER_DEFS` ready logic | 1 day | Medium: touches working OCR |
| 2 | Engine interface becomes `underwrite(raw, judgments) -> Result`; `render` reads the audit only | Duplicate questions-doc code in `run()` and `page_run()`; 22 test reads of engine internals | 1 day | Low: 30 tests cover it |
| 3 | Engine cross-checks Exparsed's `computed` figures | The silent second calculation of gross credits and overdraft days | 2 hours | Low |
| 4 | Chat tools read structured rows; the export string format has one writer and one reader | `uwLedgerRows` (a third row parser) | 1 hour | Low |
| 5 | Explicit test markers in the page | `tests/extract.py` dependence on section-heading text | 2 hours | Low |

Smaller fixes: `page_run` catches 4 exception types while its docstring says it never raises; it also converts the ledger twice per run.

## Module map

| Module | Interface | Implementation | Depth |
| :--- | :--- | :--- | :--- |
| Statement reader | `lgFileLedger(f)` returns a ledger record `L` (`exparsed.html:8010`) | 112 functions, 3,238 lines: 5 readers, `lgChooseReading` (`:6744`), reconciliation, provenance | Deep. One call, a file in, a checked ledger out. Its output record is the weak part (finding 6). |
| Ledger export | `lgLedgerExport(list)` returns `ledger-v1` (`:8064`) | Cross-file checks, ownership, `computed` block | Deep. It is the real seam to every downstream user. |
| Computed figures | `lgComputed(list)` (`:8170`) | ADB, negative days, gross inflows, 391 lines | Deep, but duplicated downstream (finding 3). |
| OCR | `PROVIDER_DEFS[k].run(f)` (`:9220`) | Mac OCR over HTTP; Claude and OpenRouter through `cloudOcrRead(f, port, hooks)` (`:8424`) | Medium. The port has 6 methods for 2 adapters (finding 1). |
| Model calls (new) | `aiCall(prov, cfg, req)` (`:8570`) | Request and reply shapes for 2 providers | Shallow. Every function branches on `prov` (finding 1). |
| Underwriting engine | `Engine(raw, judgments)`, then `.render()`, `.audit()` and 8 attributes | 13 stages, 2,479 lines in `underwriting/engine/uw.py` | Deep inside, leaky at the edge (finding 2). |
| Adapter | `convert(src)`, `page_run(ledger, judgments)` | 200 lines | Right size. One error-handling gap (finding 7). |
| Mac OCR server | HTTP on port 8091: `/health`, `/pdf`, `/ocr` | Python plus Swift helper | Deep, real seam: the page and a separate process sit on each side. |
| UI wiring | 120 top-level `var`s, 9 sections touch the DOM | Event handlers, render functions | Shallow by nature. Leave it (finding 9). |

## Findings and improvements

### 1. Two provider seams for the same two models

The page reaches Claude and OpenRouter through two unrelated modules:
- OCR uses `claudePort` and `openrouterPort` (`:9489`, `:9524`). These are objects with 6 methods (`encode`, `check`, `send`, `read`, `fail`, `emptyHelp`), driven by `cloudOcrRead`, with streaming readers (`:9451`, `:9464`).
- Judgments and chat use `aiRequest`, `aiParse` and `aiToolResults` (`:8535` on). Each function holds an `if(prov==='claude')` branch.
- Headers are built twice: `anthropicHeaders` (`:3587`) and inline in `aiRequest`.
- Readiness is checked twice: `PROVIDER_DEFS[k].ready` and `aiCfg()`.

Deletion test: delete either module and its callers must rebuild the same provider knowledge. That knowledge is URL, headers, body shape, stream format and error mapping, so the complexity reappears. Two adapters vary across this seam, Claude and OpenRouter, so the seam is real. It just exists twice.

Proposal: one model-call module.
- Interface: `modelCall(provider, { system, history, content, tools, schema, stream, onText, signal })`. It returns `{ text, calls, stop, refusal, assistant, usage }`.
- Two adapters, `claude` and `openrouter`. Each owns its URL, headers, body, stream parser and error mapping.
- OCR becomes a caller: it passes `content` (the PDF or image block), `stream: true` and an `onText` hook that drives the live preview.
- `cloudOcrRead` keeps only what is OCR policy: size limit, retry, cancel, empty-reply help.
- One `providers` object holds `{ key, model, ready() }` per provider. The OCR pick and the chat pick each name a key into it.

Tests: `tests/ai.js` already exercises request and reply shapes through a fake `fetch`. Extend it to the stream path with a fake `ReadableStream`. Then delete the OCR-specific shape checks the new tests cover. Testing strategy is replace, don't layer.

Leverage: a third provider becomes one adapter. Prompt caching, refusal fallback and retry policy then apply to OCR too; today OCR has none of the first two.

### 2. The engine's interface leaks; the audit is not yet the contract

The handoff states that every report number traces to transaction IDs in `audit.json`. The code does not enforce that:
- `Engine.tables()` (`uw.py:1883`) builds the report from engine attributes (`self.positions`, `self.month_rows`, `self.t7` and others), so the report and the audit can drift apart.
- Callers read 8 attributes after construction. `run()` (`uw.py:2429`) and `page_run()` (`exparsed_adapter.py:72`) each rebuild the questions document from `e.sha`, `e.owners`, `e.docs` and `e.questions`.
- `tests/test_engine.py` reads engine internals 22 times (`e.positions`, `e.gate`, `e.by_id`, `e.t7` and others). Those tests break on any internal rename even when behaviour holds. They test past the interface.

Proposal:
- Interface: `underwrite(raw: bytes, judgments: dict | None) -> Result`. `Result` carries `questions`, `audit`, `report`, `status` and `open_questions`. `Engine` becomes private.
- `render(audit) -> str` reads only the audit dict. Any cell it cannot fill from the audit marks a missing audit field, so the trace requirement becomes structural.
- `run()`, `page_run()` and the tests all cross `underwrite()`.
- Rewrite the 22 internal reads as assertions on `result.audit` (positions, months, backward and forward searches, returns are all there).

Deletion test on `Engine` as a public class: delete it, keep `underwrite()`, and no caller loses capability. The class surface was shallow. The function holds the depth.

### 3. Two calculations of the same figures, one silent

Exparsed's export says "computed = arithmetic derived in code from verified rows (use them, never recompute)". The engine recomputes gross credits per month and overdraft days from rows. On the real 3,069-row ledger they agreed: gross credits on 13 of 13 full months, and overdraft days 5 = 5. That agreement was checked by hand once. Nothing checks it on the next ledger.

Proposal: the adapter passes `computed.months[]` into the normalized ledger as `exparsed_computed`. `Engine.self_check` compares gross credits per month and overdraft days. On a mismatch it adds a Table 1 note naming the month and both figures. It does not fail the run, because the two sides count the partial first day differently (Sep-25 on the real ledger). This keeps one source of policy (the engine) and turns the duplicate into a test against reality on every run.

### 4. Three parsers for one row string

`lgRowStr` (`:8009`) writes `date|section|amount|balance|page|description[|type]`. It drops an empty `type` and maps `|` in descriptions to `/`. Two readers re-parse that string: the Python adapter, and `uwLedgerRows` (`:8649`) in the chat tools. Both had to learn the empty-`type` rule separately. The Python reader missed it at first; the fix is in #4.

Proposal: chat tools read `L.rows` objects from `lgFileLedger(f)` directly. This deletes `uwLedgerRows`. The export string keeps exactly one writer (`lgRowStr`) and one reader (the adapter). Adding a column to the export then means editing two places.

### 5. The test seam is the page's text layout

`tests/extract.py` cuts the page at 8 hard-coded heading strings, for example `'    var LG_MONTHS='` to `'    /* ---------- dispatch'`. The new AI CALLS section is tested only because it sits before `RENDER`, inside the last cut. Renaming a heading, or moving a function across one, silently drops it from the tests or crashes the extract.

Proposal: mark testable regions explicitly with `/* @test-begin name */` and `/* @test-end */`. `extract.py` then concatenates every marked region and fails when it finds none. The single-file page stays as it is: `file://` distribution is the reason for the one-file design, and that holds.

### 6. The ledger record `L` has no written shape

`lgFileLedger` returns an object with 34 distinct fields read as `L.x` across the page. Most are optional and read as `L.x||default`. Every consumer (render, export, computed, integrity report) must know which fields can be missing for which reader. The interface includes these invariants, and today they live only in the code.

Proposal: one JSDoc `@typedef` beside `lgFinalize`. It lists each field, which readers set it, and when it is absent. No code change. This is the cheapest locality gain in the codebase. Revisit only if a second consumer outside the page appears; `ledger-v1` already serves the engine.

### 7. `page_run` can raise, and works twice

- `page_run` (`exparsed_adapter.py:72`) catches `UWError`, `SystemExit`, `ValueError` and `KeyError` (line 87). A `TypeError` from a malformed export escapes into Pyodide. The page reports it as a JavaScript exception without the Python traceback. Fix: catch `Exception` and return `error` plus the last traceback frame.
- Each Run calls `convert()` and `Engine()` twice, once for defaults and once with judgments. The real ledger costs 0.4 s per call in CPython, so roughly 1 to 4 s of main-thread time in Pyodide per Run. Fix after finding 2: `underwrite()` takes the already-normalized bytes, and the page caches them between the two calls.

### 8. Labels have one owner now; keep it that way

#4 completes a split the repo had started. The page computes arithmetic only; `tests/families.js.removed` records the move of payee grouping and fee labels out of the page. The engine owns every label: rules, LLM questions and the evidence gate. This is good locality. One rule keeps it: no label logic (funder names, transfer detection) goes back into the page, chat tools included. Chat already follows it, because its tools return raw rows and audit sections.

### 9. UI wiring: no change recommended

120 top-level variables and 9 DOM-touching sections look like a refactor target. They have one adapter (this page) and no second UI planned. Per the seam rule, one adapter means a hypothetical seam. Introducing a UI framework or a state store now adds permanent complexity for no caller. Revisit if a second surface (a hosted version, a CLI) needs the same flows.

### 10. Embedded engine copy: keep, with its guard

The page grew from 6,688 to 10,122 lines. 3,434 of those are the embedded engine, validator, adapter and prompt. That is the cost of running Python from a `file://` page with no server. `underwriting/embed.py` plus the drift test keep the copy honest. Alternatives (a hosted engine, a local server) break the "nothing uploaded, open in Chrome" property. Keep as is.

## Suggested order

1. Finding 7 (30 min). Then finding 2 (1 day). Verify that the 30 engine tests pass, rewritten against `result.audit`, and that the real ledger still gives HEADLINE $44,883 with the saved judgments.
2. Finding 3 (2 hours), on top of finding 2. Verify a Table 1 note appears when one month's `computed` figure is edited by hand.
3. Findings 4, 5 and 6 (half a day together). Verify node tests stay at 207 or more and the e2e check stays 15 of 15.
4. Finding 1 (1 day) last: it touches working OCR. Verify one real scanned PDF through Claude OCR before and after gives an identical ledger status and row count.

Decision: **Proceed** with steps 1 to 3. **Experiment** with step 4 behind a before/after OCR comparison on 5 real scans.
