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
import os
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import pdfplumber
import requests

import history

BASE = "https://imsa.results.alkamelcloud.com/"
SERIES = "IMSA WeatherTech SportsCar Championship"
POINTS_RE = re.compile(
    r'href="([^"]*' + re.escape(quote(SERIES)) + r'/00_Championship%20Points%20-%20(Official|Provisional)\.pdf)"'
)

# Tracked cars as CLASS:NUMBER (class as printed in the points PDF: GTP, LMP2, GTDPRO, GTD).
DEFAULT_CARS = "GTDPRO:4,GTDPRO:3,GTDPRO:74,GTD:13,GTD:36,GTD:81"
CAR_CLASS = {c.split(":")[-1].strip(): (c.split(":")[0].strip() if ":" in c else os.environ.get("CLASS", "GTDPRO"))
             for c in (os.environ.get("CARS") or DEFAULT_CARS).split(",") if c.strip()}
CARS = list(CAR_CLASS)
CLASSES = list(dict.fromkeys(CAR_CLASS.values()))
INTERVAL = int(os.environ.get("INTERVAL_MINUTES", "30")) * 60
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

# Live timing: the JSONP files behind imsa.com/scoring. Unofficial and undocumented.
LIVE_URL = "https://dcqsrdkhg933g.cloudfront.net/"
LIVE_SERIES = "WeatherTech Championship"
# Polling is deliberately gentle: an occasional check when nothing is on, a minute during
# WeatherTech sessions, 30s during the race, and exponential backoff when requests fail.
LIVE_IDLE = int(os.environ.get("LIVE_IDLE_SECONDS", "300"))
LIVE_SESSION = int(os.environ.get("LIVE_SESSION_SECONDS", "60"))
LIVE_RACE = int(os.environ.get("LIVE_RACE_SECONDS", "30"))
MAX_BACKOFF = 900
LIVE_SESSIONS = re.compile(os.environ.get("LIVE_SESSIONS", r"\bRace\b"))
# Race points by class finishing position; qualifying pays a tenth of the same table.
RACE_POINTS = [350, 320, 300, 280, 260] + list(range(250, 0, -10))

log = logging.getLogger("scraper")
http = requests.Session()
http.headers["User-Agent"] = "yellowcarpoints.win standings tracker"


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


# --- live timing -------------------------------------------------------------------

def _jsonp(name):
    r = http.get(f"{LIVE_URL}{name}_JSONP.json", params={"callback": "cb"}, timeout=15)
    r.raise_for_status()
    text = r.content.decode("utf-8")
    try:
        text = text.encode("latin-1").decode("utf-8")  # the feed double-encodes UTF-8
    except UnicodeError:
        pass
    return json.loads(text[text.index("(") + 1:text.rindex(")")])


def _pts(pos, scale=1):
    return RACE_POINTS[pos - 1] // scale if pos and pos <= len(RACE_POINTS) else 0


def _read(name):
    try:
        return json.loads((DATA_DIR / name).read_text())
    except (OSError, ValueError):
        return None


