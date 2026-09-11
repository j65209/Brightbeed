"""Durable, single-flight read-only collection and validated snapshot publication.

Install in the proxy's scripts directory. No inventory mutations belong here.
"""
import csv
import fcntl
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid


class InvalidSnapshot(ValueError):
    pass


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


def read_json(path):
    try:
        with open(path) as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def source_time(data):
    for key in ("fetchedAt", "fetched_at", "updatedAt", "updated_at"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return value / 1000 if value > 1e12 else value
    return None


def require(condition, reason):
    if not condition:
        raise InvalidSnapshot(reason)


def number(value, integer=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (not integer or (value >= 0 and int(value) == value)))


def validate(data, kind, now=None, started_at=None, previous=None):
    now = time.time() if now is None else now
    require(isinstance(data, dict), "invalid_object")
    stamp = source_time(data)
    require(stamp is not None and 0 <= now - stamp + 120 <= 3720, "invalid_source_time")
    if started_at is not None:
        require(stamp >= started_at - 2, "unchanged_source")
    if kind != "orders":
        require(data.get("ok") is True, "source_failed")
    if kind == "sales":
        summary = data.get("summary")
        require(isinstance(summary, dict), "missing_summary")
        for key in ("today", "yesterday", "thirtyDays"):
            row = summary.get(key, {})
            require(isinstance(row, dict) and number(row.get("revenue")) and number(row.get("orders"), True), "invalid_summary")
        rows = data.get("daily")
        require(isinstance(rows, list) and len(rows) > 0, "empty_daily")
        keys = [r.get("date") if isinstance(r, dict) else None for r in rows]
        require(all(isinstance(k, str) and len(k) == 10 for k in keys) and len(keys) == len(set(keys)), "invalid_daily_dates")
        return len(rows)
    if kind == "bestsellers":
        rows = data.get("brands")
        require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), "missing_brands")
        require({r.get("brand") for r in rows} == {"6a", "ct", "pp", "yar", "kop", "apt", "koz"} and len(rows) == 7, "incomplete_brands")
        for row in rows:
            require(row.get("ok") is True and isinstance(row.get("top10"), list), "brand_failed")
            stamp = source_time(row)
            require(stamp is not None and -120 <= now - stamp <= 3600, "stale_brand")
        return sum(len(r["top10"]) for r in rows)
    if kind == "report":
        require(isinstance(data.get("summary"), dict) and isinstance(data.get("yesterdayTop10"), list), "invalid_report")
        return len(data["yesterdayTop10"])
    field, identity = ("orders", "ord_no") if kind == "orders" else ("products", "id")
    rows = data.get(field)
    require(isinstance(rows, list) and len(rows) > 0, "empty_" + field)
    keys = [str(r[identity]) if isinstance(r, dict) and r.get(identity) not in (None, "", 0, False) else "" for r in rows]
    require(all(keys) and len(keys) == len(set(keys)), "duplicate_or_missing_ids")
    if kind == "orders":
        require(data.get("count") == len(rows) and all(isinstance(r.get("items"), list) for r in rows), "invalid_order_count")
    if previous and isinstance(previous.get(field), list) and len(previous[field]) >= 10:
        require(len(rows) >= len(previous[field]) * .8, "unexpected_count_drop")
    return len(rows)


def validate_csv(raw):
    text = raw.decode("utf-8-sig")
    require("<html" not in text[:1000].lower() and "<!doctype" not in text[:1000].lower(), "html_instead_of_csv")
    rows = list(csv.reader(io.StringIO(text)))
    require(len(rows) >= 2 and len(rows[0]) >= 2 and any(any(c.strip() for c in r) for r in rows[1:]), "empty_csv")
    require(any("마진" in c or "업체" in c or "브랜드" in c for r in rows[:3] for c in r), "invalid_csv_header")
    return len(rows) - 1


