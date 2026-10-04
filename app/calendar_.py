"""The season calendar: every WeatherTech round's dates, venue and race length, from IMSA's season page
(imsa.com/weathertech/<year>-schedule/). Used for the countdown to the next race when no weekend schedule
is up yet (IMSA publishes session times about two weeks before each event). Checked daily; this season's
page and next season's, so the countdown runs across the winter. Written to calendar.json.
"""

import html as htmlmod
import logging
import re
from datetime import date, datetime, timezone

from common import http, now_iso, write

log = logging.getLogger("scraper.calendar")
URL = "https://www.imsa.com/weathertech/{year}-schedule/"
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse(page, year):
    """[{name, start, end, venue, duration}] from the season page's event list (tests like the Roar left out)."""
    text = htmlmod.unescape(re.sub(r"<[^>]+>", "\n", page))
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    out = []
    for i, l in enumerate(lines):
        m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}) - ([A-Z][a-z]{2}) (\d{1,2})", l)
        if not m or i < 1 or i + 2 >= len(lines) or m.group(1) not in MONTHS:
            continue
        name, venue = lines[i - 1], lines[i + 1]
        name = re.sub(r"\b([A-Z])([A-Z]{3,})\b", lambda x: x.group(1) + x.group(2).lower(), name)   # "At DAYTONA" -> "At Daytona"
        dur = next((x.split(":", 1)[1].strip() for x in lines[i + 1:i + 4] if x.upper().startswith("DURATION")), "")
        if re.search(r"roar|test", name, re.I) or dur.upper() in ("N/A", ""):
            continue
        start = date(year, MONTHS[m.group(1)], int(m.group(2)))
        end = date(year, MONTHS[m.group(3)], int(m.group(4)))
        out.append({"name": name, "start": start.isoformat(), "end": end.isoformat(), "venue": venue, "duration": dur})
    return out


def refresh():
    """This season and next; keeps whatever parses. Returns the list written."""
    year = datetime.now(timezone.utc).year
    events = []
    for y in (year, year + 1):
        try:
            r = http.get(URL.format(year=y), timeout=30)
            if r.status_code == 200:
                events += parse(r.text, y)
        except Exception:
            log.exception("calendar %s", y)
    if events:
        events.sort(key=lambda e: e["start"])
        write("calendar.json", {"updated": now_iso(), "events": events})
        log.info("calendar: %d rounds, next %s", len(events),
                 next((e["name"] + " " + e["start"] for e in events if e["end"] >= date.today().isoformat()), "none"))
    return events
