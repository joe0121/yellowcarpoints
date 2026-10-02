"""What to show in the site's Watch card: IMSA's YouTube streams and any IMSA.tv in-car feeds.

Nothing is re-hosted. We read YouTube's public RSS feed for IMSA's channel (no API key, no page
scraping) to find WeatherTech session streams by title; the page embeds them with YouTube's own
player. Live streams appear in the feed once they start and stay as replays. IMSA.tv's in-car
cameras play in IMSA's own tokenised player, so we only note which cars have one and link to it.
Checked every few minutes during a session window and hourly otherwise.
"""

import logging
import re
import xml.etree.ElementTree as ET

from common import http, now_iso, read, write

log = logging.getLogger("scraper.watch")
CHANNEL = "UC58em84jwiyM20qR-iqBDZw"   # IMSA Official
RSS = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"
TVLIVE = "https://www.imsa.com/tvlive/"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
# Support series share the weekend; their streams are left out.
OTHER_SERIES = re.compile(r"Pilot Challenge|Fox Factory|VP Racing|Porsche|Carrera|Mazda|MX-5|Lamborghini|Super ?Trofeo|Mustang|GR Cup|Ferrari", re.I)
OURS = re.compile(r"WeatherTech|Petit Le Mans|Rolex 24|Sebring 12|Watkins Glen 6|Battle on the Bricks", re.I)


def weathertech_videos():
    root = ET.fromstring(http.get(RSS, timeout=30).content)
    out = []
    for e in root.findall("a:entry", NS):
        title = e.find("a:title", NS).text or ""
        # Session streams are titled like "2026 IMSA Motul Petit Le Mans | Qualifying | WeatherTech Championship | ...".
        if re.match(r"20\d\d IMSA ", title) and OURS.search(title) and not OTHER_SERIES.search(title):
            out.append({"id": e.find("yt:videoId", NS).text, "title": title, "published": e.find("a:published", NS).text})
    return out


def incar_cars():
    """Car numbers IMSA.tv lists with an in-car camera ('... No. 1 ...' near 'in-car'), if any."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", http.get(TVLIVE, timeout=30).text))
    cars = set()
    for m in re.finditer(r"(?i)in-?car|onboard", text):
        cars.update(re.findall(r"No\.\s*(\d{1,3})\b", text[max(0, m.start() - 400):m.end() + 400]))
    return sorted(cars, key=int)


def refresh():
    old = read("watch.json") or {}
    doc = {"updated": now_iso(), "channel": CHANNEL, "videos": old.get("videos", []),
           "incar": old.get("incar", []), "incar_url": TVLIVE}
    try:
        doc["videos"] = weathertech_videos()
    except Exception:
        log.exception("YouTube feed failed")
    try:
        doc["incar"] = incar_cars()
    except Exception:
        log.exception("IMSA.tv page failed")
    write("watch.json", doc)
    return doc
