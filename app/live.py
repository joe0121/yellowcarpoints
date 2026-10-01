"""Live timing during WeatherTech sessions, driven by IMSA's published weekend schedule.

Polling only happens around scheduled WeatherTech sessions (from LEAD before the start to
TAIL after the scheduled end). Two tiers while a session runs:

- fast (every RACE_POLL / SESSION_POLL seconds): the live leaderboard, recording every
  lap time and pit stop for each car in the tracked classes, plus the championship
  projection during the race;
- slow (every STRATEGY_EVERY seconds): strategy read-outs per car: recent pace and trend,
  stint progress against the pit window, and where the car would rejoin if it pitted now.

The leaderboard files are the JSONP behind imsa.com/scoring: unofficial and undocumented.
"""

import json
import logging
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import history
from common import CAR_CLASS, CLASSES, http, now_iso, read, write

FEED = "https://dcqsrdkhg933g.cloudfront.net/"
SCHEDULE_URL = "https://www.imsa.com/weathertech/"
SERIES = "WeatherTech Championship"
ET = ZoneInfo("America/New_York")

RACE_POLL = int(os.environ.get("LIVE_RACE_SECONDS", "30"))
SESSION_POLL = int(os.environ.get("LIVE_SESSION_SECONDS", "60"))
STRATEGY_EVERY = int(os.environ.get("STRATEGY_SECONDS", "300"))
SCHEDULE_EVERY = 6 * 3600
NO_SCHEDULE_POLL = 1800     # schedule unreadable: check the feed every 30 minutes instead
LEAD, TAIL = timedelta(minutes=10), timedelta(minutes=30)
RACE_SESSIONS = re.compile(os.environ.get("LIVE_SESSIONS", r"\bRace\b"))
# Race points by class finishing position; qualifying pays a tenth of the same table.
RACE_POINTS = [350, 320, 300, 280, 260] + list(range(250, 0, -10))

log = logging.getLogger("scraper.live")
_s = {"schedule": None, "schedule_at": 0.0, "state": None, "strategy": {}, "strategy_at": 0.0}


# --- feeds -------------------------------------------------------------------------

def jsonp(name):
    r = http.get(f"{FEED}{name}_JSONP.json", params={"callback": "cb"}, timeout=15)
    r.raise_for_status()
    text = r.content.decode("utf-8")
    try:
        text = text.encode("latin-1").decode("utf-8")  # the feed double-encodes UTF-8
    except UnicodeError:
        pass
    return json.loads(text[text.index("(") + 1:text.rindex(")")])


def parse_schedule(html):
    """WeatherTech sessions from the 'Race Weekend Schedule' block on imsa.com (times in ET)."""
    dates = re.findall(r'class="day-event-item" data-eventdate="(\d\d/\d\d/\d{4})"', html)
    start = html.find("day-event-details-container")
    if not dates or start < 0:
        return []
    days = html[start:].split("<div class='day-event-details'>")[1:len(dates) + 1]
    out = []
    for date, day in zip(dates, days):
        items = re.findall(r"<img class='series-logo' src='([^']*)' />\s*<span class='event-name-time'>([^<]+)"
                           r"<span>(\d+:\d\d [ap]m) ET to (\d+:\d\d [ap]m) ET</span>", day, re.I)
        for logo, name, t0, t1 in items:
            if "weathertech" not in (logo + name).lower():
                continue
            begin = datetime.strptime(f"{date} {t0}", "%m/%d/%Y %I:%M %p").replace(tzinfo=ET)
            end = datetime.strptime(f"{date} {t1}", "%m/%d/%Y %I:%M %p").replace(tzinfo=ET)
            if end <= begin:
                end += timedelta(days=1)
            out.append({"name": name.strip(), "start": begin.astimezone(timezone.utc).isoformat(),
                        "end": end.astimezone(timezone.utc).isoformat(),
                        "race": not re.search(r"practice|qualif|warm", name, re.I)})
    return out


