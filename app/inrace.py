"""In-race prediction: where each car is likely to finish from here, given the race so far.

For each class we take the gap to the class leader (laps down at the class pace), add the pit stops a car
still owes against the others (from the live strategy model), and project the rest of the race with each
car's pace against the class on the same recent green-flag laps (half weight, capped at 1 s/lap: pace
regresses; comparing on the same laps keeps it right through a wet restart or a tyre gamble). The spread of what can still happen and the
chance of retiring come from Petit Le Mans 2021-2025 (Al Kamel time cards):
  - how far a car's gap to the class leader moves over the remaining hours (robust spread, s per sqrt hour)
  - retirements per hour, by class
The pre-race model's strength is blended in early on, fading out as the race goes on.
"""

import math
import random
import re
import statistics

from predict import summarise, title_base

# Calibrated on Petit Le Mans 2021-2025 (seconds of gap movement per sqrt(hour left); retirements per hour).
SPREAD = {"GTP": 22, "LMP2": 40, "GTDPRO": 18, "GTD": 28}
RETIRE = {"GTP": 0.010, "LMP2": 0.023, "GTDPRO": 0.013, "GTD": 0.032}
PACE_WEIGHT = 0.5
MAX_PACE = 1.0            # s/lap: bigger differences are usually damage or a slow stint, not the car


def secs(t):
    try:
        v = 0.0
        for p in str(t).split(":"):
            v = v * 60 + float(p)
        return v
    except ValueError:
        return None


def gap_of(row, lap):
    if row.get("class_pos") == 1:
        return 0.0
    g = str(row.get("gap") or "").strip()
    m = re.match(r"-?(\d+) laps?", g)
    if m:
        return int(m.group(1)) * lap
    return secs(g) or 0.0


def recent_pace(d, n=None):
    """Median clean lap (no in/out laps, nothing over 107% of the car's best) over the whole race so far,
    so every driver in the line-up counts, not just whoever is in the car now."""
    if not d or not d.get("laps"):
        return None
    pit = set(x for s in d.get("stops", []) for x in (s, s + 1))
    laps = [(k, t) for k, t in d["laps"] if k > 1 and k not in pit and t]
    if len(laps) < 5:
        return None
    best = min(t for _, t in laps)
    clean = [t for _, t in laps if t <= best * 1.07]
    return (statistics.median(clean), len(clean)) if len(clean) >= 10 else None


def relative_pace(lapsCls, flags, rows, recent=15):
    """Each car's pace against the class on the same laps: median of (its lap - the class median on that
    lap number) over its last `recent` green-flag laps, in- and out-laps left out. Works whatever the
    conditions (a wet restart, slicks vs wets) because every car is compared on the same laps.
    Returns {car: (seconds per lap, laps used)} and the class's current lap time."""
    lead = max((int(r.get("laps") or 0) for r in rows), default=0)
    def flag_at(lap):
        k = "green"
        for l, kind in flags or []:
            if l <= lap:
                k = kind
            else:
                break
        return k
    good = {}
    for r in rows:
        d = lapsCls.get(r["car"]) or {}
        down = lead - int(r.get("laps") or 0)
        pit = {x for s in d.get("stops", []) for x in (s, s + 1, s + 2)}
        good[r["car"]] = [(k, t) for k, t in d.get("laps", []) if k > 1 and k not in pit and t and t < 400 and flag_at(k + down) == "green"]
    by_lap = {}
    for v in good.values():
        for k, t in v:
            by_lap.setdefault(k, []).append(t)
    med = {k: statistics.median(v) for k, v in by_lap.items() if len(v) >= 3}
    out = {}
    for car, v in good.items():
        deltas = [t - med[k] for k, t in v[-recent:] if k in med]
        if len(deltas) >= 5:
            out[car] = (statistics.median(deltas), len(deltas))
    last = [statistics.median([t for _, t in v[-5:]]) for v in good.values() if len(v) >= 3]
    return out, (statistics.median(last) if last else None)


