# Releasing Overwatch (Windows-only build step)

The fixes ship as code on `master`; the downloadable `Overwatch.exe` must be
built **on Windows** (`build.ps1` — PyInstaller + pywin32/wmi; can't be built or
cross-compiled on macOS/Linux).

## v2.0.2 — finish the draft release

Master is tagged `v2.0.2` and a **draft** GitHub release exists with notes. It's
a draft on purpose: publishing without the exe would break the README's
`/releases/latest` download link, and the local `dist-release/Overwatch.exe` is
the older v2.0.1 build — do NOT attach that.

On the Windows box (via Sidekick), from the repo root:

```powershell
git pull                                     # get v2.0.2 code
powershell -ExecutionPolicy Bypass -File build.ps1   # -> dist\Overwatch.exe
gh release upload v2.0.2 dist\Overwatch.exe --repo vorteniahq/Overwatch
gh release edit  v2.0.2 --draft=false        --repo vorteniahq/Overwatch
```

## Smoke-test before publishing (the fixes this release makes)

1. **#5 dashboard un-freeze** — on the machine that had the frozen feed, launch
   2.0.2 and confirm the newest events now appear at the top (ordering is by
   insertion id, so it works even on the already-mixed DB).
2. **#3 crash alert** — with Telegram configured, force a failure (e.g. rename
   the DB dir read-only) and confirm a verbatim crash message arrives.
3. **#8 control** — `curl -X POST http://127.0.0.1:7373/api/system/exit` stops it.
4. Run the suite: `python -m tests.test_timestamps`, `test_crash_alert`,
   `test_engine_degraded`, `test_db_path` — all should pass on the box.

## Still open (on-box work, tracked in issues)

- **#4** — kill the stale old instance + repoint the Startup shortcut.
- **#6** — delete orphan `winmon_events.db` files in `System32` / home (needs admin).
- **#3 follow-ups** — mid-run monitor-thread self-heal; degraded-state tray/dashboard UI.
