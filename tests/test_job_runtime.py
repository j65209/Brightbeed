import fcntl
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "macos"))
import job_runtime as runtime
import job_status


def sales():
    return {"ok": True, "fetchedAt": int(time.time() * 1000),
            "summary": {k: {"revenue": 10, "orders": 1} for k in ("today", "yesterday", "thirtyDays")},
            "daily": [{"date": "2026-09-11", "revenue": 10, "orders": 1}]}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "out").mkdir()
        self.target = self.root / "out" / "test.json"
        self.spec = dict(script="fake.py", args=[], output="test.json", kind="sales", timeout=2, interval=1800, cache_arg=False)
        self.script("import json,os,time\nfrom pathlib import Path\npayload=" + repr(sales()) + "\npayload['fetchedAt']=int(time.time()*1000)\nPath(os.environ['BRIGHTBEED_OUTPUT']).write_text(json.dumps(payload))\n")

    def script(self, body):
        (self.root / "scripts" / "fake.py").write_text(body)

    def run_job(self):
        return runtime.run_job(self.root, "test", self.spec)

    def test_success_publishes_and_backs_up(self):
        before = json.dumps(sales()).encode()
        self.target.write_bytes(before)
        result = self.run_job()
        self.assertTrue(result["ok"])
        self.assertEqual(Path(str(self.target) + ".last-good").read_bytes(), before)
        self.assertEqual(runtime.read_json(self.root / "state/jobs/test.json")["status"], "succeeded")
        self.assertEqual(result["count"], 1)

    def test_exit_zero_without_snapshot_is_failure(self):
        self.target.write_bytes(b"keep")
        self.script("print('success')")
        result = self.run_job()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "snapshot_missing")
        self.assertEqual(self.target.read_bytes(), b"keep")

    def test_corrupt_current_file_does_not_destroy_last_good_backup(self):
        backup = Path(str(self.target) + ".last-good")
        backup.write_bytes(b"earlier validated backup")
        self.target.write_bytes(b"{broken")
        self.assertTrue(self.run_job()["ok"])
        self.assertEqual(backup.read_bytes(), b"earlier validated backup")

    def test_collector_error_code_does_not_expose_diagnostic_bodies(self):
        self.assertEqual(runtime.failure_code(1, '{"error":"incomplete_order_details"}'), "incomplete_order_details")
        self.assertEqual(runtime.failure_code(1, '{"error":"url containing private token"}'), "collector_exit_1")

    def test_nonzero_with_valid_snapshot_never_publishes(self):
        self.target.write_bytes(b"keep")
        p = self.root / "scripts/fake.py"
        p.write_text(p.read_text() + "raise SystemExit(1)\n")
        self.assertFalse(self.run_job()["ok"])
        self.assertEqual(self.target.read_bytes(), b"keep")

    def test_partial_json_keeps_last_success(self):
        self.assertTrue(self.run_job()["ok"])
        before = self.target.read_bytes()
        success = runtime.read_json(self.root / "state/jobs/test.json")["last_success_at"]
        self.script("import os\nfrom pathlib import Path\nPath(os.environ['BRIGHTBEED_OUTPUT']).write_text('{')")
        result = self.run_job()
        self.assertFalse(result["ok"])
        self.assertEqual(result["last_success_at"], success)
        self.assertEqual(self.target.read_bytes(), before)

    def test_lock_skips_without_changing_owner_state(self):
        state = self.root / "state/jobs"
        state.mkdir(parents=True)
        (state / "test.json").write_text('{"status":"running","run_id":"owner"}')
        with open(state / "test.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_job()["status"], "skipped")
            self.assertEqual(runtime.read_json(state / "test.json")["run_id"], "owner")

    def test_repeated_page_refresh_obeys_persistent_failure_cooldown(self):
        self.script("raise SystemExit(1)")
        failed = self.run_job()
        before = (self.root / "state/jobs/test.json").read_bytes()
        self.assertEqual(failed["consecutive_failures"], 1)
        self.assertGreaterEqual(failed["retry_after"] - failed["started_at"], 300)
        self.assertEqual(self.run_job()["error_code"], "retry_cooldown")
        self.assertEqual((self.root / "state/jobs/test.json").read_bytes(), before)

    def test_success_after_backoff_resets_failures(self):
        runtime.write_json(self.root / "state/jobs/test.json", {
            "status": "failed", "consecutive_failures": 5, "retry_after": 1})
        result = self.run_job()
        self.assertTrue(result["ok"])
        self.assertEqual(result["consecutive_failures"], 0)
        self.assertIsNone(result["retry_after"])

    def test_interrupted_journal_is_recovered_only_after_lock(self):
        runtime.write_json(self.root / "state/jobs/test.json", {"status": "running", "run_id": "interrupted", "attempt": 2})
        result = self.run_job()
        self.assertTrue(result["ok"])
        self.assertEqual(result["interrupted_run_id"], "interrupted")
        self.assertEqual(result["attempt"], 3)

    def test_timeout_preserves_snapshot(self):
        self.target.write_bytes(b"keep")
        self.script("import time\ntime.sleep(10)")
        self.spec["timeout"] = .05
        result = self.run_job()
        self.assertEqual(result["error_code"], "timeout")
        self.assertEqual(self.target.read_bytes(), b"keep")

    def test_disk_failure_preserves_snapshot(self):
        self.target.write_bytes(b"keep")
        original = runtime.atomic_write
        def fail_target(path, raw):
            if Path(path) == self.target:
                raise OSError("disk full")
            original(path, raw)
        with patch.object(runtime, "atomic_write", side_effect=fail_target):
            self.assertFalse(self.run_job()["ok"])
        self.assertEqual(self.target.read_bytes(), b"keep")

    def test_failed_source_or_invalid_time_is_rejected(self):
        for change in ({"ok": False}, {"fetchedAt": 0}, {"fetchedAt": float('nan')}, {"fetchedAt": int((time.time()+600)*1000)}, {"daily": []}):
            with self.subTest(change=change), self.assertRaises(runtime.InvalidSnapshot):
                runtime.validate(dict(sales(), **change), "sales")

    def test_incomplete_brand_aggregation_is_rejected(self):
        payload = {"ok": True, "fetchedAt": int(time.time()*1000), "brands": [{"brand":"6a","ok":True,"top10":[]}]}
        with self.assertRaises(runtime.InvalidSnapshot):
            runtime.validate(payload, "bestsellers")
        payload["brands"] = [None]
        with self.assertRaises(runtime.InvalidSnapshot):
            runtime.validate(payload, "bestsellers")

    def test_duplicate_orders_and_sudden_loss_are_rejected(self):
        previous = {"orders": [{"ord_no": str(i), "items": []} for i in range(20)]}
        for orders in ([{"ord_no":"same", "items":[]}] * 20, previous["orders"][:10], [{"ord_no":None,"items":[]}]):
            with self.assertRaises(runtime.InvalidSnapshot):
                runtime.validate({"fetched_at": time.time(), "orders": orders, "count": len(orders)}, "orders", previous=previous)

    def test_csv_login_page_and_empty_result_are_rejected(self):
        for raw in (b'<!DOCTYPE html><html>sign in</html>', b'a,b\n'):
            with self.assertRaises(runtime.InvalidSnapshot):
                runtime.validate_csv(raw)

    def test_mtime_cannot_make_old_data_fresh(self):
        data = sales()
        data["fetchedAt"] -= 7200000
        self.target.write_text(json.dumps(data))
        with patch.dict(runtime.JOBS, {"test": self.spec}):
            result = job_status.snapshot_status(self.root, "test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "stale")

    def test_failed_attempt_does_not_report_fresh_cached_data_as_success(self):
        self.target.write_text(json.dumps(sales()))
        runtime.write_json(self.root / "state/jobs/test.json", {"status":"failed", "error_code":"timeout"})
        with patch.dict(runtime.JOBS, {"test": self.spec}):
            result = job_status.snapshot_status(self.root, "test")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "timeout")

    def test_only_exact_read_only_commands_match_runner(self):
        self.assertEqual(runtime.match_job(["python3", "/server/scripts/ably_sales.py"]), "ably-sales")
        self.assertEqual(runtime.match_job(["python3", "/server/scripts/zigzag_sales.py"]), "zigzag-sales")
        self.assertEqual(runtime.match_job(["python3", "/server/scripts/zigzag_sales.py", "--brand", "kop"]), "zigzag-sales-kop")
        self.assertIsNone(runtime.match_job(["python3", "/server/scripts/sixshop_stock_updater.py", "update", "6a"]))
        self.assertIsNone(runtime.match_job(["python3", "/server/scripts/sixshop_bestsellers.py", "all", "--start=2026-01-01"]))


if __name__ == "__main__":
    unittest.main()
