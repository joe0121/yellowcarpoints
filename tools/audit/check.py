import math, sys, json
sys.path.insert(0, "/home/joe/Work/yellowcarpoints/app")
exec(open("tune.py").read().split("base_spread")[0])
ll = n = top3 = 0
for sn in picks:
    out = inrace.predict(sn["live"], sn["laps"], std, None, pre, n=3000, seed=3)
    for cls in CLS:
        if cls in out:
            w = finish[cls][0]; p = {x["car"]: x["win"] for x in out[cls]["cars"]}
            ll += math.log(max(p.get(w, 0), 0.005)); n += 1
            top3 += w in [x["car"] for x in sorted(out[cls]["cars"], key=lambda x: x["expected"])[:3]]
print(f"tuned model: mean log p(winner) {ll/n:.2f} ({math.exp(ll/n):.1%} geometric), winner in top 3 {top3/n:.0%}")
u = sum(math.log(1/len(finish[c])) for c in CLS) / 4
print(f"uniform guess: {u:.2f} ({math.exp(u):.1%})")
