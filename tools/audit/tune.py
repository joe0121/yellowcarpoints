import json, math, sys, statistics as st
sys.path.insert(0, "/home/joe/Work/yellowcarpoints/app")
exec(open("audit.py").read().split("# --- A. next stop lap")[0])
import inrace
pre = json.load(open("predict.json"))["prerace"]
std = json.load(open("standings.json")) if False else {"classes": {}, "event": "x"}
# one snapshot per race hour (green or not), skipping the very end
picks, seen = [], set()
for sn in snaps:
    el = hms(sn["live"].get("elapsed")); rem = hms(sn["live"].get("remaining"))
    if not sn["live"].get("is_race") or el is None or rem is None or rem < 600: continue
    h = int(el // 1800)            # every half hour
    if h >= 1 and h not in seen:
        seen.add(h); picks.append(sn)
print("snapshots used:", len(picks))
base_spread = dict(inrace.SPREAD)
def score(mult, pw, fade):
    inrace.SPREAD = {k: v * mult for k, v in base_spread.items()}; inrace.PACE_WEIGHT = pw
    ll, top3, n = 0.0, 0, 0
    for sn in picks:
        prer = pre if fade else None
        out = inrace.predict(sn["live"], sn["laps"], std, None, prer, n=3000, seed=3)
        for cls in CLS:
            if cls not in out: continue
            w = finish[cls][0]; p = {x["car"]: x["win"] for x in out[cls]["cars"]}
            ll += math.log(max(p.get(w, 0), 0.005)); n += 1
            fav3 = [x["car"] for x in sorted(out[cls]["cars"], key=lambda x: x["expected"])[:3]]
            top3 += w in fav3
    return ll / n, top3 / n
for mult in (1.0, 1.5, 2.0, 3.0):
    for pw in (0.5, 0.25, 0.0):
        l, t = score(mult, pw, True)
        print(f"spread x{mult:<3} pace weight {pw:<4}: mean log p(winner) {l:.2f}  (= {math.exp(l):.1%} geometric)  winner in predicted top 3: {t:.0%}")
