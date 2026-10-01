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
import telemetry
import status
from archive import RECORDER
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
TELEMETRY = telemetry.Telemetry()
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
    if sessions:
        status.mark("schedule", sessions=len(sessions))
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
                                     "gaps": [], "last_lap": lap, "pit_in_at": None, "pit_secs": []}
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
            gap = 0.0 if c.get("PIC") == 1 else secs(c.get("DIC"))
            if gap is not None:
                st.setdefault("gaps", []).append([lap, round(gap, 3)])
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
    return [(n, t) for n, t in laps if t <= best * 1.05]


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


# --- energy (telemetry) ------------------------------------------------------------

def energy_use(lap_energy):
    """Median energy (% per lap) over the last 5 laps of the current tank."""
    drops = []
    for (l0, e0), (l1, e1) in zip(lap_energy, lap_energy[1:]):
        if e1 > e0 + 1:      # refuelled: start over
            drops = []
        elif l1 == l0 + 1 and e0 - e1 > 0.2:
            drops.append(e0 - e1)
    return statistics.median(drops[-5:]) if len(drops) >= 2 else None


def energy_info(tel, row, pace, remaining_secs, fill_per_pct):
    if not tel or tel.get("energy") is None:
        return None
    now, use = tel["energy"], energy_use(tel["lap_energy"])
    out = {"now": now, "use_per_lap": use and round(use, 2), "pit_lane": tel.get("pit_lane"),
           "refuelling": tel.get("recharging"), "refills": tel["refills"][-5:], "stops": tel.get("stops", [])[-5:]}
    if use:
        laps_left = now / use
        full = 100 / use
        out.update(laps_left=round(laps_left, 1), full_tank_laps=round(full, 1),
                   next_stop_lap=int(row.get("L") or 0) + int(laps_left),
                   eta_min=round(laps_left * pace / 60) if pace else None)
        if fill_per_pct:
            arrive = max(now - use * int(laps_left), 0)
            out["next_fill_secs"] = round((100 - arrive) * fill_per_pct)
    return out


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


def worst_winning_finish(car, base, quali, order, margin, vs=None):
    """Lowest class finish that still leaves `car` more than `margin` clear of everyone (or of `vs`),
    with the other cars holding station."""
    if car not in order:
        return None
    rest = [c for c in order if c != car]
    worst = None
    for p in range(1, len(order) + 1):
        totals = project(base, quali, rest[:p - 1] + [car] + rest[p - 1:])
        other = totals.get(vs, 0) if vs else max(v for c, v in totals.items() if c != car)
        if totals[car] - other > margin:
            worst = p
        else:
            break
    return worst


def stops_to_flag(row, energy, st, model, remaining, pace):
    """Stops still needed to reach the flag: telemetry energy if we have it, else the stint model.
    A car in the pit lane is counted as leaving on a full tank."""
    if not remaining or not pace:
        return None
    in_pit = bool(row.get("P")) or bool(energy and energy.get("pit_lane"))
    if energy and energy.get("full_tank_laps"):
        per_tank, left = energy["full_tank_laps"] * pace, energy["laps_left"] * pace
    elif model and st:
        done = st["last_lap"] - st["stops"][-1] if st["stops"] else (st["last_lap"] if st["from_start"] else None)
        if done is None:
            return None
        per_tank, left = model["typical"] * pace, max(model["typical"] - done, 0) * pace
    else:
        return None
    on_tank = per_tank if in_pit else left
    return 0 if remaining <= on_tank else int(-(-(remaining - on_tank) // per_tank))


def owed_stops(rows, state, stops, model, remaining, pace):
    """Stops each car still owes compared with the others.

    Mid-race this is the current pit cycle: once some cars in the class have stopped within the
    last W laps (W = 40% of a typical stint), the cars that haven't owe one stop. In the final
    tank of the race it's the stops still needed to reach the flag (so a late splash counts)."""
    typical = (model or {}).get("typical") or 40
    w = max(5, round(0.4 * typical))
    since = {}
    for r in rows:
        st = state["cars"].get(r["N"])
        if st and st["stops"]:
            since[r["N"]] = st["last_lap"] - st["stops"][-1]
        elif st and st["from_start"]:
            since[r["N"]] = st["last_lap"]
    final = remaining is not None and pace and remaining < 1.2 * typical * pace
    if final and sum(v is not None for v in stops.values()) >= len(rows) // 2:
        return {n: (v if v is not None else 0) for n, v in stops.items()}
    cycle_open = any(v < w for v in since.values()) and any(v >= w for v in since.values())
    return {r["N"]: 1 if cycle_open and since.get(r["N"], 0) >= w and stops.get(r["N"]) != 0 else 0 for r in rows}


def net_order(rows, gaps, owed, pit_loss, flag):
    """Class order once every car has made the stops it owes: gap + pit loss per owed stop.
    None under yellows (pit loss collapses) or without a pit loss figure."""
    if not pit_loss or re.search(r"yellow|fcy|caution|red", flag or "", re.I):
        return None
    net = {r["N"]: (gaps[r["N"]] if gaps.get(r["N"]) is not None else 1e6 + i) + pit_loss * owed.get(r["N"], 0)
           for i, r in enumerate(rows)}
    return sorted(net, key=net.get)


def projection(cls, order, net, standings, quali, info):
    base = {s["car"]: s for s in standings["standings"]}
    q = quali.get("classes", {}).get(cls, {}) if quali and quali.get("event") == info.get("E") else {}
    totals = project(base, q, order)
    after = max(standings["rounds_remaining"] - 1, 0) * standings["max_points_per_round"]
    ranked = sorted(totals, key=lambda car: -totals[car])
    leader = totals[ranked[0]]
    net_totals = project(base, q, net) if net else None
    net_ranked = sorted(net_totals, key=lambda car: -net_totals[car]) if net else None
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
                       "net_projected": net_totals and net_totals[car],
                       "net_pos": net_ranked and net_ranked.index(car) + 1,
                       "net_class_pos": net and car in net and net.index(car) + 1,
                       "tracked": CAR_CLASS.get(car) == cls} for i, car in enumerate(ranked)],
        "net_order": net,
        "_ctx": {"base": base, "q": q, "after": after, "totals": totals, "ranked": ranked,
                 "net_totals": net_totals, "net_ranked": net_ranked},
    }


