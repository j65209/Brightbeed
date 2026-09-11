"""Status from validated source data and durable run results, never log mtimes."""
import json
from pathlib import Path
import re
import subprocess
import time

try:
    from .job_runtime import JOBS, GROUPS, expected_since, read_json, source_time, validate, validate_csv
except ImportError:
    from job_runtime import JOBS, GROUPS, expected_since, read_json, source_time, validate, validate_csv


def launch_status(label):
    import os
    try:
        proc = subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True, timeout=2)
        if proc.returncode:
            missing = "could not find service" in (proc.stdout + proc.stderr).lower()
            return {"loaded": False if missing else None}
        # Only top-level fields; nested resource coalition state is not job state.
        fields = dict(re.findall(r"^\t(state|pid|last exit code) = (.+)$", proc.stdout, re.M))
        return {"loaded": True, "running": fields.get("state") == "running", "exit_code": fields.get("last exit code")}
    except (OSError, subprocess.TimeoutExpired):
        return {"loaded": None}


def snapshot_status(root, key, now=None):
    now = time.time() if now is None else now
    root = Path(root)
    spec = JOBS[key]
    record = read_json(root / "state" / "jobs" / (key + ".json"))
    path = root / "out" / spec["output"]
    result = {"id": key, "ok": False, "status": "missing", "updated_at": None,
              "last_success_at": record.get("last_success_at"), "last_attempt_at": record.get("started_at"),
              "run_status": record.get("status", "unknown"), "error_code": record.get("error_code"),
              "retry_after": record.get("retry_after"),
              "stale_after_hours": (spec["interval"] * 2) / 3600}
    try:
        raw = path.read_bytes()
        if spec["kind"] == "csv":
            validate_csv(raw)
            stamp = path.stat().st_mtime
        else:
            data = json.loads(raw)
            stamp = source_time(data)
            # Schema validity and age are separate; an old valid snapshot is stale.
            validate(data, spec["kind"], now=stamp or now)
        age = now - stamp
        result.update(updated_at=int(stamp), age_hours=round(max(0, age) / 3600, 3),
                      status="fresh" if stamp <= now + 120 and stamp >= expected_since(spec, now) else "stale")
        if spec.get("calendar_hours"):
            result.update(expected_since=int(expected_since(spec, now)), schedule="08:00,12:00,18:00 KST")
            if result["status"] == "stale":
                result["error_code"] = "missed_schedule"
        marker = read_json(str(path) + ".error.json")
        if record.get("status") == "failed" or marker.get("ts", 0) >= stamp:
            result.update(status="error", error_code=record.get("error_code") or marker.get("error", "collection_failed"))
        if record.get("status") == "running" and now - record.get("started_at", 0) > spec["timeout"] * 2 + 120:
            result.update(status="error", error_code="interrupted_or_overdue")
        if spec["kind"] == "sales" and data.get("coverage", {}).get("complete") is False:
            result["coverage"] = data["coverage"]
            if result["status"] == "fresh":
                result.update(status="partial", error_code="source_orders_unavailable", recoverable=False)
        result["ok"] = result["status"] == "fresh"
    except (OSError, ValueError, TypeError, KeyError):
        result.update(status="missing" if not path.exists() else "error", error_code="invalid_or_missing_snapshot")
    return result


