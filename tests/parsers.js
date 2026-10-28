// ---- money and date readers: characterization snapshot ----
// Every reader's output for a fixed set of inputs, checked against tests/golden/parsers.json.
// A change that alters any output fails here with the input, the old output and the new one.
// Keep a difference only when it is a deliberate fix, then: UPDATE_GOLDEN=1 node tests/run-node.js
(function () {
  var MONEY = [
    "0.00",
    ".75",
    "1.00",
    "12.34",
    "1,234.56",
    "1234.56",
    "12,345,678.90",
    "$1,234.56",
    "$ 1,234.56",
    "-1.00",
    "-$1.00",
    "$-1.00",
    "1.00-",
    "(1.00)",
    "($1,234.56)",
    "−12.34",
    "–12.34",
    "12.34 DR",
    "12.34 CR",
    "12.34DR",
    "(25.00) CR",
    "*12.34",
    "12.34*",
    "1,23.45",
    "1234,567.89",
    "25",
    "25.5",
    "25.555",
    "1e2",
    "0x10",
    "+12.34",
    "12.34+",
    "ACH DEBIT 12.34 FEE",
    "Balance 1,000.00 on 01/05",
    "",
    "  ",
    null,
    undefined,
    12.34,
    -5,
    "abc",
    "12.3",
    "1.234,56",
    "€12.34",
    "£12.34",
    "12. 34",
    "1 234.56",
    "-$ 1.00-",
  ];
  var DATES = [
    "01/05/26",
    "1/5/26",
    "01/05/2026",
    "1/5/2026",
    "13/40/26",
    "00/10/26",
    "12/31/2026",
    " 01/05/26",
    "01/05/26 ",
    "01-05-26",
    "01-05-2026",
    "01/05",
    "1/5",
    "01-05",
    "2026-01-05",
    "2026/1/5",
    "20260105",
    "20260105120000",
    "Jan 5",
    "Jan. 5, 2026",
    "JAN 05",
    "January 5, 2026",
    "Sept 30, 2026",
    "Sep 30 2026",
    "Apr06",
    "Ene 5",
    "5 Jan 2026",
    "31 Jul 2026",
    "31 July 2026",
    "Jan 32",
    "Feb 30",
    "D:20260105120000",
    "D:202601051200Z",
    "",
    null,
    "Mon",
    "2026-13-01",
    "1/5/26 10:00",
    "01/05/2026T10:00",
    "Jan 5, 2026 10:00",
    "Dec 31",
    "Jan 1",
  ];
  var PERIODS = [
    null,
    { start: "2025-12-15", end: "2026-01-14" },
    { start: "2026-01-01", end: "2026-01-31" },
    { start: "2026-12-20", end: "2027-01-19" },
  ];
  function call(fn, args) {
    try {
      var v = fn.apply(null, args);
      return v === undefined ? "(undefined)" : v;
    } catch (e) {
      return "throws " + e.message;
    }
  }
  var out = {};
  function each(name, inputs, fn) {
    out[name] = {};
    inputs.forEach(function (x) {
      out[name][
        JSON.stringify(x) === undefined ? "undefined" : JSON.stringify(x)
      ] = call(fn, [x]);
    });
  }
  each("lgCents", MONEY, lgCents);
  each("lgCentsNum", MONEY, lgCentsNum);
  each("lgDecCents", MONEY, lgDecCents);
  each("lgJsonAmount", MONEY, lgJsonAmount);
  each("lgDlCents", MONEY, lgDlCents);
  each("lgIsMoney", MONEY, lgIsMoney);
  each("parseMoneyCell", MONEY, parseMoneyCell);
  each(
    "lgPrintedAmts",
    MONEY.filter(function (x) {
      return typeof x === "string";
    }).concat(["Fees 12.34 and (5.00) and 7.50-"]),
    lgPrintedAmts,
  );
  each("lgUSDate", DATES, lgUSDate);
  each("lgDateTok", DATES, lgDateTok);
  each("lgDateIso", DATES, lgDateIso);
  each("lgParseLongDate", DATES, lgParseLongDate);
  each("lgParseDayFirst", DATES, lgParseDayFirst);
  each("lgJsonDate", DATES, lgJsonDate);
  each("lgOfxDate", DATES, lgOfxDate);
  each("lgDlDate", DATES, lgDlDate);
  each("lgPdfDate", DATES, lgPdfDate);
  each("visionDateKey", DATES, visionDateKey);
  out.lgIsoFromMMDD = {};
  ["01/05", "12/31", "12/20", "01/14", "02/29", "06/15"].forEach(function (md) {
    PERIODS.forEach(function (p) {
      out.lgIsoFromMMDD[md + " " + JSON.stringify(p)] = call(lgIsoFromMMDD, [
        md,
        p,
      ]);
    });
  });
  var json = JSON.stringify(out, null, 1) + "\n",
    path = TESTS + "/golden/parsers.json";
  if (typeof writeFile === "function") {
    writeFile(path, json);
    print("wrote " + path);
  }
  var golden = null;
  try {
    golden = JSON.parse(readFile(path));
  } catch (e) {}
  if (!golden) {
    print("FAIL readers snapshot: tests/golden/parsers.json missing");
    return;
  }
  Object.keys(out).forEach(function (fn) {
    var diffs = Object.keys(out[fn]).filter(function (k) {
      return (
        JSON.stringify(out[fn][k]) !==
        JSON.stringify(golden[fn] && golden[fn][k])
      );
    });
    print(
      (diffs.length ? "FAIL " : "PASS ") +
        "readers snapshot: " +
        fn +
        " (" +
        Object.keys(out[fn]).length +
        " inputs)" +
        (diffs.length ? "" : ""),
    );
    diffs.forEach(function (k) {
      print(
        "       " +
          k +
          ": was " +
          JSON.stringify(golden[fn] && golden[fn][k]) +
          ", now " +
          JSON.stringify(out[fn][k]),
      );
    });
  });
})();
