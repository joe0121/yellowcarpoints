import json, statistics, bisect
from datetime import datetime, timezone
import cautions as C
from model import secs
RACE = 36000
years = []
for y, r in sorted(C.races.items()):
    ps = r["truth"] if r["truth"] is not None else r["guess"]
    # leader lap by time: max completed lap among all crossings up to t
    cr = sorted((secs(l[4]), l[2]) for l in r["laps"] if secs(l[4]))
    ts = [t for t, _ in cr]; best = []; m = 0
    for _, n in cr: m = max(m, n); best.append(m)
    lap_at = lambda t: best[max(0, bisect.bisect_right(ts, t) - 1)] if ts else 0
    total = max(best) if best else 0
    years.append({"year": int(y), "source": "flags" if r["truth"] is not None else "lap times", "laps": total,
                  "cautions": [{"start": round(a), "mins": round((b - a) / 60, 1), "lap": lap_at(a), "end_lap": max(lap_at(b), lap_at(a) + 1)} for a, b in ps if a < RACE + 600]})
for y in years: print(y["year"], y["source"], y["laps"], len(y["cautions"]), [(c["lap"], c["end_lap"]) for c in y["cautions"]])
n = [len(y["cautions"]) for y in years]
mins = [sum(c["mins"] for c in y["cautions"]) for y in years]
lens = [c["mins"] for y in years for c in y["cautions"]]
claps = [sum(c["end_lap"] - c["lap"] for c in y["cautions"]) for y in years]
first = [y["cautions"][0]["start"] / 60 for y in years if y["cautions"]]
hour = lambda c: min(9, int(c["start"] // 3600))
by_hour = [sum(1 for y in years for c in y["cautions"] if hour(c) == h) / len(years) for h in range(10)]
any_hour = [sum(1 for y in years if any(hour(c) == h for c in y["cautions"])) / len(years) for h in range(10)]
out = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": "Petit Le Mans", "track": "Road Atlanta", "years": years,
       "summary": {"races": len(years), "avg_cautions": round(statistics.mean(n), 1), "min_cautions": min(n), "max_cautions": max(n),
                   "avg_caution_mins": round(statistics.mean(mins)), "pct_under_caution": round(statistics.mean(mins) / 600 * 100, 1),
                   "avg_length_mins": round(statistics.mean(lens), 1), "avg_caution_laps": round(statistics.mean(claps)),
                   "median_first_caution_mins": round(statistics.median(first)),
                   "first_hour_pct": round(100 * sum(1 for f in first if f < 60) / len(years)),
                   "last_hour_pct": round(100 * any_hour[9]), "per_hour": [round(x, 2) for x in by_hour], "any_in_hour": [round(x, 2) for x in any_hour]}}
json.dump(out, open("insights.json", "w"), separators=(",", ":"))
print(json.dumps(out["summary"], indent=1))
