#!/usr/bin/env python3
"""Batch regression for exparsed.html over real statement folders.

Serves the page with hook.js injected, runs headless Chrome workers over every accepted file,
and compares each ledger's status with the saved baseline.

Weekly loop:
  python3 tests/harness/run.py              test the inbox (Desktop folder of new failing files)
  python3 tests/harness/run.py --corpus     test the permanent corpus (FUNDED + REGRESSION)
  python3 tests/harness/run.py --promote    copy the inbox into REGRESSION, test the corpus, and
                                            save the baseline only if no ledger got worse
  Then empty the inbox and start the next batch.

Other flags: DIR [DIR ...] tests given folders, --workers N, --limit N, --page PATH,
--save-baseline (corpus runs only).
Writes tests/harness/results/last.json (git-ignored: it holds customer file names).
Exit code 1 when any ledger is worse than in tests/harness/results/baseline.json.
Inside the Claude Code sandbox, binding the local port fails with EPERM; run it outside.
OCR is not run: scanned files report needs-ocr.
"""
# snip: no Mac OCR pass. Add an --ocr flag (doOcrMac per needs-ocr ledger) when scans need regression.
import argparse, filecmp, json, os, re, shutil, subprocess, sys, tempfile, threading, time
from collections import Counter
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, '..', '..', 'exparsed.html')
RESULTS = os.path.join(HERE, 'results')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
# New failing statements land here during the week; a run with no flags tests this folder.
INBOX = '/Users/springfunding/Desktop/test files for exparsed'
STATEMENTS = '/Users/springfunding/JuniMyAgentVault/02_Library_Reference/pdf-vision-ocr/test-statements'
REGRESSION = os.path.join(STATEMENTS, 'REGRESSION')   # promoted inbox files, never emptied
CORPUS = [os.path.join(STATEMENTS, 'FUNDED'), REGRESSION]
RANK = {'verified': 3, 'partial': 2}   # every other status ranks 1
CLOSURE_END = '\n  })();\n  </script>'


def rank(status):
    return RANK.get(status, 1)


def page_with_hook(path):
    html = open(path, encoding='utf-8').read()
    at = html.rfind(CLOSURE_END)
    if at < 0:
        sys.exit('run.py: end of the main script closure not found in ' + path)
    hook = open(os.path.join(HERE, 'hook.js'), encoding='utf-8').read()
    ext = re.search(r"ACCEPTED_EXT='([^']+)'", html).group(1)   # same filter as the page's drop zone
    return (html[:at] + '\n' + hook + html[at:]).encode('utf-8'), re.compile(r'\.(' + ext + r')$', re.I)


def walk(root, accept):
    for dp, subs, names in os.walk(root):
        subs[:] = [s for s in subs if not s.startswith('.')]   # skip .claude and similar
        for n in sorted(names):
            if accept.search(n):
                yield os.path.join(dp, n)


def collect(dirs, accept):
    files = {}
    for d in dirs:
        root = os.path.abspath(os.path.expanduser(d))
        for p in walk(root, accept):
            files[os.path.basename(root) + '/' + os.path.relpath(p, root)] = p
    return files


def promote(accept):
    """Copy inbox files into REGRESSION. Identical files are skipped; a different file with a
    taken name gets a ' (n)' suffix. Returns the number copied."""
    n = 0
    for src in walk(INBOX, accept):
        dst = os.path.join(REGRESSION, os.path.relpath(src, INBOX))
        stem, ext = os.path.splitext(dst)
        i = 2
        while os.path.exists(dst) and not filecmp.cmp(src, dst, shallow=False):
            dst = '%s (%d)%s' % (stem, i, ext)
            i += 1
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