def specifications():
    jobs = {}
    def add(key, script, args, output, kind, timeout=150, interval=1800, cache_arg=True):
        jobs[key] = dict(script=script, args=args, output=output, kind=kind,
                         timeout=timeout, interval=interval, cache_arg=cache_arg)
    for brand in ("akoi", "pp", "ct", "koz"):
        add("pro-sales-" + brand, "sixshop_pro_sales.py", [brand], "pro_" + brand + "_sales.json", "sales")
        add("pro-stock-" + brand, "sixshop_pro_stock.py", [brand], "pro_" + brand + "_stock.json", "stock")
        add("report-" + brand, "brand_report.py", [brand], "report_" + brand + ".json", "report", interval=50400, cache_arg=False)
    for brand in ("6a", "yar", "kop", "apt"):
        add("admin-sales-" + brand, "sixshop_admin_sales.py", [brand], "admin_" + brand + "_sales.json", "sales", timeout=210)
        add("report-" + brand, "admin_report.py", [brand], "report_" + brand + ".json", "report", timeout=240, interval=50400, cache_arg=False)
    add("ably-sales", "ably_sales.py", ["--brand", "6a"], "ably_sales.json", "sales", timeout=90)
    for brand in ("kop", "apt"):
        add("ably-sales-" + brand, "ably_sales.py", ["--brand", brand], "ably_sales_" + brand + ".json", "sales", timeout=90)
    add("zigzag-sales", "zigzag_sales.py", [], "zigzag_6a_sales.json", "sales", timeout=90)
    add("smartstore-sales", "smartstore_sales.py", ["--brand", "pp"], "smartstore_pp_sales.json", "sales")
    add("smartstore-sales-kop", "smartstore_sales.py", ["--brand", "kop"], "smartstore_kop_sales.json", "sales")
    add("bestsellers", "sixshop_bestsellers.py", ["all"], "bestsellers_all.json", "bestsellers", timeout=210, cache_arg=False)
    for brand in ("brightbeed", "shinebeed"):
        add("kd-" + brand, "kuaidiair_fetcher.py", [brand], "kuaidiair-orders" + ("-shinebeed" if brand == "shinebeed" else "") + ".json", "orders", timeout=480, interval=600, cache_arg=False)
    add("vendor-fetch", "vendor_margin_fetcher.py", [], "vendor-margin.csv", "csv", timeout=60, interval=600, cache_arg=False)
    return jobs


JOBS = specifications()
GROUPS = {
    "platform-sales": ["ably-sales", "ably-sales-kop", "ably-sales-apt", "zigzag-sales", "smartstore-sales", "smartstore-sales-kop"],
    "pro-sales": [k for b in ("akoi", "pp", "ct", "koz") for k in ("pro-sales-" + b, "pro-stock-" + b)],
    "admin-sales": ["admin-sales-" + b for b in ("6a", "yar", "kop", "apt")],
    "brand-report": ["report-" + b for b in ("ct", "pp", "koz", "akoi", "6a", "yar", "kop", "apt")],
}


def match_job(args):
    if len(args) < 2:
        return None
    script, tail = Path(args[1]).name, args[2:]
    if script == "kuaidiair_fetcher.py" and not tail:
        tail = ["brightbeed"]
    if script in ("ably_sales.py", "smartstore_sales.py") and not tail:
        tail = ["--brand", "6a" if script == "ably_sales.py" else "pp"]
    for key, spec in JOBS.items():
        if script == spec["script"] and tail == spec["args"]:
            return key
    return None


def failure_code(code, output):
    if "MachPortRendezvousServer" in output and "Permission denied" in output:
        return "browser_permission_denied"
    for line in reversed(output.splitlines()):
        try:
            result = json.loads(line)
            error = result.get("error") if isinstance(result, dict) else None
            if isinstance(error, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", error):
                return error
        except ValueError:
            pass
    return "collector_exit_" + str(code)


def execute(command, timeout, lock_fd, env, cwd):
    # Child inherits the flock descriptor: parent death cannot release the lease
    # while the collector is still alive. Timeout kills the complete process group.
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                cwd=cwd, env=env, start_new_session=True, pass_fds=(lock_fd,))
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise InvalidSnapshot("timeout")
        output.seek(0, os.SEEK_END)
        size = output.tell()
        output.seek(max(0, size - 32768))
        return code, output.read().decode("utf-8", errors="replace")


