---
name: ship-exparsed
description: Test, install and link the current exparsed build. Runs the unit tests and statement regression, copies exparsed.html to the vault working copy, commits, and outputs only the links.
disable-model-invocation: true
---

Run from `/Users/springfunding/exparsed`. Stop at the first failing step and report it in one line.

1. Unit tests. Run `node tests/run-node.js` and `python3 -m unittest discover -s underwriting/tests`. Any failure stops the ship.
2. Statement regression. Run outside the sandbox (it binds a local port), in the background (the FUNDED set takes minutes):
   `python3 tests/harness/run.py --corpus` (FUNDED + REGRESSION, the permanent corpus)
   It compares each ledger with `tests/harness/results/baseline.json`, prints `reconciled X/Y` and one `WORSE` line per ledger that got worse, and exits 1 if any did. Per-ledger detail is in `tests/harness/results/last.json`.
3. Report reconciliation X/Y, the baseline X/Y, and every `WORSE` line.
4. If any ledger got worse, stop. Do not install or commit. If the run improved and nothing got worse, rerun step 2 with `--save-baseline`. When the inbox fixes are done, run `--promote` instead: it copies the inbox into REGRESSION and saves the baseline only if nothing got worse.
5. Install. Copy the current vault copy to `exparsed.before-ship.html` in the same folder, then copy `exparsed.html` to `/Users/springfunding/JuniMyAgentVault/03_Agent_Wiki/pdf-vision-ocr/exparsed.html`.
6. Commit the changed files on the current branch. A hook blocks `git push`, so say `git push` is ready for the user to run.
7. Output ONLY these two lines, no other text:
   - `file:///Users/springfunding/exparsed/exparsed.html`
   - `https://github.com/surgecapgrp-jpg/exparsed/blob/<current branch>/exparsed.html`
