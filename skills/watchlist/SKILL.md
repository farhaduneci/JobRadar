---
name: watchlist
description: Watch list of companies' careers pages, polled on a schedule for new postings that pass the configured screen, each new match alerted on the configured channel. Use to add or drop a company, check what is matching now, run a poll, install the schedule, or review run health.
argument-hint: [status | add <company or careers URL> | remove <slug> | run [slug] | report | install]
---

# Watchlist

One CLI does the work: `python3 -m watchlist <command>` from the repo root (or with `WATCHLIST_HOME` pointing at it).
Files: `companies.json` (the list, personal), `config.json` (screen, LLM gate, alert channel), `data/state/<slug>.json` (every posting seen, with its
verdict), `data/runs.jsonl` (one line per company per poll). Pick the mode from `$ARGUMENTS`; none means `status`.

## status
`list`, then `report --days 1`. Answer in a few lines: companies watched, roles matching now, anything flagged.

## add `<company or careers URL>`
1. Find every board the company posts on (`docs/finding-boards.md`). Often several: a global board plus per-country ones. Done when each
   board's count is known and the sum matches what the careers page shows.
2. The board must be one `boards.py` reads (`FETCHERS`). For any other ATS add a fetcher with a test first.
3. `python3 -m watchlist add --name <Name> --careers-url <url> --board <ats>:<token> [--board ...]`. It probes each board and refuses a dead one.
4. Baseline: `python3 -m watchlist run --company <slug>`. It screens what is open, sends nothing, marks it seen, so only later postings alert.
5. Show the roles matching right now (`list`).

## remove `<slug>`
`remove <slug>`: polling stops, state stays.

## run `[slug]`
`run [--company <slug>] [--dry] [--rescreen]`. Same as a scheduled poll. `--rescreen` re-judges every open posting after a config change.

## report
`report --days 1`; exit 0 and no title-gate line means clean. Clear each flag by cause:
- **no run / over 26 h**: the scheduler is not firing; check its log (`data/logs/run.log`).
- **last run suspect**: a board errored or shrank under half. Re-probe it (`docs/finding-boards.md`); a moved token or changed ATS means re-running `add`. A real shrink clears itself on the next healthy run.
- **waiting on the AI gate**: key missing or provider down. Postings retry every run.
- **matches not delivered**: the alert channel is broken; fix it, matches go out on the next run.
- **title-gate drops that look technical**: read each title. One in a target family is a miss: add a word to that company's `titles_extra` (a miss every
  company would hit belongs in `config.json` titles), then `run --company <slug> --rescreen`.
Any code change ends with `python3 -m pytest -q` green.

## install
Confirm first. macOS: `schedule/launchd.plist.example`; Linux: `schedule/crontab.example`. Both run `python3 -m watchlist run` and append to `data/logs/run.log`.
