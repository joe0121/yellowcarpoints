# yellowcarpoints.win

An unofficial Corvette fan site for the IMSA WeatherTech SportsCar Championship: where the cars stand in
the championship and what they need, what's happening live in a session, race strategy, and predictions.
It runs on one PC in Docker and is published through a Cloudflare Tunnel.

- **Championship tab**: standings for every class (GTP, LMP2, GTD PRO, GTD), what the selected car needs
  to win, clinch or stay in the fight, rival by rival, and during the race the championship "if it ended
  now". This weekend's qualifying points are banked as soon as qualifying ends.
- **Race tab**, in two views:
  - *Fan*: IMSA's video stream and a live track map first, then our cars, what just happened, race
    control and drivers.
  - *Strategy*: the pit wall (net position, gaps on net, next stop, energy, drive time), the class
    strategy board, a race strategy graph (lap time through the whole race with the projection ahead),
    "if we pit now", fuel to the flag, drive-time compliance, weather with radar, pace analysis and charts.
- **Analysis tab**: race prediction (each car's chance to win, reach the podium and finish in each
  position), championship odds, win chances through the race, and the caution history of this race.

Pick any car with the picker ("This is my car"); every tab follows it. Link straight to a car with
`yellowcarpoints.win/#13`, or a view with `strategy.html?view=strategy#4`.

## Install

You need a Linux machine with Docker and the Compose plugin. Images are built by GitHub Actions and
pulled from GitHub's container registry, so nothing has to be built locally.

    git clone https://github.com/joe0121/yellowcarpoints.git
    cd yellowcarpoints
    cp .env.example .env
    # set API_SECRET and ADMIN_TOKEN in .env (openssl rand -hex 32 for each)
    docker compose pull
    docker compose up -d scraper analyst api web

The site is then on http://localhost:8088 and the status page on http://localhost:8089 (both bound to
127.0.0.1, so only this machine sees them). The scraper fills in the championship within a minute; live
timing starts by itself 10 minutes before each WeatherTech session.

To publish it on your own domain, set up a Cloudflare Tunnel (below), then `docker compose up -d`
starts `cloudflared` too.

### Cloudflare Tunnel (once)

No port forwarding needed, and it works behind a VPN. The domain must be on Cloudflare.

    CF="docker run --rm --user $(id -u):$(id -g) -e HOME=/cf -v $HOME/.cloudflared:/cf/.cloudflared cloudflare/cloudflared:latest"
    $CF tunnel login                       # browser: authorize your domain
    $CF tunnel create yellowcarpoints      # writes ~/.cloudflared/<tunnel id>.json
    $CF tunnel route dns yellowcarpoints example.com
    $CF tunnel route dns yellowcarpoints www.example.com

Then put your tunnel id and hostnames in `cloudflared/config.yml`, and the credentials file name in the
`cloudflared` volume line of `compose.yaml`. The credentials stay in `~/.cloudflared/` (never in the repo).
No Zero Trust dashboard setup is needed for a locally managed tunnel. For passkeys, set `RP_ID` and
`ORIGINS` in `.env` to your domain.

### Configuration (`.env`)

| Variable | What it does |
|---|---|
| `API_SECRET`, `ADMIN_TOKEN` | Required. Keys the sync codes, and lets the local status page moderate the guest book. |
| `CARS` | Cars in the picker, `CLASS:NUMBER` (e.g. `GTDPRO:4,GTD:13`). Empty: the defaults in `app/common.py`. |
| `RACE_CARS` | Cars followed in live timing only (own Race tab, no championship maths). |
| `INTERVAL_MINUTES` | How often to check for a new championship points PDF (30). |
| `ANALYSIS_MINUTES` | Minutes of race time between in-race predictions (60). |
| `WX_LIVE_SECONDS` | Weather at the track and radar nowcast refresh during race weekends (300). |
| `RP_ID`, `ORIGINS` | Your domain, for passkeys. |
| `TURNSTILE_SITEKEY`, `TURNSTILE_SECRET` | Optional Cloudflare Turnstile spam check on the guest book. |

### Updating

