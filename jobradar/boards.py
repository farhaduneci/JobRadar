"""Job-board fetchers: read public ATS endpoints, return canonical posting rows.

Row: {id, title, url, loc, date, desc, remote?, org?}. `fetch(ats, token)` is the only entry point. A new ATS is one
`f_<name>(token)` function plus a FETCHERS entry (and, if its URLs are recognisable, a branch in `board_of`).
"""
import concurrent.futures as cf, html, json, re, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
TIMEOUT = 12


def is_dead(e):
    """A board that is gone for good (404/410, DNS failure) rather than slow."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in (404, 410)
    return "nodename nor servname" in str(e) or "Name or service not known" in str(e)


def board_of(url):
    """(ats, board token) for a URL on a supported ATS, else None."""
    u = urlparse(url if "://" in url else "https://" + url)
    h, p = u.netloc.lower(), [x for x in u.path.split("/") if x]
    if "greenhouse.io" in h:
        if "embed" in p or not p:
            m = re.search(r"for=([\w-]+)", u.query)
            return ("greenhouse", m.group(1)) if m else None
        return ("greenhouse", p[0]) if p[0] not in ("v1", "boards") else None
    if "ashbyhq.com" in h and p:
        return ("ashby", p[0])
    if h.endswith("lever.co") and p and h.split(".")[0] in ("jobs", "api"):
        return ("lever", p[0])
    if h.endswith("recruitee.com") and h.split(".")[0] not in ("www", "app"):
        return ("recruitee", h.split(".")[0])
    m = re.match(r"([\w-]+)\.jobs\.personio\.(de|com)$", h)
    if m:
        return ("personio", m.group(1) + "." + m.group(2))
    if h.endswith("smartrecruiters.com") and h.split(".")[0] in ("jobs", "careers") and p:
        return ("smartrecruiters", p[0])
    if h == "join.com" and len(p) >= 2 and p[0] == "companies":
        return ("join", p[1])
    if h == "apply.workable.com" and p and p[0] not in ("j", "api"):
        return ("workable", p[0])
    if h.endswith(".teamtailor.com") and h.split(".")[0] not in ("www", "app", "career"):
        return ("teamtailor", h)
    if re.match(r"^/jobs/\d{6,}-[a-z0-9-]+/?$", u.path.lower()) and h and not h.endswith(("wellfound.com", "teamtailor.com")):
        return ("teamtailor", h)  # employer's own domain on Teamtailor (careers.<co>.com/jobs/8493087-title)
    return None



def get(url, raw=False, data=None, timeout=None):
    """GET (or POST with data). One retry on a timeout, reset or 5xx; a 404 or DNS failure is final."""
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(url, headers=UA, data=data)
            with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
                body = r.read().decode("utf-8", "replace")
            return body if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            if attempt or e.code < 500:
                raise
        except (TimeoutError, ConnectionError, urllib.error.URLError) as e:
            if attempt or is_dead(e):
                raise


def text(h):
    h = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", html.unescape(h or ""), flags=re.I)
    return re.sub(r"\n\s*\n+", "\n\n", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def iso(v):
    if isinstance(v, (int, float)):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(v / 1000 if v > 1e11 else v))
    return (v or "")[:19] or None


# --- one fetcher per ATS: rows {id,title,url,loc,date,desc,remote?,org?}; a row may carry `_detail`, a callable
# returning {loc?, desc?, date?} that is only called for rows that pass the title and age cuts (one request per role).

def lazy(fn, *a):
    """A description built only if the role survives the cuts (HTML stripping dominates the scan otherwise)."""
    return lambda: fn(*a)


def lever_desc(j):
    lists = "\n\n".join(l.get("text", "") + "\n" + text(l.get("content")) for l in j.get("lists") or [])
    return "\n\n".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""])


def gh_loc(j):
    """location.name, plus the "Job Posting Location" metadata some boards use for the real place (location.name alone can be only Hybrid/In-Office)."""
    extra = [v for m in j.get("metadata") or [] if "posting location" in (m.get("name") or "").lower() for v in (m["value"] if isinstance(m.get("value"), list) else [m.get("value")]) if v]
    return "; ".join(filter(None, [(j.get("location") or {}).get("name", "")] + extra))


def f_greenhouse(tok):
    """The list without content is a fraction of the size; each kept role's description is one more request."""
    return [{"id": f"gh:{tok}:{j['id']}", "title": j["title"], "url": j["absolute_url"],
             "loc": gh_loc(j), "date": iso(j.get("first_published") or j.get("updated_at")),
             "desc": None, "org": j.get("company_name"),
             "_detail": (lambda i=j["id"]: {"desc": text(get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{i}").get("content"))})}
            for j in get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs").get("jobs", [])]


def f_ashby(tok):
    rows = []
    for j in get(f"https://api.ashbyhq.com/posting-api/job-board/{tok}").get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        rows.append({"id": f"ab:{tok}:{j['id']}", "title": j["title"], "url": j.get("jobUrl") or j.get("applyUrl"),
                     "loc": "; ".join(locs), "remote": j.get("isRemote") or j.get("workplaceType") == "Remote",
                     "date": iso(j.get("publishedAt")), "desc": j.get("descriptionPlain") or lazy(text, j.get("descriptionHtml"))})
    return rows


def f_lever(tok):
    try:
        js = get(f"https://api.lever.co/v0/postings/{tok}?mode=json")
    except Exception:
        js = get(f"https://api.eu.lever.co/v0/postings/{tok}?mode=json")
    rows = []
    for j in js:
        c = j.get("categories") or {}
        rows.append({"id": f"lv:{tok}:{j['id']}", "title": j["text"], "url": j["hostedUrl"],
                     "loc": "; ".join(c.get("allLocations") or [c.get("location") or ""]), "remote": j.get("workplaceType") == "remote",
                     "date": iso(j.get("createdAt")), "desc": lazy(lever_desc, j)})
    return rows


def f_recruitee(tok):
    return [{"id": f"rc:{tok}:{j['id']}", "title": j["title"], "url": j["careers_url"],
             "loc": "; ".join(filter(None, [j.get("location"), j.get("country")])), "remote": j.get("remote"),
             "date": iso(j.get("published_at") or j.get("created_at")),
             "desc": lazy(text, (j.get("description") or "") + "\n" + (j.get("requirements") or "")), "org": j.get("company_name")}
            for j in get(f"https://{tok}.recruitee.com/api/offers/").get("offers", [])]


def f_personio(tok):
    root = ET.fromstring(get(f"https://{tok}/xml?language=en", raw=True))
    rows = []
    for p in root.findall("position"):
        g = lambda k: (p.findtext(k) or "").strip()
        desc = lazy(lambda p=p: "\n\n".join((d.findtext("name") or "") + "\n" + text(d.findtext("value")) for d in p.findall("jobDescriptions/jobDescription")))
        rows.append({"id": f"ps:{tok.split('.')[0]}:{g('id')}", "title": g("name"), "url": f"https://{tok}/job/{g('id')}",
                     "loc": "; ".join(filter(None, [g("office")] + [o.text or "" for o in p.findall("additionalOffices/office")])),
                     "date": iso(g("createdAt")), "desc": desc, "org": g("subcompany") or None})
    return rows


def f_workable(tok):
    """The account's public widget feed (apply.workable.com/<account>): every open role with its description."""
    rows = []
    for j in get(f"https://apply.workable.com/api/v1/widget/accounts/{tok}?details=true").get("jobs", []):
        locs = j.get("locations") or [{"city": j.get("city"), "country": j.get("country")}]
        rows.append({"id": f"wk:{tok}:{j['shortcode']}", "title": j["title"], "url": j.get("url") or j.get("shortlink"),
                     "loc": "; ".join(", ".join(filter(None, [l.get("city"), l.get("country")])) for l in locs),
                     "remote": str(j.get("telecommuting")).lower() == "true", "date": iso(j.get("published_on") or j.get("created_at")),
                     "desc": lazy(text, j.get("description"))})
    return rows


def f_smartrecruiters(tok, cutoff=None):
    """Public postings list (newest first, released after the cutoff); the description is a second request per role."""
    rows, off = [], 0
    after = f"&releasedAfter={cutoff}T00:00:00.000Z" if cutoff else ""
    while off < 500:
        d = get(f"https://api.smartrecruiters.com/v1/companies/{tok}/postings?limit=100&offset={off}{after}")
        for j in d.get("content", []):
            l = j.get("location") or {}
            rows.append({"id": f"sr:{tok}:{j['id']}", "title": j["name"], "url": f"https://jobs.smartrecruiters.com/{tok}/{j['id']}",
                         "loc": l.get("fullLocation") or ", ".join(filter(None, [l.get("city"), l.get("country")])),
                         "remote": bool(l.get("remote")), "date": iso(j.get("releasedDate")), "org": (j.get("company") or {}).get("name"),
                         "_detail": (lambda i=j["id"]: sr_detail(tok, i))})
        off += 100
        if off >= d.get("totalFound", 0):
            break
    return rows


def sr_detail(tok, pid):
    d = get(f"https://api.smartrecruiters.com/v1/companies/{tok}/postings/{pid}")
    secs = (d.get("jobAd") or {}).get("sections") or {}
    out = {"desc": "\n\n".join(f"{s.get('title', '')}\n{text(s.get('text'))}" for s in secs.values() if s.get("text"))}
    if d.get("postingUrl"):
        out["url"] = d["postingUrl"].split("?")[0]
    return out


def f_join(tok):
    """join.com/companies/<token>: the list is in the page's __NEXT_DATA__; the description is on each job page's JSON-LD."""
    h = get(f"https://join.com/companies/{tok}", raw=True)
    m = re.search(r"__NEXT_DATA__[^>]*>(.*?)</script>", h, re.S)
    items = (((json.loads(m.group(1))["props"]["pageProps"].get("initialState") or {}).get("jobs") or {}).get("items")) if m else []
    rows = []
    for j in items or []:
        city = j.get("city") or {}
        loc = ", ".join(filter(None, [city.get("cityName"), city.get("countryName") or (j.get("country") or {}).get("iso3166")]))
        rows.append({"id": f"jn:{tok}:{j['id']}", "title": j["title"], "url": f"https://join.com/companies/{tok}/{j['idParam']}",
                     "loc": loc, "remote": bool(j.get("remoteType")) or str(j.get("workplaceType")).upper() == "REMOTE",
                     "date": iso(j.get("createdAt")), "org": None,
                     "_detail": (lambda u=f"https://join.com/companies/{tok}/{j['idParam']}": join_detail(u))})
    return rows


def join_detail(url):
    h = get(url, raw=True)
    m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S)
    j = json.loads(m.group(1)) if m else {}
    return {"desc": text(j.get("description")), "org": (j.get("hiringOrganization") or {}).get("name")}


def f_teamtailor(host):
    """/jobs.rss lists every posting with description and location; sites without it (some) link postings on the root page."""
    try:
        body = get(f"https://{host}/jobs.rss", raw=True)
        if body.lstrip().startswith("<?xml"):
            return teamtailor_rss(host, body)
    except Exception:
        pass
    return teamtailor_rows(host, get(f"https://{host}/", raw=True), lambda u: get(u, raw=True))


def teamtailor_rss(host, body):
    ns = {"tt": "https://teamtailor.com/locations"}
    root = ET.fromstring(body)
    org = root.findtext("channel/title")
    rows = []
    for it in root.findall("channel/item"):
        link = (it.findtext("link") or "").strip()
        m = re.search(r"/jobs/(\d+)-", link)
        if not m:
            continue
        locs = ["; ".join(filter(None, [l.findtext("tt:city", "", ns), l.findtext("tt:country", "", ns)])) for l in it.findall("tt:locations/tt:location", ns)]
        date = None
        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(it.findtext("pubDate")).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
        rows.append({"id": f"tt:{host.split('.')[0]}:{m.group(1)}", "title": html.unescape((it.findtext("title") or "").strip()), "url": link,
                     "loc": "; ".join(filter(None, locs)), "remote": it.findtext("remoteStatus") in ("fully", "remote"),
                     "date": date, "desc": lazy(text, it.findtext("description")), "org": org})
    return rows


def teamtailor_rows(host, root_html, page):
    """Teamtailor with no feed: the root page links every posting, each posting carries JobPosting JSON-LD (read only for roles whose title passes)."""
    rows = []
    for jid, slug in dict.fromkeys(re.findall(r'href="https?://[^"/]+/jobs/(\d+)-([^"/?#]+)"', root_html)):
        url = f"https://{host}/jobs/{jid}-{slug}"
        rows.append({"id": f"tt:{host.split('.')[0]}:{jid}", "title": slug.replace("-", " "), "url": url, "loc": "", "date": None,
                     "desc": "", "_detail": (lambda u=url, s=slug: tt_detail(u, s, page))})
    return rows


def tt_detail(url, slug, page):
    m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page(url), re.S)
    j = json.loads(m.group(1)) if m else {}
    locs = [(l.get("address") or {}).get("addressLocality") or "" for l in j.get("jobLocation") or []]
    return {"title": html.unescape(j.get("title") or slug.replace("-", " ")), "loc": "; ".join(filter(None, locs)),
            "date": iso(j.get("datePosted")), "desc": text(j.get("description")), "org": (j.get("hiringOrganization") or {}).get("name")}


def ssr_json(page, pat):
    """The JSON a server-rendered careers page embeds as a JS string literal: first literal whose payload holds `pat`."""
    for m in re.finditer(r'JSON\.parse\("((?:[^"\\]|\\.)*)"\)', page):
        raw = json.loads('"' + m.group(1) + '"')
        if pat in raw:
            return json.loads(raw)


def find_key(o, key):
    if isinstance(o, dict):
        if key in o:
            return o
        for v in o.values():
            r = find_key(v, key)
            if r:
                return r


def apple_rows(res):
    return [{"id": f"apple:{j['positionId']}", "title": j["postingTitle"], "loc": "; ".join(l.get("name", "") for l in j.get("locations") or []),
             "url": f"https://jobs.apple.com/en-gb/details/{j['positionId']}/{j.get('transformedPostingTitle', '')}",
             "date": (j.get("postDateInGMT") or "")[:19] or None, "desc": j.get("jobSummary") or "", "org": "Apple"} for j in res]


def f_apple(loc):
    """jobs.apple.com search, location slug as in its URL (`<country>-<CODE>`): the page embeds each result page as JSON. Token: the slug."""
    rows, page = [], 1
    while True:
        res = find_key(ssr_json(get(f"https://jobs.apple.com/en-gb/search?location={loc}&page={page}", raw=True), "searchResults") or {}, "searchResults")
        if not res or not res["searchResults"]:
            break
        rows += apple_rows(res["searchResults"])
        if len(rows) >= res.get("totalRecords", 0):
            break
        page += 1
    return rows


def google_rows(jobs):
    return [{"id": f"google:{j[0]}", "title": j[1], "url": f"https://www.google.com/about/careers/applications/jobs/results/{j[0]}",
             "loc": "; ".join(l[0] for l in j[9] or []), "date": iso((j[12] or [None])[0]),
             "desc": "\n\n".join(text(x[1]) for x in (j[3], j[4], j[10]) if x and x[1]), "org": j[7] or "Google"} for j in jobs]


def f_google(loc):
    """google.com/about/careers search: results ride in the page's AF_initDataCallback ds:1 block, 20 a page. Token: the location, e.g. Berlin."""
    rows, page = [], 1
    while True:
        pg = get(f"https://www.google.com/about/careers/applications/jobs/results/?location={urllib.parse.quote(loc)}&page={page}", raw=True)
        m = next((m for m in re.finditer(r"AF_initDataCallback\(\{key: 'ds:1', hash: '[^']*', data:(.*?), sideChannel", pg, re.S)), None)
        data = json.loads(m.group(1)) if m else None
        if not data or not data[0]:
            break
        rows += google_rows(data[0])
        if len(rows) >= (data[2] or 0):
            break
        page += 1
    return rows


MS = "https://apply.careers.microsoft.com"


def microsoft_rows(positions):
    return [{"id": f"ms:{p['id']}", "title": p["name"], "url": MS + p["positionUrl"], "loc": "; ".join(p.get("locations") or []),
             "remote": p.get("workLocationOption") == "remote", "date": iso(p.get("postedTs")), "org": "Microsoft",
             "desc": lazy(lambda i=p["id"]: text(get(f"{MS}/api/pcsx/position_details?position_id={i}&domain=microsoft.com&hl=en")["data"].get("jobDescription")))}
            for p in positions]


def f_microsoft(loc):
    """apply.careers.microsoft.com (PCSX) search by location, newest first, JD per role fetched lazily. Token: the location, e.g. Berlin."""
    rows, start = [], 0
    while True:
        d = get(f"{MS}/api/pcsx/search?domain=microsoft.com&query=&location={urllib.parse.quote(loc)}&start={start}&sort_by=timestamp")["data"]
        rows += microsoft_rows(d["positions"])
        start += len(d["positions"])
        if not d["positions"] or start >= (d.get("count") or 0):
            break
    return rows


FETCHERS = {"greenhouse": f_greenhouse, "ashby": f_ashby, "lever": f_lever, "recruitee": f_recruitee, "personio": f_personio,
            "workable": f_workable, "smartrecruiters": f_smartrecruiters, "join": f_join, "teamtailor": f_teamtailor,
            "apple": f_apple, "google": f_google, "microsoft": f_microsoft}


def fetch(ats, tok, cutoff=None, eager=True):
    """Rows for one board. eager (default): descriptions and detail pages are resolved here, one request per role where the
    list lacks them. eager=False leaves lazy `desc` callables and `_detail` hooks for a caller that cuts first."""
    rows = FETCHERS[ats](tok, cutoff) if ats == "smartrecruiters" else FETCHERS[ats](tok)
    if eager:
        def resolve(r):
            if r.get("_detail"):
                try:
                    r.update({k: v for k, v in r["_detail"]().items() if v})
                except Exception:
                    pass
            r.pop("_detail", None)
            if callable(r.get("desc")):
                r["desc"] = r["desc"]()
        with cf.ThreadPoolExecutor(8) as ex:  # one request per role on most ATSs: serial is minutes on a 400-role board
            list(ex.map(resolve, rows))
    return rows
