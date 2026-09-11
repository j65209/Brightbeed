# macOS collection reliability

The runtime is for read-only collectors. It never replays inventory writes. The optional watchdog can restore missing read-only collector registrations and start idle overdue collectors; it never unloads or kills them.

`job_runtime.py` provides a cross-process flock, durable run IDs/results, bounded collector execution,
a private staging directory, schema/count/time validation, atomic publication, and a preserved good backup.
The child inherits the lock descriptor so killing the parent cannot immediately admit a second collector.
Success is recorded only after publication. Failures retain the published snapshot and last success timestamp.

The platform suite includes Ably 6a/kop/apt, Zigzag 6a/kop/apt, and Smartstore pp/kop. Session recovery makes
one bounded login attempt with existing local credentials. Failed attempts persist a 5/10/20/30-minute backoff, shared by scheduled and browser-triggered calls, and reset it on success.

Recovery uses an optional five-minute LaunchAgent. It respects intentionally disabled jobs, rejects unknown registration state and changed command paths, waits for collector backoff, and permits at most three additional dispatches per hour per service. Running jobs are left alone. The watchdog records planned/accepted dispatch separately from actual collection success. Report freshness checks the latest completed 08:00/12:00/18:00 KST slot with a 30-minute completion allowance.

Smartstore omissions are retried individually (up to ten). Only HTTP 400/code 100001 is classified as unavailable; any other missing, duplicate, unexpected, or invalid detail fails publication. Published results include coverage and a partial-data warning. Fresh policy-limited data is shown as partial and is not retried by the watchdog; routine collection continues. See [Naver’s explanation](https://github.com/commerce-api-naver/commerce-api/discussions/3572).

Session renewal never logs credentials or saves an unverified
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

## Enable recovery from a normal Terminal

After installing the reviewed server files, inspect and then enable the additional LaunchAgent:

```sh
python3 ~/server/brightbeed-proxy/scripts/configure_watchdog.py --restart-proxy
python3 ~/server/brightbeed-proxy/scripts/configure_watchdog.py --apply --restart-proxy
```

Configuration validates all eight collector plists before writing. It creates only the new watchdog
plist; it refuses to overwrite a different existing configuration. A bootstrap failure leaves existing
collectors and the proxy running. `--restart-proxy` explicitly reloads the proxy after successful
watchdog registration; omit it when no proxy reload is needed. Inspect `state/watchdog.json`, the
collector journals, and actual `/health` results after enabling. Registration alone is not success.

Tests cover interrupted state, collector and watchdog locks, backoff surviving process restart,
calendar deadlines, disabled/unknown/changed service configuration, dry-run immutability,
registration failure, and restricted versus transient or unconfirmed Smartstore omissions.

## Server state at 2026-09-11 16:30 KST

- All eight collector registrations have been restored and the proxy was restarted. Kuaidiair
  brightbeed/shinebeed have completed subsequent runs; latest verified counts are 79 and 117.
- The first deployment attempt unloaded eight collectors and could not bootstrap them from the
  Codex sandbox. That incident is resolved for the original registrations. Future installers never unload them.
- The latest runtime/backoff/calendar/coverage modules are installed with backups, preserving the
  concurrent Zigzag multi-brand update and refining the concurrent Smartstore skip behavior.
- The **new watchdog LaunchAgent is still awaiting activation from a normal Terminal**. This sandbox
  rejects bootstrap/kickstart. Its source and configuration dry run passed; do not call it active before
  checking launchd and `state/watchdog.json`. Latest proxy module reload is also part of that command.
- Live read-only PP diagnosis found 2,192 details for 2,194 order IDs; both omitted IDs returned
  HTTP 400/code 100001 individually. Naver documents this as unavailable after Naver Pay withdrawal.
  No customer identifiers, order IDs, tokens, or response bodies are included in this repository.
- The daily PPT source sheet still says 2026-06-24. Its freshness gate has not been bypassed.
- LaunchAgents require this Mac to be awake and the service user logged in. Current sleep is disabled;
  reboot/power restoration and logged-out operation have not been verified.
- App changes remain in draft PR #3. The coverage notice is not deployed to the public site yet.
- The stock app still needs a current SixA source (legacy JSON is from 2026-06-10), verified PA routing,
  transactional DB publication, durable SKU idempotency, and channel readback. No DB migration or inventory
  test write has been performed.
