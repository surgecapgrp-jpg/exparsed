#!/usr/bin/env python3
"""Local underwriting server for Exparsed.

Exparsed's Underwriting tab posts the files loaded in its window (ledger-v1) here. This server
runs the engine, sends its questions to the model the tab picks, and answers the tab's follow-up
chat about that run. It serves JSON only; the tab is part of exparsed.html. Runs live in memory
only (last 5) and vanish when the server stops. Listens on 127.0.0.1 only.

Usage: python3 uw/server.py [--port 8092]
Keys: ANTHROPIC_API_KEY, OPENAI_API_KEY, XAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY;
UW_LOCAL_URL for a local OpenAI-compatible server (default http://localhost:11434/v1, Ollama).
"""

import argparse
import json
import re
import secrets
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "engine"))
sys.path.insert(0, str(HERE))
import adapter  # noqa: E402
import llm  # noqa: E402
import uw  # noqa: E402

DEFAULT_PORT = 8092
MAX_BODY_BYTES = 40 * 1024 * 1024
KEEP_RUNS = 5
JUDGE_PROMPT = (HERE / "prompts" / "judge.md").read_text(encoding="utf-8")
CHAT_PROMPT = (HERE / "prompts" / "chat.md").read_text(encoding="utf-8")
JUDGE_SCHEMA = json.loads(
    (HERE / "schemas" / "judgments.schema.json").read_text(encoding="utf-8")
)
_LOCAL_ORIGIN_RE = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


class Run:
    """One underwriting run: the Exparsed export and what the engine and the LLM made of it."""

    def __init__(self, export):
        self.export, self.owners, self.business = export, [], None
        self.judgments, self.judged_by, self.error = None, None, None
        self.lock = threading.Lock()
        self.compute()

    def compute(self):
        led, self.skipped = adapter.convert(self.export, self.owners, self.business)
        self.raw = json.dumps(led).encode()
        self.ledger = led
        e = uw.Engine(self.raw, self.judgments)
        self.report = e.render()
        self.audit = e.audit()
        self.audit["legacy_report_gate"] = uw.legacy_gate(self.report)
        self.questions = dict(
            ledger_sha256=e.sha,
            policy_version=uw.POLICY_VERSION,
            owner_names=e.owners,
            documents=list(e.docs.values()),
            questions=e.questions,
        )
        self.open = len(e.questions) - len(e.answers)
        self.headline = uw.usd(e.headline)

    def judge(self, model, owners, business):
        if (owners, business) != (self.owners, self.business):
            self.owners, self.business, self.judgments = owners, business, None
            self.compute()  # owner names change classification and so the questions
        j = llm.judge(
            model,
            json.loads(json.dumps(self.questions, default=uw.jsonable)),
            JUDGE_PROMPT,
            JUDGE_SCHEMA,
        )
        previous = self.judgments
        self.judgments = j
        try:
            self.compute()
        except uw.UWError as err:  # the engine is the only gate on model output
            self.judgments = previous
            self.compute()
            raise llm.LLMError(f"engine rejected the {model} answers: {err}")
        self.judged_by = model

    def context(self):
        tags = {t["txn_id"]: t["tag"] for t in self.audit["transactions"]}
        last4 = {a["account_id"]: a["last4"] for a in self.ledger["accounts"]}
        rows = "\n".join(
            "|".join(
                [
                    t["txn_id"],
                    last4[t["account_id"]],
                    t["date"],
                    t["direction"],
                    t["amount"],
                    t["balance"] or "",
                    tags.get(t["txn_id"], ""),
                    t["description"],
                    t["source_ref"],
                ]
            )
            for t in self.ledger["transactions"]
        )
        audit = {
            k: v for k, v in self.audit.items() if k != "transactions"
        }  # tags are in the rows
        return (
            f"{CHAT_PROMPT}\n\n# Report\n\n{self.report}\n\n# Audit record\n\n"
            f"{json.dumps(audit, indent=1, default=uw.jsonable)}\n\n# Accepted judgments ({self.judged_by or 'none'})\n\n"
            f"{json.dumps(self.judgments, indent=1) if self.judgments else 'None: engine defaults apply.'}\n\n"
            f"# Ledger rows\n\n{rows}\n"
        )

    def state(self):
        return dict(
            report=self.report,
            headline=self.headline,
            open_questions=self.open,
            judged_by=self.judged_by,
            skipped=[dict(file=n, reason=r) for n, r in self.skipped],
            owners=self.owners,
            business=self.business,
            context_tokens=len(self.context()) // 4,
            files=len(self.export.get("files", [])),
            transactions=len(self.ledger["transactions"]),
        )


