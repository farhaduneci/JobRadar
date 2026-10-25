# JobRadar

Poll companies' careers pages, screen new postings, alert on matches. Stdlib-only Python; one package, `jobradar/`, plus one dependency: RadarKit (`pip install -e .`), which owns the board fetchers, alert channels and the Jev client.

## Map

- `jobradar/boards.py`: sync adapter over `radarkit.boards` (`fetch`, `board_of`, `FETCHERS`). A new ATS goes into RadarKit (fetcher + fixture test, new tag), then bump the pin in `pyproject.toml`.
- `jobradar/screen.py`: cheap gates from `config.json` (title, location, wording). `llm.py`: optional AI fit gate (questions and gate here, client `radarkit.jev`). `notify.py`: templates + `radarkit.notify` channels. `core.py`: poll/diff/state/report. `__main__.py`: CLI.
- `config.json`, `companies.json`, `profile.md`, `skip_urls.txt`, `data/`: personal, gitignored; `*.example.*` files are the shipped defaults.
- `templates/`, `prompts/`: message and LLM prompt text. Static text lives there, never inline in code.
- `schedule/`: launchd / cron examples. `skills/jobradar/SKILL.md`: Claude Code skill. `docs/finding-boards.md`: how to find a company's board.

## Rules

- Incremental commits: small logical commits, stage only touched paths, push each. Never commit data, secrets, or personal config.
- Nothing personal in tracked files (names, emails, one person's preferences). Examples stay generic.
- Tests: `python3 -m pytest -q` green before every commit; a fixed failure gets a test.
- A change to gates or prompts: `python3 -m jobradar run --rescreen --dry` to see the effect before the next scheduled poll.