Pushing to `main` builds the three images (`scraper`, `web`, `api`) on GitHub Actions and publishes them
to `ghcr.io/joe0121/yellowcarpoints-*`. On the server:

    docker compose pull && docker compose up -d

During a race, update one service at a time and never recreate the scraper by hand: see
[Making changes during a race](#making-changes-during-a-race). To run your own fork, change the image
names in `compose.yaml` to your registry, or build locally:

    docker build -t ghcr.io/joe0121/yellowcarpoints-scraper:latest app
    docker build -t ghcr.io/joe0121/yellowcarpoints-web:latest -f web/Dockerfile .
    docker build -t ghcr.io/joe0121/yellowcarpoints-api:latest api

## Services

| Service | What it does |
|---|---|
| `scraper` | Championship points, race history, live timing and telemetry, race control, sectors, BoP, weather forecast, IMSA's YouTube streams. Writes JSON to the `data` volume and records every session to `./archive/`. |
| `analyst` | Same image, its own process so it can never hold up live timing: the race prediction (pre-race and every race hour), caution history, weather at the track every 5 minutes and the radar nowcast. Caches past results in the `analysis-cache` volume. |
| `web` | Caddy: the static pages plus the JSON, on 127.0.0.1:8088; the status page on 127.0.0.1:8089. |
| `api` | FastAPI + SQLite: anonymous profiles (sync code and/or passkeys) that sync display settings, and the guest book. |
| `cloudflared` | The Cloudflare Tunnel that publishes `web`. |

Data sources: IMSA's live timing (the JSON behind imsa.com/scoring) and telemetry stream (imsa.com/telemetry),
Al Kamel's published results site (points PDFs, results, time cards, race control and weather files),
IMSA's schedule and BoP bulletins, the National Weather Service, Open-Meteo, RainViewer and IMSA's
YouTube RSS feed. Al Kamel's own live timing site is not scraped (its terms forbid it). Everything is
polled gently and only around sessions.

## How the predictions work

Every number on the site comes from published data and simple, explainable maths, not a black box. Where
something is an estimate, the page says so.

### Championship: what a car needs

From the official standings (plus this weekend's qualifying points once qualifying is done; they're only
added while the standings don't include this round yet), for each rival the site works out the lowest
class finish the selected car can afford if that rival finishes in each position. "Whatever anyone else
does" assumes every rival takes the maximum it still can. Early in a season, when nobody can clinch or be
knocked out at the next round, it shows the season picture instead of scenarios. When a car only needs to
start the race, it's declared champion as soon as it has a lap scored, and the card moves on to the fight
for 2nd. Ties and penalties aren't modelled.

### During the race: net position and "if it ended now"

- **Net position**: where each car runs once everyone has made the stops they owe in the current pit
  cycle: its gap to the class leader plus the cost of each stop it still owes. A car owes a stop when some
  cars in its class stopped recently (within 40% of a typical stint) and it hasn't; in the last tank of
  the race it's the stops each car still needs to reach the flag.
- **Typical stint**: last year's race at this track until this race has six full-tank stints. Stints cut
  short (under 60% of last year's typical, or 20 laps without a baseline) don't count, so an early yellow
  or a wet start can't teach it that a stint is 8 laps.
- **What a stop costs**: the in-lap plus the lap with the stop, compared with the cars that didn't pit on
  those same laps (so a drying track or traffic cancels out). Measured from this race once there are three
  green-flag stops; before that, Petit Le Mans 2021–2025 from Al Kamel's time cards: about 75 s under
  green in 2021–25 but 54–64 s in 2026 (the figures now used), and less under a full-course yellow because
  the field is slow while the car is in the lane.
- **If we pit now**: the car's gap plus the stop cost, slotted into the class order: where it would rejoin
  and which cars it would come out between, under green and if a yellow came out now. Stopping early means
  a shorter fill, which is credited.
- **Fuel to the flag**: laps to the flag at each car's pace, against laps left on the tank and laps per
  full tank (IMSA telemetry energy, or typical stint lengths for cars without telemetry): "makes it", the
  window for a single last stop (and whether it's a short fill), or the number of stops left.
- **Drive time**: counted from live timing every poll for whoever is in the car, against the event's
  minimums (and the Bronze minimum), the per-driver maximum and the "4 hours in any 6" limit (that one
  estimated from lap times between driver changes). The page shows the latest each driver can get in and
  still make their minimum, and warns when the drivers still short need more time than the race has left.

### Pre-race prediction (Analysis tab)

A Plackett–Luce model, the standard way to model a finishing order: each car gets a strength, and the
order is drawn winner first with probability proportional to exp(strength), then 2nd from the rest, and
so on. The strength is a weighted sum of what's known before the race:

- starting position in class
- best practice lap, as % behind the class's best
- form: average class finishing position over the last six races this season, plus last season at half
  weight (shrunk toward the middle when there are few races)
- retirement rate this season
- number of Bronze-rated drivers in the line-up

The weights are fitted by maximum likelihood on every WeatherTech race since 2024 (Al Kamel's JSON
results start then), on the top three of each class, which is what win and podium odds depend on. Longer
races are allowed to be more random. The race is then simulated 40,000 times; the share of simulations a
car wins is its win chance, and adding each simulated finish to the points gives the championship odds.

**How good is it?** Backtested on 68 class results in 2025 and 2026, each predicted only from the races
before it: the model's favourite won 19 (28%), against 15 (22%) for the polesitter, and finished on the
podium about half the time. Endurance racing is chaotic, so a 20–30% favourite is normal. The research
scripts (feature selection, backtests, calibration) are in `tools/predict/`.

### In-race prediction

Every race hour (`ANALYSIS_MINUTES`) the analyst projects each car's finish from the live state:

- its gap to the class leader (laps down at the class pace), plus the stops it still owes against the
  others at the class stop cost
- plus a quarter of its pace difference against the class on the same recent green laps, times the laps left
  (capped at 1 s/lap, and only fully trusted after about 100 clean laps, so one slow stint doesn't swing it)
- plus random spread for what can still happen, and a chance of retiring, both calibrated on Petit Le Mans
  2021–2025 (gaps move by about 36–80 s per √(hour left) depending on class, doubled after the 2026 audit),
  and 1–3% of a class retires per hour
- the pre-race view fades out by half distance

Simulated 20,000 times as above. The Analysis tab draws each car's win chance after every update.

### Caution history

From Al Kamel's lap-by-lap time cards for past editions of the race: the flag at the line on every lap
(available from 2021). Earlier years have no flag column, so a caution is taken as the top class running
30%+ off green pace for over 2.5 minutes; checked against 2021–2025, that found 40 of 43 cautions
(back-to-back cautions merge). From that: cautions per race, time under caution, the chance of a caution
in each race hour, and a heat map of which laps ran under caution.

### Weather and radar

- **Forecast** (every 30 minutes around race weekends): National Weather Service hourly forecast and
  Open-Meteo for the track's own coordinates, turned into a timeline of what changes when (rain, sunset,
  dark, cooling) with the estimated lap.
- **At the track now** (every 5 minutes): Open-Meteo's model at the track, and the latest reading from the
  nearest weather station (for Road Atlanta, Gainesville airport, 14 km).
- **Radar nowcast**: forecast models miss pop-up storms, so the analyst reads RainViewer's two latest
  radar frames around the track (zoom 7, about 1 km a pixel), finds the nearest rain and its intensity,
  estimates how the rain field is moving from the shift between the frames, and extrapolates: when (if
  at all, within 3 hours) rain would reach the track. A rough heads-up, labelled as such. The Weather
  card shows a looping radar map centred on the track.
- **Track temperature**: IMSA's own station at the track (Al Kamel's `26_Weather` file, about hourly).

### Audits

After a race, `tools/audit/` scores these predictions against what happened (see its README for the
Petit Le Mans 2026 findings and the tuning that came out of them).

## Data details

- `scraper` finds the newest `00_Championship Points` PDF on Al Kamel's results site every
  `INTERVAL_MINUTES`, parses each class's Teams and Drivers tables, and writes `standings.json`.
- Live timing (`app/live.py`) is driven by IMSA's published weekend schedule (read every 6 hours into
  `schedule.json`). It only polls from 10 minutes before each WeatherTech session until 30 minutes after
  its scheduled end. While a session runs, every `LIVE_RACE_SECONDS` (10) in the race /
  `LIVE_SESSION_SECONDS` (15) otherwise: every car's laps and pit stops (`laps.json`, `race_state.json`),
  class timing and the championship if it finished now (`live.json`); qualifying positions go to
  `quali.json`. Every `STRATEGY_SECONDS` (300): pace over the last 5 clean laps, its trend, and pace
  against the cars either side. Failed requests back off exponentially up to 15 minutes.
- Telemetry (`app/telemetry.py`): one WebSocket to the stream behind imsa.com/telemetry (about 1 Hz, push
  only). Per car: energy at each lap, every refuel, and every pit-lane visit (refuelling, air jacks taken
  as a tyre change, driver change). From that: energy per lap, laps left on the tank, next stop, next fill
  time and stops to the flag. LMP2 has no telemetry; the pages fall back to stint lengths.
- After each race, Al Kamel's race reports for every round this season go into `history.json` (finish,
  grid, best lap, stops, stint lengths, laps per driver), cached in `history/`. `baseline.json` holds last
  season's stint lengths and pit-lane time at the next event's track.
- `app/racecontrol.py`: Al Kamel's official race control log (`25_FlagsAnalysisWithRCMessages`), after
  each session and hourly in endurance races. IMSA's live feeds don't carry race control messages.
- `app/sectors.py`: best and typical sector times and the ideal lap from Al Kamel's time cards.
- `app/bop.py`: IMSA's event BoP bulletin (stint energy and refuel rate per make), so a refuel's length is
  exact for GTD / GTD PRO.
- `app/watch.py`: IMSA's YouTube RSS feed for session streams (embedded with YouTube's player) and IMSA.tv
  in-car cameras (linked).
