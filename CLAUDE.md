# JobRadar

Poll companies' careers pages, screen new postings, alert on matches. Stdlib-only Python; one package, `jobradar/`.

## Map

- `jobradar/boards.py`: one fetcher per ATS (`f_<ats>`), `board_of(url)`, `fetch(ats, token)`. New ATS = a fetcher + `FETCHERS` entry + test.
- `jobradar/screen.py`: cheap gates from `config.json` (title, location, wording). `llm.py`: optional AI fit gate (Jev). `notify.py`: alert channels. `core.py`: poll/diff/state/report. `__main__.py`: CLI.
- `config.json`, `companies.json`, `profile.md`, `skip_urls.txt`, `data/`: personal, gitignored; `*.example.*` files are the shipped defaults.
- `templates/`, `prompts/`: message and LLM prompt text. Static text lives there, never inline in code.
- `schedule/`: launchd / cron examples. `skills/jobradar/SKILL.md`: Claude Code skill. `docs/finding-boards.md`: how to find a company's board.

## Rules

- Incremental commits: small logical commits, stage only touched paths, push each. Never commit data, secrets, or personal config.
- Nothing personal in tracked files (names, emails, one person's preferences). Examples stay generic.
- Tests: `python3 -m pytest -q` green before every commit; a fixed failure gets a test.
- A change to gates or prompts: `python3 -m jobradar run --rescreen --dry` to see the effect before the next scheduled poll.
