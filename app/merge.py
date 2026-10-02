"""Fill the gap a scraper restart leaves, from another recorder's data (the dev scraper).

`./dev.sh fill-gap` drops the dev scraper's race_state.json and telemetry_state.json into this
scraper's data folder as merge_race.json / merge_telemetry.json. On its next poll the scraper merges
them into what it already has (only adding what's missing, never replacing) and deletes the files.
Both must be for the same session, or they're ignored.
"""

import logging

from common import DATA_DIR, read

log = logging.getLogger("scraper.merge")


def _by(items, key):
    out = {}
    for it in items:
        out.setdefault(key(it), it)
    return out


def _union_laps(a, b):
    """[[lap, value], ...] lists: keep ours, add the other's laps we don't have."""
    have = {r[0] for r in a}
    return sorted(a + [r for r in b if r[0] not in have], key=lambda r: r[0])


def clean_events(ev):
    """Drop duplicates a gap leaves: one 's' per stop number (earliest lap), and driver / position
    changes that don't follow on from the previous one (the late, gap-spanning copy)."""
    out, stops, last = [], set(), {}
    for e in ev:
        lap, kind, a, b = e
        if kind == "s":
            if a in stops:
                continue
            stops.add(a)
        elif kind in ("d", "p"):
            if kind in last and last[kind] != a:
                continue
            last[kind] = b
        out.append(e)
    return out


def merge_race(state, other):
    """Add the other recorder's laps, stops, events, gaps, drive time, flags and margins to ours."""
    added = 0
    for car, o in other.get("cars", {}).items():
        st = state["cars"].get(car)
        if st is None:
            state["cars"][car] = o
            added += len(o.get("laps", []))
            continue
        n = len(st.get("laps", []))
        st["laps"] = _union_laps(st.get("laps", []), o.get("laps", []))
        st["gaps"] = _union_laps(st.get("gaps", []), o.get("gaps", []))
        added += len(st["laps"]) - n
        st["stops"] = sorted(set(st.get("stops", [])) | set(o.get("stops", [])))
        st["ps"] = max(st.get("ps", 0), o.get("ps", 0))
        st["from_start"] = st.get("from_start") or o.get("from_start")
        # Events: both logs in their own order (stable sort by lap), exact duplicates removed, then
        # the gap's late copies dropped.
        seen, ev = set(), []
        for e in sorted(st.get("ev", []) + o.get("ev", []), key=lambda e: e[0]):
            if tuple(e) not in seen:
                seen.add(tuple(e))
                ev.append(list(e))
        st["ev"] = clean_events(ev)
        # Stops: one per stop number, at its earliest lap (a stop made during a gap is logged late).
        stop_laps = {}
        for e in st["ev"]:
            if e[1] == "s":
                stop_laps[e[2]] = min(stop_laps.get(e[2], e[0]), e[0])
        st["stops"] = sorted(stop_laps.values()) if stop_laps else sorted(set(st.get("stops", [])) | set(o.get("stops", [])))
        # Drive time: each recorder only undercounts (it misses its own downtime), so take the larger.
        drive = dict(st.get("drive", {}))
        for d, secs in o.get("drive", {}).items():
            drive[d] = max(drive.get(d, 0), secs)
        st["drive"] = drive
    for cls, fl in other.get("flags", {}).items():
        ours = state.setdefault("flags", {}).setdefault(cls, [])
        merged = sorted({tuple(f) for f in ours} | {tuple(f) for f in fl}, key=lambda f: f[0])
        # Drop repeats so each entry is a real change.
        state["flags"][cls] = [list(f) for i, f in enumerate(merged) if i == 0 or f[1] != merged[i - 1][1]]
    for car, rows in other.get("margins", {}).items():
        state.setdefault("margins", {})[car] = _union_laps(state["margins"].get(car, []), rows)
    return added


def merge_telemetry(cars, other_cars):
    """Add the other recorder's energy-by-lap, refuels and pit stops to ours."""
    for car, o in other_cars.items():
        st = cars.get(car)
        if st is None:
            cars[car] = o
            continue
        st["lap_energy"] = _union_laps(st.get("lap_energy", []), o.get("lap_energy", []))[-400:]
        st["refills"] = sorted(_by(st.get("refills", []) + o.get("refills", []), lambda r: r["lap"]).values(), key=lambda r: r["lap"])
        st["stops"] = sorted(_by(st.get("stops", []) + o.get("stops", []), lambda r: r["lap"]).values(), key=lambda r: r["lap"])[-20:]


def pending(state, telemetry):
    """Merge any waiting gap-fill files for this session, then remove them."""
    race = read("merge_race.json")
    if race is not None:
        if race.get("key") == state.get("key"):
            log.info("gap fill: added %d laps from the other recorder", merge_race(state, race))
        else:
            log.warning("gap fill skipped: recorded session %s, running %s", race.get("key"), state.get("key"))
        (DATA_DIR / "merge_race.json").unlink(missing_ok=True)
    tel = read("merge_telemetry.json")
    if tel is not None:
        with telemetry.lock:
            if tel.get("session_key") and telemetry.session_key and tuple(tel["session_key"]) == tuple(telemetry.session_key):
                merge_telemetry(telemetry.cars, tel.get("cars", {}))
                log.info("gap fill: telemetry merged for %d cars", len(tel.get("cars", {})))
            else:
                log.warning("gap fill: telemetry is for another session, skipped")
        (DATA_DIR / "merge_telemetry.json").unlink(missing_ok=True)