def refresh_schedule(now):
    if _s["schedule"] is not None and now - _s["schedule_at"] < SCHEDULE_EVERY:
        return
    _s["schedule_at"] = now
    try:
        r = http.get(SCHEDULE_URL, timeout=30)
        r.raise_for_status()
        sessions = parse_schedule(r.text)
    except Exception:
        log.exception("schedule fetch failed")
        sessions = []
    _s["schedule"] = sessions
    write("schedule.json", {"updated": now_iso(), "sessions": sessions})
    log.info("schedule: %s", ", ".join(f'{s["name"]} {s["start"]}' for s in sessions) or "no WeatherTech sessions")


def session_window(now_dt):
    """(active session, next session start) from the schedule."""
    active, upcoming = None, None
    for s in _s["schedule"] or []:
        begin, end = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
        if begin - LEAD <= now_dt <= end + TAIL:
            active = s
        elif begin - LEAD > now_dt and (upcoming is None or begin < upcoming):
            upcoming = begin
    return active, upcoming


# --- per-car tracking --------------------------------------------------------------

def secs(t):
    return history.secs(t) if t and "-" not in str(t) and "lap" not in str(t).lower() else None


def track(state, feed, now):
    """Record laps and pit stops from one leaderboard poll."""
    for c in feed:
        n, ps, lap = c["N"], int(c.get("PS") or 0), int(c.get("L") or 0)
        st = state["cars"].get(n)
        if st is None:
            # First seen mid-session (scraper started late): earlier stops are at unknown laps.
            st = state["cars"][n] = {"cls": c["C"], "ps": ps, "stops": [], "from_start": ps == 0, "laps": [],
                                     "last_lap": lap, "pit_in_at": None, "pit_secs": []}
        if ps > st["ps"]:
            st["stops"].append(lap)
            st["ps"] = ps
        if c.get("P") and not st["pit_in_at"]:
            st["pit_in_at"] = now
        elif not c.get("P") and st["pit_in_at"]:
            if now - st["pit_in_at"] < 600:
                st["pit_secs"].append(round(now - st["pit_in_at"]))
            st["pit_in_at"] = None
        if lap > st["last_lap"]:
            t = secs(c.get("LL"))
            if t:
                st["laps"].append([lap, round(t, 3)])
            st["last_lap"] = lap


def race_stints(st):
    marks = ([0] if st["from_start"] else []) + st["stops"]
    return [b - a for a, b in zip(marks, marks[1:]) if b > a]


def clean_laps(st):
    """Lap times without in/out laps, the first lap, or slow (yellow/traffic) laps."""
    pit = {s for s in st["stops"]} | {s + 1 for s in st["stops"]}
    laps = [(n, t) for n, t in st["laps"] if n > 1 and n not in pit]
    if not laps:
        return []
    best = min(t for n, t in laps)
    return [(n, t) for n, t in laps if t <= best * 1.07]


def stint_info(st, lap, model):
    done = lap - st["stops"][-1] if st["stops"] else (lap if st["from_start"] else None)
    out = {"laps": done, "stops_seen": len(st["stops"])}
    if model and done is not None:
        to_typical = model["typical"] - done
        pace = strategy_pace(st)
        out.update({"window_open": model["short"], "typical": model["typical"], "window_close": model["long"],
                    "laps_to_window": max(model["short"] - done, 0), "laps_to_typical": to_typical,
                    "eta_min": round(to_typical * pace / 60) if pace and to_typical > 0 else None})
    return out


def strategy_pace(st, last=5, skip=0):
    clean = [t for n, t in clean_laps(st)]
    window = clean[-(last + skip):len(clean) - skip] if skip else clean[-last:]
    return statistics.median(window) if len(window) >= 3 else None


