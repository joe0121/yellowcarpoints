"""In-race prediction: where each car is likely to finish from here, given the race so far.

For each class we take the gap to the class leader (laps down at the class pace), add the pit stops a car
still owes against the others (from the live strategy model), and project the rest of the race with each
car's median clean lap so far (half weight, capped at 1 s/lap: pace regresses). The spread of what can still happen and the
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
        pn = {r["car"]: recent_pace(lapsCls.get(r["car"])) for r in rows}
        paces = {c: v and v[0] for c, v in pn.items()}
        known = [p for p in paces.values() if p]
        lap = statistics.median(known) if known else 90.0
        loss = lc.get("pit_loss") or 60
        owes = {r["car"]: r.get("owes_stop") or 0 for r in rows}
        base_owe = min(owes.values())
        laps_left = left / lap
        mean = {}
        for r in rows:
            c = r["car"]
            d = gap_of(r, lap) + (owes[c] - base_owe) * loss
            if paces[c]:
                # Trust pace more as clean laps pile up (full weight from 100 laps).
                d += PACE_WEIGHT * min(1, pn[c][1] / 100) * max(-MAX_PACE, min(MAX_PACE, paces[c] - lap)) * laps_left
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
                  "proj_gap": round(mean[c["car"]], 1)} for i, c in enumerate(cars)]
        res = summarise(cars, sample, title_base(cls, standings, quali), n, extra)
        team = {x["car"]: x.get("team", "") for x in (pre_cls or {}).get("cars", [])}
        for x in res["cars"]:
            x["team"] = team.get(x["car"], "")
        out[cls] = res
    return out
