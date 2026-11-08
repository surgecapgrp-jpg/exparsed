# exparsed design review

Date: 8 November 2026. Scope: `exparsed.html` (11,627 lines, 4,447 of them the embedded engine copy), `mac_ocr_server.py`, `underwriting/`, `tests/`, at `main` commit `7f04353`. This review replaces the 2 November review, which covered commit `195252c`. That text stays in git history.

## Answer

The two core modules are deep and stay as they are: the statement reader behind `lgFileLedger(f)` and the underwriting engine behind `underwrite(raw, judgments)`. Four of the 2 November findings are done, plus half of a fifth. One major seam is still open: the page reaches Claude and OpenRouter through two separate modules.

| # | Finding | Status | Where |
| ---: | :--- | :--- | :--- |
| 1 | Two code paths for one provider pair | Deferred 8 Nov 2026. Blocked on real merchant files and API keys | Finding A |
| 2 | Engine interface leaked internals | Done in PR #5 (`0248393`). `_Engine` is private and 0 tests read its attributes | |
| 3 | Engine silently recomputed Exparsed's `computed` figures | Done in PR #5. The adapter passes `exparsed_computed` and the engine cross-checks it | |
| 4 | Three parsers for one row string | Done in PR #5. `uwLedgerRows` is deleted | |
| 5 | Tests cut the page at heading text | Done in PR #5. `tests/extract.py` reads 10 `@test-begin` regions | |
| 6 | Ledger record `L` has no written shape | Done: `LedgerRecord` typedef above `lgFinalize` | |
| 7 | `page_run` could raise; engine works twice per Run | First half done in PR #5. Second half open | Finding C |
| 8 | Labels have one owner, the engine | Holds. PR #52 moved the last page copy of engine tags out | |
| 9 | UI wiring | No change. Still one UI and no second one planned | |
| 10 | Embedded engine copy | Keep. `underwriting/embed.py` and its drift test guard it | |
| | Page copy of credit and debit tags | Done in PR #52 (`7f04353`). Questions carry `allowed` | |

## Module map

| Module | Interface | Depth |
| :--- | :--- | :--- |
| Statement reader | `lgFileLedger(f)` returns a ledger record `L` (`exparsed.html:9387`) | Deep. A file goes in and a checked ledger comes out. The record has no written shape (finding B). |
| Ledger export | `lgLedgerExport(list, opts)` returns `ledger-v1` (`:9451`) | Deep. Every downstream user reads it. |
| Computed figures | `lgComputed(list)` (`:9551`) | Deep. The engine now cross-checks it on every run. |
| Model calls | `aiCall(prov, cfg, req, fetchFn)` (`:9953`) | Shallow. `aiRequest`, `aiParse` and `aiToolResults` each branch on `prov==='claude'` (finding A). |
| OCR cloud read | `cloudOcrRead(f, port, hooks)` (`:9805`) with `claudePort` and `openrouterPort` (`:10964`, `:10997`) | Medium. Each port rebuilds the provider request that `aiRequest` already builds (finding A). |
| Underwriting engine | `underwrite(raw, judgments) -> Result` (`underwriting/engine/uw.py:3632`), `render(audit)` (`:3593`) | Deep. 3,693 lines; `_Engine` has 57 methods behind one function (finding D). |
| Adapter | `page_run(ledger_text, judgments_text, owners)` (`underwriting/adapter/exparsed_adapter.py:100`) | Right size. Returns JSON on every error path, with file and line for bugs. |
| Review queue | `uwQueue(r)` reads `q.allowed` from engine questions | Shallow by design. It keeps no tag list of its own. |
| Mac OCR server | HTTP on port 8091: `/health`, `/pdf`, `/ocr` | Deep. The page and a separate process sit on each side. |
| UI wiring | 122 top-level `var`s | Shallow by nature. Leave it. |

## Open findings

### A. Two code paths for the same two providers (deferred)

Deferred on 8 November 2026. Blocker: no real merchant statements or Claude and OpenRouter keys in the review session. Resume when both exist. Synthetic fixtures in `tests/ai.js` can start the `modelCall` interface; the OCR switch waits for the before-and-after run.

