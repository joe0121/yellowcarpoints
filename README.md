# yellowcarpoints.win

Championship standings, race history and live race tracking for the Corvettes in the IMSA
WeatherTech SportsCar Championship (GTD PRO #4, #3, #74 and GTD #13, #36, #81; pick one at the top
of the page, or link straight to one with `#13`).

- `scraper` finds the newest `00_Championship Points` PDF on IMSA's Al Kamel results site every
  `INTERVAL_MINUTES`, parses the class's Teams and Drivers tables, and writes `standings.json`.
- Live timing (`app/live.py`) is driven by IMSA's published weekend schedule (read from imsa.com
  every 6 hours into `schedule.json`). It only polls the JSON behind imsa.com/scoring from 10 minutes
  before each WeatherTech session until 30 minutes after its scheduled end, and not at all otherwise
  (if the schedule can't be read, it checks every 30 minutes instead). While a session runs:
  - every `LIVE_RACE_SECONDS` (10) in the race / `LIVE_SESSION_SECONDS` (15) otherwise: every car's
    lap times and pit stops in the tracked classes (`laps.json`, `race_state.json`), the class
    timing, and in the race the championship if it finished now (`live.json`). Qualifying class
    positions go to `quali.json` so their points are included;
  - every `STRATEGY_SECONDS` (300): pace over the last 5 clean laps and its trend, pace against the
    cars either side, and where each car would rejoin if it pitted now.
  Failed requests back off exponentially up to 15 minutes.
- Telemetry (`app/telemetry.py`): during the same session windows it keeps one WebSocket open to the
  stream behind imsa.com/telemetry (AppSync Events, using the public key that page ships with; about
  1 Hz, push only). Per car it records energy remaining at each lap, every refuel (duration and energy
  added) and every pit-lane visit with what happened in it: seconds refuelling, seconds on the air
  jacks (`is_jacked_up` above 0.5 for 5 s+ is taken as a tyre change; its scale isn't documented, so the
  per-stop maximum is kept for checking) and whether the active driver changed. In the race the pit
  loss used for the net order is the class median of the most common stop type (fuel-only or full
  service) once there are 3 timed stops. From that, `live.json` gets energy use per lap, laps left on the tank, the
  next stop lap, the next fill time (from the class's observed fill rate) and, in the race, the stops
  still needed to reach the flag. Unofficial: if it stops working the pages fall back to lap-count
  estimates.
- `web/index.html` (Championship tab): standings, the cars still in contention (points now, most
  they can reach, and in the race where they're running and their points if it ended now), what the
  selected car needs (guaranteed finish plus a finish-by-rival table, or for an eliminated car the
  highest championship position it can still reach), the live championship projection and history.
- `web/strategy.html` (Race tab): per-car race page (same car picker) with class timing and a lap
  chart, pit strategy tiles, gap and energy charts with trend lines, pace, sectors and a strategy
  board for the whole class.
- After each race it reads Al Kamel's race reports (results, grid, lap and pit stop time cards) for
  every round this season and writes `history.json`: class finish, grid, best lap and its class rank,
  stops and their times, stint lengths and laps per driver. Each race is fetched once Provisional results are out (again for Official) and cached in
  `history/`.
- Pit windows: `baseline.json` holds the full-tank stint lengths (25th percentile, median, 90th
  percentile) from last season's race at the next event's track. During a race the scraper records
  each car's stops as its pit-stop count changes, and switches to this race's own stints once there
  are enough of them. Each tracked car shows laps into its stint and when the window opens.
- `web` (Caddy) serves `web/index.html` plus that JSON on `127.0.0.1:8088`.
- `cloudflared` publishes `web` at https://yellowcarpoints.win (and www.) through a locally managed
  Cloudflare Tunnel: no port forwarding, works behind the VPN. Routing is in `cloudflared/config.yml`;
  the tunnel credentials live in `~/.cloudflared/` on the host (never in the repo).

## Run

Pushing to `main` builds both images on GitHub Actions and publishes them to
`ghcr.io/joe0121/yellowcarpoints-scraper` and `ghcr.io/joe0121/yellowcarpoints-web`.
The compose file pulls those images; nothing is built locally.

    cp .env.example .env
    docker compose pull && docker compose up -d   # also http://localhost:8088 locally

To test a change before pushing, build locally:

    docker build -t ghcr.io/joe0121/yellowcarpoints-scraper:latest app
    docker build -t ghcr.io/joe0121/yellowcarpoints-web:latest -f web/Dockerfile .
    docker compose up -d

### Tunnel setup (done once, 2026-10-01)

    CF="docker run --rm --user $(id -u):$(id -g) -e HOME=/cf -v $HOME/.cloudflared:/cf/.cloudflared cloudflare/cloudflared:latest"
    $CF tunnel login                       # browser: authorize yellowcarpoints.win
    $CF tunnel create yellowcarpoints      # writes ~/.cloudflared/<tunnel id>.json
    $CF tunnel route dns yellowcarpoints yellowcarpoints.win
    $CF tunnel route dns yellowcarpoints www.yellowcarpoints.win

No Zero Trust dashboard setup is needed for a locally managed tunnel.

## Track other cars

Set `CARS` in `.env` as `CLASS:NUMBER` pairs, e.g. `CARS=GTDPRO:4,GTD:13`, then `docker compose up -d`.
Each car's log of stops, driver changes and position changes (`ev` in `laps.json`) and per-driver drive
time (`drivers` in `live.json`, with ratings from the entry list and the event's drive-time rules in
`DRIVE_RULES`) are kept in `race_state.json`, so restarts and page reloads lose nothing.
`api/` is a small FastAPI service (SQLite in the `api-db` volume) for anonymous profiles and the guest
book. A profile is a random sync code (stored only as an HMAC keyed by `API_SECRET`) and/or passkeys
(WebAuthn, `RP_ID`/`ORIGINS`); it holds display settings only. Guest book posts wait for approval on the
local status page: Caddy's :8089 server adds `X-Admin: $ADMIN_TOKEN` for `/api/admin/*`, while the public
:80 server refuses that path and strips the header. Set `API_SECRET` and `ADMIN_TOKEN` in `.env`
(random, private). Optional Cloudflare Turnstile spam check: `TURNSTILE_SITEKEY` / `TURNSTILE_SECRET`.
Client IPs are used in memory for rate limiting only.

`app/watch.py` reads YouTube's public RSS feed for IMSA's channel (no API key) to find WeatherTech
session streams for the Race page's Watch card (embedded with YouTube's player, nothing re-hosted), and
notes which cars IMSA.tv lists with an in-car camera (linked, never embedded: IMSA.tv uses its own
tokenised player). Checked every 3 minutes in a session window, hourly otherwise (`watch.json`).
`RACE_CARS` (default `LMP2:73`, Pratt Miller's LMP2 ORECA) adds cars that are followed in live timing
only: their class is tracked live and they get their own tab on the Race page, with no championship maths.
The pages poll `live.json` every 10 s, `laps.json` every 30 s (Championship: 60 s) and the rest every 5 minutes.
Leave it empty for the default Corvettes. The class is as printed in the PDF: `GTP`, `LMP2`, `GTDPRO`, `GTD`.

## Championship maths during the race

For each tracked car, `live.json` → `classes.<class>.focus.<car>` holds the cars that matter: the race
reference (class leader, or the car behind when leading), the car ahead on track, and the championship
neighbours either side in the projection. The projection uses the **net** order when it can: during a
pit cycle (some cars in the class stopped within the last 40% of a stint, others not) the cars that
still owe a stop are moved back by the class pit loss; in the final tank it compares stops still needed
to reach the flag. Net is switched off under yellows. A change of title rival must hold for 3 polls
before it's reported. Also: margin to each rival (raw and net), what a place is worth, the lowest
finish needed to stay ahead of / get ahead of each rival, and what the rival behind needs. The title
margin per lap is in `laps.json` (`margins`).

## Recordings and replay

Every WeatherTech session is recorded to `./archive/<date>_<session>/` (bind-mounted into the
scraper): `feed.jsonl.gz` (every leaderboard poll), `telemetry.jsonl.gz` (tracked classes every 10 s), `pit.jsonl.gz` (about 1 Hz while a tracked-class car is in the pit lane)
and `outputs.jsonl.gz` (live.json / laps.json every 5 minutes). The scraper log is
`./archive/scraper.log`. To rebuild what the live code computed:

    docker compose exec scraper python replay.py /data/archive/<folder> /tmp/replay
    # or locally: DATA_DIR is set by the script; --data points at a copy of standings/baseline/quali

## Status page (this PC only)

http://localhost:8089 shows, refreshed every 5 s: scraper heartbeat, live session window, leaderboard
feed and telemetry freshness, points/history/schedule checks, the current recording and disk space,
Cloudflare tunnel connections, public requests/min and upload use, and recent warnings/errors.

It is a separate Caddy site on `127.0.0.1:8089` (not in the tunnel's ingress, so not public). The
scraper writes `status.json` every 15 s to the `status` volume (`app/status.py`); traffic comes from
Caddy's metrics and tunnel connections from cloudflared's metrics (`--metrics`, Docker network only).
Read-only by design: restarts and logs stay in lazydocker.

## Sectors

IMSA's live feed carries no sector times, so `app/sectors.py` reads Al Kamel's time card for the latest
WeatherTech session at the current event (published at the end of each session and as hourly snapshots
during endurance races), checked every 5 minutes during session windows and every 30 minutes otherwise,
and re-downloaded only when the file changes. Per car: best time in each of IMSA's three sectors, the
ideal lap, and a typical time per sector (median of clean laps). Shown as the Sectors table on the
Race page.

## Balance of Performance (BoP)

`app/bop.py` reads IMSA's newest event BoP technical bulletin (found on
imsa.com/competitors/<year>-technical-bulletins/; only checked around a race weekend, from 4 days before
the first scheduled session to the last session's end, at most every 12 hours) and parses the GTD /
GTD PRO table: maximum stint energy (MJ) and energy replenishment rate (MJ/s) per make. GTD cars use a
virtual energy tank refilled at that fixed rate, so a refill takes exactly (energy to add / rate);
for 2026 that is 40 s for a full tank for every make. The Race page uses it for the next fill time
and shows each car's energy use in MJ per lap. Feed vehicle names are matched to BoP rows by model.