def gap_secs(row, pace):
    """Class gap as seconds; laps down count as whole laps at the class pace."""
    g = str(row.get("DIC") or "")
    if row.get("PIC") == 1:
        return 0.0
    m = re.match(r"-?(\d+) laps?", g.strip())
    if m:
        return int(m.group(1)) * (pace or 0)
    return secs(g)


# --- championship projection -------------------------------------------------------

def _pts(pos, scale=1):
    return RACE_POINTS[pos - 1] // scale if pos and pos <= len(RACE_POINTS) else 0


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


def projection(cls, order, standings, quali, info):
    base = {s["car"]: s for s in standings["standings"]}
    q = quali.get("classes", {}).get(cls, {}) if quali and quali.get("event") == info.get("E") else {}
    totals = project(base, q, order)
    after = max(standings["rounds_remaining"] - 1, 0) * standings["max_points_per_round"]
    ranked = sorted(totals, key=lambda car: -totals[car])
    leader = totals[ranked[0]]
    return {
        "quali_counted": bool(q),
        "max_points_after": after,
        "worst_winning_finish": {car: worst_winning_finish(car, base, q, order, after)
                                 for car in order if CAR_CLASS.get(car) == cls and car in base},
        "standings": [{"car": car, "team": base[car]["team"] if car in base else "",
                       "points_before": base[car]["points"] if car in base else 0,
                       "quali_pts": _pts(q.get(car), 10),
                       "race_pts": _pts(order.index(car) + 1) if car in order else 0,
                       "projected": totals[car], "proj_pos": i + 1, "proj_gap": leader - totals[car],
                       "tracked": CAR_CLASS.get(car) == cls} for i, car in enumerate(ranked)],
    }


# --- strategy (slow tier) ----------------------------------------------------------

def stint_model(cls, state, baseline):
    """This session's own completed stints once there are enough, else last year's race here."""
    stints = [x for st in state["cars"].values() if st["cls"] == cls for x in race_stints(st)]
    model = history.stint_model(stints)
    if model and model["sample"] >= 6:
        return {**model, "source": "this race"}
    b = (baseline or {}).get("classes", {}).get(cls)
    return b and {**b, "source": baseline["source"]}


def strategy(cls, rows, state, baseline, is_race):
    pits = [p for st in state["cars"].values() if st["cls"] == cls for p in st["pit_secs"]]
    pit_loss = statistics.median(pits) if len(pits) >= 3 else (baseline or {}).get("pit_lane", {}).get(cls)
    paces = {r["N"]: strategy_pace(state["cars"][r["N"]]) for r in rows if r["N"] in state["cars"]}
    class_pace = statistics.median([p for p in paces.values() if p]) if any(paces.values()) else None
    gaps = {r["N"]: gap_secs(r, class_pace) for r in rows}
    cars = {}
    for i, r in enumerate(rows):
        n = r["N"]
        st = state["cars"].get(n)
        if not st:
            continue
        pace, prev = paces.get(n), strategy_pace(st, skip=5)
        ahead, behind = (rows[i - 1]["N"] if i else None), (rows[i + 1]["N"] if i + 1 < len(rows) else None)
        rejoin = None
        # Only meaningful in a race: practice/qualifying gaps are best-lap gaps, not track position.
        if is_race and pit_loss and gaps.get(n) is not None:
            after = gaps[n] + pit_loss
            rejoin = 1 + sum(1 for m, g in gaps.items() if m != n and g is not None and g < after)
        cars[n] = {
            "pace": pace,
            "trend": round(pace - prev, 3) if pace and prev else None,
            "vs_ahead": round(pace - paces[ahead], 3) if pace and ahead and paces.get(ahead) else None,
            "vs_behind": round(pace - paces[behind], 3) if pace and behind and paces.get(behind) else None,
            "rejoin": rejoin,
            "clean_laps": len(clean_laps(st)),
        }
    return {"updated": now_iso(), "pit_loss": pit_loss, "class_pace": class_pace, "cars": cars}


# --- main step ---------------------------------------------------------------------

