"""Per-race history for the tracked cars, from Al Kamel's post-race JSON files.

For every WeatherTech race this season we read the results, starting grid, pit stop
time cards and lap time cards, and keep a small summary per tracked car plus the
class-wide stint lengths (used as the pit-window baseline for the next visit to the
same track). Each race is summarised once and cached in DATA_DIR/history/.
"""

import csv
import io
import json
import logging
import re
import statistics
from urllib.parse import quote, unquote

log = logging.getLogger("scraper.history")

FILES = {
    "results": r"03_Results_Race_(Official|Provisional|Unofficial)\.JSON",
    "grid": r"02_Grid_Race_(Official|Provisional)\.CSV",
    "pits": r"20_Pit Stops Time Cards_Race\.JSON",
    "laps": r"23_Time Cards_Race(_Unofficial)?\.JSON",
}
RANK = {"Official": 0, "Provisional": 1, "Unofficial": 2, None: 3}


def secs(t):
    """'1:23.456' / '1:02:03.4' / '83.4' -> seconds."""
    if not t:
        return None
    total = 0.0
    try:
        for part in str(t).split(":"):
            total = total * 60 + float(part)
    except ValueError:
        return None
    return total


def clock(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def pct(values, p):
    v = sorted(values)
    return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))] if v else None


def race_files(html, series):
    """Pick the final copy of each file for the WeatherTech race session on an event page."""
    links = [unquote(h) for h in re.findall(r'href="([^"]+)"', html)]
    best, pits = {}, []
    for link in links:
        if f"_{series}/" not in link or not re.search(r"_Race/", link):
            continue
        hour = re.search(r"/(\d+)_Hour \d+/", link)
        if re.search(rf"/{FILES['pits']}$", link):
            pits.append(link)  # hourly folders each hold only that hour's stops
            continue
        for key, pattern in FILES.items():
            m = re.search(rf"/{pattern}$", link)
            if not m:
                continue
            status = m.group(1).strip("_") if m.groups() and m.group(1) else None
            # Endurance races publish hourly snapshots; top level or the last hour wins,
            # then the most official version.
            score = (0 if not hour else 1, -(int(hour.group(1)) if hour else 0), RANK.get(status, 3))
            if key not in best or score < best[key][0]:
                best[key] = (score, link, status)
    out = {k: (link, status) for k, (score, link, status) in best.items()}
    if pits:
        out["pits"] = (sorted(set(pits)), None)
    return out


def _json(http, base, path):
    r = http.get(base + quote(path), timeout=120)
    r.raise_for_status()
    return json.loads(r.content.decode("utf-8-sig"))


def _stints(laps, stops=()):
    """Laps between stops; a stop is a lap that ends crossing the line in the pit lane."""
    ends = [int(l["number"]) for l in laps if l.get("crossing_pit_finish_lane")]
    out, prev = [], 0
    for n in ends:
        out.append(n - prev)
        prev = n
    if laps and int(laps[-1]["number"]) > prev:
        out.append(int(laps[-1]["number"]) - prev)  # run to the flag
    return ends, out


def _stop(lap_no, laps, stops):
    """A pit-in lap, with duration and driver from the pit stop time cards when they match."""
    lap = next(l for l in laps if int(l["number"]) == lap_no)
    t = clock(lap["hour"])
    match = next((s for s in stops if abs((clock(s["in_time"]) - t + 43200) % 86400 - 43200) < 120), None)
    return {"lap": lap_no, "time": match and match["pit_time"],
            "driver_out": match and f'{match["out_driver_firstname"]} {match["out_driver_surname"]}'}