def health_report(root, beed):
    names = {"kd-brightbeed": ("콰이디에어 (브라이트비드)", "물류"), "kd-shinebeed": ("콰이디에어 (샤인비드)", "물류"),
             "vendor-fetch": ("벤더 공구 시트", "벤더"), "ably-sales": ("에이블리 매출", "매출"),
             "zigzag-sales": ("지그재그 매출", "매출"), "smartstore-sales": ("스마트스토어 매출", "매출"),
             "bestsellers": ("브랜드 판매 순위", "매출")}
    checks = []
    for key in JOBS:
        if key.startswith("pro-stock-"):
            continue
        name, category = names.get(key, (key, "보고서" if key.startswith("report-") else "매출"))
        checks.append(dict(snapshot_status(root, key), name=name, category=category))
    fb = read_json(Path(beed) / "data/meta-ads/all-brands-scoreboard.json")
    stamp = source_time(fb)
    # Scoreboard timestamps are not guaranteed numeric on older installations.
    generated = fb.get("generated_at") or fb.get("generatedAt")
    if stamp is None and isinstance(generated, str):
        import datetime
        try:
            stamp = datetime.datetime.fromisoformat(generated.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    ok = stamp is not None and -120 <= time.time() - stamp <= 3600
    checks.append({"name": "메타 광고", "category": "마케팅", "ok": ok, "status": "fresh" if ok else "stale",
                   "updated_at": int(stamp) if stamp else None, "stale_after_hours": 1})
    watchdog = read_json(Path(root) / "state/watchdog.json")
    if watchdog:
        current = watchdog.get("mode") == "apply" and 0 <= time.time() - watchdog.get("checked_at", 0) <= 900
        checks.append({"name": "자동 복구 감시", "category": "서버", "ok": current,
                       "status": "fresh" if current else "stale", "updated_at": watchdog.get("checked_at"),
                       "stale_after_hours": .25})
    return {"ok": all(c["ok"] for c in checks), "checked_at": int(time.time()), "checks": checks}


def agents_status(root, jobs, read_plist, calendar_schedule):
    now = time.time()
    extra_jobs = [
        ("platform-sales", "com.brightbeed.platform-sales", "마케팅팀", "에이블리·지그재그·스마트스토어 매출 수집", None),
        ("bestsellers", "com.brightbeed.bestsellers", "기획팀", "브랜드 판매 순위 수집", None),
    ]
    jobs = list(jobs) + [job for job in extra_jobs if job[0] not in {j[0] for j in jobs}]
    agents = []
    for key, label, team, task, output in jobs:
        pl = read_plist(label)
        launch = launch_status(label)
        entry = dict(id=key, label=label, team=team, task=task, last_run=None, next_run=None,
                     last_success_at=None, status="stale", **launch)
        if not pl or launch["loaded"] is not True:
            entry["detail"] = "launchd 등록 또는 실행 상태 확인 필요"
            agents.append(entry)
            continue
        members = GROUPS.get(key, [key] if key in JOBS else [])
        if members:
            states = [snapshot_status(root, k, now) for k in members]
            stamps = [s["updated_at"] for s in states if s["updated_at"]]
            attempts = [s["last_attempt_at"] for s in states if s["last_attempt_at"]]
            entry["last_run"] = int(max(attempts)) if attempts else None
            entry["last_success_at"] = min(stamps) if len(stamps) == len(states) else None
            entry["jobs"] = states
            if all(s["ok"] for s in states):
                entry.update(status="running", detail="모든 수집 결과 검증 완료")
            else:
                failed = [s["id"] for s in states if not s["ok"]]
                entry.update(status="warn" if any(s["ok"] for s in states) else "stale", detail="수집 확인 필요: " + ", ".join(failed))
        else:
            # Legacy jobs without a success journal must not be declared healthy
            # just because their log was touched. Surface launchd failures first.
            entry.update(status="warn", detail="마지막 성공 결과 미확인")
        if launch.get("exit_code") not in (None, "0", "(never exited)") and not launch.get("running"):
            entry.update(status="stale", detail="최근 실행 실패 (종료 코드 " + str(launch["exit_code"]) + ")")
        if pl.get("StartInterval"):
            entry["interval_sec"] = pl["StartInterval"]
            if entry["last_run"]:
                entry["next_run"] = entry["last_run"] + pl["StartInterval"]
        elif pl.get("StartCalendarInterval"):
            entry["next_run"], _ = calendar_schedule(pl["StartCalendarInterval"], now)
            entry["schedule"] = "calendar"
        agents.append(entry)
    return {"checked_at": int(now), "agents": agents, "teams": sorted({a["team"] for a in agents})}
