# macOS collection reliability

The runtime is for read-only collectors. It never replays inventory writes or changes launchd registration.

`job_runtime.py` provides a cross-process flock, durable run IDs/results, bounded collector execution,
a private staging directory, schema/count/time validation, atomic publication, and a preserved good backup.
The child inherits the lock descriptor so killing the parent cannot immediately admit a second collector.
Success is recorded only after publication. Failures retain the published snapshot and last success timestamp.

The platform suite includes Ably 6a/kop/apt, Zigzag 6a, and Smartstore pp/kop. Session recovery makes
one bounded login attempt with existing local credentials. It never logs credentials or saves an unverified
login page. A CAPTCHA or additional authentication produces `session_login_required`.

## Installation

Run from a normal server terminal after reviewing the patch manifest:

```sh
python3 ops/macos/install.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 ops/macos/install.py --apply
launchctl kickstart -k "gui/$(id -u)/com.brightbeed.proxy"
```

The dry run and apply both reject any existing source file that differs from the reviewed before/after
hashes. This matters because this server is also being edited in another session. The installer validates
all patches before writing, backs up affected files under the proxy's `backups/` directory, and preserves
existing launchd labels, paths and schedules. Scheduled and manual collector entry points use the same
runtime. No `bootout` is used by the installer.

Each backup has `restore.json` with original file locations. Restore those files and restart the proxy
from a normal terminal to roll back code. Do not roll back caches or inventory as part of a code rollback.

## Validation and limitations

`tests/test_job_runtime.py` exercises actual subprocess success, timeout, exit-zero-without-output,
nonzero-with-valid-output, corrupt JSON, lock exclusion, interrupted records, disk publication failure,
backup preservation, duplicate IDs, data loss, freshness and failure status. It uses temporary files only.

Individual snapshots are atomic. A suite of brand snapshots is not a cross-file transaction; status
reports all child outcomes instead of treating partial completion as complete. Existing report history
side files are not covered by the primary snapshot transaction. Ad collection and the legacy PPT job
still use their existing runners; a touched log never counts as proven success.

## Server state from 2026-09-11

- Code changes and parser/helper files were copied to the server with backups.
- Reload is **not yet verified**: this Codex macOS sandbox rejects launchd bootstrap and kickstart.
- During the first deployment attempt, eight collector services were unloaded. Original files were restored
  and verified byte-for-byte when bootstrap failed. A revised installer then applied code without modifying
  registrations. **The eight registrations still need recovery from a normal terminal.**
- The existing proxy and tunnel continue serving, but the running proxy still has old code until restarted.
- Services needing bootstrap: `com.brightbeed.platform-sales`, `pro-sales`, `admin-sales`, `bestsellers`,
  `brand-report`, `kuaidiair-fetch`, `kuaidiair-fetch-shinebeed`, `vendor-fetch` (all with the same prefix).
- The calling task's `outputs/restore-launchd.sh` restores those registrations and restarts the proxy.
- Chromium launch from this sandbox fails at MachPortRendezvous bootstrap with Permission denied;
  browser-backed live validation must run through the normal operational environment.
- Smartstore kop collection passed using an isolated output directory. Smartstore pp returned 85 detail
  rows for 87 requested IDs in the final batch; it now fails validation instead of publishing a partial total.
- The daily PPT source sheet still says 2026-06-24. Its failure gate has not been bypassed.
- The stock app still needs a current SixA source (legacy JSON is from 2026-06-10), verified PA routing,
  transactional DB publication, durable SKU idempotency, and channel readback. No DB migration or inventory
  test write has been performed.
