"""Optional fit gate: one model call per unseen job description.

providers (config.json "llm"."provider", with an optional "fallback" block of the same shape, used when the primary errors):
  jev         TypeSafe System One (key in $TYPESAFE_API_KEY): typed questions from prompts/jev_questions.json answered against the
              profile and posting, as scores and probabilities. Cheap and consistent; enough for a yes/no filter.
  workers-ai  Cloudflare Workers AI ($CLOUDFLARE_ACCOUNT_ID, $CLOUDFLARE_API_TOKEN, "model" e.g. "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
  anthropic   Messages API ($ANTHROPIC_API_KEY, "model")
  command     any shell command that reads the prompt on stdin and prints the answer
The generative providers (workers-ai, anthropic, command) use prompts/fit.md and answer JSON {"match", "fit", "reason"};
`gate` applies each provider's own thresholds. Edit the prompt and question files, not the code.
"""
import json, os, re, subprocess, urllib.request

from .paths import ROOT, PROMPTS


def read(path):
    return open(path if os.path.isabs(path) else os.path.join(ROOT, path)).read()


def post_json(url, body, headers, retries=3):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json", **headers})
    err = None
    for _ in range(retries):  # transient failures
        try:
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:
            err = e
    raise RuntimeError(err)


def job_of(r, company):
    return {"title": r["title"], "company": company, "location": r.get("loc") or "", "remote": bool(r.get("remote")),
            "description": (r.get("desc") or "")[:9000]}


def build_prompt(cfg, block, r, company):
    text = read(block.get("prompt", os.path.join(PROMPTS, "fit.md")))
    j = job_of(r, company)
    fill = {"profile": read(cfg["llm"].get("profile", "profile.md")).strip(), "company": company, "title": j["title"],
            "location": j["location"], "remote": "yes" if j["remote"] else "unknown", "description": j["description"]}
    for k, v in fill.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def parse(out):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise RuntimeError(f"no JSON in answer: {out[:120]!r}")
    a = json.loads(m.group(0))
    return {"match": bool(a["match"]), "fit": float(a.get("fit", 0)), "reason": str(a.get("reason", ""))[:300]}


def ask(block, prompt):
    p = block["provider"]
    if p == "command":
        out = subprocess.run(block["command"], shell=True, input=prompt, capture_output=True, text=True, timeout=180)
        if out.returncode:
            raise RuntimeError(out.stderr.strip()[:200])
        return out.stdout
    if p == "anthropic":
        d = post_json("https://api.anthropic.com/v1/messages", {"model": block["model"], "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
                      {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        return d["content"][0]["text"]
    if p == "workers-ai":
        d = post_json(f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/ai/run/{block['model']}",
                      {"messages": [{"role": "user", "content": prompt}], "max_tokens": 300},
                      {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"})
        if not d.get("success", True):
            raise RuntimeError(str(d.get("errors"))[:200])
        r = d["result"]["response"]
        return r if isinstance(r, str) else json.dumps(r)
    raise SystemExit(f"unknown llm provider {p!r}")


def jev(cfg, block, r, company):
    q = json.loads(read(block.get("questions", os.path.join(PROMPTS, "jev_questions.json"))))
    a = post_json("https://api.typesafe.ai/v1/systemone",
                  {"model": block.get("model", "jev-latest"), "state": {"candidate": read(cfg["llm"].get("profile", "profile.md")).strip(), "job": job_of(r, company)},
                   "questions": q}, {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"})["answers"]
    return {"fit": a["fit"]["score"], **{k: a[k]["noul"] for k in ("role_match", "language_block", "eligibility_block")}}


def judge_with(cfg, block, r, company):
    if block["provider"] == "jev":
        ans = jev(cfg, block, r, company)
    else:
        ans = parse(ask(block, build_prompt(cfg, block, r, company)))
    return {**ans, "by": block["provider"]}


def judge(cfg, r, company):
    """The primary provider's answer; on an error the fallback's, if configured."""
    try:
        return judge_with(cfg, cfg["llm"], r, company)
    except Exception:
        if not cfg["llm"].get("fallback"):
            raise
        return judge_with(cfg, cfg["llm"]["fallback"], r, company)


def gate(cfg, a):
    """Why the answer rules a posting out, else None. Thresholds come from the block of the provider that answered."""
    llm = cfg["llm"]
    b = llm if a.get("by", llm["provider"]) == llm["provider"] else llm.get("fallback", llm)
    if "match" in a:
        if not a["match"]:
            return a["reason"] or "not a match"
        return f"fit {a['fit']:g} below {b.get('min_fit', 3)}" if a["fit"] < b.get("min_fit", 3) else None
    why = [n for n, bad in [("role mismatch", a["role_match"] <= b.get("role_match_min", 0.5)),
                            ("language", a["language_block"] >= b.get("language_block_max", 0.9)),
                            ("eligibility", a["eligibility_block"] >= b.get("eligibility_block_max", 0.8)),
                            ("low fit", a["fit"] < b.get("fit_min", 2))] if bad]
    return ", ".join(why) or None
