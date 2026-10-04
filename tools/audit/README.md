# Post-race audit of the strategy predictions

Scores what the site predicted during a race against what happened, from the session recording
(`archive/<race>/outputs.jsonl.gz`: live.json and laps.json every 5 minutes) and Al Kamel's results.

    # results.json: the race's 03_Results_Race JSON from Al Kamel; predict.json: copy from the data volume
    python3 audit.py     # next-stop lap, stops to the flag, stop cost, laps to go, net position vs the result
    python3 audit2.py    # fuel left at pit entry, fuel-based net, hourly win predictions vs the winners
    python3 tune.py      # replays the in-race model half-hourly with different spread / pace weights
    python3 check.py     # scores the current in-race model

Petit Le Mans 2026 findings (and what changed):
- Next stop within 10 laps: accurate (median 0, MAE 2 laps). Further out, cars stopped ~16 laps before
  their fuel ran out: they pitted with 60-70% left, under yellows and for tyres/drivers. -> The pit wall
  calls it "Fuel lasts" and says stops often come sooner.
- Stops to the flag: fuel-only figure under-counted early (median +4 with 5h+ left), exact in the last 2h.
  Cars made 13-15 stops against a fuel minimum of 6-7. -> "To the flag" adds about 0.3 stops per hour left.
- Stop cost: 54-64 s under green (2021-25 history said ~75 s); yellow 35-63 s. -> New priors.
- Laps to go: the leaders ran 0.78-0.82 of the green-pace laps (16 cautions, a red flag). -> Laps to go
  allow for cautions at the track's historical rate.
- Net position: the fuel-based net beat track position 2-5 h out (0.55 vs 0.48 rank correlation with the
  result), equal in the last 2 h; the scraper's old pit-cycle net was no better than track position.
- Hourly win odds: too confident (worse than a random pick: 7.2% vs 7.6% geometric probability on the
  winner). -> Spread doubled, pace weight halved: 10.5%.

Fuel (fuel.py), Petit Le Mans 2026:
- A yellow minute uses 32-46% of a green minute's fuel (GTD PRO 32%, GTD 39%, GTP 46%); per lap 0.9-1.6% vs 2.1-2.2%.
- A full tank is ~65 green minutes in GT, ~55 in GTP; all-green GT stints ran a median 58-64 min.
- On a yellow, cars with <=10 green minutes of fuel pitted ~always, 10-40 min 55-80%, 40-60 min 30-45%,
  60+ ~20%. -> Pit window: "a yellow brings it in" at <=40 min, "must stop" at <=10.
- Fuel saving by lifting isn't visible at the telemetry's ~0.1%/lap resolution: not modelled.
