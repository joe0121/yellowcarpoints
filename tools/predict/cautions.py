import json, glob, statistics
from model import secs
def periods_from_flags(laps):
    ev = sorted((secs(e), f) for _, _, _, _, e, f, _ in laps if secs(e))
    out, cur = [], None
    for t, f in ev:
        y = f in ("FCY", "SC")
        if y and cur is None: cur = [t, t]
        elif y: cur[1] = t
        elif cur is not None and f == "GF":
            out.append(cur); cur = None
    if cur: out.append(cur)
    # merge periods split by a stray green crossing (< 60 s apart)
    m = []
    for p in out:
        if m and p[0] - m[-1][1] < 60: m[-1][1] = p[1]
        else: m.append(p)
    return [p for p in m if p[1] - p[0] > 90]
def periods_from_times(laps):
    """No flag column: a caution is when the top class's laps (no pit laps) run >30% over green pace for 2+ minutes."""
    cls_counts = {}
    for l in laps: cls_counts[l[1]] = cls_counts.get(l[1], 0) + 1
    top = [l for l in laps if l[1] in ("GTP", "DPi", "P")] or laps
    pts = sorted((secs(l[4]), secs(l[3])) for l in top if secs(l[3]) and secs(l[4]) and not l[6].strip())
    green = statistics.median(sorted(x for _, x in pts)[: len(pts) // 2])
    # rolling: median lap time of crossings within a 90 s window
    out, cur = [], None
    for i, (t, lt) in enumerate(pts):
        win = [x for tt, x in pts[max(0, i - 15): i + 15] if abs(tt - t) < 90]
        slow = statistics.median(win) > green * 1.3
        if slow and cur is None: cur = [t - statistics.median(win), t]
        elif slow: cur[1] = t
        elif cur is not None: out.append(cur); cur = None
    if cur: out.append(cur)
    m = []
    for p in out:
        if m and p[0] - m[-1][1] < 120: m[-1][1] = p[1]
        else: m.append(p)
    return [p for p in m if p[1] - p[0] > 150]
def leader_lap_at(laps, t):
    """Overall leader's lap at elapsed time t (max lap any car had completed)."""
    return max((l[2] for l in laps if secs(l[4]) and secs(l[4]) <= t), default=0)
races = {}
for f in sorted(glob.glob("plm/*.json")):
    d = json.load(open(f)); y = d["season"][3:]
    truth = periods_from_flags(d["laps"]) if d["has_flag"] else None
    guess = periods_from_times(d["laps"])
    races[y] = {"truth": truth, "guess": guess, "laps": d["laps"]}
    fmt = lambda ps: [(round(a/3600, 2), round((b-a)/60, 1)) for a, b in ps]
    print(y, "truth", len(truth) if truth is not None else "-", "guess", len(guess))
    if truth is not None:
        print("   T", fmt(truth)); print("   G", fmt(guess))
