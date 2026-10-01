# yellowcarpoints.win

Championship standings, race history and live race tracking for the Corvettes in the IMSA
WeatherTech SportsCar Championship (GTD PRO #4, #3, #74 and GTD #13, #36, #81; pick one at the top
of the page, or link straight to one with `#13`).

- `scraper` finds the newest `00_Championship Points` PDF on IMSA's Al Kamel results site every
  `INTERVAL_MINUTES`, parses the class's Teams and Drivers tables, and writes `standings.json`.
- During a WeatherTech race it also polls IMSA's live timing (the JSON behind imsa.com/scoring)
  every `LIVE_RACE_SECONDS` (30; 60 during other WeatherTech sessions, 300 when nothing is on,
  backing off up to 15 minutes when requests fail) and writes `live.json`: the championship if the race finished
  now, plus the worst class finish that still wins the title. Qualifying class positions are saved
  to `quali.json` during qualifying so their points are included. The page shows a live card until
  the official points PDF for that race is published.
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
