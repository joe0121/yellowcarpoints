import json, math, statistics
import model as M
from backtest import G
M.FEATS = ["q_rank", "p_gap", "form2", "dnf", "bronze"]; M.TOPK = 3
res = {"fav_win": 0, "pole_win": 0, "fav_podium": 0, "pole_podium": 0, "n": 0, "pwin_actual": [], "fav_prob": []}
for test_season, train in (("2025", {"2024"}), ("2026", {"2024", "2025"})):
    w, beta = M.fit([g for g in G if g["season"] in train])
    for g in (g for g in G if g["season"] == test_season):
        sc = M.scale_of(g["hours"], beta); s = [M.strength(c, w, sc) for c in g["cars"]]
        z = sum(math.exp(x) for x in s); p = [math.exp(x) / z for x in s]
        fav = max(range(len(s)), key=lambda i: s[i]); pole = min(range(len(s)), key=lambda i: g["cars"][i]["q_rank"])
        res["n"] += 1; res["fav_win"] += fav == 0; res["pole_win"] += pole == 0
        res["fav_podium"] += fav <= 2; res["pole_podium"] += pole <= 2
        res["fav_prob"].append(p[fav]); res["pwin_actual"].append(p[0])
out = {"class_races": res["n"], "seasons": "2025-2026 (each predicted using only earlier races)",
       "favourite_won": res["fav_win"], "pole_won": res["pole_win"], "favourite_podium": res["fav_podium"], "pole_podium": res["pole_podium"],
       "avg_favourite_prob": round(statistics.mean(res["fav_prob"]), 3), "avg_prob_given_to_winner": round(statistics.mean(res["pwin_actual"]), 3),
       "avg_field": round(statistics.mean(len(g["cars"]) for g in G if g["season"] in ("2025", "2026") and g["done"]), 1)}
json.dump(out, open("backtest.json", "w"), indent=1); print(out)
