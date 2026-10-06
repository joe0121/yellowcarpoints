"""Other Corvette series from OpenWEC (api.openwec.com): race results for WEC, ELMS and Asian LMS, with each
Corvette's class finish and its best lap against the class's best lap (relative pace). Past races only:
OpenWEC has no live data. Written to series.json once a day; finished sessions are cached in
<DATA_DIR>/openwec/ so each one is fetched once.

Not available from OpenWEC (checked 2026-10-06): championship points (computed points would be unofficial),
BoP (WEC stopped publishing its tables in 2026), and stint/lap pace (needs an approved API key; the
results endpoints work without one). OPENWEC_API_KEY is sent when set, ready for the stint endpoints.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from common import DATA_DIR, http, now_iso, read, write

log = logging.getLogger("scraper.openwec")
API = "https://api.openwec.com/api/v1"
SERIES = [s.strip().upper() for s in os.environ.get("OPENWEC_SERIES", "WEC,ELMS,ALMS").split(",") if s.strip()]
MAKE = re.compile(os.environ.get("OPENWEC_MAKE", r"corvette"), re.I)
KEY = os.environ.get("OPENWEC_API_KEY", "")
EVERY = 86400
RETRY = 3600
CACHE = DATA_DIR / "openwec"
_last = [0.0]


def _get(path):
    time.sleep(1)                                     # gentle: one call a second
    r = http.get(f"{API}/{path}", timeout=60, headers={"X-API-Key": KEY} if KEY else {})
    r.raise_for_status()
    return r.json()


def _results(session_id):
    """A session's results, cached once the session is over (results don't change after that)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"results_{session_id}.json"
    if f.exists():
        return json.loads(f.read_text())
    rows = _get(f"sessions/{session_id}/results")
    if rows:
        f.write_text(json.dumps(rows))
    return rows


def _dedupe(rows):
    """OpenWEC lists every car twice; keep one row per car (best classified position)."""
    best = {}
    for r in rows:
        k = str(r.get("car_number"))
        if k not in best or (r.get("position") or 9999) < (best[k].get("position") or 9999):
            best[k] = r
    return sorted(best.values(), key=lambda r: r.get("position") or 9999)


def _finished(r, winner):
    """Classified for points: OpenWEC's own status (it marks every ELMS car 'Classified', even one that
    retired after 9 laps), plus running at the flag (total time within 1.5 laps of the class winner's)
    and at least 70% of the winner's laps (the series' classification rule)."""
    if (r.get("status") or "").lower() != "classified":
        return False
    wl, wt = winner.get("laps_completed") or 0, winner.get("total_time_s")
    if wl and (r.get("laps_completed") or 0) < 0.7 * wl:
        return False
    if wt and r.get("total_time_s") is not None and r["total_time_s"] < wt - 1.5 * wt / wl:
        return False
    return True


def race_summary(rows):
    """{class: {entries, winner, best_lap, corvettes: [...]}} for classes with a Corvette in them."""
    rows = _dedupe(rows)
    out = {}
    for cls in dict.fromkeys(r.get("car_class") for r in rows):
        cars = [r for r in rows if r.get("car_class") == cls]
        ours = [r for r in cars if MAKE.search(r.get("vehicle") or "")]
        if not ours:
            continue
        laps = sorted(r["fl_time_s"] for r in cars if r.get("fl_time_s"))
        best = laps[0] if laps else None
        w = cars[0]
        out[cls] = {
            "entries": len(cars),
            "winner": {"car": w["car_number"], "team": w.get("team"), "vehicle": w.get("vehicle"), "laps": w.get("laps_completed")},
            "best_lap": best,
            "corvettes": [{
                "car": r["car_number"], "team": r.get("team"), "class_pos": cars.index(r) + 1,
                "status": "Classified" if _finished(r, w) else ("DSQ" if (r.get("status") or "").upper() == "DSQ" else "Retired"),
                "laps": r.get("laps_completed"),
                "laps_down": (w.get("laps_completed") or 0) - (r.get("laps_completed") or 0),
                "best_lap": r.get("fl_time_s"),
                "pace_pct": round((r["fl_time_s"] - best) / best * 100, 3) if best and r.get("fl_time_s") else None,
                "pace_rank": laps.index(r["fl_time_s"]) + 1 if r.get("fl_time_s") in laps else None,
                "drivers": [" ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) for d in r.get("drivers") or []
                            ] if isinstance(r.get("drivers"), list) else r.get("drivers"),
            } for r in ours],
        }
    return out


