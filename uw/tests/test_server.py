#!/usr/bin/env python3
"""Smoke test for server.py with a stub in place of the LLM: post, judge, reject, chat, refuse."""

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
import server  # noqa: E402
from test_adapter import SAMPLE, to_export  # noqa: E402

CALLS = []


def stub_complete(ref, system, messages, schema=None):
    CALLS.append(dict(ref=ref, system=system, messages=messages, schema=schema))
    if schema is None:
        return "stub reply"
    q = json.loads(messages[0]["content"])
    if ref == "stub:bad":  # removes revenue without evidence: the engine must reject it
        first = next(
            x for x in q["questions"] if x["question_id"].startswith("Q-credit")
        )
        return json.dumps(
            {"answers": [{"question_id": first["question_id"], "tag": "STRIP_FUNDING"}]}
        )
    core = next(x for x in q["questions"] if x["question_id"].startswith("Q-core"))
    return (
        "```json\n"
        + json.dumps(
            {
                "ledger_sha256": "0" * 64,
                "answers": [
                    {
                        "question_id": core["question_id"],
                        "text": "Restaurant paid mostly through Square.",
                    }
                ],
            }
        )
        + "\n```"
    )


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.llm.complete = stub_complete
        server.llm.PROVIDERS["stub"] = dict(label="Stub", key=None, base=None)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = cls.httpd.server_address[1]
        cls.httpd.RequestHandlerClass = server.make_handler(cls.port)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def call(self, method, path, body=None, headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "null",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_flow(self):
        code, r = self.call("POST", "/runs", to_export(SAMPLE))
        self.assertEqual(code, 200, r)
        rid = r["run"]
        code, s = self.call("GET", f"/runs/{rid}")
        self.assertEqual((code, s["judged_by"], s["transactions"]), (200, None, 321))
        open_before = s["open_questions"]

        code, s = self.call(
            "POST",
            f"/runs/{rid}/judge",
            {
                "model": "stub:good",
                "owners": ["Jane Doe"],
                "business": "Sample Bistro LLC",
            },
        )
        self.assertEqual(code, 200, s)
        self.assertEqual(s["judged_by"], "stub:good")
        self.assertIn("Restaurant paid mostly through Square.", s["report"])
        self.assertNotIn("minLength", json.dumps(CALLS[-1]["schema"]))
        good_report = s["report"]

        code, r = self.call(
            "POST",
            f"/runs/{rid}/judge",
            {
                "model": "stub:bad",
                "owners": ["Jane Doe"],
                "business": "Sample Bistro LLC",
            },
        )
        self.assertEqual(code, 400)
        self.assertIn("engine rejected", r["error"])
        code, s = self.call("GET", f"/runs/{rid}")
        self.assertEqual(
            (s["judged_by"], s["report"]), ("stub:good", good_report)
        )  # previous answers kept
        self.assertLess(s["open_questions"], open_before + 1)

        code, r = self.call(
            "POST",
            f"/runs/{rid}/chat",
            {
                "model": "stub:x",
                "messages": [
                    {"role": "user", "content": "Which MCA positions are live?"}
                ],
            },
        )
        self.assertEqual((code, r["reply"]), (200, "stub reply"))
        system = CALLS[-1]["system"]
        self.assertIn("# Ledger rows", system)
        self.assertIn("SQUARE INC DEP", system)
        self.assertIn("Table 9", system)

    def test_refuses_other_origins_and_hosts(self):
        self.assertEqual(
            self.call("GET", "/health", headers={"Origin": "https://example.com"})[0],
            403,
        )
        self.assertEqual(
            self.call("GET", "/health", headers={"Host": "attacker.example:80"})[0], 403
        )
        self.assertEqual(self.call("GET", "/health")[0], 200)

    def test_bad_input(self):
        self.assertEqual(self.call("POST", "/runs", {"format": "other"})[0], 400)
        self.assertEqual(self.call("GET", "/runs/0123456789abcdef")[0], 404)


if __name__ == "__main__":
    unittest.main()
