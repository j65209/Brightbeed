"""Recover eight read-only launchd jobs without unloading or killing a service.

Dry run by default. The optional launchd job runs --apply every five minutes.
Normal collection schedules remain responsible for routine execution.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import time

from job_runtime import GROUPS, JOBS, read_json, write_json
from job_status import launch_status, snapshot_status


SERVICES = {
    "platform-sales": "platform-sales",
    "pro-sales": "pro-sales",
    "admin-sales": "admin-sales",
    "bestsellers": "bestsellers",
    "brand-report": "brand-report",
    "kuaidiair-fetch": "kd-brightbeed",
    "kuaidiair-fetch-shinebeed": "kd-shinebeed",
    "vendor-fetch": "vendor-fetch",
}
MAX_ATTEMPTS = 3
WINDOW = 3600
RETRY_DELAYS = (900, 1800, 3600)


def command(args):
    try:
        proc = subprocess.run(["/bin/launchctl"] + args, capture_output=True, text=True, timeout=10)
        return {"accepted": proc.returncode == 0, "exit_code": proc.returncode}
    except (OSError, subprocess.TimeoutExpired):
        return {"accepted": False, "error_code": "launchctl_unavailable"}


def disabled_services():
    try:
        proc = subprocess.run(["/bin/launchctl", "print-disabled", f"gui/{os.getuid()}"],
                              capture_output=True, text=True, timeout=3)
        if proc.returncode:
            return None
        return set(re.findall(r'"([^"]+)"\s*=>\s*true', proc.stdout))
    except (OSError, subprocess.TimeoutExpired):
        return None


def valid_plist(path, label, root):
    """Do not start a changed label pointing somewhere outside known collectors."""
    try:
        data = plistlib.loads(Path(path).read_bytes())
        suffix = label.removeprefix("com.brightbeed.")
        key = SERVICES[suffix]
        script_dir = str(Path(root).resolve() / "scripts")
        if key in GROUPS or key == "bestsellers":
            expected = ["/bin/bash", script_dir + "/refresh_" + key.replace("-", "_") + ".sh"]
        else:
            spec = JOBS[key]
            expected = ["/usr/bin/python3", script_dir + "/" + spec["script"]] + spec["args"]
        args = data.get("ProgramArguments")
        if isinstance(args, list) and len(args) >= 2 and isinstance(args[1], str):
            args = list(args)
            args[1] = str(Path(args[1]).resolve())
        # The legacy default account omits its optional brand argument.
        matches = args == expected or (key == "kd-brightbeed" and args == expected[:-1])
        return data.get("Label") == label and matches and not data.get("Disabled", False)
    except (OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        return False


def decision(launch, snapshots, retry, now):
    if launch.get("loaded") is None:
        return {"action": None, "reason": "registration_unknown"}
    if launch.get("running"):
        return {"action": None, "reason": "already_running"}
    bad = [row for row in snapshots if not row["ok"] and row.get("recoverable") is not False]
    if launch["loaded"] and not bad:
        return {"action": None, "reason": "healthy" if all(row["ok"] for row in snapshots) else "source_limited"}
    if launch["loaded"]:
        # Give a completed failed attempt five minutes before an extra retry.
        latest = max((row.get("finished_at") or row.get("last_attempt_at") or 0 for row in bad), default=0)
        ready = max(latest + 300, max((row.get("retry_after") or 0 for row in bad), default=0))
        if now < ready:
            return {"action": None, "reason": "collection_cooldown", "retry_after": ready}
    active_window = now - retry.get("window_started_at", 0) < WINDOW
    count = retry.get("attempts", 0) if active_window else 0
    if active_window and count >= MAX_ATTEMPTS:
        return {"action": None, "reason": "retry_budget_exhausted", "retry_after": retry["window_started_at"] + WINDOW}
    if now < retry.get("retry_after", 0):
        return {"action": None, "reason": "recovery_cooldown", "retry_after": retry["retry_after"]}
    return {"action": "kickstart" if launch["loaded"] else "bootstrap",
            "reason": "failed_or_overdue" if launch["loaded"] else "registration_missing",
            "attempt": count + 1,
            "window_started_at": retry["window_started_at"] if active_window and count else now}


def inspect(root, agents_dir, state, now, apply=False):
    disabled = disabled_services()
    result = {"checked_at": now, "mode": "apply" if apply else "dry_run", "services": {}, "ok": True}
    for suffix, key in SERVICES.items():
        label = "com.brightbeed." + suffix
        launch = launch_status(label)
        members = GROUPS.get(key, [key])
        snapshots = []
        for member in members:
            row = snapshot_status(root, member, now)
            row["finished_at"] = read_json(Path(root) / "state/jobs" / (member + ".json")).get("finished_at")
            snapshots.append(row)
        prior = state.get("services", {}).get(label, {})
        plan = decision(launch, snapshots, prior, now)
        path = Path(agents_dir) / (label + ".plist")
        if disabled is None:
            plan = {"action": None, "reason": "disabled_state_unknown"}
        elif label in disabled:
            plan = {"action": None, "reason": "intentionally_disabled"}
        elif not valid_plist(path, label, root):
            plan = {"action": None, "reason": "plist_review_required"}
        row = {**prior, "loaded": launch.get("loaded"), "running": launch.get("running", False),
               "healthy": launch.get("loaded") is True and all(s["ok"] for s in snapshots),
               "failed_jobs": [s["id"] for s in snapshots if not s["ok"]], "plan": plan}
        if plan["reason"] == "healthy":
            row.update(attempts=0, retry_after=0)
        if apply and plan["action"]:
            # Reserve budget before dispatch so a crash cannot bypass backoff.
            row.update(attempts=plan["attempt"], window_started_at=plan["window_started_at"],
                       retry_after=now + RETRY_DELAYS[plan["attempt"] - 1], last_action_at=now)
            state.setdefault("services", {})[label] = row
            write_json(Path(root) / "state/watchdog.json", state)
            args = (["bootstrap", f"gui/{os.getuid()}", str(path)] if plan["action"] == "bootstrap"
                    else ["kickstart", f"gui/{os.getuid()}/{label}"])
            row["dispatch"] = command(args)
            # Accepted means scheduled, not successful data publication.
        result["services"][label] = row
        result["ok"] = result["ok"] and row["healthy"]
    return result


def run(root, agents_dir, apply=False):
    root = Path(root)
    state_path = root / "state/watchdog.json"
    if not apply:
        return inspect(root, agents_dir, read_json(state_path), time.time())
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(root / "state/watchdog.lock", "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "reason": "already_running"}
        result = inspect(root, agents_dir, read_json(state_path), time.time(), apply=True)
        write_json(state_path, result)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--agents-dir", type=Path, default=Path.home() / "Library/LaunchAgents")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.server, args.agents_dir, args.apply), ensure_ascii=False))
