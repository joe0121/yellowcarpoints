# yellowcarpoints.win

Championship standings for the Corvette Racing entries in the IMSA WeatherTech SportsCar Championship.

- `scraper` finds the newest `00_Championship Points` PDF on IMSA's Al Kamel results site every
  `INTERVAL_MINUTES`, parses the class's Teams and Drivers tables, and writes `standings.json`.
- During a WeatherTech race it also polls IMSA's live timing (the JSON behind imsa.com/scoring)
  every `LIVE_INTERVAL_SECONDS` (30) and writes `live.json`: the championship if the race finished
  now, plus the worst class finish that still wins the title. Qualifying class positions are saved
  to `quali.json` during qualifying so their points are included. The page shows a live card until
  the official points PDF for that race is published.
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

## Track another car

Set `CARS=4,3` in `.env` (first car yellow, second blue) and `docker compose up -d`.
`CLASS` is the class name as printed in the PDF: `GTP`, `LMP2`, `GTDPRO`, `GTD`.
