// Batch run: reads every statement in a folder through the page's real path (readFileContent, the
// account/statement split, lgFileLedger) in headless Chrome and appends one JSON line per ledger.
//   node tests/batch/run.js <dir> <out.jsonl> [--ocr] [--workers 4] [--only list.txt]
//   node tests/batch/run.js compare <old.jsonl> <new.jsonl>
// --ocr sends needs-ocr PDFs to the Mac OCR server (python3 mac_ocr_server.py) first.
// Reruns skip files already in out.jsonl, so a stopped run picks up where it left off.
// Needs Playwright: npm i playwright (uses the installed Chrome, else Playwright's Chromium).
const fs = require("fs"),
  path = require("path");

const RANK = {
  verified: 6,
  partial: 5,
  untestable: 4,
  "not-statement": 3,
  "needs-ocr": 2,
  breaks: 1,
  error: 0,
  timeout: 0,
};

function load(f) {
  const m = new Map();
  for (const l of fs.readFileSync(f, "utf8").split("\n"))
    if (l) {
      const r = JSON.parse(l);
      m.set(r.file + " | " + r.ledger, r.status);
    }
  return m;
}

function compare(a, b) {
  const old = load(a),
    now = load(b),
    tally = (m) =>
      [...m.values()].reduce((t, s) => ((t[s] = (t[s] || 0) + 1), t), {});
  console.log("old", tally(old));
  console.log("new", tally(now));
  const worse = [],
    better = [];
  for (const [k, s] of now) {
    const o = old.get(k);
    if (o === undefined || o === s) continue;
    (RANK[s] < RANK[o] ? worse : better).push(`${k}: ${o} -> ${s}`);
  }
  const gone = [...old.keys()].filter((k) => !now.has(k));
  console.log(`\n${worse.length} worse`);
  worse.forEach((l) => console.log("  " + l));
  console.log(`${better.length} better`);
  better.forEach((l) => console.log("  " + l));
  console.log(`${gone.length} ledgers missing from the new run`);
  gone.forEach((l) => console.log("  " + l));
  process.exit(worse.length ? 1 : 0);
}

// The page keeps its functions inside one closure; this exposes the ones the run needs.
const HOOK = `
    window.__exparsed=async function(name, b64, ocr){
      var bytes=Uint8Array.from(atob(b64), function(ch){ return ch.charCodeAt(0); });
      var file=new File([bytes], name), out=[];
      function report(rec, ledger, via){
        var L=lgFileLedger(rec);
        out.push({ ledger:ledger, status:L.status, note:L.note||'', docKind:L.docKind||'', rows:(L.rows||[]).length, via:via });
      }
      var c;
      try{ c=await readFileContent(file); }
      catch(e){ return [{ ledger:name, status:'error', note:String(e&&e.message||e), via:'text' }]; }
      var rec=recFromContent(name, file.size, c); rec.blob=file;
      var recs=c.children ? c.children.map(function(k){ return [recFromContent(k.name, file.size, k.content), k.name]; }) : [[rec, name]];
      if(ocr && !c.children && lgFileLedger(rec).status==='needs-ocr'){
        var r=await doOcrMac(rec);
        if(!r || !r.ok) return [{ ledger:name, status:'needs-ocr', note:'OCR failed: '+(r&&r.message||'no result'), via:'ocr' }];
        Object.assign(rec, { ocrMarkdown:r.text, ocrPages:r.pages||null, ocrSecs:r.secs, ocrStatus:'done', ocrProvider:'Mac OCR' });
        var kids=r.pages && lgAccountChildren(c, name, r.pages, { ocrStatus:'done', ocrProvider:'Mac OCR', ocrSecs:r.secs });
        recs=kids ? kids.map(function(k){ return [recFromContent(k.name, file.size, k.content), k.name]; }) : [[rec, name]];
        recs.forEach(function(p){ report(p[0], p[1], 'ocr'); });
        return out;
      }
      recs.forEach(function(p){ report(p[0], p[1], 'text'); });
      return out;
    };
  })();
  </script>`;

