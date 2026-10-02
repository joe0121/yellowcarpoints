"""Caution history for this weekend's race: past editions' full-course cautions, from Al Kamel time cards.

The CSV time cards carry the flag at the finish line for every lap (FLAG_AT_FL, from 2021). Older years
have no flag column: there a caution is when the top class runs 30%+ off green pace for over 2.5
minutes (checked against 2021-2025 Petit Le Mans: it found 40 of the 43 cautions; back-to-back
cautions merge). Each edition is downloaded once and cached.
"""

import bisect
import csv
import io
import json
import logging
import re
import statistics
from pathlib import Path
from urllib.parse import unquote

from predict import CACHE, _get, options, secs

log = logging.getLogger("analyst.cautions")
CARDS = CACHE.parent / "timecards"
ALIASES = {"Road Atlanta": ["Road Atlanta", "Petit Le Mans"]}
FIRST_SEASON = 2016


def _edition(season, names):
    """Compact laps [car, class, lap, lap time, elapsed, flag, in pit] for the race at this track."""
    fn = CARDS / f"{season}.json"
    if fn.exists():
        return json.loads(fn.read_text())
    evs = [e for e in options(_get({"season": season}).text, "evvent") if any(n.lower() in e.lower() for n in names)]
    doc = {"season": season, "laps": None}
    if evs:
        html = _get({"season": season, "evvent": evs[-1]}).text
        best = None
        for link in (unquote(h) for h in re.findall(r'href="([^"]+)"', html)):
            if "WeatherTech" in link and "_Race/" in link and re.search(r"/23_Time Cards_Race[^/]*\.CSV$", link):
                hr = re.search(r"/(\d+)_Hour \d+/", link)
                key = (0 if not hr else 1, -(int(hr.group(1)) if hr else 0), "Unofficial" in link)
                if best is None or key < best[0]:
                    best = (key, link)
        if best:
            rows = csv.reader(io.StringIO(_get(path=best[1]).content.decode("utf-8-sig", "replace")), delimiter=";")
            head = [h.strip() for h in next(rows)]
            ix = {h: i for i, h in enumerate(head)}
            g = lambda r, k: r[ix[k]].strip() if k in ix and ix[k] < len(r) else ""
            doc = {"season": season, "event": evs[-1], "has_flag": "FLAG_AT_FL" in ix,
                   "laps": [[g(r, "NUMBER"), g(r, "CLASS"), int(g(r, "LAP_NUMBER") or 0), g(r, "LAP_TIME"), g(r, "ELAPSED"),
                             g(r, "FLAG_AT_FL"), g(r, "CROSSING_FINISH_LINE_IN_PIT")] for r in rows if len(r) >= len(head) - 1]}
    CARDS.mkdir(parents=True, exist_ok=True)
    fn.write_text(json.dumps(doc))
    return doc


def _merge(periods, gap):
    m = []
    for p in periods:
        if m and p[0] - m[-1][1] < gap:
            m[-1][1] = p[1]
        else:
            m.append(list(p))
    return m


def from_flags(laps):
    out, cur = [], None
    for t, f in sorted((secs(l[4]), l[5]) for l in laps if secs(l[4])):
        y = f in ("FCY", "SC")
        if y and cur is None:
            cur = [t, t]
        elif y:
            cur[1] = t
        elif cur is not None and f == "GF":
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return [p for p in _merge(out, 60) if p[1] - p[0] > 90]


def from_times(laps):
    top = [l for l in laps if l[1] in ("GTP", "DPi", "P")] or laps
    pts = sorted((secs(l[4]), secs(l[3])) for l in top if secs(l[3]) and secs(l[4]) and not l[6].strip())
    if len(pts) < 50:
        return []
    green = statistics.median(sorted(x for _, x in pts)[: len(pts) // 2])
    out, cur = [], None
    for i, (t, _) in enumerate(pts):
        win = statistics.median(x for tt, x in pts[max(0, i - 15): i + 15] if abs(tt - t) < 90)
        if win > green * 1.3:
            cur = [t - win, t] if cur is None else [cur[0], t]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return [p for p in _merge(out, 120) if p[1] - p[0] > 150]


def history(track, season, race_secs):
    """insights.json for this track: every past edition with a time card, newest last."""
    names = ALIASES.get(track, [track])
    years = []
    for y in range(FIRST_SEASON, int(season)):
        try:
            d = _edition(f"{y % 100:02d}_{y}", names)
        except Exception:
            log.exception("time cards %s", y)
            continue
        if not d.get("laps"):
            continue
        ps = from_flags(d["laps"]) if d["has_flag"] else from_times(d["laps"])
        cr = sorted((secs(l[4]), l[2]) for l in d["laps"] if secs(l[4]))
        ts, best, m = [t for t, _ in cr], [], 0
        for _, n in cr:
            m = max(m, n)
            best.append(m)
        lap_at = lambda t: best[max(0, bisect.bisect_right(ts, t) - 1)]
        years.append({"year": y, "source": "flags" if d["has_flag"] else "lap times", "laps": max(best),
                      "cautions": [{"start": round(a), "mins": round((b - a) / 60, 1), "lap": lap_at(a), "end_lap": max(lap_at(b), lap_at(a) + 1)}
                                   for a, b in ps if a < race_secs + 600]})
    if not years:
        return None
    hours = max(1, round(race_secs / 3600))
    n = [len(y["cautions"]) for y in years]
    mins = [sum(c["mins"] for c in y["cautions"]) for y in years]
    lens = [c["mins"] for y in years for c in y["cautions"]] or [0]
    first = [y["cautions"][0]["start"] / 60 for y in years if y["cautions"]] or [0]
    hour = lambda c: min(hours - 1, int(c["start"] // 3600))
    any_in = [sum(1 for y in years if any(hour(c) == h for c in y["cautions"])) / len(years) for h in range(hours)]
    return {"track": track, "event": track, "years": years, "summary": {
        "races": len(years), "avg_cautions": round(statistics.mean(n), 1), "min_cautions": min(n), "max_cautions": max(n),
        "avg_caution_mins": round(statistics.mean(mins)), "pct_under_caution": round(statistics.mean(mins) / (race_secs / 60) * 100, 1),
        "avg_length_mins": round(statistics.mean(lens), 1),
        "avg_caution_laps": round(statistics.mean(sum(c["end_lap"] - c["lap"] for c in y["cautions"]) for y in years)),
        "median_first_caution_mins": round(statistics.median(first)),
        "first_hour_pct": round(100 * sum(1 for f in first if f < 60) / len(years)),
        "last_hour_pct": round(100 * any_in[-1]),
        "per_hour": [round(sum(1 for y in years for c in y["cautions"] if hour(c) == h) / len(years), 2) for h in range(hours)],
        "any_in_hour": [round(x, 2) for x in any_in]}}
