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
                "status": r.get("status"), "laps": r.get("laps_completed"),
                "laps_down": (w.get("laps_completed") or 0) - (r.get("laps_completed") or 0),
                "best_lap": r.get("fl_time_s"),
                "pace_pct": round((r["fl_time_s"] - best) / best * 100, 3) if best and r.get("fl_time_s") else None,
                "pace_rank": laps.index(r["fl_time_s"]) + 1 if r.get("fl_time_s") in laps else None,
                "drivers": [" ".join(x for x in (d.get("first_name"), d.get("last_name")) if x) for d in r.get("drivers") or []
                            ] if isinstance(r.get("drivers"), list) else r.get("drivers"),
            } for r in ours],
        }
    return out


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
        races = [s for s in _get(f"series/{key.lower()}/seasons/{year}/events/{ev['id']}/sessions")
                 if (s.get("session_type") or "").lower() == "race" and not s.get("snapshot_hour")]
        sessions = []
        for s in races:
            try:
                classes = race_summary(_results(s["id"]))
            except Exception:
                log.exception("openwec %s %s %s", key, ev.get("name"), s.get("name"))
                continue
            if classes:
                sessions.append({"session": s.get("name"), "start": s.get("session_at"), "classes": classes})
        rounds.append({"round": ev.get("round"), "event": (ev.get("name") or "").title(), "races": sessions})
    return {"series": key, "season": year, "rounds": sorted(rounds, key=lambda r: r.get("round") or 0)}


def refresh(force=False):
    """Once a day (or forced). Keeps the previous series.json if OpenWEC is down."""
    if not force and time.time() - _last[0] < EVERY:
        return None
    _last[0] = time.time()
    names = {s["key"]: s["name"] for s in _get("series")}
    out = []
    for key in SERIES:
        try:
            doc = collect_series(key)
            if doc:
                out.append({**doc, "name": names.get(key, key)})
        except Exception:
            log.exception("openwec %s failed", key)
    if out:
        write("series.json", {"updated": now_iso(), "source": "OpenWEC (api.openwec.com)", "series": out})
        log.info("openwec: %s", ", ".join(f"{s['series']} {s['season']} {sum(bool(r['races']) for r in s['rounds'])}/{len(s['rounds'])} rounds"
                                         for s in out))
    return out
