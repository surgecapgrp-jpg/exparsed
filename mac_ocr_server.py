#!/usr/bin/env python3
"""
Mac OCR server for exparsed.html: Apple's built-in text recognition (the Vision framework,
the engine behind Live Text), run on this Mac. Nothing leaves the machine: the server
listens on 127.0.0.1 only.

Start it (Terminal), leave the window open; Ctrl+C stops it:
  python3 /Users/springfunding/JuniMyAgentVault/03_Agent_Wiki/pdf-vision-ocr/mac_ocr_server.py

No downloads, no model, no virtualenv. It uses the system python3 and compiles the small
Swift helper next to this file (mac_ocr.swift -> mac_ocr) the first time, which needs
the Xcode Command Line Tools (`xcode-select --install`, already present if git works).

Why it exists: Unlimited-OCR writes a transcript one token at a time (5-40 s a page on an
M4 Air) and on statement tables it misread amounts, shifted them onto the wrong rows and
looped. Vision reads a page in ~0.2 s and returns each line's text with its position, so
the extractor can rebuild the page's columns and read it like a text PDF.

API
  GET    /health          -> {"status":"healthy","engine":"mac-vision","pdf":true}
  POST   /ocr             -> body {"image":"data:image/jpeg;base64,..."} (one page image)
                             reply: the helper's JSON (see mac_ocr.swift)
  POST   /pdf             -> body: the PDF's bytes. Reply {"id":..., "pages":n}. The server
                             draws the pages itself (PDFKit), so the browser sends the file once.
  GET    /pdf/<id>/<n>    -> page n (0-based), drawn and recognized; adds pxPerPt / heightPt
  DELETE /pdf/<id>        -> forget the file (also dropped after 30 minutes)
"""
import argparse
import base64
import errno
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8091
MAX_BODY_BYTES = 40 * 1024 * 1024
MAX_PDF_BYTES = 200 * 1024 * 1024
PDF_TTL = 30 * 60
HERE = os.path.dirname(os.path.abspath(__file__))
SWIFT_SRC = os.path.join(HERE, "mac_ocr.swift")
HELPER = os.path.join(HERE, "mac_ocr")
_DATA_URI_RE = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)
# Who may use the server: exparsed opened from disk (a file:// page sends Origin "null"), a page
# served from this Mac, or a client that sends no Origin (curl, scripts). Any other web page the
# user has open is refused, so it cannot keep Vision busy.
_LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")
TEMP_PREFIX = "macocr_"


