#!/usr/bin/env bash
# Dev site helper. Only update-scraper and fill-gap touch production (compose.yaml).
#   ./dev.sh up                 dev site on http://localhost:8098 showing production's live data
#   ./dev.sh replay [folder]    run your scraper code over a recording (default: the newest one,
#                               works mid-race) and show the result on the dev site; no IMSA traffic
#   ./dev.sh scraper            run the dev scraper live against IMSA (gentler polling) into dev data:
#                               a second recorder that keeps going while production restarts
#   ./dev.sh update-scraper     update production's scraper, then fill the gap from the dev recorder
#   ./dev.sh fill-gap           just the gap fill (production merges the dev recorder's data, adding
#                               only what it's missing)
#   ./dev.sh prod-data          point the dev site back at production's live data
#   ./dev.sh down               stop the dev site and dev recorder
set -euo pipefail
cd "$(dirname "$0")"
DC=(docker compose -f compose.dev.yaml --env-file .env)
use_volume() { DEV_DATA_VOLUME="$1" "${DC[@]}" up -d --build web api >/dev/null; echo "Dev site: http://localhost:8098 (data: $1)"; }
# Hand the dev recorder's session state to production as merge files; production's next poll merges
# them (same session only) and deletes them.
fill_gap() {
  docker run --rm --user 0 -v ycp-dev_dev-data:/devdata:ro -v yellowcarpoints_data:/prod alpine sh -c '
    [ -f /devdata/race_state.json ] || { echo "No dev recorder data yet"; exit 1; }
    cp /devdata/race_state.json /prod/merge_race.json
    [ -f /devdata/telemetry_state.json ] && cp /devdata/telemetry_state.json /prod/merge_telemetry.json
    chown 65534 /prod/merge_*.json; echo "Gap-fill files handed to production; it merges them on its next poll."'
}
case "${1:-up}" in
  up|prod-data)
    "${DC[@]}" stop scraper >/dev/null 2>&1 || true
    use_volume yellowcarpoints_data ;;
  replay)
    dir="${2:-$(ls -td archive/*/ | head -1)}"
    echo "Replaying ${dir%/} with the scraper code in ./app ..."
    "${DC[@]}" --profile scraper build -q scraper
    docker volume create ycp-dev_replay-data >/dev/null
    # Replay the recording into its own volume, seeded with production's standings, schedule, etc.
    docker run --rm --user 0 -v yellowcarpoints_data:/prod:ro -v ycp-dev_replay-data:/devdata \
      -v "$PWD/app:/src:ro" -v "$PWD/${dir%/}:/rec:ro" --entrypoint sh ycp-scraper:dev -c \
      'cd /src && python replay.py /rec /devdata --data /prod | tail -2 &&
       for f in schedule.json sectors.json history.json config.json watch.json bop.json; do [ -e /prod/$f ] && cp /prod/$f /devdata/; done; true'
    use_volume ycp-dev_replay-data ;;
  scraper)
    "${DC[@]}" --profile scraper up -d --build scraper >/dev/null
    use_volume ycp-dev_dev-data
    echo "Dev scraper running (logs: docker compose -f compose.dev.yaml logs -f scraper)" ;;
  fill-gap)
    fill_gap ;;
  update-scraper)
    if ! "${DC[@]}" --profile scraper ps --status running --services 2>/dev/null | grep -qx scraper; then
      echo "The dev recorder isn't running, so nothing would cover the gap."
      echo "Start it with ./dev.sh scraper a few minutes before updating, then run this again."; exit 1
    fi
    echo "Updating production's scraper..."
    docker compose pull -q scraper && docker compose up -d --no-deps scraper
    echo "Waiting for it to pick the session back up..."; sleep 45
    fill_gap
    sleep 15; docker compose logs scraper --since 30s 2>&1 | grep -i "gap fill" || echo "(no gap-fill line yet: check docker compose logs scraper)" ;;
  down)
    "${DC[@]}" --profile scraper down ;;
  *) sed -n '2,14p' "$0"; exit 1 ;;
esac