def focus(car, rows, proj, state):
    """The cars that matter for `car`: race reference, car ahead on track, and the championship
    neighbours either side in the projection (net order when available). Rival changes need to
    hold for 3 polls before they're reported, so pit-cycle flicker doesn't spam."""
    order = [r["N"] for r in rows]
    if car not in order:
        return None
    i = order.index(car)
    ref = order[0] if i else (order[1] if len(order) > 1 else None)
    ahead = order[i - 1] if i > 1 else None          # i == 1: the car ahead is the leader (= ref)
    out = {"ref": ref, "ref_role": "leader" if i else "car behind", "ahead": ahead}
    if not proj:
        return out
    ctx = proj["_ctx"]
    use_net = bool(ctx["net_ranked"])
    ranked, totals = (ctx["net_ranked"], ctx["net_totals"]) if use_net else (ctx["ranked"], ctx["totals"])
    j = ranked.index(car)
    champ_ahead = ranked[j - 1] if j else None
    champ_behind = ranked[j + 1] if j + 1 < len(ranked) else None

    w = state.setdefault("watch", {}).setdefault(car, {"champ_ahead": champ_ahead, "champ_behind": champ_behind,
                                                     "pending": {}, "events": []})
    lap = state["cars"].get(car, {}).get("last_lap")
    for role, now_car in (("champ_ahead", champ_ahead), ("champ_behind", champ_behind)):
        if now_car == w[role]:
            w["pending"].pop(role, None)
            continue
        cand, n = w["pending"].get(role, (None, 0))
        n = n + 1 if cand == now_car else 1
        w["pending"][role] = (now_car, n)
        if n >= 3:
            w["events"].append({"lap": lap, "role": role, "from": w[role], "to": now_car, "at": now_iso()})
            w["events"] = w["events"][-20:]
            w[role] = now_car
            w["pending"].pop(role, None)
    champ_ahead, champ_behind = w["champ_ahead"], w["champ_behind"]

    p = i + 1
    raw, net_t = ctx["totals"], ctx["net_totals"]
    margin = lambda t, other: t[car] - t[other] if t and other in t else None
    net = proj["net_order"] or order
    out.update({
        "basis": "net" if use_net else "raw",
        "champ_pos": j + 1,
        "champ_ahead": champ_ahead, "champ_behind": champ_behind,
        "margin_ahead": margin(raw, champ_ahead), "margin_behind": margin(raw, champ_behind),
        "net_margin_ahead": margin(net_t, champ_ahead), "net_margin_behind": margin(net_t, champ_behind),
        "place_gain": _pts(p - 1) - _pts(p) if p > 1 else 0,
        "place_lose": _pts(p) - _pts(p + 1),
        # lowest class finish for us to stay ahead of the rival behind / get ahead of the one in front,
        # and for the rival behind to get ahead of us, everyone else holding (net) position
        "we_need_vs_ahead": champ_ahead and worst_winning_finish(car, ctx["base"], ctx["q"], net, 0, vs=champ_ahead),
        "we_hold_vs_behind": champ_behind and worst_winning_finish(car, ctx["base"], ctx["q"], net, 0, vs=champ_behind),
        "rival_needs": champ_behind and worst_winning_finish(champ_behind, ctx["base"], ctx["q"], net, 0, vs=car),
        "events": w["events"][-5:],
    })
    # Title margin history, one point per lap of ours.
    hist = state.setdefault("margins", {}).setdefault(car, [])
    if lap and (not hist or lap > hist[-1][0]):
        hist.append([lap, out["margin_behind"], out["net_margin_behind"], out["margin_ahead"], out["net_margin_ahead"],
                     champ_behind, champ_ahead])
    return out


