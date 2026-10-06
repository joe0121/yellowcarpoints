"""Upcoming rounds for the other Corvette series (WEC, ELMS, Asian LMS), from the series' own websites
(fiawec.com, europeanlemansseries.com, asianlemansseries.com: same ACO site layout). Each race page carries a
schema.org SportsEvent (name, dates, venue) and its session timetable (name + unix timestamp per session).
Checked once a day; written to series_schedule.json. Schedules only, no timing data.
"""

import html as htmlmod
import json
import logging
import re
import time
from datetime import datetime, timezone

from common import http, now_iso, write

log = logging.getLogger("scraper.series_schedule")
SITES = {"WEC": "https://www.fiawec.com", "ELMS": "https://www.europeanlemansseries.com",
         "ALMS": "https://www.asianlemansseries.com"}
SKIP = re.compile(r"summary|test|prologue", re.I)
EVERY = 86400
_last = [0.0]


def _get(url):
    time.sleep(1)
    r = http.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def parse_race(page):
    """{name, start, end, venue, sessions: [{name, at}]} from one race page, or None."""
    ev = None
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for it in (d if isinstance(d, list) else d.get("@graph", [d])):
            if "Event" in str(it.get("@type")) and it.get("startDate"):
                ev = ev or it
    if not ev:
        return None
    sessions = []
    for m in re.finditer(r'data-timestamp="(\d+)"', page):
        names = re.findall(r'class="fw-bold lh-sm\s*">\s*([^<]+?)\s*</div>', page[max(0, m.start() - 600):m.start()])
        if names:
            at = datetime.fromtimestamp(int(m.group(1)), timezone.utc).isoformat(timespec="minutes")
            name = htmlmod.unescape(names[-1])
            if not any(s["name"] == name and s["at"] == at for s in sessions):
                sessions.append({"name": name, "at": at})
    sessions.sort(key=lambda s: s["at"])
    return {"name": htmlmod.unescape(ev.get("name") or ""), "start": ev["startDate"], "end": ev.get("endDate") or ev["startDate"],
            "venue": (ev.get("location") or {}).get("name") if isinstance(ev.get("location"), dict) else None,
            "sessions": sessions}


def collect(key, base):
    home = _get(f"{base}/en")
    slugs = sorted({m for m in re.findall(r'href="(/en/race/[^"]+)"', home) if not SKIP.search(m)})
    events = []
    for slug in slugs:
        try:
            ev = parse_race(_get(base + slug))
        except Exception:
            log.exception("schedule %s %s", key, slug)
            continue
        if ev:
            events.append({**ev, "url": base + slug})
    events.sort(key=lambda e: e["start"])
    now = datetime.now(timezone.utc)
    upcoming = [e for e in events if datetime.fromisoformat(e["end"]) >= now]
    return {"events": events, "next": upcoming[0] if upcoming else None}


def refresh(force=False):
    if not force and time.time() - _last[0] < EVERY:
        return None
    _last[0] = time.time()
    out = {}
    for key, base in SITES.items():
        try:
            out[key] = collect(key, base)
        except Exception:
            log.exception("schedule %s failed", key)
    if out:
        write("series_schedule.json", {"updated": now_iso(), "series": out})
        log.info("series schedule: %s", ", ".join(f"{k} next {v['next']['name']} {v['next']['start'][:10]} ({len(v['next']['sessions'])} sessions)"
                                                  if v.get("next") else f"{k} none" for k, v in out.items()))
    return out