const EXT =
  /\.(pdf|csv|tsv|xlsx|xls|xlsm|xlsb|ods|txt|json|xml|ofx|qfx|qbo|jpg|jpeg|png|webp)$/i;
const walk = (d) =>
  fs
    .readdirSync(d, { withFileTypes: true })
    .flatMap((e) =>
      e.isDirectory()
        ? walk(path.join(d, e.name))
        : EXT.test(e.name)
          ? [path.join(d, e.name)]
          : [],
    );

async function run(dir, outFile, opts) {
  const { chromium } = require("playwright");
  const html = fs.readFileSync(
    path.join(__dirname, "..", "..", "exparsed.html"),
    "utf8",
  );
  const end = html.lastIndexOf("\n  })();\n  </script>");
  if (end < 0)
    throw new Error(
      'exparsed.html: closing "})();" of the main script not found; update HOOK placement',
    );
  const page = path.join(path.dirname(outFile), ".exparsed-hooked.html");
  fs.writeFileSync(
    page,
    html.slice(0, end) +
      HOOK +
      html.slice(end + "\n  })();\n  </script>".length),
  );

  const done = new Set(
    fs.existsSync(outFile)
      ? fs
          .readFileSync(outFile, "utf8")
          .split("\n")
          .filter(Boolean)
          .map((l) => JSON.parse(l).file)
      : [],
  );
  const only =
    opts.only &&
    new Set(
      fs
        .readFileSync(opts.only, "utf8")
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean),
    );
  const todo = walk(dir).filter((f) => {
    const rel = path.relative(dir, f);
    return (
      !done.has(rel) && (!only || only.has(rel) || only.has(path.basename(f)))
    );
  });
  console.log(
    `${todo.length} files to read (${done.size} already in ${outFile})`,
  );

  let browser;
  try {
    browser = await chromium.launch({ channel: "chrome" });
  } catch {
    browser = await chromium.launch();
  }
  const url = "file://" + path.resolve(page),
    limit = opts.ocr ? 600e3 : 120e3;
  const open = async () => {
    const p = await browser.newPage();
    await p.goto(url);
    await p.waitForFunction(() => window.__exparsed);
    return p;
  };
  let next = 0,
    n = 0;
  const worker = async () => {
    let p = await open();
    while (next < todo.length) {
      const f = todo[next++],
        rel = path.relative(dir, f);
      let res;
      const timer = new Promise((r) => setTimeout(() => r(null), limit));
      try {
        res = await Promise.race([
          p.evaluate(
            ([n, b, o]) => window.__exparsed(n, b, o),
            [
              path.basename(f),
              fs.readFileSync(f).toString("base64"),
              !!opts.ocr,
            ],
          ),
          timer,
        ]);
      } catch (e) {
        res = [
          {
            ledger: path.basename(f),
            status: "error",
            note: String(e.message).split("\n")[0],
          },
        ];
      }
      if (!res) {
        res = [
          {
            ledger: path.basename(f),
            status: "timeout",
            note: `over ${limit / 1000}s`,
          },
        ];
        await p.close().catch(() => {});
        p = await open();
      }
      fs.appendFileSync(
        outFile,
        res.map((r) => JSON.stringify({ file: rel, ...r })).join("\n") + "\n",
      );
      if (++n % 25 === 0 || n === todo.length)
        console.log(`${n}/${todo.length}`);
    }
    await p.close();
  };
  await Promise.all(
    Array.from({ length: Math.min(opts.workers, todo.length) || 1 }, worker),
  );
  await browser.close();
  fs.unlinkSync(page);
}

const a = process.argv.slice(2);
if (a[0] === "compare") compare(a[1], a[2]);
else if (a.length < 2) {
  console.error(
    "usage: node tests/batch/run.js <dir> <out.jsonl> [--ocr] [--workers 4] [--only list.txt]\n       node tests/batch/run.js compare <old.jsonl> <new.jsonl>",
  );
  process.exit(2);
} else {
  const opt = (k) => {
    const i = a.indexOf(k);
    return i < 0 ? null : a[i + 1];
  };
  run(a[0], a[1], {
    ocr: a.includes("--ocr"),
    workers: +(opt("--workers") || 4),
    only: opt("--only"),
  }).catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
