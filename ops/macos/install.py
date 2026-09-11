"""Prepare/apply the reviewed patch without unloading any launchd service.

Default is a dry run. The entire existing-file manifest must match before writes.
"""
import argparse
import ast
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from job_runtime import atomic_write

MODULES = ("job_runtime.py", "job_status.py", "refresh_session.py", "job_watchdog.py", "configure_watchdog.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install(server, apply=False):
    bundle = Path(__file__).resolve().parent
    server = Path(server).resolve()
    manifest = json.loads((bundle / "patch-manifest.json").read_text())
    changes = []
    with tempfile.TemporaryDirectory(prefix="brightbeed-prepare-") as tmp:
        tmp = Path(tmp)
        for item in manifest:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or relative.parts[0] == "launchd":
                raise ValueError("invalid source manifest")
            target = server / relative
            current = digest(target)
            if current == item["after"]:
                continue
            if current != item["before"]:
                raise RuntimeError("Source changed since review: " + str(relative))
            staged = tmp / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, staged)
            patch = bundle / "patches" / (str(relative).replace("/", "__") + ".patch")
            subprocess.run(["/usr/bin/patch", "--batch", "-p1", "-i", str(patch)], cwd=tmp, check=True, capture_output=True)
            if digest(staged) != item["after"]:
                raise RuntimeError("Patch verification failed: " + str(relative))
            if relative.suffix == ".py":
                ast.parse(staged.read_text())
            elif relative.suffix == ".sh":
                subprocess.run(["/bin/bash", "-n", str(staged)], check=True)
            changes.append((target, staged.read_bytes(), current))
        for filename in MODULES:
            path = bundle / filename
            ast.parse(path.read_text())
            target = server / "scripts" / filename
            if not target.exists() or target.read_bytes() != path.read_bytes():
                changes.append((target, path.read_bytes(), digest(target) if target.exists() else None))
        print(f"Validated {len(changes)} file changes. launchd registrations are preserved.")
        if not apply or not changes:
            return None
        # Recheck after preparation to avoid losing a concurrent editor's work.
        for target, _, original in changes:
            if (digest(target) if target.exists() else None) != original:
                raise RuntimeError("Source changed during preparation: " + str(target))
        backup = server / "backups" / datetime.datetime.now().strftime("stability-%Y%m%d-%H%M%S")
        backup.mkdir(parents=True)
        restore = []
        for target, _, original in changes:
            copy = backup / target.relative_to(server)
            if original:
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, copy)
            restore.append({"target": str(target), "backup": str(copy) if original else None})
        (backup / "restore.json").write_text(json.dumps(restore, indent=2))
        written = []
        try:
            # Modules first, then callers: running services can keep using old code
            # until the proxy is explicitly restarted after validation.
            changes.sort(key=lambda item: 0 if item[0].name in MODULES else 1)
            for target, content, _ in changes:
                mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
                atomic_write(target, content)
                target.chmod(mode)
                written.append(target)
        except Exception:
            for item in restore:
                if Path(item["target"]) not in written:
                    continue
                if item["backup"]:
                    shutil.copy2(item["backup"], item["target"])
                else:
                    Path(item["target"]).unlink()
            raise
        print("Backup:", backup)
        return backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=str(Path.home() / "server/brightbeed-proxy"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    install(args.server, args.apply)
