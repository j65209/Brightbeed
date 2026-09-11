"""Install the optional recovery LaunchAgent from a normal macOS terminal.

Dry run by default; never unloads an existing service. Proxy restart is explicit.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import plistlib

from job_runtime import atomic_write
from job_status import launch_status
from job_watchdog import SERVICES, command, valid_plist

LABEL = "com.brightbeed.watchdog"


def configure(server, agents_dir, apply=False, restart_proxy=False):
    server, agents_dir = Path(server).resolve(), Path(agents_dir)
    for name in ("job_runtime.py", "job_status.py", "job_watchdog.py", "refresh_session.py"):
        ast.parse((server / "scripts" / name).read_text())
    for suffix in SERVICES:
        label = "com.brightbeed." + suffix
        if not valid_plist(agents_dir / (label + ".plist"), label, server):
            raise RuntimeError("Collector configuration needs review: " + label)
    data = {"Label": LABEL,
            "ProgramArguments": ["/usr/bin/python3", str(server / "scripts/job_watchdog.py"), "--apply"],
            "WorkingDirectory": str(server), "StartInterval": 300, "RunAtLoad": True,
            "StandardOutPath": str(server / "logs/watchdog.out.log"),
            "StandardErrorPath": str(server / "logs/watchdog.err.log")}
    path = agents_dir / (LABEL + ".plist")
    if path.exists() and plistlib.loads(path.read_bytes()) != data:
        raise RuntimeError("Existing watchdog configuration differs; preserved for review")
    current = launch_status(LABEL)
    proxy = launch_status("com.brightbeed.proxy")
    if current.get("loaded") is None or (restart_proxy and proxy.get("loaded") is not True):
        raise RuntimeError("Cannot verify launchd state; no configuration changed")
    result = {"mode": "apply" if apply else "dry_run", "validated_collectors": len(SERVICES),
              "watchdog_loaded": current["loaded"], "restart_proxy": restart_proxy, "plist": str(path)}
    if not apply:
        return result
    (server / "logs").mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write(path, plistlib.dumps(data))
        path.chmod(0o600)
    domain = f"gui/{os.getuid()}"
    if not current["loaded"]:
        dispatched = command(["bootstrap", domain, str(path)])
        if not dispatched["accepted"]:
            raise RuntimeError("Watchdog registration failed; existing collectors remain loaded. Use a normal Terminal.")
    loaded = launch_status(LABEL)
    if loaded.get("loaded") is not True:
        raise RuntimeError("Watchdog registration could not be verified")
    if not loaded.get("running"):
        if not command(["kickstart", domain + "/" + LABEL])["accepted"]:
            raise RuntimeError("Watchdog is registered but its first execution needs verification")
    if restart_proxy:
        if not command(["kickstart", "-k", domain + "/com.brightbeed.proxy"])["accepted"]:
            raise RuntimeError("Watchdog installed; proxy reload failed. Use a normal Terminal.")
    result.update(watchdog_loaded=True, first_check="scheduled", collection_success="verify job journals")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--agents-dir", type=Path, default=Path.home() / "Library/LaunchAgents")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart-proxy", action="store_true")
    args = parser.parse_args()
    print(json.dumps(configure(args.server, args.agents_dir, args.apply, args.restart_proxy), ensure_ascii=False))