def summarise(http, base, files, cars, classes):
    """Build one race's summary: tracked cars in detail, plus stint stats for each class."""
    results = _json(http, base, files["results"][0])
    pits = {}
    for path in files.get("pits", ([], None))[0]:
        for p in _json(http, base, path)["pit_stop_analysis"]:
            seen = pits.setdefault(p["number"], {})
            for stop in p.get("pit_stops", []):
                seen[stop["in_time"]] = stop
    pits = {n: sorted(v.values(), key=lambda s: s["in_time"]) for n, v in pits.items()}
    lapdata = {p["number"]: p for p in _json(http, base, files["laps"][0])["participants"]} if "laps" in files else {}

    grid = {}
    if "grid" in files:
        r = http.get(base + quote(files["grid"][0]), timeout=60)
        rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
        for cls in classes:
            for i, row in enumerate(x for x in rows if x.get("CLASS") == cls):
                grid[row["NUMBER"]] = i + 1

    session = results["session"]
    by_class = {}
    for row in results["classification"]:
        by_class.setdefault(row["class"], []).append(row)

    out = {"event": session.get("event_name"), "date": session.get("session_date"), "cars": {}, "class_stints": {}}
    for cls in classes:
        rows = by_class.get(cls, [])
        best = sorted(secs(r["fastest_lap_time"]) for r in rows if secs(r.get("fastest_lap_time")))
        full = []
        for r in rows:
            ends, stints = _stints(lapdata.get(r["number"], {}).get("laps", []))
            # Stints that ended in a stop; the run to the flag is usually a short fill.
            full += stints[:len(ends)]
        out["class_stints"][cls] = full
        for i, r in enumerate(rows):
            if r["number"] not in cars or cars[r["number"]] != cls:
                continue
            laps = lapdata.get(r["number"], {}).get("laps", [])
            stops = pits.get(r["number"], [])
            ends, stints = _stints(laps)
            names = {d["number"]: f'{d["firstname"]} {d["surname"]}' for d in lapdata.get(r["number"], {}).get("drivers", [])}
            drivers = {}
            for l in laps:
                d = drivers.setdefault(names.get(int(l["driver_number"]), l["driver_number"]), [])
                if l.get("is_valid") and secs(l["time"]):
                    d.append(secs(l["time"]))
            fl = secs(r.get("fastest_lap_time"))
            out["cars"][r["number"]] = {
                "class_pos": i + 1,
                "class_entries": len(rows),
                "grid": grid.get(r["number"]),
                "status": r["status"],
                "laps": int(r["laps"] or 0),
                "best_lap": r.get("fastest_lap_time"),
                "best_lap_rank": best.index(fl) + 1 if fl in best else None,
                "stops": [_stop(n, laps, stops) for n in ends],
                "stints": stints,
                "drivers": [{"name": n, "laps": sum(1 for l in laps if names.get(int(l["driver_number"])) == n),
                             "median_lap": round(statistics.median(t), 3) if t else None}
                            for n, t in drivers.items()],
            }
    out["results_status"] = files["results"][1]
    out["results_path"] = files["results"][0]
    return out


def stint_model(stints):
    """Typical and long full-tank stint (laps) from a list of stint lengths."""
    long = pct([s for s in stints if s >= 5], 0.9)
    if not long:
        return None
    full = [s for s in stints if s >= 0.75 * long]
    return {"short": pct(full, 0.25), "typical": round(statistics.median(full)), "long": pct(full, 0.9),
            "sample": len(full)} if full else None


def update(http, base, page, options, data_dir, series, cars, classes, season=None, only=None):
    """Summarise any not-yet-cached (or since upgraded) races this season. Returns {event: summary}."""
    cache = data_dir / "history"
    cache.mkdir(parents=True, exist_ok=True)
    index = page()
    seasons, current = options(index, "season")
    season = season or current
    events, _ = options(page(season), "evvent")
    out = {}
    for event in only or events:
        path = cache / f"{season}__{event}.json"
        cached = json.loads(path.read_text()) if path.exists() else None
        if cached and cached.get("results_status") == "Official":
            out[event] = cached
            continue
        files = race_files(page(season, event), series)
        if "results" not in files:
            continue
        # During and just after a race the files are re-published hour by hour; redo when they move.
        if cached and cached.get("results_path") == files["results"][0] \
                and RANK[cached.get("results_status")] <= RANK[files["results"][1]]:
            out[event] = cached
            continue
        try:
            summary = summarise(http, base, files, cars, classes)
        except Exception:
            log.exception("history: %s %s failed", season, event)
            continue
        summary["round"] = event
        path.write_text(json.dumps(summary))
        log.info("history: %s %s (%s)", season, event, summary["results_status"])
        out[event] = summary
    return out
