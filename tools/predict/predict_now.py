"""Fit on every finished 2024-2026 race, predict the upcoming one, and work out title odds -> predict.json."""
import glob, json, math, random, sys
from datetime import datetime, timezone
import model as M

M.FEATS = ["q_rank", "p_gap", "form2", "dnf", "bronze"]
M.TOPK = 3
RACE_POINTS = [350, 320, 300, 280, 260, 250, 240, 230, 220, 210, 200, 190, 180, 170, 160, 150, 140, 130, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10]
race_pts = lambda p: RACE_POINTS[p - 1] if p <= len(RACE_POINTS) else 0
quali_pts = lambda p: race_pts(p) // 10
N = 40000

races = M.load(glob.glob("cache/*.json"))
G = M.build(races)
done = [g for g in G if g["done"]]
target = [g for g in G if not g["done"]]
w, beta = M.fit(done)
print("weights", {k: round(v, 3) for k, v in w.items()}, "beta", beta, file=sys.stderr)

standings = json.load(open("standings.json"))
quali = json.load(open("quali.json"))
backtest = json.load(open("backtest.json"))
rnd = random.Random(7)
out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": target[0]["circuit"],
       "season": target[0]["season"], "hours": target[0]["hours"] or 10, "races_used": len({(g["season"], g["event"]) for g in done}),
       "weights": {k: round(v, 3) for k, v in w.items()}, "backtest": backtest, "classes": {}}
hours = 10.0   # Petit Le Mans
for g in target:
    g["hours"] = hours
    cls, cars = g["cls"], g["cars"]
    sc = M.scale_of(hours, beta)
    s = [M.strength(c, w, sc) for c in cars]
    k = len(cars)
    st = (standings["classes"].get(cls) or {}).get("standings", [])
    q = quali["classes"].get(cls, {})
    base = {x["car"]: x["points"] + (quali_pts(q[x["car"]]) if x["car"] in q else 0) for x in st}
    pos = [[0] * k for _ in range(k)]
    champ = {c: 0 for c in base}
    for _ in range(N):
        order = sorted(range(k), key=lambda i: -(s[i] - math.log(-math.log(rnd.random() or 1e-12))))
        tot = dict(base)
        for p, i in enumerate(order):
            pos[i][p] += 1
            if cars[i]["car"] in tot: tot[cars[i]["car"]] += race_pts(p + 1)
        if tot:
            best = max(tot.values())
            lead = [c for c, v in tot.items() if v == best]
            for c in lead: champ[c] += 1 / len(lead)
    rows = []
    for i, c in enumerate(cars):
        p = [x / N for x in pos[i]]
        rows.append({"car": c["car"], "team": c["team"], "make": c["make"],
                     "win": round(p[0], 4), "podium": round(sum(p[:3]), 4), "top5": round(sum(p[:5]), 4),
                     "expected": round(sum((j + 1) * x for j, x in enumerate(p)), 2),
                     "likely": max(range(k), key=lambda j: p[j]) + 1,
                     "dist": [round(x, 4) for x in p],
                     "why": {"grid": round(c["q_rank"] * (k - 1)) + 1, "practice_gap": round(c["p_gap"], 2),
                             "form": round(c["form2"], 3), "dnf": round(c["dnf"], 3), "bronze": c["bronze"]}})
    rows.sort(key=lambda r: -r["win"])
    title = sorted(({"car": c, "points_now": base[c], "odds": round(v / N, 4)} for c, v in champ.items() if v), key=lambda r: -r["odds"])
    out["classes"][cls] = {"cars": rows, "title": title}
json.dump(out, open("predict.json", "w"), separators=(",", ":"))
for cls, d in out["classes"].items():
    print(cls, [(r["car"], f'{r["win"]:.0%}', f'{r["podium"]:.0%}', r["expected"]) for r in d["cars"][:6]])
    print("   title", [(t["car"], f'{t["odds"]:.1%}') for t in d["title"][:4]])
