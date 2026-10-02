import glob, math, statistics, time, sys
import model as M
races = M.load(glob.glob("cache/*.json"))
G = [g for g in M.build(races) if g["done"]]
def spearman(a, b):
    n = len(a); d = sum((x - y) ** 2 for x, y in zip(a, b)); return 1 - 6 * d / (n * (n * n - 1))
def evaluate(train, test, feats, label):
    M.FEATS = feats
    t = time.time(); w, beta = M.fit(train)
    wins = pods = 0; rho = []; ll = 0; llu = 0; brier = []
    for g in test:
        sc = M.scale_of(g["hours"], beta); s = [M.strength(c, w, sc) for c in g["cars"]]
        ll += M.loglik([g], w, beta)[0]; llu += -sum(math.log(k) for k in range(2, len(s) + 1))
        z = sum(math.exp(x) for x in s); pw = [math.exp(x) / z for x in s]
        top = max(range(len(s)), key=lambda i: s[i])
        wins += top == 0
        pods += top <= 2
        order = sorted(range(len(s)), key=lambda i: -s[i]); rank = {i: r for r, i in enumerate(order)}
        rho.append(spearman([rank[i] for i in range(len(s))], list(range(len(s)))))
        brier.append(sum((p - (i == 0)) ** 2 for i, p in enumerate(pw)))
    n = len(test)
    print(f"{label:28s} winner {wins}/{n} ({wins/n:.0%})  fav on podium {pods/n:.0%}  spearman {statistics.mean(rho):.2f}  "
          f"loglik gain vs coin-flip {(ll-llu)/n:+.2f}/race  win-brier {statistics.mean(brier):.3f}  beta {beta}  ({time.time()-t:.0f}s)")
    return w, beta
import sys
ALL = ["q_rank", "q_gap", "p_gap", "form", "dnf", "trk", "make", "bronze"]
SETS = {"grid+pace+form": ["q_rank", "p_gap", "form", "dnf"], "+bronze": ["q_rank", "p_gap", "form", "dnf", "bronze"],
        "form2 +bronze": ["q_rank", "p_gap", "form2", "dnf", "bronze"], "form2 +bronze+qgap": ["q_rank", "q_gap", "p_gap", "form2", "dnf", "bronze"]}
if __name__ == "__main__":
    for topk in (99, 3):
      M.TOPK = topk
      print(f"=== fitted on top {topk} of each class")
      for test_season, train_seasons in (("2025", {"2024"}), ("2026", {"2024", "2025"})):
          train = [g for g in G if g["season"] in train_seasons]; test = [g for g in G if g["season"] == test_season]
          print(f"--- test {test_season}")
          for k, v in SETS.items(): evaluate(train, test, v, k)