def _write(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(DATA_DIR / name)


def project(base, quali, order):
    """Championship totals if the race finished with the class in `order` (car numbers)."""
    totals = {car: b["points"] + _pts(quali.get(car), 10) for car, b in base.items()}
    for car in order:
        totals.setdefault(car, _pts(quali.get(car), 10))
    for i, car in enumerate(order):
        totals[car] += _pts(i + 1)
    return totals


def worst_winning_finish(car, base, quali, order, margin):
    """Lowest class finish that still leaves `car` more than `margin` clear, rivals holding station."""
    rest = [c for c in order if c != car]
    worst = None
    for p in range(1, len(order) + 1):
        totals = project(base, quali, rest[:p - 1] + [car] + rest[p - 1:])
        if totals[car] - max(v for c, v in totals.items() if c != car) > margin:
            worst = p
        else:
            break
    return worst


def _secs(t):
    return history.secs(t) if t and "-" not in str(t) else None


def track_pits(state, feed, now):
    """Update per-car pit/lap state from one live poll; stops are recorded at the lap they happened."""
    for c in feed:
        n, ps, laps = c["N"], int(c.get("PS") or 0), int(c.get("L") or 0)
        st = state["cars"].get(n)
        if st is None:
            # Seen first mid-race (scraper restarted): earlier stops happened at unknown laps.
            st = state["cars"][n] = {"ps": ps, "stops": [], "from_start": ps == 0, "recent": [],
                                     "last_ll": None, "pit_in_at": None, "pit_secs": []}
        elif ps > st["ps"]:
            st["stops"].append(laps)
            st["ps"] = ps
        if c.get("P") and not st["pit_in_at"]:
            st["pit_in_at"] = now
        elif not c.get("P") and st["pit_in_at"]:
            if now - st["pit_in_at"] < 600:
                st["pit_secs"].append(round(now - st["pit_in_at"]))
            st["pit_in_at"] = None
        if c.get("LL") != st["last_ll"]:
            st["last_ll"] = c.get("LL")
            if _secs(c.get("LL")):
                st["recent"] = (st["recent"] + [_secs(c["LL"])])[-8:]


def race_stints(st):
    marks = ([0] if st["from_start"] else []) + st["stops"]
    return [b - a for a, b in zip(marks, marks[1:]) if b > a]


def stint_info(st, laps, model):
    if st["stops"]:
        done = laps - st["stops"][-1]
    elif st["from_start"]:
        done = laps
    else:
        done = None
    green = [t for t in st["recent"] if t <= 1.1 * min(st["recent"])] if st["recent"] else []
    pace = statistics.median(green) if green else None
    out = {"laps": done, "stops_seen": len(st["stops"]), "pace": pace,
           "pit_secs": st["pit_secs"][-1] if st["pit_secs"] else None}
    if model and done is not None:
        to_typical = model["typical"] - done
        out.update({
            "window_open": model["short"], "typical": model["typical"], "window_close": model["long"],
            "laps_to_window": max(model["short"] - done, 0),
            "laps_to_typical": to_typical,
            "eta_min": round(to_typical * pace / 60) if pace and to_typical > 0 else None,
        })
    return out


def build_live_class(cls, info, cars, standings, quali, state, baseline):
    base = {s["car"]: s for s in standings["standings"]}
    q = (quali or {}).get("classes", {}).get(cls, {}) if (quali or {}).get("event") == info.get("E") else {}
    cars = sorted(cars, key=lambda c: c.get("PIC") or 999)
    order = [c["N"] for c in cars]
    totals = project(base, q, order)
    after = max(standings["rounds_remaining"] - 1, 0) * standings["max_points_per_round"]
    ranked = sorted(totals, key=lambda car: -totals[car])
    leader = totals[ranked[0]]
    feed = {c["N"]: c for c in cars}

    # Pit window: this race's own completed stints once there are enough, else last year's race here.
    stints = [x for n in order if n in state["cars"] for x in race_stints(state["cars"][n])]
    model, source = history.stint_model(stints), "this race"
    if not model or model["sample"] < 6:
        model, source = (baseline or {}).get(cls), (baseline or {}).get("source")

    rows = []
    for i, car in enumerate(ranked):
        f, b = feed.get(car), base.get(car)
        rows.append({
            "car": car,
            "team": b["team"] if b else (f or {}).get("V", ""),
            "points_before": b["points"] if b else 0,
            "quali_pts": _pts(q.get(car), 10),
            "race_pts": _pts(order.index(car) + 1) if car in order else 0,
            "projected": totals[car],
            "proj_pos": i + 1,
            "proj_gap": leader - totals[car],
            "tracked": CAR_CLASS.get(car) == cls,
            "running": f and {
                "class_pos": f.get("PIC"), "laps": f.get("L"), "gap": f.get("DIC"), "interval": f.get("GIC"),
                "last_lap": f.get("LL"), "best_lap": f.get("BL"), "pit_stops": f.get("PS"),
                "in_pit": bool(f.get("P")), "driver": f.get("F"), "vehicle": f.get("V"),
                "stint": stint_info(state["cars"][car], int(f.get("L") or 0), model) if car in state["cars"] else None,
            },
        })
    return {
        "quali_counted": bool(q),
        "max_points_after": after,
        "worst_winning_finish": {car: worst_winning_finish(car, base, q, order, after)
                                 for car in order if CAR_CLASS.get(car) == cls and car in base},
        "stint_model": model and {**model, "source": source},
        "standings": rows,
    }


_race_state = None


def live_once():
    """Poll IMSA live timing. Returns how many seconds to wait before the next poll."""
    global _race_state
    info = _jsonp("SessionInfo")
    name = info.get("S", "")
    is_quali, is_race = "Qualif" in name, bool(LIVE_SESSIONS.search(name))
    if not name.startswith(LIVE_SERIES):
        return LIVE_IDLE
    if not (is_quali or is_race):
        return LIVE_SESSION
    feed = [c for c in _jsonp("RaceResults").get("B", []) if c.get("C") in CLASSES and c.get("PIC")]
    if not feed:
        return LIVE_SESSION
    by_class = {}
    for c in feed:
        by_class.setdefault(c["C"], []).append(c)
    if is_quali:
        # Class qualifying can be split across sessions; keep whatever each class last showed.
        quali = _read("quali.json") or {}
        if quali.get("event") != info.get("E"):
            quali = {"event": info.get("E"), "classes": {}}
        for cls, cars in by_class.items():
            quali["classes"][cls] = {c["N"]: c["PIC"] for c in cars}
        _write("quali.json", quali)
        return LIVE_SESSION

    key = f'{info.get("E")}|{name}'
    if not _race_state or _race_state.get("key") != key:
        saved = _read("race_state.json")
        _race_state = saved if saved and saved.get("key") == key else {"key": key, "cars": {}}
    track_pits(_race_state, feed, time.time())
    _write("race_state.json", _race_state)

    standings = _read("standings.json")
    if not standings:
        return LIVE_RACE
    baseline = _read("baseline.json")
    baseline = baseline and baseline.get("event") == info.get("E") and \
        {**baseline["classes"], "source": baseline["source"]}
    flag = info.get("F", "")
    _write("live.json", {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": info.get("E"),
        "session": name,
        "flag": flag,
        "elapsed": info.get("TT"),
        "remaining": info.get("TR"),
        "finished": bool(re.search(r"check|finish", flag, re.I)),
        "base_event": standings["event"],
        "classes": {cls: build_live_class(cls, info, by_class.get(cls, []), standings["classes"][cls],
                                          _read("quali.json"), _race_state, baseline)
                    for cls in CLASSES if cls in standings["classes"]},
    })
    log.info("live: %s %s, %s, %d cars", info.get("E"), name, flag, len(feed))
    return LIVE_RACE


def refresh_history():
    """Season race-by-race summaries for the tracked cars, and the pit-window baseline."""
    races = history.update(http, BASE, _page, _options, DATA_DIR, SERIES, CAR_CLASS, CLASSES)
    seasons, current = _options(_page(), "season")
    cars = {c: [] for c in CARS}
    for event, summary in races.items():
        for car, row in summary["cars"].items():
            cars[car].append({"round": event.split("_", 1)[1], "date": summary["date"], **row})
    _write("history.json", {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "season": current.split("_", 1)[1], "cars": cars})

    # Baseline for the latest event (the one in progress or next): last season's race at the same track.
    events, _ = _options(_page(current), "evvent")
    track = events[-1].split("_", 1)[1] if events else None
    prev = [s for s in seasons if s < current]
    if not track or not prev or (_read("baseline.json") or {}).get("event") == track:
        return
    prev_events, _ = _options(_page(prev[-1]), "evvent")
    match = [e for e in prev_events if e.split("_", 1)[1] == track]
    if not match:
        return
    old = history.update(http, BASE, _page, _options, DATA_DIR, SERIES, CAR_CLASS, CLASSES,
                         season=prev[-1], only=match)
    if match[0] in old:
        stints = old[match[0]]["class_stints"]
        _write("baseline.json", {"event": track, "source": f'{prev[-1].split("_", 1)[1]} {track}',
                                 "classes": {c: history.stint_model(stints.get(c, [])) for c in CLASSES}})
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
    _write("standings.json", {
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
    last, next_pdf, failures = None, 0.0, 0
    while True:
        if time.monotonic() >= next_pdf:
            next_pdf = time.monotonic() + INTERVAL
            try:
                last = run_once(last)
            except Exception:
                log.exception("scrape failed")
            try:
                refresh_history()
            except Exception:
                log.exception("history failed")
        try:
            wait = live_once()
            failures = 0
        except Exception:
            failures += 1
            wait = min(LIVE_RACE * 2 ** failures, MAX_BACKOFF)
            log.exception("live timing failed (%d in a row), retrying in %ds", failures, wait)
        time.sleep(wait)


if __name__ == "__main__":
    main()
