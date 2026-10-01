#!/usr/bin/env python3
"""Invoke exactly one discovered debug action; optionally await fresh log evidence."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class ActionError(Exception):
    pass


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and positive")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("name", help="exact action name, not a substring")
    result.add_argument("--category", help="optional exact category")
    result.add_argument("--assembly", help="optional exact assembly")
    result.add_argument("--base-url", default="http://localhost:8765")
    result.add_argument("--request-timeout", type=positive_seconds, default=60)
    result.add_argument("--log-file", type=Path)
    result.add_argument("--wait-event", help="regex matching completion in NEW log lines")
    result.add_argument("--fail-event", action="append", default=[], help="terminal failure regex; repeatable")
    result.add_argument("--wait-timeout", type=positive_seconds, default=120)
    return result


class LogEvidence:
    def __init__(self, path, success, failures):
        self.path = path
        self.success = re.compile(success)
        self.failures = [re.compile(pattern) for pattern in failures]
        with path.open("rb") as stream:
            # Snapshot before POST: pre-existing completion lines cannot pass.
            stat = os.fstat(stream.fileno())
            stream.seek(0, 2)
            self.offset = stream.tell()
        self.identity = (stat.st_dev, stat.st_ino)
        self.pending = b""

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            with self.path.open("rb") as stream:
                stat = os.fstat(stream.fileno())
                if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.offset:
                    raise ActionError("Log replaced/truncated; completion is unverified. Inspect before retrying.")
                stream.seek(self.offset)
                chunk = stream.read()
                self.offset += len(chunk)
            lines = (self.pending + chunk).split(b"\n")
            self.pending = lines.pop()
            for raw in lines:
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                if any(pattern.search(line) for pattern in self.failures):
                    raise ActionError("Terminal failure evidence: " + line)
                if self.success.search(line):
                    return line
            if time.monotonic() >= deadline:
                raise ActionError("No fresh completion evidence before timeout; action may still run. Inspect before retrying.")
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def invoke(args):
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ActionError("Use an HTTP(S) base URL without query or fragment")
    if bool(args.log_file) != bool(args.wait_event) or (args.fail_event and not args.wait_event):
        raise ActionError("--log-file and --wait-event must be supplied together; --fail-event requires them")
    # Preflight regex/path before any mutation; record the log offset just before POST.
    if args.wait_event:
        re.compile(args.wait_event)
        for pattern in args.fail_event:
            re.compile(pattern)
        with args.log_file.open("rb"):
            pass
    opener = build_opener(ProxyHandler({}))

    def request(route, query, post=False):
        url = base + "/api/v1/debug-actions/debug-actions" + route + "?" + urlencode(query)
        req = Request(url, data=b"{}" if post else None,
                      headers={"Content-Type": "application/json"} if post else {})
        try:
            with opener.open(req, timeout=args.request_timeout) as response:
                data = json.load(response)
        except (OSError, URLError, ValueError) as error:
            if post:
                raise ActionError("POST outcome uncertain; no retry sent. Inspect logs before retrying: " + str(error)) from error
            raise ActionError("Discovery failed: " + str(error)) from error
        if not isinstance(data, dict):
            raise ActionError("Invalid API response" + ("; POST may have run" if post else ""))
        return data

    discovered = request("", {"filter": args.name})
    actions = discovered.get("actions")
    if discovered.get("success") is False or not isinstance(actions, list) or not all(isinstance(a, dict) for a in actions):
        raise ActionError("Invalid action discovery response")
    matches = [a for a in actions if a.get("name") == args.name
               and (args.category is None or a.get("category") == args.category)
               and (args.assembly is None or a.get("assembly") == args.assembly)]
    if len(matches) != 1:
        raise ActionError("Expected exactly one action, found %d; refine --category/--assembly. No POST sent." % len(matches))
    action = matches[0]
    if action.get("is_runnable") is not True or not isinstance(action.get("id"), str) or not action["id"]:
        raise ActionError("Action is not runnable or has no valid ID. No POST sent.")
    evidence = LogEvidence(args.log_file, args.wait_event, args.fail_event) if args.wait_event else None
    response = request("/run", {"id": action["id"]}, post=True)
    if response.get("success") is not True:
        raise ActionError("Invocation failed: " + str(response.get("error", response)) + "; no retry sent")
    result = {"status": "invoked_only", "action": action}
    if evidence:
        result.update(status="completion_evidence_observed", evidence=evidence.wait(args.wait_timeout))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        print(json.dumps(invoke(args)))
        return 0
    except (ActionError, OSError, re.error) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