- `web/track.js`: the track outline behind the pages (OpenStreetMap, ODbL) and Corvette Racing's honours
  in the margins.

## Recordings and replay

Every WeatherTech session is recorded to `./archive/<date>_<session>/`: `feed.jsonl.gz` (every
leaderboard poll), `telemetry.jsonl.gz`, `pit.jsonl.gz` (about 1 Hz while a car is in the pit lane) and
`outputs.jsonl.gz` (live.json / laps.json every 5 minutes). The scraper log is `./archive/scraper.log`.
To rebuild what the live code computed:

    docker compose exec scraper python replay.py /data/archive/<folder> /tmp/replay

## Status page (this machine only)

http://localhost:8089, refreshed every 5 s: scraper heartbeat, live session window, feed and telemetry
freshness, the current recording and disk space, tunnel connections, public requests/min, recent
warnings and errors, and the guest book moderation queue. Not in the tunnel's ingress, so never public.

## Making changes during a race

Production keeps its data across restarts: the scraper saves the whole session state on every poll and
restores it on start. Web-only changes (`docker compose up -d --no-deps web`) and analyst changes
(`docker compose up -d --no-deps analyst`) never touch the scraper.

The dev site (`compose.dev.yaml`) is separate from production:

    ./dev.sh up              # http://localhost:8098 (DEV badge): ./web from disk, production's data
                             # read-only. NOTE: this stops the dev recorder.
    ./dev.sh replay [dir]    # run ./app over a recording into dev data; no IMSA traffic
    ./dev.sh scraper         # a second recorder live against IMSA (30 s polling)
    ./dev.sh update-scraper  # update production's scraper, then fill its gap from the dev recorder
    ./dev.sh fill-gap        # just the gap fill
    ./dev.sh prod-data       # dev site back on production's data
    ./dev.sh down

To change the scraper mid-race: start the dev recorder (`./dev.sh scraper`) well before, push the change,
wait for the image build, then `./dev.sh update-scraper`. Production restarts on the new image and merges
the dev recorder's state (`app/merge.py`: same session only, adds what's missing). Never pull and recreate
the scraper by hand mid-race: the analyst uses the same image, so a newer one may already be pulled.

## License and credits

Unofficial fan project, not affiliated with IMSA, Al Kamel, GM, Chevrolet or Corvette Racing. Track
outlines © OpenStreetMap contributors (ODbL). Weather: National Weather Service, Open-Meteo (CC BY 4.0),
RainViewer.
