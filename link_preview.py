"""Fetches what a link card needs from an article page — its Open Graph title,
description, site name and picture — so the public site can show Giselle's
"proof" the way X does, with the article's photo. Only stdlib: the bot doesn't
need another dependency for one HTTP GET per Giselle reply.

Best effort by design: a paywall, a consent wall, a bot block or a missing
og:image leaves a plain card (domain + title if any). Never raises to callers."""

from __future__ import annotations

import io
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; TrashbotVillage/1.0; +https://trashbotvillage.com)"
TIMEOUT = 12
MAX_HTML_BYTES = 2_000_000
MAX_IMAGE_BYTES = 15_000_000
CARD_IMAGE_WIDTH = 1000


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("property") or a.get("name") or "").lower()
            content = a.get("content")
            if key and content and key not in self.meta:
                self.meta[key] = content.strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_og(html: str, base_url: str) -> dict:
    """Pick title / description / site / image out of a page's <head>."""
    p = _MetaParser()
    try:
        p.feed(html)
    except Exception:  # malformed markup — use whatever was collected
        pass
    m = p.meta
    image = m.get("og:image:secure_url") or m.get("og:image") or m.get("twitter:image") or ""
    if image:
        image = urllib.parse.urljoin(base_url, image)
    site = m.get("og:site_name") or urllib.parse.urlsplit(base_url).hostname or ""
    return {
        "title": (m.get("og:title") or m.get("twitter:title") or p.title.strip())[:200],
        "description": (m.get("og:description") or m.get("description") or "")[:300],
        "site": site.removeprefix("www."),
        "image": image,
    }


def _get(url: str, max_bytes: int) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(max_bytes), resp.headers.get_content_type()


def fetch_card(url: str, media_dir: Path, post_id: str) -> dict | None:
    """Return {title, description, site, image?} for the site's feed.json, with
    the article picture saved as media/<post_id>-card.jpg. None if the page
    couldn't be read at all."""
    try:
        body, ctype = _get(url, MAX_HTML_BYTES)
    except (urllib.error.URLError, ValueError, OSError) as e:
        logger.warning("Link card: could not fetch %s (%s)", url, e)
        return None
    if not ctype.startswith("text/html"):
        return None
    card = parse_og(body.decode("utf-8", errors="replace"), url)
    image_url = card.pop("image", "")
    if image_url:
        try:
            data, image_type = _get(image_url, MAX_IMAGE_BYTES)
            if image_type == "image/svg+xml":  # a site logo, not a photo — plain card is better
                return card
            img = Image.open(io.BytesIO(data)).convert("RGB")
            if img.width > CARD_IMAGE_WIDTH:
                img = img.resize((CARD_IMAGE_WIDTH, round(img.height * CARD_IMAGE_WIDTH / img.width)), Image.LANCZOS)
            media_dir.mkdir(parents=True, exist_ok=True)
            img.save(media_dir / f"{post_id}-card.jpg", "JPEG", quality=82, optimize=True)
            card["image"] = f"media/{post_id}-card.jpg"
        except Exception as e:
            logger.warning("Link card: could not fetch image for %s (%s)", url, e)
    return card
