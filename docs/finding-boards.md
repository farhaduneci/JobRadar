# Finding a company's job board

How to get **every** open role off a company's careers page, without a browser. 

## 1. Find the board

Two cheap moves, both in the first pass. Whichever answers first wins.

**Guess the slug.** The lowercase, punctuation-stripped company name hits more often than not.
Confirm from the response body, never from a 200 (verified 2026-09-26: `algolia` on Greenhouse,
`resend` and `supabase` on Ashby all resolved this way).

**Grep the careers page for the ATS.** The page is usually a JS shell whose rendered list is empty,
but its source, script hosts, or an iframe still name the board:

```sh
curl -sL <careers-url> | grep -Eoi \
  '(boards|job-boards)\.(eu\.)?greenhouse\.io/[a-z0-9_-]+|jobs\.lever\.co/[a-z0-9_-]+|jobs\.ashbyhq\.com/[a-z0-9_-]+|apply\.workable\.com/[a-z0-9_-]+|[a-z0-9_-]+\.teamtailor\.com|[a-z0-9_-]+\.jobs\.personio\.(de|com)|jobs\.smartrecruiters\.com/[a-z0-9_-]+|[a-z0-9_-]+\.recruitee\.com|[a-z0-9_-]+\.bamboohr\.com|[a-z0-9_.-]*myworkdayjobs\.com[^"]*' \
  | sort -u
```

The captured path segment is `<board>`.
When the ATS grep comes back empty but the page still mentions the vendor, widen the grep to its
side URLs. Seen on a Greenhouse-hosted careers page: nothing matched the pattern above, but
`grep -Eoi '[a-z0-9_.-]*greenhouse[a-z0-9_./-]*'` surfaced
`s101.recruiting.eu.greenhouse.io/ai_opt_out_request/job_post/<id>/ai_opt_out` on every posting,
naming the ATS. The whole board (131 jobs, JD text in `content`, `departments`, `offices`,
`first_published`, `metadata`) was already inline in `__NEXT_DATA__` at
`props.pageProps.jobs.dataMap.<board>.jobs`, so no API call was needed. Update 2026-10-12: the payload
moved to `props.jobs.dataMap`, and it holds four boards: `<co>en` (the global one, 221 postings
on the API, the page groups multi-location postings into 152), `<co>fr`, `<co>de`, `<co>es`.
All four answer on the plain Greenhouse API (`boards-api.greenhouse.io/v1/boards/<co>en/jobs`);
the bare company token 404s. A careers page's `dataMap` keys are the board tokens.

When the page names no ATS, grep the same HTML for an
embedded payload before reaching for a browser: `application/ld+json` with `"@type":"JobPosting"`,
`__NEXT_DATA__`, or `self.__next_f` chunks often carry the whole list inline.

## 2. Verified endpoints

Probe in order, stop at the first that returns jobs. The three below were re-verified 2026-09-26
against live boards.

| ATS | Endpoint | JD text in the list response |
|---|---|---|
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/<board>` | yes, `descriptionPlain` |
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true` | yes, `content` (HTML entity encoded, decode it) |
| Lever | `https://api.lever.co/v0/postings/<board>?mode=json` | yes, `descriptionPlain`, plus `lists[]` for the requirement bullets |

All three return the whole board in one response. Greenhouse states its own count in `meta.total`,
so compare against it. Ashby carries `isListed`, `isRemote`, `workplaceType`, `publishedAt`,
`jobUrl`, and `applyUrl`; Lever carries `categories` (location, commitment), `createdAt`,
`hostedUrl`, and `applyUrl`.

Workable has two candidate endpoints, both reachable, neither confirmed to return a populated list:
`https://apply.workable.com/api/v1/widget/accounts/<board>` returned `jobs: []` for every live
account tried, and `POST https://apply.workable.com/api/v3/accounts/<board>/jobs` with
`{"query":""}` returned `total: 0`. Treat a zero from either as unproven rather than as an empty
board: cross-check the careers page and fall back to the browser.

## 3. Less common, verify the shape before trusting it

Probe these when the three above miss, and read the response before believing a row: field names
differ by tenant and some return unlisted or archived postings.

- Workable, as above.
- SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/<board>/postings?limit=100`, then
  `.../postings/<id>` for the JD. Pages via `offset`.
- Personio: `https://<board>.jobs.personio.de/xml`, an XML feed with the JD inline.
- Recruitee: `https://<board>.recruitee.com/api/offers/`.
- Workday: POST `https://<host>.wd<n>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs` with
  `{"limit":20,"offset":0,"searchText":""}`. Pages via `offset`; the tenant and site come out of
  the careers URL.
