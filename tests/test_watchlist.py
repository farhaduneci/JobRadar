"""Diff, screen, alert and broken-board guard, with the board and the LLM faked. Run: python3 -m pytest -q"""
import json, os, sys, types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from watchlist import core, llm, screen  # noqa: E402

JD = "Python services, Kubernetes. Hybrid in Vilnius."
GOOD = {"fit": 3.0, "role_match": 0.9, "language_block": 0.1, "eligibility_block": 0.1}
CFG = {"titles": {"include": ["engineer"], "exclude": ["site reliability"]}, "title_drop": [],
       "locations": {"include": ["Lithuania", "Vilnius"], "remote_words": ["remote"], "allow_remote": True, "exclude_regex": r"\b(new york|usa)\b"},
       "wording_drop": {"no sponsorship": r"cannot sponsor"}, "llm": {"enabled": True, "fit_min": 2}}


def row(i, title, loc="Vilnius, Lithuania", desc=JD):
    return {"id": f"gh:x:{i}", "title": title, "url": f"https://x/{i}", "loc": loc, "date": "2026-10-10", "desc": desc}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE", str(tmp_path / "state"))
    monkeypatch.setattr(core, "RUNS", str(tmp_path / "runs.jsonl"))
    board, sent, calls = {"rows": []}, [], []
    monkeypatch.setattr(core, "fetch", lambda ats, tok: list(board["rows"]))
    monkeypatch.setattr(core, "judge", lambda cfg, r, co: calls.append(r["title"]) or GOOD)
    monkeypatch.setattr(core, "send", lambda cfg, event, dry, **v: sent.append((event, v)) or True)
    os.makedirs(tmp_path / "state")
    c = {"name": "Acme", "slug": "acme", "boards": ["greenhouse:acme"]}
    args = types.SimpleNamespace(rescreen=False, dry=False)
    return board, sent, calls, (lambda: core.run_company(c, args, CFG, set())), tmp_path


def test_role_part_keeps_team_names_out_of_exclusions():
    assert screen.role_part("Senior Backend Engineer, Site Reliability Group") == "Senior Backend Engineer"
    assert screen.role_part("Engineer - Android/Kotlin") == "Engineer - Android/Kotlin"


def test_baseline_is_silent_then_only_new_matches_alert(env):
    board, sent, calls, run, _ = env
    board["rows"] = [row(1, "Backend Engineer, Payments"), row(2, "Accountant")]
    r = run()
    assert r["mode"] == "baseline" and r["matches"] == ["Backend Engineer, Payments"] and not sent
    board["rows"].append(row(3, "Backend Engineer, Search"))
    r = run()
    assert r["new"] == 1 and len(sent) == 1 and "Backend Engineer, Search" in sent[0][1]["roles"]
    run()
    assert len(sent) == 1


def test_same_jd_other_location_reuses_llm_answer(env):
    board, sent, calls, run, _ = env
    board["rows"] = [row(1, "Backend Engineer, Payments"), row(2, "Backend Engineer, Payments", "Vilnius, Lithuania ")]
    run()
    assert len(calls) == 1


def test_broken_board_closes_nothing_and_alerts_once(env):
    board, sent, calls, run, tmp = env
    board["rows"] = [row(i, f"Accountant {i}") for i in range(10)]
    run()
    board["rows"] = board["rows"][:2]
    for _ in range(3):
        r = run()
        assert not r["ok"] and r["closed"] == 0
    assert [e for e, _ in sent] == ["broken"]
    assert not any(p["closed"] for p in json.load(open(tmp / "state" / "acme.json"))["postings"].values())


def test_cheap_gate_reasons():
    inc, exc = screen.titles(CFG)
    g = lambda r: screen.cheap_gate(r, CFG, inc, exc, {"https://x/9"})
    assert g(row(1, "Backend Engineer")) is None
    assert g(row(1, "Accountant")) == "title"
    assert g(row(1, "Site Reliability Engineer")) == "title"
    assert g(row(1, "Backend Engineer", "New York, USA")) == "location"
    assert g(row(1, "Backend Engineer", "")) is None
    assert g(row(9, "Backend Engineer")) == "skipped url"
    assert g(row(1, "Backend Engineer", desc="We cannot sponsor visas")) == "wording: no sponsorship"


def test_jev_gate_uses_thresholds():
    assert llm.gate(CFG, GOOD) is None
    assert llm.gate(CFG, dict(GOOD, language_block=0.95, fit=1)) == "language, low fit"
    assert llm.gate(CFG, dict(GOOD, role_match=0.2)) == "role mismatch"
    assert llm.gate(CFG, dict(GOOD, eligibility_block=0.8)) == "eligibility"


def test_no_llm_company_matches_on_cheap_gates(env):
    board, sent, calls, _, tmp = env
    c = {"name": "Shop", "slug": "shop", "boards": ["greenhouse:shop"], "no_llm": True}
    board["rows"] = [row(1, "Backend Engineer")]
    r = core.run_company(c, types.SimpleNamespace(rescreen=False, dry=False), CFG, set())
    assert r["matches"] == ["Backend Engineer"] and not calls