# --- strategy (slow tier) ----------------------------------------------------------

def stint_model(cls, state, baseline):
    """This session's own completed stints once there are enough, else last year's race here."""
    stints = [x for st in state["cars"].values() if st["cls"] == cls for x in race_stints(st)]
    model = history.stint_model(stints)
    if model and model["sample"] >= 6:
        return {**model, "source": "this race"}
    b = (baseline or {}).get("classes", {}).get(cls)
    return b and {**b, "source": baseline["source"]}


def pit_types(cls, tel):
    """Median pit-lane time for fuel-only stops and for full service (tyres and/or driver change)."""
    stops = [s for t in tel["cars"].values() if t["cls"] == cls for s in t.get("stops", [])]
    fuel_only = [s["lane"] for s in stops if not s["tyres"] and not s["driver_change"]]
    full = [s["lane"] for s in stops if s["tyres"] or s["driver_change"]]
    med = lambda xs: round(statistics.median(xs), 1) if xs else None
    return {"fuel_only": med(fuel_only), "full": med(full), "n_fuel_only": len(fuel_only), "n_full": len(full)}


def pit_loss_for(cls, tel, baseline, is_race):
    """Class pit-lane time per stop for the net order and pit-now estimates: in the race, the median
    of the class's most common stop type (fuel-only or full service) once there are 3+ telemetry-timed
    stops; otherwise last year's race here. Practice/qualifying visits (garage time) are never used."""
    if is_race:
        types = pit_types(cls, tel)
        n = types["n_fuel_only"] + types["n_full"]
        if n >= 3:
            common = "full" if types["n_full"] >= types["n_fuel_only"] else "fuel_only"
            return types[common], f"telemetry, {common.replace('_', '-')} stops"
    b = (baseline or {}).get("pit_lane", {}).get(cls)
    return (b, "last year") if b else (None, None)


def strategy(cls, rows, state, baseline, is_race, tel):
    pit_loss, pit_source = pit_loss_for(cls, tel, baseline, is_race)
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
    return {"updated": now_iso(), "pit_loss": pit_loss, "pit_loss_source": pit_source,
            "pit_types": pit_types(cls, tel) if is_race else None, "class_pace": class_pace, "cars": cars}


# --- main step ---------------------------------------------------------------------

