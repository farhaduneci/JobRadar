"""The cheap gates: everything a posting must pass before an LLM is asked (or, with the LLM off, before it is a match).
All rules come from config.json; nothing here is specific to one person's search."""
import json, os, re

from .paths import CONFIG, ROOT


def load_config(path=None):
    path = path or CONFIG
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing: copy config.example.json to config.json and edit it")
    return json.load(open(path))


def titles(cfg, extra=(), exclude=()):
    """Include/exclude title lists: the config's, plus a company's own (titles_extra, titles_exclude)."""
    t = cfg["titles"]
    return t["include"] + list(extra), t["exclude"] + list(exclude)


def title_ok(t, inc, exc):
    tl = t.lower()
    if any(re.search(r"\b" + re.escape(x.lower()) + r"\b", tl) for x in exc):
        return False
    return any(x.lower().rstrip(":*") in tl for x in inc)


def role_part(title):
    """The title without its team suffix: 'Senior Backend Engineer, Payments Network' -> 'Senior Backend Engineer'.
    Exclusion words test only this part, so a team name never drops a role. Cut at ', ' only: after ' - ' the title
    often names the stack ('Engineer - Android/Kotlin') and must stay excludable."""
    return title.split(", ", 1)[0]


def loc_ok(row, cfg):
    L = cfg["locations"]
    loc = (row.get("loc") or "").lower()
    if any(re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", loc) for n in L["include"]):
        return True
    if L.get("allow_remote", True) and any(re.search(r"\b" + re.escape(w.lower()) + r"\b", loc) for w in L.get("remote_words", [])):
        return True
    if L.get("exclude_regex") and re.search(L["exclude_regex"], loc, re.I):
        return False
    return not loc or (L.get("allow_remote", True) and (bool(row.get("remote")) or "remote" in loc))


def skip_urls(cfg):
    """URLs to never alert on again (roles already applied to, dismissed, ...): one per line in cfg['skip_urls_file']."""
    p = cfg.get("skip_urls_file")
    p = os.path.join(ROOT, p) if p and not os.path.isabs(p) else p
    return {l.strip() for l in open(p) if l.strip() and not l.startswith("#")} if p and os.path.exists(p) else set()


def cheap_gate(r, cfg, inc, exc, skip):
    """First reason a posting is out before the LLM, else None."""
    if not title_ok(r["title"], inc, []) or not title_ok(role_part(r["title"]), [""], exc):
        return "title"
    if any(re.search(rx, r["title"], re.I) for rx in cfg.get("title_drop", [])):
        return "title policy"
    if not loc_ok(r, cfg):
        return "location"
    if r["url"] in skip:
        return "skipped url"
    desc = (r.get("desc") or "").lower()
    for name, rx in cfg.get("wording_drop", {}).items():
        if re.search(rx, desc):
            return f"wording: {name}"
    return None