def run_job(root, key, spec=None):
    root = Path(root)
    spec = JOBS[key] if spec is None else spec
    state_dir = root / "state" / "jobs"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / (key + ".json")
    target = root / "out" / spec["output"]
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(state_dir / (key + ".lock"), "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "status": "skipped", "job_id": key, "error_code": "already_running"}
        old = read_json(state_path)
        started = time.time()
        record = {"job_id": key, "run_id": str(uuid.uuid4()), "status": "running", "started_at": started,
                  "finished_at": None, "last_success_at": old.get("last_success_at"),
                  "attempt": int(old.get("attempt", 0)) + 1, "pid": os.getpid(), "error_code": None}
        if old.get("status") == "running":
            record["interrupted_run_id"] = old.get("run_id")
        write_json(state_path, record)
        stage_root = root / "state" / "staging"
        stage_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix=key + "-", dir=stage_root) as stage:
                candidate = Path(stage) / spec["output"]
                cmd = [sys.executable, str(root / "scripts" / spec["script"])] + spec["args"]
                if spec.get("cache_arg"):
                    cmd += ["--cache", str(candidate)]
                env = dict(os.environ, BRIGHTBEED_OUTPUT=str(candidate))
                code, output = execute(cmd, spec["timeout"], lock.fileno(), env, root)
                # At most one session refresh, only for the two read-only sources.
                expired = "session expired" in output or "session missing" in output
                if expired and (key.startswith("ably-sales") or key == "zigzag-sales"):
                    record["recovery"] = "session_refresh"
                    write_json(state_path, record)
                    renew = [sys.executable, str(root / "scripts" / "refresh_session.py"), key.split("-")[0]]
                    if key.startswith("ably-sales"):
                        renew += [spec["args"][-1]]
                    renewal_code, _ = execute(renew, 75, lock.fileno(), env, root)
                    require(renewal_code == 0, "session_login_required")
                    code, output = execute(cmd, spec["timeout"], lock.fileno(), env, root)
                require(code == 0, failure_code(code, output))
                require(candidate.exists(), "snapshot_missing")
                raw = candidate.read_bytes()
                if spec["kind"] == "csv":
                    count = validate_csv(raw)
                else:
                    data = json.loads(raw)
                    count = validate(data, spec["kind"], started_at=started, previous=read_json(target))
                if target.exists():
                    prior = target.read_bytes()
                    try:
                        if spec["kind"] == "csv":
                            validate_csv(prior)
                        else:
                            previous = json.loads(prior)
                            validate(previous, spec["kind"], now=source_time(previous))
                    except (ValueError, TypeError, KeyError):
                        pass  # A corrupt current file must not replace a good backup.
                    else:
                        atomic_write(str(target) + ".last-good", prior)
                atomic_write(target, raw)
                record.update(status="succeeded", last_success_at=time.time(), count=count,
                              sha256=hashlib.sha256(raw).hexdigest())
                marker = Path(str(target) + ".error.json")
                if marker.exists():
                    marker.unlink()
        except Exception as error:
            code = str(error) if isinstance(error, InvalidSnapshot) else type(error).__name__
            record.update(status="failed", error_code=code)
            write_json(str(target) + ".error.json", {"ts": int(time.time()), "error": code, "run_id": record["run_id"]})
        record["finished_at"] = time.time()
        write_json(state_path, record)
        # A bounded history, excluding response bodies and credentials.
        history = state_dir / (key + ".history.json")
        items = read_json(history).get("runs", [])[-49:]
        write_json(history, {"runs": items + [record]})
        return {"ok": record["status"] == "succeeded", **record}


def main():
    root = Path(__file__).resolve().parent.parent
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    if key not in JOBS and key not in GROUPS:
        raise SystemExit("unknown read-only collector")
    results = []
    for job in GROUPS.get(key, [key]):
        result = run_job(root, job)
        results.append(result)
        print(json.dumps(result), flush=True)
        if key == "pro-sales":
            time.sleep(8)
    raise SystemExit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
