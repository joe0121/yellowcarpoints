"""IMSA telemetry (energy, refuelling, pit lane), pushed over AppSync Events.

This is the stream behind imsa.com/telemetry, using the public key that page ships with.
It's a push stream (about 1 Hz), so there is no polling: one WebSocket stays open while
a WeatherTech session is scheduled and is closed otherwise. Unofficial: if IMSA changes or
blocks it, the strategy page falls back to lap-count estimates.

Per car we keep the latest values, energy at each lap crossing, and every refuel
(is_recharging true -> false) with its duration and how much energy went in.
"""

import base64
import json
import logging
import threading
import time
import uuid

import websocket

from archive import RECORDER
from common import CLASSES

API = "wzidxebhlbgqpm7kt22wkx2pri"
HOST = f"{API}.appsync-api.us-east-1.amazonaws.com"
URL = f"wss://{API}.appsync-realtime-api.us-east-1.amazonaws.com/event/realtime"
KEY = "da2-zjztqnoq7zfsxjenuhapcprllu"  # public key embedded in imsa.com/telemetry
CHANNELS = ("/telemetry/message", "/telemetry/session")
STALE = 300  # reconnect if nothing arrives for this long
# is_jacked_up's scale isn't documented: count time above this as "on the jacks" (likely a tyre
# change) and keep the per-stop maximum so the threshold can be checked against recordings.
JACK_ON = 0.5
TYRES_MIN_SECS = 5

log = logging.getLogger("scraper.telemetry")


class Telemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.cars, self.session, self.session_key = {}, None, None
        self.wanted = False
        self.thread = None
        self.ws = None
        self.last_data = 0.0

    # --- lifecycle -------------------------------------------------------------

    def ensure(self, on):
        """Open the stream while `on`, close it otherwise."""
        self.wanted = on
        if on and not (self.thread and self.thread.is_alive()):
            self.thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
            self.thread.start()
        elif not on and self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _run(self):
        failures = 0
        while self.wanted:
            try:
                self._connect_and_read()
                failures = 0
            except Exception as e:
                failures += 1
                log.warning("telemetry stream dropped (%s), retry %d", e, failures)
            if self.wanted:
                time.sleep(min(30 * 2 ** failures, 900))
        log.info("telemetry stream closed")

    def _connect_and_read(self):
        header = base64.urlsafe_b64encode(json.dumps({"host": HOST, "x-api-key": KEY}).encode()).decode().rstrip("=")
        self.ws = ws = websocket.create_connection(
            URL, subprotocols=["aws-appsync-event-ws", f"header-{header}"], timeout=60,
            header={"User-Agent": "yellowcarpoints.win standings tracker"})
        try:
            ws.send(json.dumps({"type": "connection_init"}))
            for channel in CHANNELS:
                ws.send(json.dumps({"type": "subscribe", "id": str(uuid.uuid4()), "channel": channel,
                                    "authorization": {"x-api-key": KEY, "host": HOST}}))
            log.info("telemetry stream open")
            self.last_data = time.time()
            while self.wanted:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    raw = "{}"
                if not raw:
                    if not self.wanted:
                        break
                    raise ConnectionError("closed by server")
                msg = json.loads(raw)
                if time.time() - self.last_data > STALE:
                    raise ConnectionError("no data")
                kind = msg.get("type")
                if kind == "data":
                    self.last_data = time.time()
                    self._handle(msg.get("event"))
                elif kind in ("error", "subscribe_error", "connection_error"):
                    raise ConnectionError(str(msg)[:200])
        finally:
            self.ws = None
            ws.close()

    # --- messages --------------------------------------------------------------

    def _handle(self, event):
        ev = json.loads(event) if isinstance(event, str) else event
        raw = ev.get("data") if isinstance(ev, dict) else ev
        payload = json.loads(base64.b64decode(raw)) if isinstance(raw, str) else raw
        with self.lock:
            if isinstance(payload, dict):
                self.session = payload
                key = (payload.get("series_name_short"), payload.get("session_name"), payload.get("session_start_time"))
                if key != self.session_key:
                    self.session_key, self.cars = key, {}
                    RECORDER.telemetry_session(payload)
            elif isinstance(payload, list):
                for f in payload:
                    self._car(f)
                RECORDER.telemetry_cars(payload)
                RECORDER.telemetry_pit(payload)

    def _car(self, f):
        sc = f.get("scoring") or {}
        cls, number = sc.get("class"), sc.get("number")
        if cls not in CLASSES or not number:
            return
        now = f.get("time") or time.time()
        energy = f.get("energy_remaining")
        lap = int(f.get("lap_number") or 0)
        st = self.cars.setdefault(number, {"cls": cls, "lap_energy": [], "refills": [], "refill": None,
                                           "pit_since": None, "pit_visits": [], "stops": [], "visit": None})
        # Energy at each lap crossing (the first reading on a new lap).
        if energy is not None and lap and (not st["lap_energy"] or lap > st["lap_energy"][-1][0]):
            st["lap_energy"].append([lap, round(energy, 1)])
            st["lap_energy"] = st["lap_energy"][-400:]
        # Refuels: is_recharging from true back to false.
        if f.get("is_recharging") and not st["refill"]:
            st["refill"] = {"lap": lap, "start": now, "from": energy}
        elif not f.get("is_recharging") and st["refill"]:
            r = st["refill"]
            secs = now - r["start"]
            if 1 < secs < 120 and energy is not None and r["from"] is not None and energy > r["from"]:
                st["refills"].append({"lap": r["lap"], "secs": round(secs, 1), "from": r["from"], "to": energy,
                                      "rate": round((energy - r["from"]) / secs, 3)})
            st["refill"] = None
        # Pit-lane visits, timed at the telemetry's ~1 Hz (entry to exit), with what happened in them:
        # seconds refuelling, seconds on the air jacks (tyres) and whether the driver changed.
        # Garage visits and drive-throughs are kept out by the bounds.
        a = sc.get("activeDriver") or {}
        driver = f'{a.get("firstName") or ""} {a.get("lastName") or ""}'.strip() or None
        jack = f.get("is_jacked_up") or 0
        if f.get("pit_lane"):
            v = st.get("visit")
            if not v:
                st["pit_since"] = now
                v = st["visit"] = {"lap": lap, "start": now, "last": now, "fuel": 0.0, "jack": 0.0, "jack_max": 0.0,
                                   "driver_in": driver, "e_in": energy}
            dt = min(max(now - v["last"], 0), 3)
            if f.get("is_recharging"):
                v["fuel"] += dt
            if jack > JACK_ON:
                v["jack"] += dt
            v["jack_max"] = max(v["jack_max"], jack)
            v["last"] = now
            if driver:
                v["driver_out"] = driver
        elif st.get("visit"):
            v = st["visit"]
            lane = now - v["start"]
            if 20 <= lane <= 300:
                st.setdefault("pit_visits", []).append(round(lane, 1))
                st["pit_visits"] = st["pit_visits"][-20:]
                st.setdefault("stops", []).append({
                    "lap": v["lap"], "lane": round(lane, 1), "fuel": round(v["fuel"], 1), "jack": round(v["jack"], 1),
                    "jack_max": round(v["jack_max"], 3), "tyres": v["jack"] >= TYRES_MIN_SECS,
                    "driver_change": bool(v.get("driver_in") and v.get("driver_out") and v["driver_in"] != v["driver_out"]),
                    "driver_in": v.get("driver_in"), "driver_out": v.get("driver_out"),
                    "e_in": v["e_in"], "e_out": energy})
                st["stops"] = st["stops"][-20:]
            st["visit"] = None
            st["pit_since"] = None
        st.update(energy=energy, lap=lap, pit_lane=bool(f.get("pit_lane")), recharging=bool(f.get("is_recharging")),
                  speed=f.get("speed"), seen=now)

    def snapshot(self):
        with self.lock:
            return {"session": dict(self.session or {}), "connected": bool(self.ws),
                    "last_data": self.last_data, "cars": json.loads(json.dumps(self.cars))}
