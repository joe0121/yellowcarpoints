import json, statistics as st
from collections import defaultdict
exec(open("audit.py").read().split("# --- A. next stop lap")[0])

print("== 1. Fuel per minute and per lap: green vs yellow (laps with no stop, consecutive energy readings)")
gmin = defaultdict(list); ymin = defaultdict(list); glap = defaultdict(list); ylap = defaultdict(list)
for cls in ("GTP", "GTDPRO", "GTD"):
    cars = final["classes"][cls]; flags = final["flags"].get(cls); lead = max(len(d["laps"]) for d in cars.values())
    for car, d in cars.items():
        L = dict(d["laps"]); en = d.get("energy") or []; down = lead - len(d["laps"])
        pit = {x for s in d.get("stops", []) for x in (s - 1, s, s + 1, s + 2)}
        for (m, e0), (n, e) in zip(en, en[1:]):
            if n != m + 1 or n in pit or n not in L: continue
            drop, t = e0 - e, L[n]
            if not (0 < drop < 8) or not (40 < t < 400): continue
            k, k0 = flag_at(flags, n + down), flag_at(flags, m + down)
            if k == k0 == "green" and t < 120: gmin[cls].append(drop / t * 60); glap[cls].append(drop)
            elif k == k0 == "yellow": ymin[cls].append(drop / t * 60); ylap[cls].append(drop)
    g, y = st.median(gmin[cls]), st.median(ymin[cls])
    print(f"  {cls:6s} green {st.median(glap[cls]):.2f}%/lap = {g:.2f}%/min (full tank ~{100/g:.0f} min green) | yellow {st.median(ylap[cls]):.2f}%/lap = {y:.2f}%/min | a yellow minute uses {y/g:.0%} of a green minute (n={len(ymin[cls])})")

print("\n== 2. Green stint length (minutes of green running between stops, stints with no yellow)")
for cls in ("GTP", "GTDPRO", "GTD"):
    cars = final["classes"][cls]; flags = final["flags"].get(cls); lead = max(len(d["laps"]) for d in cars.values())
    mins = []
    for car, d in cars.items():
        L = dict(d["laps"]); down = lead - len(d["laps"]); stops = d.get("stops", [])
        for a, b in zip(stops, stops[1:]):
            laps = range(a + 2, b + 1)
            if len(laps) < 10 or any(flag_at(flags, n + down) != "green" for n in laps): continue
            mins.append(sum(L.get(n, 0) for n in range(a + 1, b + 1)) / 60)
    print(f"  {cls:6s} all-green stints: median {st.median(mins):.0f} min (10–90% {pct(mins,.1):.0f}..{pct(mins,.9):.0f}, n={len(mins)})" if mins else f"  {cls}: none")

print("\n== 3. Under a yellow: green minutes of fuel left vs whether the car pitted during that caution")
for cls in ("GTP", "GTDPRO", "GTD"):
    cars = final["classes"][cls]; flags = final["flags"].get(cls) or []; lead = max(len(d["laps"]) for d in cars.values())
    g = st.median(gmin[cls]); rows = []
    periods = [(l, flags[i + 1][0] if i + 1 < len(flags) else 10**6) for i, (l, k) in enumerate(flags) if k == "yellow"]
    for a, b in periods:
        for car, d in cars.items():
            down = lead - len(d["laps"]); en = dict(d.get("energy") or [])
            start = a - down
            e = en.get(start) or en.get(start - 1)
            if e is None: continue
            pitted = any(start <= s <= b - down for s in d.get("stops", []))
            rows.append((e / g, pitted))
    for lo, hi in ((0, 10), (10, 20), (20, 30), (30, 40), (40, 60), (60, 200)):
        sel = [p for m, p in rows if lo <= m < hi]
        if sel: print(f"  {cls:6s} {lo:>3}-{hi:<3} green min left: pitted {sum(sel)/len(sel):4.0%} (n={len(sel)})")

print("\n== 4. Fuel saving: within a stint, slower green laps vs fuel per lap (pace given up -> fuel saved)")
for cls in ("GTDPRO", "GTD", "GTP"):
    cars = final["classes"][cls]; flags = final["flags"].get(cls); lead = max(len(d["laps"]) for d in cars.values())
    xs, ys = [], []
    for car, d in cars.items():
        L = dict(d["laps"]); en = d.get("energy") or []; down = lead - len(d["laps"])
        pit = {x for s in d.get("stops", []) for x in (s - 1, s, s + 1, s + 2)}
        pts = [(L[n], e0 - e) for (m, e0), (n, e) in zip(en, en[1:]) if n == m + 1 and n not in pit and n in L and flag_at(flags, n + down) == flag_at(flags, m + down) == "green" and 0.5 < e0 - e < 6 and L[n] < 120]
        if len(pts) < 30: continue
        mt, mu = st.median(p[0] for p in pts), st.median(p[1] for p in pts)
        xs += [p[0] - mt for p in pts]; ys += [p[1] - mu for p in pts]
    sl = sum(x * y for x, y in zip(xs, ys)) / sum(x * x for x in xs)
    slow = [y for x, y in zip(xs, ys) if 0.5 < x < 3]; fast = [y for x, y in zip(xs, ys) if -1.5 < x < -0.2]
    print(f"  {cls:6s} each second slower per lap ~ {sl:+.3f}%/lap fuel; laps 0.5–3 s off a car's typical: {st.median(slow):+.2f}%/lap vs quicker laps {st.median(fast):+.2f}%/lap")