# Unofficial points, computed from results (OpenWEC has no standings). WEC, ELMS and Asian LMS all use
# 25-18-15-12-10-8-6-4-2-1 for the top 10 classified in class plus 1 for class pole; Le Mans counts double in
# WEC (pole point included only if the series doubles it: checked against the official tables).
SCALE = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
# Series whose computed points matched the official tables (2026-10-06): WEC LMGT3 exactly (with poles),
# ELMS LMGT3 on race points (poles from overrides). Asian LMS did not match (entries outside the teams
# championship, post-race changes, extra points), so it shows results and pace only.
# The series' own classes. OpenWEC files support races (one-make cups) under the same event as
# "Race 1"/"Race 2"; races without any of these classes are dropped.
SERIES_CLASSES = {"WEC": {"HYPERCAR", "LMP2", "LMGT3"}, "ELMS": {"LMP2", "LMP2 PRO/AM", "LMP3", "LMGT3"},
                  "ALMS": {"LMP2", "LMP3", "GT"}}
POINTS_SERIES = {s.strip().upper() for s in os.environ.get("OPENWEC_POINTS_SERIES", "WEC,ELMS").split(",") if s.strip()}
DOUBLE = {"WEC": re.compile(r"le mans", re.I)}


def _class_rows(rows, cls):
    return [r for r in _dedupe(rows) if r.get("car_class") == cls]


def _pole_session(sessions, race, cls):
    """The session that set this race's grid for the class: Hyperpole (last one) > class qualifying >
    overall qualifying. Asian LMS race 2 uses the '2nd Best Lap' qualifying."""
    quali = [s for s in sessions if (s.get("session_type") or "") in ("Qualifying", "Hyperpole")]
    if re.search(r"race 2", race.get("name") or "", re.I):
        second = [s for s in quali if re.search(r"2nd best", s.get("name") or "", re.I)]
        if second:
            return second[-1]
    quali = [s for s in quali if not re.search(r"2nd best", s.get("name") or "", re.I)]
    for kind in ("Hyperpole", "Qualifying"):
        named = [s for s in quali if s["session_type"] == kind and re.search(rf"\b{re.escape(cls)}\b", s.get("name") or "", re.I)]
        if named:
            return named[-1]
    plain = [s for s in quali if (s.get("name") or "").strip().lower() == "qualifying"]
    return plain[-1] if plain else None


def points(key, event_name, sessions, race, rows, season_cars=None, pole_override=None):
    """{class: {car: {"pts": n, "pole": bool, "team": .., "vehicle": ..}}} for one race.

    season_cars: in WEC, Le Mans one-off entries don't score and the points pass to the season entries
    behind them (checked against the official 2026 LMGT3 Teams table). pole_override: {class: car} set by
    hand, because OpenWEC's qualifying sessions carry no times."""
    double = bool(DOUBLE.get(key) and DOUBLE[key].search(event_name or ""))
    mult = 2 if double else 1
    out = {}
    for cls in dict.fromkeys(r.get("car_class") for r in _dedupe(rows)):
        cars = _class_rows(rows, cls)
        got = {}
        classified = [r for r in cars if cars and _finished(r, cars[0])
                      and (not double or season_cars is None or str(r["car_number"]) in season_cars)]
        for i, r in enumerate(classified[:len(SCALE)]):
            got[str(r["car_number"])] = SCALE[i] * mult
        pole_car = (pole_override or {}).get(cls)
        ps = None if pole_car else _pole_session(sessions, race, cls)
        if ps:
            try:
                q = [r for r in _class_rows(_results(ps["id"]), cls) if r.get("position")]
                pole_car = str(q[0]["car_number"]) if q else None
            except Exception:
                log.exception("openwec pole %s %s", key, ps.get("name"))
        out[cls] = {str(r["car_number"]): {"pts": got.get(str(r["car_number"]), 0) + (1 if str(r["car_number"]) == pole_car else 0),
                                           "pole": str(r["car_number"]) == pole_car, "team": r.get("team"), "vehicle": r.get("vehicle")}
                    for r in cars}
    return out


def standings(rounds, scoring=None):
    """Per class: every scoring car's unofficial total, sorted. races[i] is the car's points in the i-th
    race of the season (None = didn't take part), so the columns line up round by round. Cars outside
    `scoring` (WEC's Le Mans one-off entries) aren't in the table at all."""
    races = [race for rd in rounds for race in rd["races"]]
    tot = {}
    for i, race in enumerate(races):
        for cls, cars in (race.get("points") or {}).items():
            for car, p in cars.items():
                if scoring is not None and car not in scoring:
                    continue
                t = tot.setdefault(cls, {}).setdefault(car, {"car": car, "team": p["team"], "vehicle": p["vehicle"], "pts": 0,
                                                             "races": [None] * len(races)})
                t["pts"] += p["pts"]
                t["races"][i] = p["pts"]
    return {cls: sorted(cars.values(), key=lambda c: -c["pts"]) for cls, cars in tot.items()}


