import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops/macos"))
from smartstore_orders import fetch_details
import job_runtime as runtime
import job_status
import job_watchdog


def row(identity):
    return {"productOrder": {"productOrderId": identity}}


class SmartstoreTests(unittest.TestCase):
    def test_transient_missing_detail_is_recovered_by_one_individual_read(self):
        calls = []
        def query(ids):
            calls.append(ids)
            return {"data": [row("a")] if len(ids) == 2 else [row("b")]}
        rows, coverage = fetch_details(query, ["a", "b"])
        self.assertEqual(calls, [["a", "b"], ["b"]])
        self.assertEqual(len(rows), 2)
        self.assertTrue(coverage["complete"])

    def test_confirmed_policy_restriction_records_coverage(self):
        def query(ids):
            if len(ids) == 2:
                return {"data": [row("a")]}
            raise HTTPError("unused", 400, "restricted", {}, io.BytesIO(b'{"code":"100001"}'))
        rows, coverage = fetch_details(query, ["a", "b"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(coverage, {"requestedOrders": 2, "returnedOrders": 1, "unavailableOrders": 1,
                                    "complete": False, "unavailableReason": "naver_api_100001"})

    def test_other_errors_and_unconfirmed_omissions_cannot_be_skipped(self):
        for status, code in [(401, "100001"), (400, "OTHER"), (429, "RATE_LIMIT")]:
            def query(ids):
                if len(ids) == 2:
                    return {"data": [row("a")]}
                raise HTTPError("unused", status, "failure", {}, io.BytesIO(json.dumps({"code": code}).encode()))
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, "order_lookup_failed"):
                fetch_details(query, ["a", "b"])
        with self.assertRaisesRegex(ValueError, "unconfirmed_missing_order"):
            fetch_details(lambda ids: {"data": []}, ["a"])

    def test_duplicate_unexpected_and_malformed_details_fail(self):
        for rows in ([row("a"), row("a")], [row("another-order")], [None], [{"productOrder": {}}]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "mismatched_order_details"):
                fetch_details(lambda ids: {"data": rows}, ["a", "b"])

    def test_large_omission_does_not_create_unbounded_individual_requests(self):
        calls = []
        def query(ids):
            calls.append(ids)
            return {"data": []}
        with self.assertRaisesRegex(ValueError, "too_many_missing_orders"):
            fetch_details(query, list(range(11)))
        self.assertEqual(len(calls), 1)

    def test_partial_coverage_is_visible_without_recovery_storm(self):
        now = time.time()
        coverage = {"requestedOrders": 2, "returnedOrders": 1, "unavailableOrders": 1,
                    "complete": False, "unavailableReason": "naver_api_100001"}
        data = {"ok": True, "fetchedAt": now * 1000, "coverage": coverage,
                "summary": {k: {"revenue": 10, "orders": 1} for k in ("today", "yesterday", "thirtyDays")},
                "daily": [{"date": "2026-09-11"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime.write_json(root / "out/smartstore_pp_sales.json", data)
            status = job_status.snapshot_status(root, "smartstore-sales", now)
            self.assertEqual(status["status"], "partial")
            self.assertFalse(status["ok"])
            self.assertEqual(job_watchdog.decision({"loaded": True}, [status], {}, now)["reason"], "source_limited")
            stale = job_status.snapshot_status(root, "smartstore-sales", now + 3700)
            self.assertEqual(job_watchdog.decision({"loaded": True}, [stale], {}, now + 3700)["action"], "kickstart")
        for changed in ({"complete": True}, {"returnedOrders": 2}, {"unavailableReason": "unknown"}):
            data["coverage"] = dict(coverage, **changed)
            with self.assertRaisesRegex(runtime.InvalidSnapshot, "invalid_coverage"):
                runtime.validate(data, "sales", now=now)


if __name__ == "__main__":
    unittest.main()