def step():
    """One live-timing step. Returns seconds to wait before the next one."""
    now = time.time()
    now_dt = datetime.now(timezone.utc)
    refresh_schedule(now)
    active, upcoming = session_window(now_dt)
    if _s["schedule"] and not active:
        wait = (upcoming - LEAD - now_dt).total_seconds() if upcoming else SCHEDULE_EVERY
        return max(60, min(wait, SCHEDULE_EVERY))

    info = jsonp("SessionInfo")
    name = info.get("S", "")
    if not name.startswith(SERIES):
        # Before the green flag, or a support race overrunning into the slot.
        return SESSION_POLL if active else NO_SCHEDULE_POLL
    is_race, is_quali = bool(RACE_SESSIONS.search(name)), "Qualif" in name
    feed = [c for c in jsonp("RaceResults").get("B", []) if c.get("C") in CLASSES and c.get("PIC")]
    if not feed:
        return SESSION_POLL

    key = f'{info.get("E")}|{name}'
    if not _s["state"] or _s["state"].get("key") != key:
        saved = read("race_state.json")
        _s["state"] = saved if saved and saved.get("key") == key else {"key": key, "cars": {}}
        _s["strategy"], _s["strategy_at"] = {}, 0.0
    state = _s["state"]
    track(state, feed, now)
    write("race_state.json", state)

    by_class = {}
    for c in sorted(feed, key=lambda c: c["PIC"]):
        by_class.setdefault(c["C"], []).append(c)
    if is_quali:
        quali = read("quali.json") or {}
        if quali.get("event") != info.get("E"):
            quali = {"event": info.get("E"), "classes": {}}
        for cls, rows in by_class.items():
            quali["classes"][cls] = {c["N"]: c["PIC"] for c in rows}
        write("quali.json", quali)

    baseline = read("baseline.json")
    baseline = baseline if baseline and baseline.get("event") == info.get("E") else None
    if now - _s["strategy_at"] >= STRATEGY_EVERY:
        _s["strategy"] = {cls: strategy(cls, rows, state, baseline, is_race) for cls, rows in by_class.items()}
        _s["strategy_at"] = now

    standings = read("standings.json") if is_race else None
    flag = info.get("F", "")
    classes = {}
    for cls, rows in by_class.items():
        model = stint_model(cls, state, baseline)
        out = {
            "stint_model": model,
            "strategy": _s["strategy"].get(cls),
            "cars": [{
                "car": r["N"], "class_pos": r["PIC"], "laps": r.get("L"), "gap": r.get("DIC"),
                "interval": r.get("GIC"), "last_lap": r.get("LL"), "best_lap": r.get("BL"),
                "pit_stops": r.get("PS"), "in_pit": bool(r.get("P")), "driver": r.get("F"),
                "vehicle": r.get("V"), "tracked": CAR_CLASS.get(r["N"]) == cls,
                "stint": stint_info(state["cars"][r["N"]], int(r.get("L") or 0), model) if is_race else None,
            } for r in rows],
        }
        if standings and cls in standings["classes"]:
            out.update(projection(cls, [r["N"] for r in rows], standings["classes"][cls], read("quali.json"), info))
        classes[cls] = out
    write("live.json", {
        "updated": now_iso(), "event": info.get("E"), "session": name, "is_race": is_race,
        "flag": flag, "elapsed": info.get("TT"), "remaining": info.get("TR"),
        "finished": bool(re.search(r"check|finish", flag, re.I)),
        "scheduled_end": active and active["end"],
        "base_event": standings and standings["event"], "classes": classes,
    })
    write("laps.json", {"updated": now_iso(), "session": name, "classes": {
        cls: {n: {"laps": st["laps"], "stops": st["stops"]} for n, st in state["cars"].items() if st["cls"] == cls}
        for cls in CLASSES}})
    log.info("live: %s %s, %s, %d cars", info.get("E"), name, flag, len(feed))
    return RACE_POLL if is_race else SESSION_POLL
