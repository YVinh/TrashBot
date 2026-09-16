"""Writes the bots' posts to the public site (site/feed.json + site/media/) and
ships it, so people can read the threads without logging in to X.

bot.py already knows every tweet the instant it posts it — text, id, who said it,
what it replies to — so the site never needs to *read* X for the bots' own posts.
It records here, then `publish()` runs whatever command ships the folder (a git
push to the Pages repo, an rsync to a web host — see FEED_PUBLISH_CMD).

Marc's photos are archived downsized and with all metadata dropped: the originals
carry GPS coordinates by design (that's how the hashtags get picked), and those
must not end up on a public site."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from heic_utils import is_heic, open_heic
import link_preview

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).parent
SOURCE_SITE_DIR = PROJECT_DIR / "site"
# Where the deployable copy lives. Defaults to the source tree (fine for local
# runs); on the server point it at a clone of the site repo so the bot's feed
# commits don't land in the code repo.
SITE_DIR = Path(os.getenv("FEED_SITE_DIR") or SOURCE_SITE_DIR)
PUBLISH_CMD = os.getenv("FEED_PUBLISH_CMD", "").strip()

URL_RE = re.compile(r"https?://\S+")
MAX_IMAGE_EDGE = 1200


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_feed() -> dict:
    try:
        data = json.loads((SITE_DIR / "feed.json").read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    if data.get("sample"):
        # The design prototype ships with example threads; the first real post
        # replaces them rather than sitting underneath invented ones.
        data = {}
    data.setdefault("observations", [])
    return data


def save_feed(data: dict):
    data["generated_at"] = _now()
    data.pop("sample", None)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SITE_DIR / "feed.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(SITE_DIR / "feed.json")


def _observation(data: dict, chain_id: str) -> dict:
    for obs in data["observations"]:
        if obs["id"] == chain_id:
            return obs
    obs = {"id": chain_id, "started_at": _now(), "posts": []}
    data["observations"].append(obs)
    return obs


def _archive_image(image_path: str, post_id: str) -> str:
    img = open_heic(image_path) if is_heic(image_path) else Image.open(image_path)
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    media = SITE_DIR / "media"
    media.mkdir(parents=True, exist_ok=True)
    # Saving a fresh Image without an exif= argument writes no EXIF at all.
    img.save(media / f"{post_id}.jpg", "JPEG", quality=85, optimize=True)
    return f"media/{post_id}.jpg"


def record_post(
    chain_id: str,
    *,
    post_id: str,
    author: str,
    text: str,
    reply_to: str | None = None,
    image_path: str | None = None,
    url: str | None = None,
    at: str | None = None,
) -> bool:
    """Append one of the bots' posts to its thread. Returns False if it was
    already there (a chain resumed after a restart may record twice)."""
    data = load_feed()
    obs = _observation(data, chain_id)
    if any(p["id"] == post_id for p in obs["posts"]):
        return False

    post = {"id": post_id, "author": author, "at": at or _now(), "reply_to": reply_to, "text": text}
    if url:
        post["url"] = url
    if author == "giselle":
        # Her "proof" is the trailing link; the site renders it as a link card
        # with the article's own title and picture, fetched now (X does the same
        # server-side — the browser can't read another site's page).
        urls = URL_RE.findall(text)
        if urls:
            post["source_url"] = urls[-1].rstrip(".,)")
            card = link_preview.fetch_card(post["source_url"], SITE_DIR / "media", post_id)
            if card:
                post["source_card"] = card
    if image_path:
        try:
            post["image"] = _archive_image(image_path, post_id)
        except Exception:
            logger.exception("Could not archive %s for the feed", image_path)
            post["image"] = None

    obs["posts"].append(post)
    save_feed(data)
    return True


def record_visitor(chain_id: str, *, post_id: str, visitor: str, text: str, reply_to: str | None, at: str) -> bool:
    """A real person's reply, shown as a numbered visitor — no handle, no name."""
    data = load_feed()
    obs = _observation(data, chain_id)
    if any(p["id"] == post_id for p in obs["posts"]):
        return False
    obs["posts"].append(
        {"id": post_id, "author": "public", "visitor": visitor, "at": at, "reply_to": reply_to, "text": text}
    )
    save_feed(data)
    return True


def set_metrics(chain_id: str, post_id: str, metrics: dict) -> bool:
    data = load_feed()
    for obs in data["observations"]:
        if obs["id"] != chain_id:
            continue
        for post in obs["posts"]:
            if post["id"] == post_id:
                post["metrics"] = {**metrics, "fetched_at": _now()}
                save_feed(data)
                return True
    return False


def set_report(chain_id: str, post_id: str, report: dict) -> bool:
    """Attach the FixMyStreet report (id, url, category, status) to Marc's post."""
    data = load_feed()
    for obs in data["observations"]:
        if obs["id"] != chain_id:
            continue
        for post in obs["posts"]:
            if post["id"] == post_id:
                post["report"] = {**post.get("report", {}), **report}
                save_feed(data)
                return True
    return False


def refresh_report_statuses(lookup) -> bool:
    """Update the status of open reports via `lookup(id) -> {status, ...} | None`.
    Returns True if anything changed."""
    data = load_feed()
    changed = False
    for obs in data["observations"]:
        for post in obs["posts"]:
            rep = post.get("report")
            if not rep or rep.get("status") in ("CLOSED", "DISMISSED"):
                continue
            info = lookup(rep["id"])
            if info and info.get("status") and info["status"] != rep.get("status"):
                rep["status"] = info["status"]
                if info.get("organisation"):
                    rep["organisation"] = info["organisation"]
                changed = True
    if changed:
        save_feed(data)
    return changed


def backfill_cards() -> int:
    """Fetch link cards for Giselle posts recorded before cards existed."""
    data = load_feed()
    n = 0
    for obs in data["observations"]:
        for post in obs["posts"]:
            if post.get("source_url") and "source_card" not in post:
                card = link_preview.fetch_card(post["source_url"], SITE_DIR / "media", post["id"])
                if card:
                    post["source_card"] = card
                    n += 1
    if n:
        save_feed(data)
    return n


def publish():
    """Ship the site. The page itself is copied from the source tree first, so a
    design change deploys with the next post without a separate step."""
    if SITE_DIR.resolve() != SOURCE_SITE_DIR.resolve():
        SITE_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("index.html",):
            shutil.copy2(SOURCE_SITE_DIR / name, SITE_DIR / name)
        src_media, dst_media = SOURCE_SITE_DIR / "media", SITE_DIR / "media"
        dst_media.mkdir(exist_ok=True)
        for f in src_media.glob("avatar-*.jpg"):
            shutil.copy2(f, dst_media / f.name)

    if not PUBLISH_CMD:
        logger.info("FEED_PUBLISH_CMD not set — feed written to %s but not published", SITE_DIR)
        return
    try:
        subprocess.run(
            PUBLISH_CMD, shell=True, cwd=SITE_DIR, check=True, timeout=180, capture_output=True, text=True
        )
        logger.info("Feed published")
    except subprocess.CalledProcessError as e:
        # A "nothing to commit" is the usual reason git exits non-zero here; it's not an error.
        if "nothing to commit" in (e.stdout or "") + (e.stderr or ""):
            logger.info("Feed unchanged, nothing to publish")
            return
        logger.error("Publishing the feed failed: %s", (e.stderr or e.stdout or "").strip()[-500:])
        raise
