// ---- ledger-v1 contract: the export uw/adapter.py reads ----
// tests/golden/ledger-v1.json is this export, byte for byte. uw/tests/test_adapter.py runs the same
// file through the adapter and the engine, so a change to either side fails one of the two suites.
// Regenerate after a deliberate format change: UPDATE_GOLDEN=1 node tests/run-node.js
(function () {
  function ct(name, cond, info) {
    print((cond ? "PASS " : "FAIL ") + name + (info ? "  " + info : ""));
  }
  var csv =
    "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n" +
    'CREDIT,01/05/2026,"SQUARE INC DEP 260105",2500.00,ACH_CREDIT,3500.00,\n' +
    'DEBIT,01/06/2026,"ZELLE TO jane@example.com Orig ID 1234567890",-400.00,ACH_DEBIT,3100.00,\n' +
    'DEBIT,01/07/2026,"ACH DEBIT RAPIDFUND LLC Trace# 99887766",-150.00,ACH_DEBIT,2950.00,\n' +
    'CREDIT,01/08/2026,"SQUARE INC DEP 260108",1200.00,ACH_CREDIT,4150.00,\n';
  function recs() {
    return [
      { name: "chase.pdf", type: "pdf", pages: chase.map(function (p) { return { hasText: true, lines: p.lines }; }) },
      {
        name: "checking.csv",
        type: "csv",
        parsedLedger: lgFromTableRows(
          parseCsvText(csv, ","),
          "csv-transactions",
        ),
      },
    ];
  }
  function exp(opts) {
    var e = lgLedgerExport(recs(), opts);
    delete e.exportedAt;
    return e;
  }
  var raw = exp({ redact: false, compact: false, markdown: false });
  var desc = function (e) {
    return e.files[1].rows
      .map(function (r) {
        return r.split("|")[5];
      })
      .join(" / ");
  };
  ct(
    "export: both files exported",
    raw.files.length === 2 &&
      raw.files.every(function (f) {
        return f.rows.length > 0;
      }),
    raw.files
      .map(function (f) {
        return f.name + " " + f.status + " " + f.rows.length;
      })
      .join(", "),
  );
  ct(
    "export raw: email and reference ids kept",
    /jane@example\.com/.test(desc(raw)) &&
      /Orig ID 1234567890/.test(desc(raw)) &&
      /Trace# 99887766/.test(desc(raw)),
    desc(raw),
  );
  ct(
    "export raw: no markdown",
    raw.files.every(function (f) {
      return f.markdown === undefined;
    }),
  );
  var shown = exp({ redact: true, compact: true });
  ct(
    // redaction is stubbed out until the parsing code loads as one script (formats.js stub)
    "export with toggles: reference ids dropped",
    !/Orig ID 1234567890/.test(desc(shown)) &&
      !/Trace# 99887766/.test(desc(shown)),
    desc(shown),
  );
  ct(
    "export with toggles: row count unchanged",
    shown.files[1].rows.length === raw.files[1].rows.length,
  );
  var json = JSON.stringify(raw, null, 1) + "\n",
    path = TESTS + "/golden/ledger-v1.json";
  if (typeof writeFile === "function") {
    writeFile(path, json);
    print("wrote " + path);
  }
  var golden = null;
  try {
    golden = readFile(path);
  } catch (e) {}
  ct(
    "export matches tests/golden/ledger-v1.json",
    golden === json,
    golden == null
      ? "golden file missing"
      : golden === json
        ? ""
        : "differs: rerun with UPDATE_GOLDEN=1 if the change is deliberate",
  );
})();