The page reaches Claude and OpenRouter in two places:
- Judgments and chat call `aiCall` (`:9953`). `aiRequest` (`:9918`) builds URL, headers and body; `aiParse` (`:9936`) reads the reply.
- OCR calls `claudePort` and `openrouterPort` (`:10964`, `:10997`). Each has 6 methods (`encode`, `check`, `send`, `read`, `fail`, `emptyHelp`) and its own `fetch`, body and stream reader (`readAnthropicStream` `:10926`, `readChatStream` `:10939`).
- PR #18 already shares the header builders `anthropicHeaders` (`:4938`) and `openrouterHeaders` (`:4947`).
- Readiness is still checked twice: `PROVIDER_DEFS[k].ready` (`:10696`) and `aiCfg()` (`:11484`).

Deletion test: delete either path and its callers must rebuild the same provider knowledge (URL, body shape, stream format, error mapping). Two adapters vary across this seam, so the seam is real. It exists twice.

Cost of leaving it: a third provider needs two adapters. OCR misses the prompt caching and the server-side model fallback that `aiRequest` sends to Claude.

Proposal: one `modelCall(provider, { system, history, content, tools, schema, stream, onText, signal })` returning `{ text, calls, stop, refusal, assistant, usage }`. Each provider adapter owns its URL, body, stream parser and error mapping. `cloudOcrRead` keeps only OCR rules: size limit, retry, cancel and empty-reply help. The OpenRouter 16,000 `max_tokens` cap and the free-model PDF-engine warning stay in the OCR caller.

Tests: `tests/ai.js` already drives request and reply shapes through a fake `fetch`. Add the stream path with a fake `ReadableStream`, then delete the OCR shape checks the new tests cover.

Verify: one real scanned PDF through Claude OCR and one through OpenRouter, before and after, give the same ledger status and row count. About 1 day. Medium risk, because it touches working OCR.

### B. The ledger record `L` has no written shape (done)

`lgFileLedger` returns an object whose 30 distinct fields are read as `L.x` across the page. Most are optional and read as `L.x||default`. Each consumer (render, export, computed, integrity report) must know which reader leaves which field empty. That knowledge lives only in the code.

Proposal: one JSDoc `@typedef` beside `lgFinalize` (`:8082`). It lists each field, the readers that set it, and when it is absent. No code change. About 1 hour.

### C. Each Run converts the same ledger several times

`uwEngine(ledgerText)` (`:11508`) calls `page_run` once per engine round: defaults, judgments, and the character round. Each call runs `normalized()` and `underwrite()` from the JSON text again. The 2 November review measured 0.4 s per call in CPython on the 3,069-row real ledger, so a Run spends roughly 1 to 4 s of Pyodide main-thread time.

Proposal: none until it is measured in the page. Time one Run in Chrome on the real ledger first. Cache the normalized bytes between rounds only if a Run takes over 5 s.

### D. The engine class is large, and its interface still holds

`underwriting/engine/uw.py` grew from 2,479 to 3,693 lines in 6 days. `_Engine` (`:609`) holds 57 methods. Only `underwrite()` and `render()` are public, and the 116 engine tests cross `underwrite()`. Callers and tests see none of this growth.

No change now. Split a stage into its own module when a change to one stage breaks tests of an unrelated stage.

## Suggested order

1. Underwrite 3 to 5 real merchant files (`HANDOFF.md` section 9, item 1). Findings A and C both need those runs as their before-and-after baseline.
2. Finding B (1 hour). Verify `node tests/run-node.js` stays at 267 passed.
3. Finding C measurement (15 minutes, during step 1).
4. Finding A (1 day), deferred. Blocked on step 1's files and keys. Verify with the OCR before-and-after check above.

Decision: **Proceed** with step 1 and finding B. **Experiment** with finding A behind the OCR comparison. **Defer** finding A until step 1 has files and keys, and findings C and D until a measurement or a failing test calls for them.
