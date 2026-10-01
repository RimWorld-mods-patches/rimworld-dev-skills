"""No game required: exercise discovery, single POST, and fresh log evidence."""

from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import run_debug_action as runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "game.log"
        self.log.write_text("old COMPLETE\n", encoding="utf-8")
        self.action = dict(name="Generate test", id="test+/=?&", category="Testing",
                           assembly="Fixture", is_runnable=True)
        self.actions = [self.action]
        self.posts = []
        self.response = {"success": True}
        self.on_post = lambda: None
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, data):
                encoded = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                fixture.get_path = self.path
                self.reply({"actions": fixture.actions})

            def do_POST(self):
                fixture.posts.append((self.path, self.headers,
                                      self.rfile.read(int(self.headers.get("Content-Length", 0)))))
                fixture.on_post()
                self.reply(fixture.response)

        self.server = ThreadingHTTPServer(("localhost", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def args(self, *extra):
        return runner.parser().parse_args([
            "Generate test", "--base-url", "http://localhost:%d" % self.server.server_port,
            "--request-timeout", "1", "--wait-timeout", "0.15", *extra])

    def wait_args(self, *extra):
        return self.args("--log-file", str(self.log), "--wait-event", "COMPLETE", *extra)

    def append(self, value):
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(value)

    def test_exact_selection_encoded_id_body_and_proxy_bypass(self):
        self.actions.append(dict(self.action, name="Generate test extra"))
        with patch.dict(os.environ, {"http_proxy": "http://localhost:1", "HTTP_PROXY": "http://localhost:1", "no_proxy": ""}):
            result = runner.invoke(self.args())
        self.assertEqual("invoked_only", result["status"])
        self.assertEqual(1, len(self.posts))
        path, headers, body = self.posts[0]
        self.assertEqual(self.action["id"], parse_qs(urlsplit(path).query)["id"][0])
        self.assertEqual(b"{}", body)
        self.assertEqual("2", headers["Content-Length"])
        self.assertEqual("application/json", headers["Content-Type"])
        self.assertEqual("Generate test", parse_qs(urlsplit(self.get_path).query)["filter"][0])

    def test_missing_ambiguous_or_nonrunnable_never_posts(self):
        for actions in ([], [self.action, self.action], [dict(self.action, is_runnable=False)],
                        [dict(self.action, id="")]):
            with self.subTest(actions=actions):
                self.actions = actions
                with self.assertRaises(runner.ActionError):
                    runner.invoke(self.args())
                self.assertEqual([], self.posts)

    def test_category_and_assembly_disambiguate(self):
        self.actions = [dict(self.action, category="Other"), dict(self.action, assembly="Other"), self.action]
        self.assertEqual("invoked_only", runner.invoke(self.args("--category", "Testing", "--assembly", "Fixture"))["status"])
        self.assertEqual(1, len(self.posts))

    def test_invalid_preflight_never_posts(self):
        for extra in (("--wait-event", "COMPLETE"), ("--log-file", str(self.log)),
                      ("--fail-event", "FAIL"),
                      ("--log-file", str(self.log), "--wait-event", "["),
                      ("--log-file", str(self.log) + ".missing", "--wait-event", "COMPLETE")):
            with self.subTest(extra=extra):
                with self.assertRaises((runner.ActionError, OSError, runner.re.error)):
                    runner.invoke(self.args(*extra))
                self.assertEqual([], self.posts)

    def test_api_failure_does_not_retry(self):
        self.response = {"success": False, "error": "Fixture refused"}
        with self.assertRaisesRegex(runner.ActionError, "Fixture refused"):
            runner.invoke(self.args())
        self.assertEqual(1, len(self.posts))

    def test_stale_completion_ignored_without_retry(self):
        with self.assertRaisesRegex(runner.ActionError, "No fresh completion"):
            runner.invoke(self.wait_args())
        self.assertEqual(1, len(self.posts))

    def test_completion_during_post_is_observed(self):
        self.on_post = lambda: self.append("new COMPLETE map=2\n")
        result = runner.invoke(self.wait_args())
        self.assertEqual("completion_evidence_observed", result["status"])
        self.assertEqual("new COMPLETE map=2", result["evidence"])

    def test_queued_completion_and_split_line(self):
        timer = threading.Timer(0.04, lambda: self.append("LETE map=3\n"))
        self.addCleanup(timer.join)
        def queued():
            self.append("new COMP")
            timer.start()
        self.on_post = queued
        self.assertEqual("new COMPLETE map=3", runner.invoke(self.wait_args())["evidence"])
        self.assertEqual(1, len(self.posts))

    def test_failure_before_completion(self):
        self.on_post = lambda: self.append("REJECT map=2\nCOMPLETE map=2\n")
        with self.assertRaisesRegex(runner.ActionError, "Terminal failure evidence: REJECT"):
            runner.invoke(self.wait_args("--fail-event", "REJECT"))
        self.assertEqual(1, len(self.posts))

    def test_replacement_and_truncation_fail_closed(self):
        def replace():
            replacement = self.log.with_suffix(".new")
            replacement.write_text("COMPLETE\n", encoding="utf-8")
            replacement.replace(self.log)
        for change in (replace, lambda: self.log.write_text("", encoding="utf-8")):
            with self.subTest(change=change):
                self.log.write_text("old COMPLETE\n", encoding="utf-8")
                self.on_post = change
                with self.assertRaisesRegex(runner.ActionError, "replaced/truncated"):
                    runner.invoke(self.wait_args())

    def test_uncertain_post_outcome_does_not_retry(self):
        # Simulate response loss after the server has received the mutation.
        self.response = ["not an envelope"]
        with self.assertRaisesRegex(runner.ActionError, "POST may have run"):
            runner.invoke(self.args())
        self.assertEqual(1, len(self.posts))

    def test_cli_reports_failure_nonzero(self):
        self.actions = []
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(1, runner.main(["Generate test", "--base-url",
                                           "http://localhost:%d" % self.server.server_port]))
        self.assertIn("No POST sent", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
