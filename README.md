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
  - every `LIVE_RACE_SECONDS` (30) in the race / `LIVE_SESSION_SECONDS` (60) otherwise: every car's
    lap times and pit stops in the tracked classes (`laps.json`, `race_state.json`), the class
    timing, and in the race the championship if it finished now (`live.json`). Qualifying class
    positions go to `quali.json` so their points are included;
  - every `STRATEGY_SECONDS` (300): pace over the last 5 clean laps and its trend, pace against the
    cars either side, and where each car would rejoin if it pitted now.
  Failed requests back off exponentially up to 15 minutes.
- Telemetry (`app/telemetry.py`): during the same session windows it keeps one WebSocket open to the
  stream behind imsa.com/telemetry (AppSync Events, using the public key that page ships with; about
  1 Hz, push only). Per car it records energy remaining at each lap, every refuel (duration and energy
  added) and pit-lane time. From that, `live.json` gets energy use per lap, laps left on the tank, the
  next stop lap, the next fill time (from the class's observed fill rate) and, in the race, the stops
  still needed to reach the flag. Unofficial: if it stops working the pages fall back to lap-count
  estimates.
- `web/strategy.html`: per-car strategy page (same car picker) with those numbers as tiles, lap time,
  gap and energy charts with trend lines, and a strategy board for the whole class.
- After each race it reads Al Kamel's race reports (results, grid, lap and pit stop time cards) for
  every round this season and writes `history.json`: class finish, grid, best lap and its class rank,
  stops and their times, stint lengths and laps per driver. Each race is fetched once Provisional results are out (again for Official) and cached in
  `history/`.
- Pit windows: `baseline.json` holds the full-tank stint lengths (25th percentile, median, 90th
  percentile) from last season's race at the next event's track. During a race the scraper records
  each car's stops as its pit-stop count changes, and switches to this race's own stints once there
  are enough of them. Each tracked car shows laps into its stint and when the window opens.
- `web` (Caddy) serves `web/index.html` plus that JSON on `127.0.0.1:8088`.
- `cloudflared` publishes `web` through a Cloudflare Tunnel (no port forwarding; works behind the VPN).

## Run

Pushing to `main` builds both images on GitHub Actions and publishes them to
`ghcr.io/joe0121/yellowcarpoints-scraper` and `ghcr.io/joe0121/yellowcarpoints-web`.
The compose file pulls those images; nothing is built locally.

    cp .env.example .env              # set CARS, and TUNNEL_TOKEN once the tunnel exists
    docker compose pull && docker compose up -d   # local only: http://localhost:8088

Set `COMPOSE_PROFILES=tunnel` in `.env` to start the tunnel along with the rest.

To test a change before pushing, build locally:

    docker build -t ghcr.io/joe0121/yellowcarpoints-scraper:latest app
    docker build -t ghcr.io/joe0121/yellowcarpoints-web:latest -f web/Dockerfile .
    docker compose up -d

In the Cloudflare tunnel's public hostname, point `yellowcarpoints.win` at `http://web:80`.

## Track other cars

Set `CARS` in `.env` as `CLASS:NUMBER` pairs, e.g. `CARS=GTDPRO:4,GTD:13`, then `docker compose up -d`.
Leave it empty for the default Corvettes. The class is as printed in the PDF: `GTP`, `LMP2`, `GTDPRO`, `GTD`.
