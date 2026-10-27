# exparsed

`exparsed.html` reads bank statements (text PDFs, CSV, OFX, Excel, and scans through Mac OCR) into a ledger
and checks each one against the statement's own totals and balances. Open it in Chrome; nothing is uploaded.

- `mac_ocr_server.py` + `mac_ocr.swift`: the local OCR server the page uses for scans (Apple Vision, port 8091).
  Run `python3 mac_ocr_server.py`; it compiles the Swift helper (`mac_ocr`) on first start.
- `tests/`: unit tests. Run `bash tests/run.sh` (macOS) or `node tests/run-node.js`.
  `tests/README.md` also describes real statement batches (`../test-statements/...`); those hold customer
  documents and are not in this repo.

- `uw/`: underwriting. The **Underwrite** button sends loaded files to `uw/server.py`, which runs the V3.0 engine,
  asks the chosen LLM (Claude, OpenAI, Grok, Gemini, OpenRouter or a local model) its judgment questions, and hosts a
  follow-up chat. See `uw/README.md`.

Handoff notes, status and open items: `HANDOFF.md`.
