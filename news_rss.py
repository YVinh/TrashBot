"""Giselle's news source: Brussels regional RSS feeds filtered for litter stories.

Local models invent URLs, so the link Giselle posts is ALWAYS one of the items
fetched here — the model only writes the reaction text."""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import logging
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

SITES = ["dhnet.be", "lalibre.be", "lavenir.net"]
FEED_URL = "https://www.{site}/arc/outboundfeeds/rss/section/regions/bruxelles/?outputType=xml"
MAX_AGE_DAYS = 14
USED_FILE = Path(__file__).parent / "rss_used.json"
KEEP_USED = 50

KEYWORDS = re.compile(
    r"propret|déchet|dechet|dépôts? clandestin|poubelle|encombrant|immondice|détritus|saleté|"
    r"ordures|Bruxelles-Propreté|Net Brussel|incivilit|dépotoir|crasse|sacs? (blancs?|poubelles?)",
    re.I,
)
# Litter stories only: a waste fire or an accident is not what Giselle rants about.
EXCLUDE = re.compile(r"\bfeu\b|incendie|pompiers|explosion|bless|mort|décès|agression", re.I)


def _parse(xml_bytes: bytes, site: str) -> list[dict]:
    out = []
    for item in ET.fromstring(xml_bytes).findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        try:
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if link.startswith("https://") and title:
            out.append({"site": site, "title": title, "link": link, "published": published,
                        "summary": re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()})
    return out


def fetch_items(session=None) -> list[dict]:
    s = session or requests
    items: list[dict] = []
    for site in SITES:
        try:
            r = s.get(FEED_URL.format(site=site), timeout=20, headers={"User-Agent": "Mozilla/5.0 TrashBot"})
            r.raise_for_status()
            items += _parse(r.content, site)
        except Exception as e:  # one dead feed must not stop the others
            logger.warning("RSS %s failed: %s", site, e)
    return items


def relevant(items: list[dict], now: dt.datetime | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    keep, seen_titles = [], set()
    for it in sorted(items, key=lambda i: i["published"], reverse=True):
        text = f"{it['title']} {it['summary']}"
        if (now - it["published"]).days > MAX_AGE_DAYS or not KEYWORDS.search(text) or EXCLUDE.search(text):
            continue
        key = re.sub(r"\W+", "", it["title"].lower())[:40]
        if key in seen_titles:  # same story on two sites
            continue
        seen_titles.add(key)
        keep.append(it)
    return keep


def _used() -> list[str]:
    try:
        return json.loads(USED_FILE.read_text())
    except (OSError, ValueError):
        return []


def mark_used(link: str) -> None:
    used = [u for u in _used() if u != link] + [link]
    USED_FILE.write_text(json.dumps(used[-KEEP_USED:]))


def pick_article(items: list[dict] | None = None) -> dict | None:
    """A recent, not-yet-used litter story, or None (Giselle then reacts without a link)."""
    candidates = [i for i in relevant(fetch_items() if items is None else items) if i["link"] not in set(_used())]
    return random.choice(candidates[:3]) if candidates else None