def run(keys, files, page, workers):
    """Serve the page and the files, run headless Chrome workers, return one result per ledger."""
    results, done, lock = [], set(), threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, body, ctype):
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == '/':
                self.send(page, 'text/html; charset=utf-8')
            elif u.path == '/list':
                i, n = int(q['shard'][0]), int(q['of'][0])
                self.send(json.dumps(keys[i::n]).encode(), 'application/json')
            elif u.path.startswith('/file/') and unquote(u.path[6:]) in files:
                self.send(open(files[unquote(u.path[6:])], 'rb').read(), 'application/octet-stream')
            else:
                self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            with lock:
                if u.path == '/result':
                    results.extend(json.loads(body))
                elif u.path == '/done':
                    done.add(parse_qs(u.query)['shard'][0])
            self.send(b'{}', 'application/json')

    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    n = max(1, min(workers, len(keys)))
    profiles = [tempfile.mkdtemp(prefix='exparsed-harness-') for _ in range(n)]
    procs = [subprocess.Popen([CHROME, '--headless=new', '--disable-gpu', '--no-first-run',
                               '--no-default-browser-check', '--disable-extensions',
                               '--user-data-dir=' + profiles[i],
                               'http://127.0.0.1:%d/?harness=1&shard=%d&of=%d' % (port, i, n)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for i in range(n)]
    deadline = time.time() + 120 + 100 * len(keys) / n   # hook.js gives up on a file after 90 s
    t0 = time.time()
    try:
        while len(done) < n and time.time() < deadline:
            time.sleep(5)
            seen = len({r['file'].split(' · ')[0] for r in results})
            print('\r%d/%d files, %ds' % (seen, len(keys), time.time() - t0), end='', flush=True)
    finally:
        for p in procs:
            p.kill()
        for d in profiles:
            shutil.rmtree(d, ignore_errors=True)
        srv.shutdown()
    print()
    got = {r['file'].split(' · ')[0] for r in results}
    results += [{'file': k, 'status': 'missing', 'rows': 0, 'breaks': 0, 'note': 'no result (worker died or run timed out)'}
                for k in keys if k not in got]
    return sorted(results, key=lambda r: r['file'])


def score(rows):
    c = Counter(r['status'] for r in rows)
    return c, len(rows) - c['not-statement']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dirs', nargs='*', help='folders to test (default: the inbox)')
    ap.add_argument('--corpus', action='store_true', help='test FUNDED + REGRESSION (about 7,500 files, 15 min)')
    ap.add_argument('--promote', action='store_true', help='copy the inbox into REGRESSION, then run --corpus')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--limit', type=int, default=0, help='first N files only (quick check)')
    ap.add_argument('--save-baseline', action='store_true', help='store this corpus run as the baseline')
    ap.add_argument('--page', default=PAGE, help='another copy of exparsed.html to test')
    a = ap.parse_args()
    corpus = a.corpus or a.promote
    if a.save_baseline and not corpus:
        sys.exit('run.py: --save-baseline needs --corpus, so the baseline never holds inbox paths')
    if corpus and (a.limit or a.dirs):
        sys.exit('run.py: --corpus and --promote run the whole corpus; drop --limit and folder arguments')

    page, accept = page_with_hook(a.page)
    if a.promote:
        print('promoted %d inbox files into %s' % (promote(accept), REGRESSION))
    dirs = a.dirs or (CORPUS if corpus else [INBOX])
    files = collect(dirs, accept)
    keys = sorted(files)[:a.limit or None]
    if not keys:
        sys.exit('run.py: no accepted files under ' + ', '.join(dirs))
    results = run(keys, files, page, a.workers)
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, 'last.json'), 'w') as f:
        json.dump(results, f, indent=1)

    c, tested = score(results)
    print('reconciled %d/%d ledgers (not-statement excluded), %d files' % (c['verified'], tested, len(keys)))
    print('  ' + ', '.join('%s %d' % kv for kv in c.most_common()))

    base_path = os.path.join(RESULTS, 'baseline.json')
    base_rows = json.load(open(base_path)) if os.path.exists(base_path) else []
    base = {r['file']: r['status'] for r in base_rows}
    inbox_root = os.path.basename(INBOX) + '/'

    def base_key(k):   # an inbox file already promoted is compared with its REGRESSION entry
        return 'REGRESSION/' + k[len(inbox_root):] if k.startswith(inbox_root) else k

    ran = {base_key(k) for k in keys}   # compare only ledgers whose source file was in this run
    now = {base_key(r['file']): r['status'] for r in results}
    worse = [(k, s, now.get(k, 'gone')) for k, s in sorted(base.items())
             if k.split(' · ')[0] in ran and rank(now.get(k, 'gone')) < rank(s)]
    better = [k for k, s in base.items() if k.split(' · ')[0] in ran and rank(now.get(k, 'gone')) > rank(s)]
    fresh = [r for r in results if base_key(r['file']) not in base]
    if base:
        bc, bt = score(base_rows)
        print('baseline %d/%d over the whole corpus; in this run %d better, %d worse, %d new' % (
            bc['verified'], bt, len(better), len(worse), len(fresh)))
    for k, old, new in worse:
        print('WORSE  %s: %s -> %s' % (k, old, new))
    for r in results:
        if r['status'] != 'verified' and not corpus:
            print('FAIL   %s: %s%s' % (r['file'], r['status'], ' (new)' if r in fresh else ''))
    if a.save_baseline or (a.promote and not worse):
        shutil.copy(os.path.join(RESULTS, 'last.json'), base_path)
        print('baseline saved')
    elif a.promote:
        print('baseline NOT saved: fix the WORSE ledgers, then run --promote again')
    sys.exit(1 if worse else 0)


if __name__ == '__main__':
    main()