def step():
    """One live-timing step. Returns seconds to wait before the next one."""
    now = time.time()
    now_dt = datetime.now(timezone.utc)
    refresh_schedule(now)
    active, upcoming = session_window(now_dt)
    TELEMETRY.ensure(bool(active))
    RECORDER.start(active and f'{active["start"][:10]}_{active["name"]}')
    status.live(window=active and active["name"], window_end=active and active["end"],
                next_session=upcoming and upcoming.isoformat())
    if _s["schedule"] and not active:
        wait = (upcoming - LEAD - now_dt).total_seconds() if upcoming else SCHEDULE_EVERY
        return max(60, min(wait, SCHEDULE_EVERY))

    info = jsonp("SessionInfo")
    name = info.get("S", "")
    status.live(feed_session=name, flag=info.get("F"))
    if not name.startswith(SERIES):
        # Before the green flag, or a support race overrunning into the slot.
        return SESSION_POLL if active else NO_SCHEDULE_POLL
    TELEMETRY.ensure(True)
    if not active:   # no schedule: record under the feed's own session name
        RECORDER.start(f'{now_dt.date()}_{info.get("E")}_{name}')
    is_race, is_quali = bool(RACE_SESSIONS.search(name)), "Qualif" in name
    results = jsonp("RaceResults")
    RECORDER.feed(info, results)
    status.mark("feed", session=name, cars=len(results.get("B", [])))
    feed = [c for c in results.get("B", []) if c.get("C") in CLASSES and c.get("PIC")]
    if not feed:
        return SESSION_POLL

    key = f'{info.get("E")}|{name}'
    if not _s["state"] or _s["state"].get("key") != key:
        saved = read("race_state.json")
        _s["state"] = saved if saved and saved.get("key") == key else {"key": key, "cars": {}}
        _s["strategy"], _s["strategy_at"] = {}, 0.0
    state = _s["state"]
    track(state, feed, now)

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
        _s["strategy"] = {cls: strategy(cls, rows, state, baseline, is_race, TELEMETRY.snapshot()) for cls, rows in by_class.items()}
        _s["strategy_at"] = now

    standings = read("standings.json") if is_race else None
    flag = info.get("F", "")
    tel = TELEMETRY.snapshot()
    remaining = history.secs(info.get("TR")) if is_race else None
    classes = {}
    for cls, rows in by_class.items():
        model = stint_model(cls, state, baseline)
        # Seconds per % of energy from fills of 40%+ (small top-ups are mostly hook-up time).
        per = [r["secs"] / (r["to"] - r["from"]) for t in tel["cars"].values() if t["cls"] == cls
               for r in t["refills"] if r["to"] - r["from"] >= 40]
        fill_per_pct = statistics.median(per) if len(per) >= 2 else None
        paces = {r["N"]: strategy_pace(state["cars"][r["N"]]) for r in rows}
        class_pace = statistics.median([p for p in paces.values() if p]) if any(paces.values()) else None
        energies = {r["N"]: energy_info(tel["cars"].get(r["N"]), r, paces[r["N"]], remaining, fill_per_pct) for r in rows}
        stops = {r["N"]: stops_to_flag(r, energies[r["N"]], state["cars"][r["N"]], model, remaining,
                                       paces[r["N"]] or class_pace) for r in rows}
        for n, e in energies.items():
            if e:
                e["stops_remaining"] = stops[n]
        pit_loss = pit_loss_for(cls, tel, baseline, is_race)[0]
        gaps = {r["N"]: gap_secs(r, class_pace) for r in rows}
        owed = owed_stops(rows, state, stops, model, remaining, class_pace) if is_race else {}
        net = net_order(rows, gaps, owed, pit_loss, flag) if is_race else None
        out = {
            "stint_model": model,
            "strategy": _s["strategy"].get(cls),
            "cars": [{
                "car": r["N"], "class_pos": r["PIC"], "laps": r.get("L"), "gap": r.get("DIC"),
                "interval": r.get("GIC"), "last_lap": r.get("LL"), "best_lap": r.get("BL"),
                "pit_stops": r.get("PS"), "in_pit": bool(r.get("P")), "driver": r.get("F"),
                "vehicle": r.get("V"), "tracked": CAR_CLASS.get(r["N"]) == cls,
                "stint": stint_info(state["cars"][r["N"]], int(r.get("L") or 0), model) if is_race else None,
                "energy": energies[r["N"]], "stops_remaining": stops[r["N"]],
                "net_pos": net.index(r["N"]) + 1 if net else None, "owes_stop": owed.get(r["N"], 0),
            } for r in rows],
            "fill_secs_per_pct": fill_per_pct, "pit_loss": pit_loss,
        }
        proj = None
        if standings and cls in standings["classes"]:
            proj = projection(cls, [r["N"] for r in rows], net, standings["classes"][cls], read("quali.json"), info)
            out.update({k: v for k, v in proj.items() if k != "_ctx"})
        out["focus"] = {car: focus(car, rows, proj, state) for car, k in CAR_CLASS.items() if k == cls}
        classes[cls] = out
    live_out = {
        "updated": now_iso(), "event": info.get("E"), "session": name, "is_race": is_race,
        "flag": flag, "elapsed": info.get("TT"), "remaining": info.get("TR"),
        "finished": bool(re.search(r"check|finish", flag, re.I)),
        "scheduled_end": active and active["end"],
        "telemetry": {"connected": tel["connected"], "age": round(now - tel["last_data"]) if tel["last_data"] else None},
        "base_event": standings and standings["event"], "classes": classes,
    }
    write("live.json", live_out)
    RECORDER.output("live.json", live_out)
    laps_out = {"updated": now_iso(), "session": name, "classes": {
        cls: {n: {"laps": st["laps"], "stops": st["stops"], "gaps": st.get("gaps", []),
                  "energy": tel["cars"].get(n, {}).get("lap_energy", []),
                  "margins": state.get("margins", {}).get(n, [])}
              for n, st in state["cars"].items() if st["cls"] == cls}
        for cls in CLASSES}}
    write("laps.json", laps_out)
    RECORDER.output("laps.json", laps_out)
    write("race_state.json", state)
    log.info("live: %s %s, %s, %d cars", info.get("E"), name, flag, len(feed))
    return RACE_POLL if is_race else SESSION_POLL