RUNS = OrderedDict()


def make_handler(port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(
                f"[uw] {self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}",
                flush=True,
            )

        def _origin_ok(self):
            origin = self.headers.get("Origin")
            local_origin = (
                origin is None
                or origin == "null"
                or bool(_LOCAL_ORIGIN_RE.match(origin))
            )
            return (
                local_origin and self.headers.get("Host") in hosts
            )  # Host check stops DNS rebinding

        def _cors(self):
            if self._origin_ok() and self.headers.get("Origin"):
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")

        def _json(self, status, obj):
            body = json.dumps(obj, default=uw.jsonable).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _refused(self):
            if self._origin_ok():
                return False
            self._json(403, {"error": "requests from this web page are not accepted"})
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= MAX_BODY_BYTES:
                raise ValueError("request body missing or over 40 MB")
            return json.loads(self.rfile.read(n))

        def _run(self, rid):
            run = RUNS.get(rid)
            if not run:
                self._json(
                    404,
                    {
                        "error": "run not found; it was dropped or the server restarted. Press Underwrite in Exparsed again."
                    },
                )
            return run

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if self._refused():
                return
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._json(200, {"status": "ok"})
            elif path == "/models":
                models, errors = llm.available()
                self._json(200, {"models": models, "errors": errors})
            elif m := re.fullmatch(r"/runs/([0-9a-f]{16})", path):
                if run := self._run(m[1]):
                    with run.lock:
                        self._json(200, run.state())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self._refused():
                return
            path = self.path.split("?", 1)[0]
            try:
                body = self._body()
                if path == "/runs":
                    run = Run(body)
                    rid = secrets.token_hex(8)
                    RUNS[rid] = run
                    while len(RUNS) > KEEP_RUNS:
                        RUNS.popitem(last=False)
                    self._json(200, {"run": rid})
                elif m := re.fullmatch(r"/runs/([0-9a-f]{16})/(judge|chat)", path):
                    run = self._run(m[1])
                    if not run:
                        return
                    with run.lock:
                        if m[2] == "judge":
                            owners = [
                                o.strip() for o in body.get("owners", []) if o.strip()
                            ]
                            run.judge(
                                body["model"],
                                owners,
                                (body.get("business") or "").strip() or None,
                            )
                            self._json(200, run.state())
                        else:
                            msgs = [
                                dict(role=x["role"], content=str(x["content"]))
                                for x in body["messages"]
                                if x.get("role") in ("user", "assistant")
                            ]
                            self._json(
                                200,
                                {
                                    "reply": llm.complete(
                                        body["model"], run.context(), msgs
                                    )
                                },
                            )
                else:
                    self._json(404, {"error": "not found"})
            except (
                ValueError,
                KeyError,
                TypeError,
                adapter.AdapterError,
                uw.UWError,
                llm.LLMError,
            ) as e:
                self._json(
                    400,
                    {
                        "error": (
                            f"{type(e).__name__}: {e}"
                            if isinstance(e, (KeyError, TypeError))
                            else str(e)
                        )
                    },
                )

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.port))
    print(
        f"[uw] underwriting server on http://127.0.0.1:{args.port} (Ctrl-C stops it; runs are not saved)",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