def build_helper():
    """Compile mac_ocr.swift when the binary is missing or older than the source."""
    if os.path.exists(HELPER) and os.path.getmtime(HELPER) >= os.path.getmtime(SWIFT_SRC):
        return
    print("[build] compiling mac_ocr.swift (first run only, ~15 s)…", flush=True)
    r = subprocess.run(["swiftc", "-O", SWIFT_SRC, "-o", HELPER], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("[build] swiftc failed:\n" + r.stderr +
                 "\nInstall the command line tools with:  xcode-select --install")


class Worker:
    """One long-lived helper process; Vision's models load once, then each page is ~0.2 s."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None

    def _start(self):
        self.proc = subprocess.Popen([HELPER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)

    def recognize(self, path):
        return self.ask(path)

    def ask(self, request):
        with self.lock:
            for attempt in (0, 1):   # one restart if the helper died
                if self.proc is None or self.proc.poll() is not None:
                    self._start()
                try:
                    self.proc.stdin.write(request + "\n")
                    self.proc.stdin.flush()
                    line = self.proc.stdout.readline()
                    if line:
                        return json.loads(line)
                except (BrokenPipeError, ValueError):
                    pass
                self.proc = None
            return {"error": "the OCR helper stopped responding"}


class PdfStore:
    """Uploaded PDFs, kept as temp files while their pages are read."""

    def __init__(self):
        self.lock = threading.Lock()
        self.files = {}   # id -> (path, last used)
        # Uploads are bank statements: expired ones are deleted on a timer, not only when the
        # next upload arrives.
        threading.Thread(target=self._sweep, daemon=True).start()

    def _sweep(self):
        while True:
            time.sleep(60)
            with self.lock:
                self._expire()

    @staticmethod
    def remove_leftovers():
        """Delete uploads and page images an earlier run of this server left behind (it crashed,
        or was restarted): their ids died with it, so nothing else would delete them."""
        for path in glob.glob(os.path.join(tempfile.gettempdir(), TEMP_PREFIX + "*")):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _expire(self):
        now = time.time()
        for k, (path, used) in list(self.files.items()):
            if now - used > PDF_TTL:
                self.drop(k)

    def add(self, data):
        fd, path = tempfile.mkstemp(prefix=TEMP_PREFIX, suffix=".pdf")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        key = uuid.uuid4().hex
        with self.lock:
            self._expire()
            self.files[key] = (path, time.time())
        return key, path

    def get(self, key):
        with self.lock:
            hit = self.files.get(key)
            if hit:
                self.files[key] = (hit[0], time.time())
            return hit[0] if hit else None

    def drop(self, key):
        hit = self.files.pop(key, None)
        if hit:
            try:
                os.unlink(hit[0])
            except OSError:
                pass


def make_handler(worker, store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MacOCR/1.0"

        def log_message(self, fmt, *args):
            pass

        def _origin_ok(self):
            origin = self.headers.get("Origin")
            return origin is None or origin == "null" or bool(_LOCAL_ORIGIN_RE.match(origin))

        # The extractor is opened from file://, so its Origin is "null".
        def _cors(self):
            if not self._origin_ok():
                return
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def _refused(self):
            """True (and answered 403) for a request from a web page that is not exparsed."""
            if self._origin_ok():
                return False
            self._json(403, {"error": {"message": "requests from this web page are not accepted"}})
            return True

        def _json(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # exparsed.html from this folder, read fresh on every request. Chrome can block a page opened
        # from disk (file://) from reaching this server; a page served from 127.0.0.1 is not blocked.
        def _page(self):
            try:
                with open(os.path.join(HERE, "exparsed.html"), "rb") as fh:
                    body = fh.read()
            except OSError:
                self._json(404, {"error": {"message": "exparsed.html is not in " + HERE}})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if self._refused():
                return
            path = self.path.split("?", 1)[0].rstrip("/")
            if path == "/exparsed.html":
                self._page()
                return
            if path in ("/health", ""):
                self._json(200, {"status": "healthy", "engine": "mac-vision", "pdf": True})
                return
            m = re.match(r"^/pdf/([0-9a-f]{32})/(\d+)$", path)
            if not m:
                self._json(404, {"error": {"message": "not found"}})
                return
            pdf = store.get(m.group(1))
            if not pdf:
                self._json(404, {"error": {"message": "that PDF is no longer on the server; send it again"}})
                return
            result = worker.ask("pdf\t" + pdf + "\t" + m.group(2))
            if "error" in result:
                self._json(500, {"error": {"message": result["error"]}})
                return
            print(f"[ocr]  pdf page {int(m.group(2)) + 1} read in {result.get('secs', 0):.2f}s · {len(result.get('lines', []))} lines", flush=True)
            self._json(200, result)

        def do_DELETE(self):
            if self._refused():
                return
            m = re.match(r"^/pdf/([0-9a-f]{32})$", self.path.split("?", 1)[0].rstrip("/"))
            if m:
                with store.lock:
                    store.drop(m.group(1))
            self._json(200, {"ok": True})

        def _post_pdf(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_PDF_BYTES:
                self._json(413 if length > MAX_PDF_BYTES else 400, {"error": {"message": "PDF missing or too large"}})
                return
            data = self.rfile.read(length)
            if not data.startswith(b"%PDF"):
                self._json(400, {"error": {"message": "that is not a PDF"}})
                return
            key, path = store.add(data)
            pages = worker.ask("count\t" + path).get("pages", 0)
            if not pages:
                with store.lock:
                    store.drop(key)
                self._json(400, {"error": {"message": "PDFKit could not open this PDF"}})
                return
            self._json(200, {"id": key, "pages": pages})

        def do_POST(self):
            if self._refused():
                return
            route = self.path.split("?", 1)[0].rstrip("/")
            if route == "/pdf":
                self._post_pdf()
                return
            if route != "/ocr":
                self._json(404, {"error": {"message": "not found"}})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._json(413 if length > MAX_BODY_BYTES else 400, {"error": {"message": "request body missing or too large"}})
                return
            try:
                payload = json.loads(self.rfile.read(length))
                m = _DATA_URI_RE.match(payload.get("image") or "")
                raw = base64.b64decode(m.group(2)) if m else None
            except Exception:
                raw = None
            if not raw:
                self._json(400, {"error": {"message": "send {\"image\": \"data:image/...;base64,...\"}"}})
                return
            ext = {"png": ".png", "webp": ".webp"}.get(m.group(1).lower(), ".jpg")
            fd, img_path = tempfile.mkstemp(prefix=TEMP_PREFIX + "page_", suffix=ext)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(raw)
                result = worker.recognize(img_path)
            finally:
                try:
                    os.unlink(img_path)
                except OSError:
                    pass
            if "error" in result:
                self._json(500, {"error": {"message": result["error"]}})
                return
            print(f"[ocr]  page read in {result.get('secs', 0):.2f}s · {len(result.get('lines', []))} lines", flush=True)
            self._json(200, result)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Mac OCR (Apple Vision) server for exparsed.html")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    if sys.platform != "darwin":
        sys.exit("This needs macOS (it uses Apple's Vision framework).")
    build_helper()
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Worker(), PdfStore()))
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        # Usually this server, already started in another Terminal window or tab.
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=3) as r:
                running = json.load(r).get("engine") == "mac-vision"
        except Exception:
            running = False
        if running:
            print(f"Mac OCR is already running on http://127.0.0.1:{args.port} (in another Terminal "
                  f"window or tab) -- nothing to do, exparsed can use it.")
            return
        sys.exit(f"Port {args.port} is in use by another program. Stop it, or start this server "
                 f"with --port <another port> and enter that URL in exparsed's Settings.")
    httpd.daemon_threads = True
    PdfStore.remove_leftovers()   # only now: had the port been taken, they could be the running server's
    print(f"[ready] Mac OCR listening on http://127.0.0.1:{args.port}  "
          f"— pick 'Mac OCR' in exparsed. Ctrl+C to stop.\n"
          f"[open]  exparsed: http://127.0.0.1:{args.port}/exparsed.html", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[stop] bye", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
