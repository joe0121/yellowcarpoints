#!/usr/bin/env bash
# Dev site helper. Production (compose.yaml) is never touched by these commands.
#   ./dev.sh up                 dev site on http://localhost:8098 showing production's live data
#   ./dev.sh replay [folder]    run your scraper code over a recording (default: the newest one,
#                               works mid-race) and show the result on the dev site; no IMSA traffic
#   ./dev.sh scraper            run your scraper code live against IMSA (gentler polling) into dev data
#   ./dev.sh prod-data          point the dev site back at production's live data
#   ./dev.sh down               stop the dev site
set -euo pipefail
cd "$(dirname "$0")"
DC=(docker compose -f compose.dev.yaml --env-file .env)
use_volume() { DEV_DATA_VOLUME="$1" "${DC[@]}" up -d --build web api >/dev/null; echo "Dev site: http://localhost:8098 (data: $1)"; }
case "${1:-up}" in
  up|prod-data)
    "${DC[@]}" stop scraper >/dev/null 2>&1 || true
    use_volume yellowcarpoints_data ;;
  replay)
    dir="${2:-$(ls -td archive/*/ | head -1)}"
    echo "Replaying ${dir%/} with the scraper code in ./app ..."
    "${DC[@]}" --profile scraper build -q scraper
    docker volume create ycp-dev_dev-data >/dev/null
    # Replay the recording into the dev volume, seeded with production's standings, schedule, etc.
    docker run --rm --user 0 -v yellowcarpoints_data:/prod:ro -v ycp-dev_dev-data:/devdata \
      -v "$PWD/app:/src:ro" -v "$PWD/${dir%/}:/rec:ro" --entrypoint sh ycp-scraper:dev -c \
      'cd /src && python replay.py /rec /devdata --data /prod | tail -2 &&
       for f in schedule.json sectors.json history.json config.json watch.json bop.json; do [ -e /prod/$f ] && cp /prod/$f /devdata/; done; true'
    use_volume ycp-dev_dev-data ;;
  scraper)
    "${DC[@]}" --profile scraper up -d --build scraper >/dev/null
    use_volume ycp-dev_dev-data
    echo "Dev scraper running (logs: docker compose -f compose.dev.yaml logs -f scraper)" ;;
  down)
    "${DC[@]}" --profile scraper down ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
