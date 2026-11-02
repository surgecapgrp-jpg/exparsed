#!/bin/bash
# Runs the ledger / format / grouping / Mac OCR tests against ../exparsed.html with macOS's built-in
# JavaScriptCore (no node needed). Usage: tests/run.sh [path/to/exparsed.html]
cd "$(dirname "$0")" || exit 1
PAGE="${1:-../exparsed.html}"
JSC=/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc
python3 extract.py "$PAGE" .build || exit 1
OUT=$("$JSC" -e "var TESTS='$PWD';" .build/lg.js fixtures.js desktop.js edge.js formats.js macocr.js analytics.js ocr.js ai.js 2>&1)
echo "$OUT" | grep -v '^       directions\|^```\|^[0-9][0-9]/\|^Date \|^Statement Period'
PASS=$(echo "$OUT" | grep -c '^PASS'); FAIL=$(echo "$OUT" | grep -c '^FAIL')
# a test file that throws stops early: its remaining checks never print, so count it as a failure
CRASH=$(echo "$OUT" | grep -c 'Exception:')
echo; echo "$PASS passed, $FAIL failed$( [ "$CRASH" -gt 0 ] && echo ", $CRASH test file(s) crashed" )"
[ "$FAIL" -eq 0 ] && [ "$CRASH" -eq 0 ]
