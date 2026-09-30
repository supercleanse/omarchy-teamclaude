import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import urllib.error

spec = importlib.util.spec_from_file_location("bridge", Path(__file__).with_name("teamclaude_bridge.py"))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

STATUS = {"server": {"version": "1.1.21"}, "currentIndexes": {"anthropic": 0},
          "accounts": [{"name": "Example", "type": "oauth", "provider": "anthropic",
                        "usage": {"totalRequests": 4}, "accessToken": "never-export-me"}]}
QUOTA = {"accounts": [{"name": "Example", "type": "oauth", "tier": {"weight": 5},
                       "buckets": {"fiveHour": {"utilization": 0.4, "resetAt": 1790000000},
                                   "weeklySonnet": {"utilization": 0.2, "source": "unified7d"}}}],
         "aggregate": {"fiveHour": {"utilization": 0.4, "knownAccounts": 1}}}


class BridgeTests(unittest.TestCase):
    def test_status_has_only_display_fields(self):
        result = b.normalize(STATUS, QUOTA)
        self.assertNotIn("never-export-me", json.dumps(result))
        self.assertTrue(result["accounts"][0]["active"])
        self.assertEqual(result["requests"], 4)
        self.assertEqual(result["accounts"][0]["meters"][0]["percent"], .4)

    def test_unknown_is_not_zero_and_shared_is_not_duplicated(self):
        rows = b.normalize(STATUS, QUOTA)["accounts"][0]["meters"]
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[1]["percent"])

    def test_racing_account_snapshots_do_not_assign_wrong_quota(self):
        result = b.normalize(STATUS, {"accounts": [{"name": "Someone else", "type": "oauth", "buckets": QUOTA["accounts"][0]["buckets"]}]})
        self.assertIsNone(result["accounts"][0]["meters"][0]["percent"])

    def test_refuse_remote_endpoint(self):
        with self.assertRaises(RuntimeError):
            b.Client({"proxy": {"host": "example.org"}})

    def test_redirect_cannot_forward_credentials(self):
        with self.assertRaises(RuntimeError):
            b.LocalOnlyRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.org")

    def test_reject_unrelated_service(self):
        with self.assertRaises(RuntimeError):
            b.normalize({"ok": True}, {})

    def test_reject_unconfirmed_action(self):
        client = b.Client({})
        with patch.object(client, "call", return_value={}):
            with self.assertRaises(RuntimeError):
                client.action("reload", {})

    def test_log_tail_is_bounded_and_plain_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.log"
            path.write_text("\n".join(f"line {i}\x00" for i in range(1000)))
            with patch.object(b, "activity_path", return_value=path):
                result = b.activity()
            self.assertEqual(len(result["lines"]), 200)
            self.assertEqual(result["lines"][-1], "line 999")

    def test_stop_does_not_kill_external_server(self):
        with patch.object(b, "read_config", return_value={}), patch.object(b, "managed", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "started elsewhere"):
                b.action("stop")

    def test_auth_failure_does_not_start_second_server(self):
        error = urllib.error.HTTPError("url", 401, "Denied", {}, None)
        with patch.object(b, "read_config", return_value={}), patch.object(b.Client, "call", side_effect=error), patch.object(b.subprocess, "run") as run:
            with self.assertRaises(urllib.error.HTTPError):
                b.action("start")
            run.assert_not_called()

    def test_remove_disabled_before_deleting(self):
        config = {"accounts": [{"name": "Example"}]}
        calls = []
        with patch.object(b, "read_config", return_value=config), patch.object(b, "run_cli", side_effect=lambda *args: calls.append(args)), patch.object(b.Client, "action", return_value={"ok": True}), patch.object(b.Client, "call", return_value={"accounts": [{"name": "Example", "disabled": True}]}):
            b.action("remove", "Example")
        self.assertEqual(calls, [("disable", "Example"), ("remove", "Example")])

    def test_remove_aborts_if_disable_not_confirmed(self):
        with patch.object(b, "read_config", return_value={"accounts": [{"name": "Example"}]}), patch.object(b, "run_cli") as run, patch.object(b.Client, "action", return_value={"ok": True}), patch.object(b.Client, "call", return_value={"accounts": [{"name": "Example", "disabled": False}]}):
            with self.assertRaises(RuntimeError):
                b.action("remove", "Example")
            run.assert_called_once_with("disable", "Example")


if __name__ == "__main__":
    unittest.main()