def predict(live, laps, standings, quali, pre, n=20000, seed=11):
    """Odds for every class from the live state. pre: the pre-race prediction (for the blend)."""
    left = secs(live.get("remaining")) or 0
    elapsed = secs(live.get("elapsed")) or 0
    total = left + elapsed or 1
    hours_left = left / 3600
    rnd = random.Random(seed)
    out = {}
    for cls, lc in (live.get("classes") or {}).items():
        rows = [r for r in lc.get("cars", []) if r.get("class_pos")]
        if len(rows) < 2:
            continue
        lapsCls = (laps or {}).get("classes", {}).get(cls, {})
        rel, lap_now = relative_pace(lapsCls, (laps or {}).get("flags", {}).get(cls), rows)
        pn = {r["car"]: recent_pace(lapsCls.get(r["car"])) for r in rows}
        paces = {c: v and v[0] for c, v in pn.items()}
        known = [p for p in paces.values() if p]
        lap = lap_now or (statistics.median(known) if known else 90.0)   # laps left at the current conditions' pace
        loss = lc.get("pit_loss") or 60
        # Stops owed by fuel in hand (laps to go minus laps left, in standard class tanks), not by the timing
        # of recent stops: tyre-only stops (wets to slicks) don't make the others look like they owe one.
        owes = {r["car"]: r.get("owes_stop") or 0 for r in rows}
        tanks = [r["energy"]["full_tank_laps"] for r in rows if (r.get("energy") or {}).get("full_tank_laps")]
        if len(tanks) >= len(rows) / 2:
            tank = statistics.median(tanks)
            to_go = left / lap
            need = {r["car"]: max(0.0, (to_go - (tank if r.get("in_pit") else r["energy"]["laps_left"])) / tank)
                    for r in rows if (r.get("energy") or {}).get("laps_left") is not None}
            if need:
                least = min(need.values())
                owes = {c: round(need[c] - least, 2) if c in need else owes[c] for c in owes}
        base_owe = min(owes.values())
        laps_left = left / lap
        mean = {}
        for r in rows:
            c = r["car"]
            d = gap_of(r, lap) + (owes[c] - base_owe) * loss
            if c in rel:
                # Pace against the class on the same recent green laps (full weight from 15 laps).
                d += PACE_WEIGHT * min(1, rel[c][1] / 15) * max(-MAX_PACE, min(MAX_PACE, rel[c][0])) * laps_left
            mean[c] = d
        # Pre-race strength, converted to seconds and fading out by half-race.
        pre_cls = (pre or {}).get("classes", {}).get(cls)
        fade = max(0.0, 1 - elapsed / (0.5 * total))
        if pre_cls and fade:
            exp = {x["car"]: x["expected"] for x in pre_cls["cars"]}
            avg = statistics.mean(exp.values())
            for c in mean:
                if c in exp:
                    mean[c] += fade * (exp[c] - avg) * 10     # ~10 s per expected place
        sd = SPREAD.get(cls, 30) * math.sqrt(max(hours_left, 0.02)) + 3
        p_out = 1 - math.exp(-RETIRE.get(cls, 0.02) * hours_left)
        cars = [{"car": r["car"], "team": ""} for r in sorted(rows, key=lambda r: r["class_pos"])]
        mu = [mean[c["car"]] for c in cars]
        k = len(cars)

        def sample():
            v = [mu[i] + rnd.gauss(0, sd) + (1e6 * rnd.random() if rnd.random() < p_out else 0) for i in range(k)]
            return sorted(range(k), key=lambda i: v[i])

        extra = [{"now": i + 1, "pace": round(paces[c["car"]], 3) if paces[c["car"]] else None,
                  "rel_pace": round(rel[c["car"]][0], 2) if c["car"] in rel else None,
                  "proj_gap": round(mean[c["car"]], 1)} for i, c in enumerate(cars)]
        res = summarise(cars, sample, title_base(cls, standings, quali), n, extra)
        team = {x["car"]: x.get("team", "") for x in (pre_cls or {}).get("cars", [])}
        for x in res["cars"]:
            x["team"] = team.get(x["car"], "")
        out[cls] = res
    return out
