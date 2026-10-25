"""Poll companies' job boards, diff against what was seen, screen what is new, alert on matches, log every run."""
import collections, concurrent.futures as cf, hashlib, json, os, re, sys, time

from . import boards, llm, notify, screen
from .paths import COMPANIES, RUNS, STATE, ROOT

fetch = boards.fetch
SHRINK = 0.5  # a board returning under half of last run's count is suspect: nothing gets closed on that run
TODAY = time.strftime("%Y-%m-%d")
ATS = tuple(boards.FETCHERS)


def jload(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def use_llm(cfg, c):
    return bool(cfg.get("llm", {}).get("enabled")) and not c.get("no_llm")


def judge(cfg, r, company):
    return llm.judge(cfg, r, company)


def send(cfg, event, dry, **vars):
    """One alert. True only when it went out: a dry run or a delivery failure leaves matches unsent for the next run."""
    if dry or os.environ.get("JOBRADAR_NOTIFY") == "0":
        print(f"  (not sent: {event} {vars.get('company')})")
        return False
    try:
        return notify.deliver(cfg, event, **vars)
    except Exception as e:
        print(f"  notify {event} failed: {e}")
        return False


def role_lines(rows):
    """'Title (City, City): url' per distinct title, best fit first. Multi-location postings collapse into one line."""
    by = collections.OrderedDict()
    for p in sorted(rows, key=lambda p: -(p.get("llm") or {}).get("fit", 0)):
        by.setdefault(p["t"], {"locs": [], "url": p["url"]})["locs"].append((p.get("loc") or "?").split(",")[0])
    return [f"{t} ({', '.join(dict.fromkeys(v['locs']))}): {v['url']}" for t, v in by.items()]


def run_company(c, args, cfg, skip):
    """Poll one company. Returns the run record (also appended to runs.jsonl)."""
    t0, sp = time.time(), os.path.join(STATE, c["slug"] + ".json")
    st = jload(sp, {"company": c["name"], "baseline": None, "postings": {}, "fail_streak": 0, "last_count": 0})
    baseline = st["baseline"] is None
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "company": c["slug"], "mode": "baseline" if baseline else "rescreen" if args.rescreen else "run",
           "ok": True, "fetched": 0, "boards": {}, "new": 0, "closed": 0, "reopened": 0,
           "llm_calls": 0, "llm_cached": 0, "llm_errors": 0, "matches": [], "notified": 0, "errors": [], "stages": {}}
    rows = {}
    for b in c["boards"]:
        ats, tok = b.split(":", 1)
        try:
            got = fetch(ats, tok)
            rec["boards"][b] = len(got)
            for r in got:
                rows[r["id"]] = r
        except Exception as e:
            rec["errors"].append(f"{b}: {type(e).__name__}: {str(e)[:160]}")
    rec["fetched"] = len(rows)
    suspect = bool(rec["errors"]) or not rows or (st["last_count"] and len(rows) < SHRINK * st["last_count"])
    if suspect:
        rec["ok"] = False
        if not rec["errors"]:
            rec["errors"].append(f"board shrank: {len(rows)} postings vs {st['last_count']} last run")
    P = st["postings"]
    if not suspect:  # a broken fetch must not mark the whole board closed
        for pid, p in P.items():
            if pid not in rows and not p.get("closed"):
                p["closed"] = TODAY
                rec["closed"] += 1
        st["last_count"] = len(rows)
    inc, exc = screen.titles(cfg, c.get("titles_extra", []), c.get("titles_exclude", []))
    llm_on = use_llm(cfg, c)
    todo, screened = [], []
    for pid, r in rows.items():
        r["title"] = re.sub(r"\s+", " ", r["title"]).strip()
        h = hashlib.sha1((r["title"] + "\n" + (r.get("desc") or "")[:9000]).encode()).hexdigest()[:16]
        p = P.get(pid)
        if p is None:
            p = P[pid] = {"t": r["title"], "url": r["url"], "loc": r.get("loc"), "posted": (r.get("date") or "")[:10],
                          "first_seen": TODAY, "closed": None, "notified": None}
            rec["new"] += 0 if baseline else 1
        elif p.get("closed"):
            p["closed"] = None
            rec["reopened"] += 1
        p.update(last_seen=TODAY, h=h, url=r["url"], loc=r.get("loc"), t=r["title"])
        if "stage" in p and not args.rescreen and p["stage"] != "pending":
            continue
        p["stage"] = screen.cheap_gate(r, cfg, inc, exc, skip) or ("llm" if llm_on else "match")
        screened.append(pid)
        if p["stage"] == "llm":
            todo.append((pid, r))
    # The LLM only sees unseen JDs: a posting whose JD hash was judged before (another location, an earlier run) reuses it.
    cache = {p["h"]: p["llm"] for p in P.values() if p.get("llm") and p.get("h")}
    need = {}
    for pid, r in todo:
        h = P[pid]["h"]
        if h in cache:
            P[pid]["llm"] = cache[h]
            rec["llm_cached"] += 1
        else:
            need.setdefault(h, []).append((pid, r))
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(judge, cfg, grp[0][1], c["name"]): h for h, grp in need.items()}
        for f in cf.as_completed(futs):
            h = futs[f]
            rec["llm_calls"] += 1
            try:
                ans = f.result()
            except Exception as e:
                rec["llm_errors"] += 1
                rec["errors"].append(f"llm: {str(e)[:160]}")
                ans = None
            for pid, _ in need[h]:
                if ans:
                    P[pid]["llm"] = ans
    for pid, _ in todo:
        p = P[pid]
        if not p.get("llm"):
            p["stage"] = "pending"  # LLM failed: judged again next run
            continue
        why = llm.gate(cfg, p["llm"])
        p["stage"] = f"llm: {why}" if why else "match"
    rec["stages"] = dict(collections.Counter(P[pid]["stage"] for pid in screened))
    # Matches never sent before, open, outside a baseline. Baseline matches are recorded as already seen.
    fresh = [dict(p, id=pid) for pid, p in P.items() if p["stage"] == "match" and not p.get("notified") and not p.get("closed")]
    rec["matches"] = [p["t"] for p in fresh]
    if baseline:
        for p in fresh:
            P[p["id"]]["notified"] = "baseline"
        st["baseline"] = TODAY
    elif fresh:
        lines = role_lines(fresh)
        ok = send(cfg, "match" if len(lines) == 1 else "matches", args.dry, company=c["name"], n=len(lines),
                  roles="\n".join(lines[:4]) + (f"\n…and {len(lines) - 4} more" if len(lines) > 4 else ""))
        if ok:
            for p in fresh:
                P[p["id"]]["notified"] = TODAY
            rec["notified"] = len(fresh)
    # A broken board alerts once, on its second failing run in a row, then stays quiet until it recovers.
    st["fail_streak"] = st["fail_streak"] + 1 if not rec["ok"] else 0
    if st["fail_streak"] == 2:
        send(cfg, "broken", args.dry, company=c["name"])
    rec["ms"] = int((time.time() - t0) * 1000)
    st["last_run"] = rec["ts"]
    jsave(sp, st)
    os.makedirs(os.path.dirname(RUNS), exist_ok=True)
    with open(RUNS, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def enabled():
    return [c for c in jload(COMPANIES, {"companies": []})["companies"] if c.get("enabled", True)]


def cmd_run(args):
    cfg, cos = screen.load_config(), enabled()
    if args.company:
        cos = [c for c in cos if c["slug"] == args.company]
        if not cos:
            sys.exit(f"no enabled company '{args.company}' in {COMPANIES}")
    if not cos:
        sys.exit(f"no companies: copy companies.example.json to {COMPANIES} or use `add`")
    skip = screen.skip_urls(cfg)
    for c in cos:
        r = run_company(c, args, cfg, skip)
        print(f"{c['slug']}: {r['mode']} {'ok' if r['ok'] else 'SUSPECT'} fetched {r['fetched']} new {r['new']} closed {r['closed']} "
              f"llm {r['llm_calls']}+{r['llm_cached']} cached, errors {len(r['errors'])}, matches {len(r['matches'])} notified {r['notified']} ({r['ms']} ms)")
        for t in r["matches"]:
            print(f"  match: {t}")
        for e in r["errors"]:
            print(f"  error: {e}")


def cmd_add(args):
    data = jload(COMPANIES, {"companies": []})
    s = slug(args.name)
    for b in args.board:
        ats, _, tok = b.partition(":")
        if ats not in ATS or not tok:
            sys.exit(f"bad --board {b!r}: want <ats>:<token>, ats one of {', '.join(ATS)}")
        n = len(fetch(ats, tok))  # raises on a dead board: better here than on the first scheduled run
        print(f"{b}: {n} postings")
        if not n:
            sys.exit(f"{b} returned no postings; check the token (docs/finding-boards.md) before registering it")
    entry = {"name": args.name, "slug": s, "careers_url": args.careers_url, "boards": args.board,
             "titles_extra": [t.strip() for t in (args.titles or "").split(",") if t.strip()], "added": TODAY, "enabled": True}
    data["companies"] = [c for c in data["companies"] if c["slug"] != s] + [entry]
    jsave(COMPANIES, data)
    print(f"registered {s}; next: python3 -m jobradar run --company {s} (silent baseline)")


def cmd_remove(args):
    data = jload(COMPANIES, {"companies": []})
    for c in data["companies"]:
        if c["slug"] == args.slug:
            c["enabled"] = False
    jsave(COMPANIES, data)
    print(f"{args.slug} disabled")


def cmd_list(_):
    for c in jload(COMPANIES, {"companies": []})["companies"]:
        st = jload(os.path.join(STATE, c["slug"] + ".json"), {"postings": {}})
        openp = [p for p in st["postings"].values() if not p.get("closed")]
        print(f"{c['slug']:<16} {'on ' if c.get('enabled', True) else 'off'} {','.join(c['boards'])}  open {len(openp)}  "
              f"matching {sum(p.get('stage') == 'match' for p in openp)}  last run {st.get('last_run', '-')}")
        for p in openp:
            if p.get("stage") == "match":
                print(f"    {p['t']} ({p.get('loc')}) {p['url']}")


def cmd_report(args):
    """Digest of the last N days of runs. Flags (exit 1) are what a periodic review acts on."""
    cfg = screen.load_config()
    cut = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - args.days * 86400))
    runs = [json.loads(l) for l in open(RUNS)] if os.path.exists(RUNS) else []
    runs = [r for r in runs if r["ts"] >= cut]
    flags = []
    watch_rx = re.compile(cfg.get("report", {}).get("technical_title_regex", "engineer|developer"), re.I)
    print(f"jobradar report, last {args.days} days: {len(runs)} company-runs")
    for c in enabled():
        rs = [r for r in runs if r["company"] == c["slug"]]
        P = jload(os.path.join(STATE, c["slug"] + ".json"), {"postings": {}})["postings"]
        last = rs[-1] if rs else None
        bad = [r for r in rs if not r["ok"]]
        print(f"\n{c['slug']}: {len(rs)} runs, {len(bad)} suspect, llm calls {sum(r['llm_calls'] for r in rs)} "
              f"(+{sum(r['llm_cached'] for r in rs)} cached), new {sum(r['new'] for r in rs)}, notified {sum(r['notified'] for r in rs)}, "
              f"avg {int(sum(r['ms'] for r in rs) / len(rs)) if rs else 0} ms, open postings {sum(not p.get('closed') for p in P.values())}")
        if not last:
            flags.append(f"{c['slug']}: no run in {args.days} days (schedule not firing?)")
        elif time.time() - time.mktime(time.strptime(last["ts"], "%Y-%m-%dT%H:%M:%S")) > 26 * 3600:
            flags.append(f"{c['slug']}: last run {last['ts']}, over 26 h ago (schedule not firing?)")
        if last and not last["ok"]:
            flags.append(f"{c['slug']}: last run suspect: {'; '.join(last['errors'])[:300]}")
        errs = collections.Counter(e.split(":")[0] for r in rs for e in r["errors"])
        if errs:
            print("  errors: " + ", ".join(f"{k} x{v}" for k, v in errs.most_common()))
        pending = [p for p in P.values() if p.get("stage") == "pending" and not p.get("closed")]
        if pending:
            flags.append(f"{c['slug']}: {len(pending)} postings waiting on Jev (TYPESAFE_API_KEY missing or Jev down?)")
        unsent = [p for p in P.values() if p.get("stage") == "match" and not p.get("notified") and not p.get("closed")]
        if unsent:
            flags.append(f"{c['slug']}: {len(unsent)} matches not delivered (notify channel broken?)")
        inc, exc = screen.titles(cfg, c.get("titles_extra", []), c.get("titles_exclude", []))
        miss = sorted({p["t"] for p in P.values() if p.get("stage") == "title" and not p.get("closed") and p["first_seen"] >= cut[:10]
                       and watch_rx.search(p["t"]) and screen.title_ok(screen.role_part(p["t"]), [""], exc)})
        if miss:
            print(f"  title-gate drops that look technical ({len(miss)}), widen titles_extra if one should have been judged: " + "; ".join(miss[:25]))
        stages = collections.Counter((p.get("stage") or "?").split(":")[0] for p in P.values() if not p.get("closed"))
        print("  open postings by verdict: " + ", ".join(f"{k} {v}" for k, v in stages.most_common()))
    print("\nFLAGS" if flags else "\nno flags")
    for f in flags:
        print("  - " + f)
    return 1 if flags else 0


