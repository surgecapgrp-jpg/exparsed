# MCA UW V3.0 handoff package (policy V2.2)

Code computes every number. The LLM answers a short list of classification questions, and the engine checks each answer against source text before using it.

## Files

- `docs/HANDOFF.md`: design, contracts, policy readings that need sign-off, test results.
- `engine/uw.py`: the engine. Ledger in; questions, audit record and ten-table report out. Standard library only.
- `prompts/judge.md`: the judgment prompt. Answers `questions.json`. The page chat prompt is `uwChatSystem` in `exparsed.html`.
- `schemas/ledger.schema.json`: normalized ledger the adapter must produce.
- `schemas/judgments.schema.json`: structured-output schema for the LLM call.
- `adapter/exparsed_adapter.py`: Exparsed `ledger-v1` export to normalized ledger, plus `page_run()`, the entry point `exparsed.html` calls. Checked against one real export.
- `embed.py`: copies the engine, validator, adapter and judge prompt into `exparsed.html`. Run it after changing any of them; a test fails while the page copy is stale.
- `checker/validate_report.py`: the V1.7 report checker (started as the V2.2 validator). The engine runs it on every report.
- `tests/`: synthetic fixture builder, sample ledger and judgments, 65 tests, mostly through `underwrite()`.

## Quick start

```bash
python engine/uw.py tests/fixtures/sample_ledger.json --out run/
python engine/uw.py tests/fixtures/sample_ledger.json --judgments tests/fixtures/sample_judgments.json --out run/
python -m unittest discover -s tests -v
```

The first run writes `run/questions.json` and a report on default answers (HEADLINE $17,578). The second applies the sample judgments (HEADLINE $5,218).

In the page: Underwrite button > Run. Python runs in Chrome through Pyodide; the model call uses the key from Settings > AI providers.

## Status

Experiment. Run on one real Exparsed ledger; results in `docs/HANDOFF.md` section 7.
