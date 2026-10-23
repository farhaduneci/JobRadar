"""Where things live. WATCHLIST_HOME (default: the repo root) holds companies.json, config.json, profile.md and data/."""
import os

ROOT = os.path.abspath(os.environ.get("WATCHLIST_HOME") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PKG = os.path.dirname(os.path.abspath(__file__))
COMPANIES = os.path.join(ROOT, "companies.json")
CONFIG = os.path.join(ROOT, "config.json")
DATA = os.path.join(ROOT, "data")
STATE = os.path.join(DATA, "state")
RUNS = os.path.join(DATA, "runs.jsonl")
TEMPLATES = os.path.join(ROOT, "templates")
PROMPTS = os.path.join(ROOT, "prompts")
