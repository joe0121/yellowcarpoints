# Race prediction and caution history (offline)

Run by hand once qualifying is done; the outputs go into the site's data volume.

```sh
cd tools/predict
../../.venv/bin/python fetch.py              # past race/qualifying/practice results (2024+, JSON), cached in cache/
../../.venv/bin/python bt_final.py           # backtest -> backtest.json (each season predicted from earlier ones)
docker compose exec -T scraper cat /data/standings.json > standings.json
docker compose exec -T scraper cat /data/quali.json > quali.json
../../.venv/bin/python predict_now.py        # fit on every finished race, simulate the next one -> predict.json
../../.venv/bin/python fetch_plm.py          # Petit Le Mans time cards (CSV with FLAG_AT_FL) -> plm/
../../.venv/bin/python insights.py           # caution history -> insights.json
for f in predict insights; do docker compose exec -T scraper sh -c "cat > /data/$f.json" < $f.json; done
```

The model (model.py) is Plackett-Luce on: starting position, best practice lap gap, form (this season,
last season at half weight), retirement rate and the number of Bronze drivers. It's fitted on the top 3 of
each class, which suits win/podium odds. fetch_plm.py and insights.py are Road Atlanta specific for now.
Requests are spaced 1 s apart; everything is cached so reruns only fetch new events.
