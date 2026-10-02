"""Sector times per car from Al Kamel's time cards (IMSA's live feed carries none).

Al Kamel publishes a time card for each session when it ends, and hourly snapshots during
endurance races. For the latest WeatherTech session at the current event we take the newest
time card, and for every car in the tracked classes work out per sector: the best time, a
typical time (median of clean laps) and the ideal lap (sum of best sectors). The file is only
re-downloaded when its path or size changes.
"""

import json
import logging
import re
import statistics
from urllib.parse import quote, unquote

import history
from common import LIVE_CLASSES as CLASSES, http, now_iso, read, write

log = logging.getLogger("scraper.sectors")
TIME_CARDS = re.compile(r"/23_Time Cards_[^/]*\.JSON$")


def latest_time_card(page_html, series):
    """(session folder, file path, label) for the newest WeatherTech session that has a time card."""
    links = [unquote(h) for h in re.findall(r'href="([^"]+)"', page_html)]
    best = None
    for link in links:
        if f"_{series}/" not in link or not TIME_CARDS.search(link):
            continue
        m = re.search(rf"_{re.escape(series)}/(\d{{12}})_([^/]+)/(?:(\d+)_Hour (\d+)/)?", link)
        if not m:
            continue
        stamp, session, hour = m.group(1), m.group(2), int(m.group(4) or 0)
        # Newest session first; within it the top-level (final) file beats hourly snapshots,
        # and later hours beat earlier ones.
        key = (stamp, 1 if not m.group(3) else 0, hour)
        if best is None or key > best[0]:
            best = (key, link, session + (f" (hour {hour})" if hour else ""))
    return best and (best[1], best[2])


def summarise(data):
    out = {}
    for p in data.get("participants", []):
        if p.get("class") not in CLASSES or not p.get("laps"):
            continue
        laps = []
        for lap in p["laps"]:
            t = history.secs(lap.get("time"))
            secs = [history.secs(s.get("time")) for s in sorted(lap.get("sector_times", []), key=lambda s: s["index"])]
            if t and len(secs) == 3 and all(secs):
                laps.append((int(lap["number"]), t, secs, lap.get("crossing_pit_finish_lane") or not lap.get("is_valid", True)))
        if not laps:
            continue
        best_lap = min(t for _, t, _, _ in laps)
        # Clean laps: not lap 1, not a pit-lane lap or invalidated, within 105% of the car's best.
        clean = [s for n, t, s, flagged in laps if n > 1 and not flagged and t <= best_lap * 1.05]
        best = [min(s[i] for _, _, s, _ in laps) for i in range(3)]
        typical = [round(statistics.median(x[i] for x in clean), 3) for i in range(3)] if len(clean) >= 3 else None
        out[p["number"]] = {"cls": p["class"], "best": [round(b, 3) for b in best], "ideal": round(sum(best), 3),
                            "best_lap": round(best_lap, 3), "typical": typical, "clean_laps": len(clean), "laps": len(laps)}
    classes = {}
    for car, row in out.items():
        classes.setdefault(row.pop("cls"), {})[car] = row
    return {cls: {"cars": cars,
                  "fastest": [min(c["best"][i] for c in cars.values()) for i in range(3)],
                  "fastest_typical": [min((c["typical"][i] for c in cars.values() if c["typical"]), default=None) for i in range(3)]}
            for cls, cars in classes.items()}


def refresh(base, page, season, event, series):
    """Update sectors.json if a newer time card exists. Returns True when it changed."""
    found = latest_time_card(page(season, event), series)
    if not found:
        return False
    path, label = found
    head = http.head(base + quote(path), timeout=30)
    size = head.headers.get("Content-Length")
    old = read("sectors.json") or {}
    if old.get("path") == path and old.get("size") == size:
        return False
    data = json.loads(http.get(base + quote(path), timeout=120).content.decode("utf-8-sig"))
    write("sectors.json", {"updated": now_iso(), "event": event.split("_", 1)[1], "session": label,
                           "path": path, "size": size, "classes": summarise(data)})
    log.info("sectors: %s %s", event, label)
    return True
