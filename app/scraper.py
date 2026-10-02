"""Scrape IMSA WeatherTech championship points from Al Kamel timing and write standings.json.

The standings only exist as a PDF ("00_Championship Points - Official.pdf"), so the
parser works on individual characters and their x positions: column centres come from
the rotated "Qualifying"/"Race" header labels, and numbers are bucketed into the
nearest column. Long team names wrap and get drawn over the numbers, which is why we
read characters rather than words.
"""

import hashlib
import io
import json
import logging
import logging.handlers
import os
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import pdfplumber

import bop
import watch
import history
import live
import racecontrol
import sectors
import status
from common import CAR_CLASS, CARS, CLASSES, GROUPS, DATA_DIR, LIVE_CLASSES, RACE_CARS, http, now_iso, read, write

BASE = "https://imsa.results.alkamelcloud.com/"
SERIES = "IMSA WeatherTech SportsCar Championship"
POINTS_RE = re.compile(
    r'href="([^"]*' + re.escape(quote(SERIES)) + r'/00_Championship%20Points%20-%20(Official|Provisional)\.pdf)"'
)

INTERVAL = int(os.environ.get("INTERVAL_MINUTES", "30")) * 60
MAX_BACKOFF = 900

log = logging.getLogger("scraper")


# --- finding the latest points PDF -------------------------------------------------

def _options(html, select_name):
    m = re.search(rf'<select name="{select_name}".*?</select>', html, re.S)
    if not m:
        return [], None
    opts = re.findall(r'<option Value="([^"]+)"( SELECTED)?', m.group(0))
    return [v for v, _ in opts], next((v for v, s in opts if s), None)


