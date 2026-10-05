# Handoff: where yellowcarpoints.win stands (2026-10-04)

Written at the end of the 2026 season (Petit Le Mans, Oct 3) so a new session can pick up. The README has
install and "how the predictions work"; this is the working state, operations and open items.

## State

- Season 2026 is over. Provisional points are in; the Championship page shows final standings, the
  Manufacturers' championship and the Michelin Endurance Cup, with a "provisional until IMSA certifies"
  note that switches to "official" by itself when Al Kamel publishes the Official points.
- Header countdown runs to the 2027 Rolex 24 (Jan 28-31) from IMSA's season calendar; the exact countdown
  takes over when IMSA posts that weekend's session times (about two weeks before).
- Everything is deployed; `main` is what's running. The dev backup recorder can be stopped (`./dev.sh down`).

## Services (compose.yaml)

| Service | Image | Role |
|---|---|---|
| scraper | yellowcarpoints-scraper | points, history, live timing + telemetry, race control, sectors, BoP, weather forecast, YouTube, titles (`titles.py`), season calendar (`calendar_.py`). Records sessions to `./archive/`. |
| analyst | same image, `python analyst.py` | race prediction (pre-race after qualifying, in-race every hour and 10 min after a red), caution history, weather at the track + radar nowcast (`wxlive.py`), onboard streams (`onboards.py`). Never restart-sensitive. |
| web | yellowcarpoints-web | Caddy: pages + `/data`; status page on 127.0.0.1:8089 (guest book moderation) |
| api | yellowcarpoints-api | profiles (sync code/passkeys), settings sync, guest book |
| cloudflared | cloudflare/cloudflared | tunnel to yellowcarpoints.win |

Data files the pages read (volume `yellowcarpoints_data`, served at /data): standings, history, entries,
schedule, calendar, titles, live, laps, race_state, quali, sectors, racecontrol, weather, wx_live, watch,
onboards, predict, insights, bop, config, overrides (hand-set tyre tags; empty now).

## Pages

- `index.html` Championship: hero answer per season phase (picture / clinch / survive / title / sealed
  champion / season over), title fight chart, Manufacturers and Endurance Cup cards, history.
- `strategy.html` Race, two views (`?view=fan|strategy`, saved per device):
  - Fan: video (IMSA broadcast + makes'/teams' onboard streams), track map, our cars, feed, race control, drivers.
  - Strategy: pit wall strip; full-width class strategy board, race strategy graph, timing; then
    if-we-pit-now, pit strategy, to the flag, drivers, weather (with radar), pace analysis, builder.
  - Most strategy maths is in `web/pitwall.js` (net to the flag by fuel, pit window in green minutes,
    stop cost, fuel to the flag, drive time, strategy graph, title-fight asterisks).
- `analysis.html` Analysis: prediction, championship odds, win chances through the race, caution history.

## Operating rules (learned the hard way)

- During a race, never pull+recreate the scraper by hand (the analyst shares its image, so a newer one
  is often already pulled). Scraper changes mid-race: start `./dev.sh scraper` early, push, wait for the
  build, then `./dev.sh update-scraper` (gap fill from the dev recorder).
- `./dev.sh` with no argument (= `up`) STOPS the dev recorder. To repoint the dev site without stopping
  it: `DEV_DATA_VOLUME=<volume> docker compose -f compose.dev.yaml --env-file .env up -d web api`.
- Web-only deploys: `docker compose pull -q web && docker compose up -d --no-deps web` (safe any time).
  Analyst: same with `analyst` (safe any time).
- Test UI changes headless (the Chrome extension browser is on another machine and can't reach
  localhost): `chromium --headless=new --user-data-dir=<tmp> --window-size=1600,1600
  --virtual-time-budget=9000 --screenshot=out.png http://localhost:8098/...`.
- Replay a recording as if it were a race: run `app/replay.py` with `-e LIVE_SESSIONS=Qualifying`, or load
  a snapshot from `archive/<race>/outputs.jsonl.gz` into the `ycp-dev_replay-data` volume.
- Never put secrets (tunnel token, API_SECRET, ADMIN_TOKEN) in chat or the repo.
- Poll IMSA/Al Kamel gently; don't scrape Al Kamel's live timing (livetiming.alkamelsystems.com).

## Things learned at Petit Le Mans 2026 (see tools/audit/README.md)

- Stop logged at lap s: in-lap = s, the stop itself in s+1, out-lap s+2. Pit-lane timing line is after
  the boxes, so energy on lap s is already post-refuel (use s-1 for "how empty").
- Green stop cost 54-64 s (2026), yellow 35-63 s; a yellow minute burns 32-46% of a green minute's fuel;
  cars with <=40 green minutes mostly pit on a yellow; full tank ~65 green min (GT), ~55 (GTP).
- The scraper's pit-cycle "owes a stop" fails after tyre-only stops; the page uses fuel in hand instead.
  The scraper's version still feeds cars without telemetry (LMP2).
- IMSA's feed never showed the early wet laps as yellow; slow laps alone don't mean a caution.
- Forecast models (Open-Meteo/HRRR) missed pop-up storms; radar (RainViewer) didn't.

## Open items / ideas

- Before the 2027 Rolex 24: add Daytona to `TRACKS` (weather.py), `RACE_LAPS`/`PIT_PRIOR` (pitwall.js),
  `DRIVE_RULES` (live.py, from the event's supplementary regs), the track outline (track.js),
  `RADAR_PLACES`, `EVENT_WORDS` (onboards.py), `EXTRA_STATIONS` (wxlive.py). The caution history
  (`cautions.py`) and pre-race model work for any track automatically.
- 2027 car list: DragonSpeed's #81 moved series; recheck the Corvette entries and AO Racing's liveries
  (they change every race: `CAR_LIVERY` in theme.js).
- Scraper: switch the YouTube check to 3-minute polling as soon as a session window opens (it waited for
  the hourly timer on race day).
- Re-run `tools/audit/` after a "normal" race to recheck the yellow-pit thresholds and model spread
  (tuned on one race with 16 cautions).
- Docker could move to the empty SSD (/mnt/ssd2); steps in the session notes. Not urgent (root has >500 GB free).
- Optional: Caddy access logs for a real visitor count (Cloudflare's dashboard has one already).
- Endurance Cup and Manufacturers' cards show standings only; in-season "what's needed" maths for those
  titles isn't built.