def cmd_scout(args):
    """Rank candidate companies by open roles passing the cheap gates now (no LLM). FILE: one 'Name | careers or board URL' per line."""
    cfg, skip = screen.load_config(), None
    skip = screen.skip_urls(cfg)
    inc, exc = screen.titles(cfg)
    watched = {c["slug"] for c in jload(COMPANIES, {"companies": []})["companies"]}
    cos = [tuple(x.strip() for x in l.split("|", 1)) for l in open(os.path.expanduser(args.file)) if "|" in l and not l.startswith("#")]
    todo = [(n, boards.board_of(u)) for n, u in cos if slug(n) not in watched]
    todo = [(n, b) for n, b in todo if b]

    def one(nb):
        n, (ats, tok) = nb
        try:
            rows = fetch(ats, tok)
        except Exception as e:
            return n, ats, tok, None
        for r in rows:
            r["title"] = re.sub(r"\s+", " ", r["title"]).strip()
        return n, ats, tok, (len(rows), [r["title"] for r in rows if not screen.cheap_gate(r, cfg, inc, exc, skip)])
    with cf.ThreadPoolExecutor(12) as ex:
        out = list(ex.map(one, todo))
    ok = sorted((o for o in out if o[3] and o[3][1]), key=lambda o: -len(o[3][1]))
    lines = [f"# JobRadar candidates, {TODAY}", "", f"From `{args.file}`: {len(cos)} companies, {len(todo)} on a readable board.", "",
             "| Company | Board | Open | Passing | Example titles |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {ats}:{tok} | {c} | {len(h)} | {'; '.join(sorted(set(h))[:3])} |" for n, ats, tok, (c, h) in ok]
    path = os.path.join(ROOT, "data", f"scout-{TODAY}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("\n".join(lines) + "\n")
    print(f"{len(ok)} companies with passing roles, of {len(todo)} readable -> {path}")
