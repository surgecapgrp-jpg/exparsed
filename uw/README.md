# uw: underwriting from Exparsed (engine V3.0, policy V2.2)

Code computes every number. The LLM answers only the engine's judgment questions (ambiguous credits, financing evidence, funder names, the Core Operation line). The engine checks each answer against source text before using it. You pick the LLM per run, and a follow-up chat answers questions about that one run.

## Run it

```bash
pip install anthropic openai          # only the SDKs for the providers you use
export ANTHROPIC_API_KEY=...          # set any of the keys below
python3 uw/server.py                  # http://127.0.0.1:8092, stop with Ctrl-C
```

In Exparsed, load the merchant's statements, open the export menu and press **Underwrite**. Every file loaded in that window goes to the server as one ledger. A tab opens with the default-answer report.

In that tab:
1. Pick a model, add owner names and a business name, and press **Run judgments**. The engine accepts the answers or rejects the whole set and says why. A rejected set leaves the previous report in place.
2. Read the ten tables.
3. Ask questions in the chat panel. The model gets the ledger rows, report, audit record and accepted judgments. It quotes the engine's figures and transaction IDs, and computes nothing new.

Runs live in server memory only (last 5) and are gone when the server stops. Chat history lives in the tab only.

## Providers

| Provider | Key | Notes |
| :--- | :--- | :--- |
| Claude | `ANTHROPIC_API_KEY` | Anthropic SDK; structured output; server-side refusal fallback on current Opus, Fable and Sonnet 5.5 models |
| OpenAI | `OPENAI_API_KEY` | OpenAI SDK |
| xAI Grok | `XAI_API_KEY` | OpenAI SDK, `https://api.x.ai/v1` |
| Google Gemini | `GEMINI_API_KEY` | OpenAI SDK, Gemini's OpenAI-compatible endpoint |
| OpenRouter | `OPENROUTER_API_KEY` | OpenAI SDK, any model OpenRouter lists |
| Local | none | `UW_LOCAL_URL`, default `http://localhost:11434/v1` (Ollama); LM Studio is `http://localhost:1234/v1` |

The model list comes live from each provider whose key is set, so new models appear without a code change. Providers without JSON Schema output fall back to JSON mode. The engine validates every answer either way.

Privacy: the judge call sends the questions (transaction descriptions and amounts) to the chosen provider. The chat sends every ledger row. A local model keeps both on the Mac.

## Files

- `server.py`: local server and run state. `ui.html`: model picker, report, chat.
- `adapter.py`: Exparsed `ledger-v1` export to the engine's ledger. Stable transaction IDs; the same statement loaded twice is dropped as a duplicate. Federal Reserve holidays computed per year.
- `llm.py`: provider calls. `prompts/judge.md`, `prompts/chat.md`: the only two prompts.
- `engine/uw.py`, `schemas/`, `legacy/validate_uw_report_v2_2.py`: the V3.0 package, unchanged. Design and the 12 policy readings that need underwriter sign-off: `docs/HANDOFF.md` (its section 5 and `adapter/` predate this folder; `adapter.py` replaces that adapter).
- `tests/`: engine (24), adapter (6), server with a stub LLM (3). Run `python3 -m unittest discover -s uw/tests`.

## Status

Experiment. Tested on the package's synthetic ledger and Exparsed's CSV samples. Not yet run against a real merchant or a real provider. Next: one real merchant per provider, then the package's 10-ledger comparison and sign-off on `docs/HANDOFF.md` section 4.1.
