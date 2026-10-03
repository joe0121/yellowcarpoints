"""Onboard and team livestreams for the current race, from manufacturers' and teams' YouTube channels.

IMSA's own channel carries the broadcast; onboard cameras are streamed by the makes and teams themselves
(e.g. Cadillac Racing's "Experience Petit Le Mans | IMSA Livestream", Ford Racing's "Mustang GT3 Onboard
Cam"). We read each channel's public RSS feed (no API key) during race weekends and keep the streams whose
titles name this event and look like a live/onboard stream. Run by the analyst, written to onboards.json;
the Race page's Watch card lets viewers switch to them (embedded with YouTube's player, nothing re-hosted).
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from common import http, now_iso, read, write

log = logging.getLogger("analyst.onboards")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
# make: the manufacturer as live timing names it (so the selected car's make comes first).
CHANNELS = [
    ("Cadillac Racing", "UCMMTsbfETvrSwwcvB7VE-iw", "Cadillac"),
    ("Cadillac Racing", "UCl-Ai_paKPyR2GU4JRmMy7w", "Cadillac"),
    ("Chevrolet", "UCSVpCNZzOeMekuMiFze3fnQ", "Chevrolet"),
    ("Corvette Racing", "UCik2bQW1BYLYMsMM6_ob88A", "Chevrolet"),
    ("Ford Racing", "UC87j_-SIjbzUqlY8tuKlZyQ", "Ford"),
    ("Ford", "UCKA96UxTdgFBwGZMGZ-135w", "Ford"),
    ("BMW M Motorsport", "UCyQ8hm6TnkJfoAqHW_hNNDA", "BMW"),
    ("Porsche", "UC_BaxRhNREI_V0DVXjXDALA", "Porsche"),
    ("Acura", "UCxl79GCsb6-xhrdQuPgnuJA", "Acura"),
    ("Acura Performance", "UCrlaNQpiUJNLjRJqP4GL7xg", "Acura"),
    ("Lexus", "UCEDHfFp2GZonrhuAaz7VjPw", "Lexus"),
    ("Lamborghini Squadra Corse", "UCO2SBo6hz0FewMjl6n5Md-Q", "Lamborghini"),
    ("Mercedes-AMG Motorsport", "UCS6lXSV9dt6yg8uGKaLqzdg", "Mercedes-AMG"),
    ("Aston Martin", "UCYi_2iWdjuktf9GzwCMIjtw", "Aston Martin"),
    ("Ferrari", "UCd8iY-kEHtaB8qt8MH--zGw", "Ferrari"),
    ("Heart of Racing", "UCUxfA_QBcHCx8jGsR_TywPQ", "Aston Martin"),
    ("Risi Competizione", "UC_vZkh7Yous2DaWvj8ihUNw", "Ferrari"),
    ("Paul Miller Racing", "UC57u5ynX2b6Uzyt4ASQpOGw", "BMW"),
    ("AO Racing", "UC25ARkOA6RwP4DqPn31fLBg", "Porsche"),
    ("Wayne Taylor Racing", "UCNrU3tqRHOB3Sc7P4i2NZwA", "Cadillac"),
]
# Words for the current event in stream titles (live timing calls Petit Le Mans "Road Atlanta").
EVENT_WORDS = {"Road Atlanta": r"petit le mans|road atlanta"}
STREAM = re.compile(r"onboard|on-board|in-car|livestream|live stream|\blive\b|cam\b", re.I)


def refresh():
    """Returns True when it ran (a race weekend at an event we have words for)."""
    from weather import in_weekend
    event = (read("live.json") or {}).get("event") or ""
    words = next((v for k, v in EVENT_WORDS.items() if k.lower() in event.lower()), None)
    if not words or not in_weekend():
        return False
    since = datetime.now(timezone.utc) - timedelta(days=14)
    found, seen = [], set()
    for name, cid, make in CHANNELS:
        try:
            root = ET.fromstring(http.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=30).content)
        except Exception:
            log.warning("feed failed: %s", name)
            continue
        for e in root.findall("a:entry", NS):
            title, vid = e.find("a:title", NS).text or "", e.find("yt:videoId", NS).text
            published = datetime.fromisoformat(e.find("a:published", NS).text)
            if vid in seen or published < since or not re.search(words, title, re.I) or not STREAM.search(title):
                continue
            seen.add(vid)
            car = re.search(r"#\s?(\d{1,3})\b", title)
            found.append({"id": vid, "title": title, "channel": name, "make": make, "car": car and car.group(1),
                          "published": published.isoformat()})
        time.sleep(0.5)
    write("onboards.json", {"updated": now_iso(), "event": event, "streams": found})
    log.info("onboard streams: %d", len(found))
    return True