- Teamtailor: no public list API. Fetch `https://<board>.teamtailor.com/jobs` and follow the
  posting links.
  One company on its own Teamtailor domain: `/jobs` and `/jobs.rss` 404, but the root page links every posting . Each posting
  has JobPosting JSON-LD. `fetch("teamtailor", "<host>")` reads root + JSON-LD; board `teamtailor:<host>`.

## 4. Browser fallback

When no endpoint answers, drive the browser: navigate the careers page, snapshot, click the
"load more" or pagination control until the list stops growing, and collect the posting links.
Slower and interactive, so it is the last resort, not the first move. A caller with no browser
reports the board as unreachable instead of switching tools.

## 5. Sanity checks on the list

- Compare the list length against any count the page or API advertises. A short list means
  pagination was missed.
- Drop rows flagged unlisted or internal (Ashby `isListed: false`, Workable `state` other than
  published). They are not applyable.
- Verify a posting URL before trusting the company and title attached to it. Aggregator and
  scanner metadata has pointed at the wrong company before.

## 6. Field notes

- 2026-09-29, Octopus Energy Group and Kraken Technologies: one company, two boards. The Lever slug
  came straight off the section 1 grep of `octopusenergy.com/careers` (`jobs.lever.co/octoenergy`,
  170 postings, `lists[]` carries the requirement bullets). Kraken's own `kraken.tech/careers` is a
  Next.js 404 shell that names no ATS; the board URL (`jobs.ashbyhq.com/krakentech`) only appears in
  the HTML of the sibling page `kraken.tech/working-at-kraken`. Lesson: when a careers URL 404s,
  grep the careers-adjacent pages linked from the homepage before declaring the board unreachable.
- 2026-10-03, boards resolved in one batch scan:
  - Ashby slugs are not always the bare name: `happyrobot.ai` (dot kept, found by grepping
    `happyrobot.ai/careers`) and `prosper-ai` (hyphen). "Prosper" alone on Lever is the US lender,
    a different company.
  - Glovo (`careers.glovoapp.com`, WordPress): POST `wp-admin/admin-ajax.php` with
    `action=glovo_filter_jobs&page=N&search=`; `data.total` is the count, `data.html` holds the
    `/job/<slug>-in-<city>-jid-<id>/` links. JD only on the posting page.
  - Murphy AI (`careers.getmurphy.ai/jobs`, Teamtailor): the list pages via `?page=N`; page 1 alone
    showed 20 of 36.
  - Factorial (`careers.factorialhr.com`, its own ATS): every posting link
    (`/job_posting/<slug>-<id>`) is in the first page's HTML, no pagination. The same title repeats
    with a different id per city.
  - Capgemini NL: `GET https://cg-jobstream-api.azurewebsites.net/api/job-search?country_code=nl-nl&size=100&page=N`
    returns `count` plus full HTML `description`, no auth.
  - Spilberg (`spilberg.com/nl/vacatures/`): a staffing agency; the ~10 postings are `-BBBH<id>`
    links inline in the page HTML.
- Ashby example: the page names no ATS in plain text; only `ashby_jid=` query params in its links give it away. Guessing the bare slug also works, and the posting count should match the page's "N open positions".

### Big-tech boards without a public ATS (verified 2026-10-23; fetchers in RadarKit `radarkit/boards/bigtech.py`, token = location or `*`)

- **Apple** `apple:<location-slug>`: `jobs.apple.com/en-gb/search?location=<slug>&page=N` embeds the results as `JSON.parse("...")` in the HTML (the `/api/v1/search` POST returns empty without the SPA's session). Slug as in the search URL, `<country>-<CODE>` (check the code: a wrong one silently returns another country). Retail roles are titled `TR-Expert`, `TR-Specialist`, `TR-Technical Specialist`; set `no_llm` and `titles_extra` on the company entry.
- **Google** `google:<city>`: `google.com/about/careers/applications/jobs/results/?location=<city>&page=N`, 20 a page, results in `AF_initDataCallback` block `ds:1`. Titles carry the languages, e.g. "(English, German)".
- **Microsoft** `microsoft:<city>`: `apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&location=<city>&start=N`, JD via `/api/pcsx/position_details?position_id=<id>`. Throttles (429) after bursts; retry later.
- **Greenhouse `location.name`** can be only Hybrid/In-Office/Distributed on some boards; the real places are in metadata "Job Posting Location" (read by `gh_loc`).

## 7. Upkeep

An endpoint that worked, an ATS not listed here, a slug pattern that broke: add it to this file in
the same pass. 
