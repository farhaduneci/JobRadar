"""Optional AI fit gate: TypeSafe System One (Jev) answers typed questions about each unseen job description.

Key in $TYPESAFE_API_KEY. The questions live in prompts/jev_questions.json and run against the candidate profile (profile.md) and the posting;
answers are a fit score and probabilities, ruled on by the thresholds in config.json "llm". Edit the files, not the code.
"""
import json, os

from radarkit import http, jev

from .paths import ROOT, PROMPTS


def read(path):
    return open(path if os.path.isabs(path) else os.path.join(ROOT, path)).read()


def job_of(r, company):
    return {"title": r["title"], "company": company, "location": r.get("loc") or "", "remote": bool(r.get("remote")),
            "description": (r.get("desc") or "")[:9000]}


def judge(cfg, r, company):
    """Jev's answers for one posting: fit score, role_match, language_block, eligibility_block."""
    llm = cfg["llm"]
    q = json.loads(read(llm.get("questions", os.path.join(PROMPTS, "jev_questions.json"))))
    state = {"candidate": read(llm.get("profile", "profile.md")).strip(), "job": job_of(r, company)}
    a = http.run(jev.ask(state, q, model=llm.get("model", jev.MODEL)))
    return {"fit": a["fit"]["score"], **{k: a[k]["noul"] for k in ("role_match", "language_block", "eligibility_block")}}


def gate(cfg, a):
    """Why the answers rule a posting out, else None."""
    b = cfg["llm"]
    why = [n for n, bad in [("role mismatch", a["role_match"] <= b.get("role_match_min", 0.5)),
                            ("language", a["language_block"] >= b.get("language_block_max", 0.9)),
                            ("eligibility", a["eligibility_block"] >= b.get("eligibility_block_max", 0.8)),
                            ("low fit", a["fit"] < b.get("fit_min", 2))] if bad]
    return ", ".join(why) or None