def _page(season=None, event=None):
    params = {}
    if season:
        params["season"] = season
    if event:
        params["evvent"] = event
    r = http.get(BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.text


def find_latest_points():
    """Walk events newest-first and return the most recent championship points PDF."""
    index = _page()
    seasons, current = _options(index, "season")
    # Early in a new season there are no points yet; fall back to the previous one.
    for season in [current] + [s for s in reversed(seasons) if s < current][:1]:
        events, _ = _options(_page(season), "evvent")
        for event in reversed(events):
            found = dict((kind, href) for href, kind in POINTS_RE.findall(_page(season, event)))
            href = found.get("Official") or found.get("Provisional")
            if href:
                return {
                    "season": season.split("_", 1)[1],
                    "event": event.split("_", 1)[1],
                    "status": "Official" if "Official" in found else "Provisional",
                    "url": BASE + href,
                }
    return None


# --- PDF parsing -------------------------------------------------------------------

def _tokens(chars, gap=2.5):
    """Join characters into tokens, splitting on horizontal gaps."""
    out = []
    for c in sorted(chars, key=lambda c: c["x0"]):
        if out and c["x0"] - out[-1]["x1"] < gap:
            out[-1]["text"] += c["text"]
            out[-1]["x1"] = c["x1"]
        else:
            out.append({"text": c["text"], "x0": c["x0"], "x1": c["x1"]})
    for t in out:
        t["xc"] = (t["x0"] + t["x1"]) / 2
    return out


def _parse_table(page):
    """Return (events, rows) for one standings page. rows carry raw per-column tokens."""
    words = page.extract_words()
    # Rotated headers come out reversed: "gniyfilauQ" / "ecaR".
    quals = sorted((w["x0"] + w["x1"]) / 2 for w in words if w["text"] == "gniyfilauQ")
    races = sorted((w["x0"] + w["x1"]) / 2 for w in words if w["text"] == "ecaR")
    total_hdr = next(w for w in words if w["text"] == "Total")
    header_top = min(w["top"] for w in words if w["text"] == "gniyfilauQ")

    # Event names sit in the band above the rotated labels; assign each word to the
    # nearest qualifying/race column pair.
    centres = [(q + r) / 2 for q, r in zip(quals, races)]
    names = [[] for _ in centres]
    band = [w for w in words if header_top - 30 < w["top"] < header_top - 2 and w["x0"] > total_hdr["x1"]]
    for w in sorted(band, key=lambda w: (w["top"], w["x0"])):
        i = min(range(len(centres)), key=lambda i: abs(centres[i] - (w["x0"] + w["x1"]) / 2))
        names[i].append(w["text"])
    events = [" ".join(n) for n in names]

    cols = [("total", (total_hdr["x0"] + total_hdr["x1"]) / 2)]
    for i, (q, r) in enumerate(zip(quals, races)):
        cols += [(("q", i), q), (("r", i), r)]
    num_left = total_hdr["x0"] - 6

    body = [c for c in page.chars if c["top"] > header_top + 20 and c["text"].strip()]
    starts = []
    for y in sorted(c["top"] for c in body if c["x1"] < 50 and c["text"].isdigit()):
        if not starts or y - starts[-1] > 4:
            starts.append(y)
    rows = []
    for n, top in enumerate(starts):
        bottom = starts[n + 1] - 1 if n + 1 < len(starts) else top + 14
        rc = [c for c in body if top - 2 <= c["top"] < bottom]
        # Digits in the numbers area are points; "/" (DNP) and "*" (DNS) only count
        # when they stand alone, since wrapped names like "Acura/Curb" contain them.
        marks = set()
        for t in _tokens([c for c in rc if c["x0"] >= num_left and not c["text"].isdigit()]):
            if t["text"] in "/*":
                marks.add(round(t["x0"], 1))
        letters = [c for c in rc if c["text"].isalpha()]
        in_word = lambda d: any(abs(l["top"] - d["top"]) < 3 and (abs(l["x1"] - d["x0"]) < 0.05 or abs(d["x1"] - l["x0"]) < 0.05)
                                for l in letters)
        is_num = lambda c: c["x0"] >= num_left and (
            (c["text"].isdigit() and not in_word(c)) or round(c["x0"], 1) in marks)
        cells = {}
        for t in _tokens([c for c in rc if is_num(c)]):
            cells[min(cols, key=lambda kc: abs(kc[1] - t["xc"]))[0]] = t["text"]
        if "total" not in cells:
            continue
        # Text left of the numbers: pos, then (teams) car number, then the name. A
        # wrapped name continues on a second line, drawn into the numbers area.
        text = [c for c in rc if not is_num(c)]
        first = _tokens([c for c in text if c["top"] < top + 4], gap=1.5)
        wrap = _tokens([c for c in text if c["top"] >= top + 4], gap=1.5)
        rows.append({"left": [t["text"] for t in first + wrap]})
        rows[-1]["cells"] = cells
    return events, rows


def _num(v):
    return int(v) if v and v.isdigit() else None


def parse_points(pdf_bytes, cls):
    teams, drivers, events = [], [], None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            head = (page.extract_text() or "").split("\n", 1)[0]
            m = re.search(rf"{re.escape(SERIES)} (\S+) (Teams|Drivers)$", head)
            if not m or m.group(1) != cls:
                continue
            ev, rows = _parse_table(page)
            events = events or ev
            for row in rows:
                left = row["left"]
                rounds = []
                for i in range(len(ev)):
                    q, r = row["cells"].get(("q", i)), row["cells"].get(("r", i))
                    rounds.append(None if q is None and r is None else {
                        "q": _num(q), "r": _num(r), "dnp": "/" in (q or "") + (r or ""),
                        "dns": "*" in (q or "") + (r or "")})
                entry = {"pos": int(left[0]), "points": int(row["cells"]["total"]), "rounds": rounds}
                if m.group(2) == "Teams":
                    entry.update(car=left[1], team=" ".join(left[2:]))
                    teams.append(entry)
                else:
                    entry["name"] = " ".join(left[1:])
                    drivers.append(entry)
    return events or [], teams, drivers


# --- summary -----------------------------------------------------------------------

def build(cls, events, teams, drivers):
    def state(i):
        cells = [t["rounds"][i] for t in teams]
        if any(c and (c["q"] is not None or c["r"] is not None) for c in cells):
            return "done"
        return "skipped" if any(cells) else "upcoming"

    states = [state(i) for i in range(len(events))]
    max_q = max((c["q"] or 0 for t in teams for c in t["rounds"] if c), default=0)
    max_r = max((c["r"] or 0 for t in teams for c in t["rounds"] if c), default=0)
    remaining = states.count("upcoming")
    max_left = remaining * (max_q + max_r)

    teams.sort(key=lambda t: t["pos"])
    leader = teams[0]["points"] if teams else 0
    for t in teams:
        key = [r and (r["q"], r["r"]) for r in t["rounds"]]
        t["drivers"] = [d["name"] for d in drivers
                        if d["points"] == t["points"] and [r and (r["q"], r["r"]) for r in d["rounds"]] == key]
        t["gap"] = leader - t["points"]
        t["alive"] = t["gap"] <= max_left
        t["tracked"] = CAR_CLASS.get(t["car"]) == cls

    return {
        "events": [{"name": n, "state": s} for n, s in zip(events, states)],
        "rounds_remaining": remaining,
        "max_points_per_round": max_q + max_r,
        "max_points_remaining": max_left,
        "standings": teams,
    }


# --- race history ------------------------------------------------------------------

def refresh_entries(season, event):
    """Team, car and driver line-up per tracked-class car, from the latest session's results."""
    html = _page(season, event)
    files = sorted(set(unquote(h) for h in re.findall(r'href="([^"]+)"', html)
                       if re.search(rf"_{re.escape(quote(SERIES))}/\d{{12}}_[^/]+/03_Results_[^/]*\.JSON$", h)))
    if not files:
        return
    latest = max(files, key=lambda f: re.search(r"/(\d{12})_", f).group(1))
    results = json.loads(http.get(BASE + quote(latest), timeout=60).content.decode("utf-8-sig"))
    cars = {r["number"]: {"class": r["class"], "team": r["team"], "vehicle": r["vehicle"],
                          "drivers": [f'{d["firstname"]} {d["surname"]}' for d in r.get("drivers", [])],
                          "ratings": {f'{d["firstname"]} {d["surname"]}': d.get("license") for d in r.get("drivers", [])}}
            for r in results["classification"] if r["class"] in LIVE_CLASSES}
    write("entries.json", {"updated": now_iso(), "event": event.split("_", 1)[1],
                           "session": results["session"].get("session_name"), "cars": cars})


_event = []   # [season, event] of the latest event, set by refresh_history()
SECTORS_LIVE, SECTORS_IDLE = 300, 1800


def refresh_sectors():
    """Sector times and the race control log, from one download of the event's results page."""
    if not _event:
        return
    html = _page(_event[0], _event[1])
    if sectors.refresh(BASE, lambda *_: html, _event[0], _event[1], SERIES):
        status.mark("sectors", session=(read("sectors.json") or {}).get("session"))
    else:
        status.mark("sectors_check")
    try:
        if racecontrol.refresh(BASE, html, SERIES):
            status.mark("racecontrol", session=(read("racecontrol.json") or {}).get("label"))
    except Exception:
        log.exception("race control log failed")


def refresh_history():
    """Season race-by-race summaries for the tracked cars, and the pit-window baseline."""
    races = history.update(http, BASE, _page, _options, DATA_DIR, SERIES, CAR_CLASS, CLASSES)
    seasons, current = _options(_page(), "season")
    cars = {c: [] for c in CARS}
    for event, summary in races.items():
        for car, row in summary["cars"].items():
            cars[car].append({"round": event.split("_", 1)[1], "date": summary["date"], **row})
    write("history.json", {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "season": current.split("_", 1)[1], "cars": cars})

    # Baseline for the latest event (the one in progress or next): last season's race at the same track.
    events, _ = _options(_page(current), "evvent")
    track = events[-1].split("_", 1)[1] if events else None
    if events:
        _event[:] = [current, events[-1]]
    if events:
        try:
            refresh_entries(current, events[-1])
        except Exception:
            log.exception("entry list failed")
    prev = [s for s in seasons if s < current]
    old_base = read("baseline.json") or {}
    if not track or not prev or (old_base.get("event") == track and "pit_lane" in old_base):
        return
    prev_events, _ = _options(_page(prev[-1]), "evvent")
    match = [e for e in prev_events if e.split("_", 1)[1] == track]
    if not match:
        return
    old = history.update(http, BASE, _page, _options, DATA_DIR, SERIES, CAR_CLASS, CLASSES,
                         season=prev[-1], only=match)
    if match[0] in old:
        stints, pits = old[match[0]]["class_stints"], old[match[0]].get("class_pit_secs", {})
        write("baseline.json", {"event": track, "source": f'{prev[-1].split("_", 1)[1]} {track}',
                                "classes": {c: history.stint_model(stints.get(c, [])) for c in CLASSES},
                                "pit_lane": {c: statistics.median(pits[c]) for c in CLASSES if pits.get(c)}})
        log.info("baseline: %s %s", prev[-1], track)


def run_once(last_hash=None):
    meta = find_latest_points()
    if not meta:
        log.warning("no championship points PDF found")
        return last_hash
    r = http.get(meta["url"], timeout=60)
    r.raise_for_status()
    digest = hashlib.sha256(r.content + json.dumps(CAR_CLASS).encode()).hexdigest()
    if digest == last_hash:
        log.info("unchanged: %s %s (%s)", meta["season"], meta["event"], meta["status"])
        return digest
    classes = {}
    for cls in CLASSES:
        events, teams, drivers = parse_points(r.content, cls)
        if not teams:
            raise RuntimeError(f"no {cls} teams table in {unquote(meta['url'])}")
        classes[cls] = build(cls, events, teams, drivers)
    write("standings.json", {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{k: meta[k] for k in ("season", "event", "status", "url")},
        "cars": [{"car": c, "class": k} for c, k in CAR_CLASS.items()],
        "classes": classes,
    })
    log.info("updated: %s %s (%s), %s", meta["season"], meta["event"], meta["status"],
             ", ".join(f"{len(c['standings'])} {k}" for k, c in classes.items()))
    return digest


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Also keep a log next to the session recordings, for debugging after the fact.
    (DATA_DIR / "archive").mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(DATA_DIR / "archive" / "scraper.log", maxBytes=5_000_000, backupCount=5)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(fh)
    status.start()
    # For the web pages: which cars are followed for the race only (their own tab).
    grouped = {c for _, cars in GROUPS for c in cars}
    groups = [{"name": name, "cars": [c for c in cars if c in CAR_CLASS]} for name, cars in GROUPS]
    rest = [c for c in CAR_CLASS if c not in grouped]
    write("config.json", {"race_cars": [{"car": c, "class": k} for c, k in RACE_CARS.items()],
                          "groups": groups + ([{"name": "Other cars", "cars": rest}] if rest else [])})
    last, next_pdf, failures, next_sectors, next_watch, next_rc = None, 0.0, 0, 0.0, 0.0, 0.0
    while True:
        if time.monotonic() >= next_pdf:
            next_pdf = time.monotonic() + INTERVAL
            try:
                last = run_once(last)
                status.mark("points", event=(read("standings.json") or {}).get("event"))
            except Exception:
                log.exception("scrape failed")
            try:
                refresh_history()
                status.mark("history")
            except Exception:
                log.exception("history failed")
            try:
                bop.refresh()
                status.mark("bop", bulletin=(read("bop.json") or {}).get("bulletin"))
            except Exception:
                log.exception("BoP bulletin failed")
        if time.monotonic() >= next_sectors:
            next_sectors = time.monotonic() + (SECTORS_LIVE if live.in_window() else SECTORS_IDLE)
            try:
                refresh_sectors()
            except Exception:
                log.exception("sectors failed")
        # Race control: every 15 s, but only once the log has shown it's updated that often.
        if racecontrol.fast() and live.in_window() and time.monotonic() >= next_rc:
            next_rc = time.monotonic() + racecontrol.FAST_SECS
            try:
                racecontrol.quick_check(BASE)
            except Exception:
                log.exception("race control quick check failed")
        if time.monotonic() >= next_watch:
            next_watch = time.monotonic() + (180 if live.in_window() else 3600)
            try:
                watch.refresh()
            except Exception:
                log.exception("watch feeds failed")
        try:
            wait = live.step()
            failures = 0
            status.live(last_step=time.time(), wait_until=time.time() + wait, failures=0)
        except Exception:
            failures += 1
            wait = min(live.RACE_POLL * 2 ** failures, MAX_BACKOFF)
            log.exception("live timing failed (%d in a row), retrying in %ds", failures, wait)
            status.live(last_step=time.time(), wait_until=time.time() + wait, failures=failures)
        # Cap the sleep so the points, history and sector checks keep running between sessions.
        time.sleep(min(wait, 1800))


if __name__ == "__main__":
    main()
