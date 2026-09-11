import datetime
import fcntl
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops/macos"))
import job_runtime as runtime
import job_status
import job_watchdog as watchdog


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agents = self.root / "agents"
        self.agents.mkdir()
        self.label = "com.brightbeed.kuaidiair-fetch"
        self.plist = self.agents / (self.label + ".plist")
        self.plist.write_bytes(plistlib.dumps({"Label": self.label,
            "ProgramArguments": ["/usr/bin/python3", str(self.root / "scripts/kuaidiair_fetcher.py")]}))
        self.bad = [{"id": "kd-brightbeed", "ok": False, "last_attempt_at": 0}]

    def decision(self, launch, snapshots=None, retry=None, now=10000):
        return watchdog.decision(launch, self.bad if snapshots is None else snapshots, retry or {}, now)

    def test_running_job_never_restarted_even_when_snapshot_is_stale(self):
        result = self.decision({"loaded": True, "running": True})
        self.assertIsNone(result["action"])
        self.assertEqual(result["reason"], "already_running")

    def test_unknown_launch_state_never_treated_as_missing(self):
        self.assertIsNone(self.decision({"loaded": None})["action"])
        for message, loaded in [("Operation not permitted", None), ("Could not find service abc", False)]:
            with patch.object(job_status.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", message)):
                self.assertIs(job_status.launch_status(self.label)["loaded"], loaded)

    def test_failed_job_waits_for_collector_and_watchdog_cooldowns(self):
        bad = [{"ok": False, "finished_at": 9900}]
        self.assertEqual(self.decision({"loaded": True}, bad)["reason"], "collection_cooldown")
        bad = [{"ok": False, "finished_at": 8000, "retry_after": 11000}]
        self.assertEqual(self.decision({"loaded": True}, bad)["retry_after"], 11000)
        result = self.decision({"loaded": True}, retry={"retry_after": 11000})
        self.assertEqual(result["reason"], "recovery_cooldown")

    def test_missing_service_can_be_restored_and_failed_idle_service_started(self):
        self.assertEqual(self.decision({"loaded": False})["action"], "bootstrap")
        self.assertEqual(self.decision({"loaded": True})["action"], "kickstart")
        self.assertIsNone(self.decision({"loaded": True}, [{"ok": True}])["action"])

    def test_maximum_three_extra_attempts_per_hour_survives_restart(self):
        retry = {"window_started_at": 9000, "attempts": 3, "retry_after": 9500}
        encoded = json.loads(json.dumps(retry))
        result = self.decision({"loaded": False}, retry=encoded)
        self.assertEqual(result["reason"], "retry_budget_exhausted")
        self.assertEqual(self.decision({"loaded": False}, retry=encoded, now=13000)["attempt"], 1)

    def test_changed_plist_cannot_run_a_write_command(self):
        self.assertTrue(watchdog.valid_plist(self.plist, self.label, self.root))
        self.plist.write_bytes(plistlib.dumps({"Label": self.label,
            "ProgramArguments": ["/usr/bin/python3", str(self.root / "scripts/sixshop_stock_updater.py"), "update"]}))
        self.assertFalse(watchdog.valid_plist(self.plist, self.label, self.root))

    def inspect(self, apply=False, disabled=None):
        with patch.dict(watchdog.SERVICES, {"kuaidiair-fetch": "kd-brightbeed"}, clear=True), \
             patch.object(watchdog, "disabled_services", return_value=set() if disabled is None else disabled), \
             patch.object(watchdog, "launch_status", return_value={"loaded": False}), \
             patch.object(watchdog, "snapshot_status", return_value=self.bad[0]):
            return watchdog.inspect(self.root, self.agents, {}, 10000, apply)

    def test_dry_run_never_dispatches_or_writes_state(self):
        with patch.object(watchdog, "command") as command:
            self.assertEqual(self.inspect()["services"][self.label]["plan"]["action"], "bootstrap")
            command.assert_not_called()
        self.assertFalse((self.root / "state").exists())

    def test_intentionally_disabled_service_is_left_alone(self):
        with patch.object(watchdog, "command") as command:
            result = self.inspect(True, {self.label})
            self.assertEqual(result["services"][self.label]["plan"]["reason"], "intentionally_disabled")
            command.assert_not_called()

    def test_reserve_before_dispatch_and_do_not_claim_collection_success(self):
        def dispatch(args):
            record = runtime.read_json(self.root / "state/watchdog.json")["services"][self.label]
            self.assertEqual(record["attempts"], 1)
            self.assertGreater(record["retry_after"], 10000)
            self.assertEqual(args[0], "bootstrap")
            self.assertNotIn("-k", args)
            return {"accepted": True}
        with patch.object(watchdog, "command", side_effect=dispatch):
            result = self.inspect(True)
        self.assertFalse(result["ok"])
        self.assertTrue(result["services"][self.label]["dispatch"]["accepted"])

    def test_process_lock_excludes_duplicate_watchdog(self):
        (self.root / "state").mkdir()
        with open(self.root / "state/watchdog.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(watchdog, "inspect") as inspect:
                self.assertEqual(watchdog.run(self.root, self.agents, True)["reason"], "already_running")
                inspect.assert_not_called()

    def test_report_slot_grace_and_kst_midnight(self):
        spec = runtime.JOBS["report-6a"]
        def stamp(text):
            return datetime.datetime.fromisoformat(text + "+09:00").timestamp()
        for now, expected in [("2026-09-11T12:29:59", "2026-09-11T08:00:00"),
                              ("2026-09-11T12:30:00", "2026-09-11T12:00:00"),
                              ("2026-09-12T00:01:00", "2026-09-11T18:00:00")]:
            with self.subTest(now=now):
                self.assertEqual(runtime.expected_since(spec, stamp(now)), stamp(expected))
        runtime.write_json(self.root / "out/report_6a.json", {
            "ok": True, "fetchedAt": stamp("2026-09-11T08:05:00") * 1000,
            "summary": {}, "yesterdayTop10": []})
        before = job_status.snapshot_status(self.root, "report-6a", stamp("2026-09-11T12:29:59"))
        after = job_status.snapshot_status(self.root, "report-6a", stamp("2026-09-11T12:30:00"))
        self.assertTrue(before["ok"])
        self.assertFalse(after["ok"])
        self.assertEqual(after["error_code"], "missed_schedule")


if __name__ == "__main__":
    unittest.main()