def _season(key):
    seasons = sorted({s["year"] for s in _get(f"series/{key.lower()}/seasons")})
    year = datetime.now(timezone.utc).year
    return max(y for y in seasons if y <= year) if seasons else None


def collect_series(key):
    year = _season(key)
    if not year:
        return None
    rounds = []
    for ev in _get(f"series/{key.lower()}/seasons/{year}/events"):
        all_sessions = _get(f"series/{key.lower()}/seasons/{year}/events/{ev['id']}/sessions")
        races = [s for s in all_sessions if (s.get("session_type") or "").lower() == "race" and not s.get("snapshot_hour")]
        if not races:
            continue                                    # tests / prologues
        sessions = []
        for s in races:
            try:
                rows = _results(s["id"])
            except Exception:
                log.exception("openwec %s %s %s", key, ev.get("name"), s.get("name"))
                continue
            own = SERIES_CLASSES.get(key)
            if rows and own and not any((r.get("car_class") or "").upper() in own for r in rows):
                continue                                # a support series' race on the same weekend
            if rows:
                sessions.append({"session": s.get("name"), "start": s.get("session_at"), "classes": race_summary(rows),
                                 "_rows": rows, "_sessions": all_sessions, "_race": s})
        rounds.append({"round": ev.get("round"), "event": (ev.get("name") or "").title(), "_name": ev.get("name"), "races": sessions})
    rounds.sort(key=lambda r: r.get("round") or 0)
    # Season entries: cars that ran a race other than the double-points one (Le Mans).
    dbl = DOUBLE.get(key)
    season_cars = {str(r["car_number"]) for rd in rounds if not (dbl and dbl.search(rd["_name"] or ""))
                   for race in rd["races"] for r in race["_rows"]} or None
    non_season = ({str(r["car_number"]) for rd in rounds for race in rd["races"] for r in race["_rows"]} - season_cars
                  if season_cars else set())
    poles = (read("overrides.json") or {}).get("poles", {})
    for rd in rounds:
        for race in rd["races"]:
            ov = poles.get(f"{key} {year} {rd['round']}" + (f" {race['session']}" if len(rd["races"]) > 1 else ""), {})
            try:
                race["points"] = points(key, rd["_name"], race.pop("_sessions"), race.pop("_race"), race.pop("_rows"),
                                        season_cars, ov)
            except Exception:
                log.exception("openwec points %s %s", key, rd["event"])
        rd.pop("_name", None)
    if key not in POINTS_SERIES:
        for rd in rounds:
            for race in rd["races"]:
                race.pop("points", None)
    return {"series": key, "season": year, "rounds": rounds,
            "standings": standings(rounds, season_cars if DOUBLE.get(key) else None) if key in POINTS_SERIES else None,
            "one_off": sorted({str(r) for r in (non_season or [])}),
            "poles_set": sorted(k for k in (read("overrides.json") or {}).get("poles", {}) if k.startswith(f"{key} {year}"))}


def refresh(force=False):
    """Once a day (or forced). Keeps the previous series.json if OpenWEC is down."""
    if not force and time.time() - _last[0] < EVERY:
        return None
    # Counts as done for the day only once something was written; after a failure (network, DNS), retry
    # in an hour rather than tomorrow.
    _last[0] = time.time() - EVERY + RETRY
    names = {s["key"]: s["name"] for s in _get("series")}
    out = []
    for key in SERIES:
        try:
            doc = collect_series(key)
            if doc:
                out.append({**doc, "name": names.get(key, key)})
        except Exception:
            log.exception("openwec %s failed", key)
            prev = next((x for x in (read("series.json") or {}).get("series", []) if x.get("series") == key), None)
            if prev:
                out.append(prev)                        # keep the last good copy of this series
    if out:
        _last[0] = time.time()
        write("series.json", {"updated": now_iso(), "source": "OpenWEC (api.openwec.com)", "series": out})
        log.info("openwec: %s", ", ".join(f"{s['series']} {s['season']} {sum(bool(r['races']) for r in s['rounds'])}/{len(s['rounds'])} rounds"
                                         for s in out))
    return out
