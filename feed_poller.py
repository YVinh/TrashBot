"""Reads the two things X knows that the bot doesn't: replies from real people
in the bots' threads, and the engagement counts on Marc's posts. Both go into
the public site's feed.json (see feed_publisher.py).

This costs X API read credits, so it runs only when FEED_POLL_HOURS is set.
Marc's own credentials are used (user context — that's what returns the
impression count on his tweets). search/recent only covers the last 7 days,
which is also all we care about: threads older than that are done.

Real people are shown as "Visiteur n°NNNN": a stable number derived from their
author id, never their handle or name. Every new reply is screened by Claude
before it goes on the site — the bots are meant to provoke, and what they
provoke shouldn't be republished if it's a slur, a threat, or someone's
personal details. Fail-closed: if the screen errors, the reply is not shown."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os

import anthropic
import tweepy

import feed_publisher as feed
from x_accounts import make_v2_client

logger = logging.getLogger(__name__)

# The bots themselves — their replies are recorded by bot.py at post time, and a
# reply from one of them must never be shown as a "visitor".
BOT_USERNAMES = {"bxlpoubelle", "giselledebxl", "yousufbxlpropre"}
MAX_THREAD_AGE_DAYS = 7
MODERATION_MODEL = "claude-opus-5"

MODERATION_PROMPT = """You screen replies that members of the public posted under a satirical bot \
thread about litter in Brussels, before they are republished (anonymised) on the project's website.

Answer SHOW if the reply is fit to republish: ordinary disagreement, mockery, complaints, \
rudeness, swearing at the situation or at the bots are all fine — that's the point of the piece.

Answer HIDE only if the reply contains: slurs or hate towards a group; threats or incitement; \
someone's personal details (name of a private person, address, phone, licence plate); \
sexual content; spam or scams. When in doubt, HIDE.

Reply with exactly one word: SHOW or HIDE."""


def visitor_number(author_id: str | int) -> str:
    salt = os.getenv("FEED_VISITOR_SALT", "trashbot-village")
    digest = hashlib.sha256(f"{salt}:{author_id}".encode()).hexdigest()
    return f"{int(digest, 16) % 10000:04d}"


def fit_to_show(text: str) -> bool:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        logger.warning("CLAUDE_API_KEY not set — public reply hidden (fail-closed)")
        return False
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODERATION_MODEL,
            max_tokens=16,
            system=MODERATION_PROMPT,
            messages=[{"role": "user", "content": f"Reply to screen:\n\n{text}"}],
        )
        verdict = "".join(b.text for b in response.content if b.type == "text").strip().upper()
        return verdict.startswith("SHOW")
    except anthropic.APIError:
        logger.exception("Moderation call failed — public reply hidden (fail-closed)")
        return False


def _metrics(tweet) -> dict:
    pm = tweet.public_metrics or {}
    return {
        "likes": pm.get("like_count", 0),
        "reposts": pm.get("retweet_count", 0) + pm.get("quote_count", 0),
        "replies": pm.get("reply_count", 0),
        "impressions": pm.get("impression_count", 0),
    }


def poll_once() -> bool:
    """One pass over the recent threads. Returns True if the feed changed."""
    client = make_v2_client("MARC")  # falls through to Marc's unprefixed X_* credentials
    data = feed.load_feed()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_THREAD_AGE_DAYS)
    changed = False

    for obs in data["observations"]:
        started = dt.datetime.fromisoformat(obs["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        if started < cutoff:
            continue
        chain_id = obs["id"]
        known_ids = {p["id"] for p in obs["posts"]}
        hidden_ids = set(obs.get("hidden", []))

        try:
            root = client.get_tweet(chain_id, tweet_fields=["public_metrics"], user_auth=True)
            if root.data:
                changed |= feed.set_metrics(chain_id, chain_id, _metrics(root.data))
        except tweepy.TweepyException:
            logger.exception("Could not fetch metrics for %s", chain_id)

        try:
            result = client.search_recent_tweets(
                query=f"conversation_id:{chain_id}",
                max_results=100,
                tweet_fields=["created_at", "author_id", "referenced_tweets"],
                expansions=["author_id"],
                user_auth=True,
            )
        except tweepy.TweepyException:
            logger.exception("Could not search replies for %s", chain_id)
            continue

        users = {u.id: u for u in (result.includes or {}).get("users", [])}
        for tweet in result.data or []:
            tid = str(tweet.id)
            if tid in known_ids or tid in hidden_ids:
                continue
            user = users.get(tweet.author_id)
            if user is None or user.username.lower() in BOT_USERNAMES:
                continue
            if not fit_to_show(tweet.text):
                # Remember the decision so the next poll doesn't pay to re-screen it.
                d = feed.load_feed()
                for o in d["observations"]:
                    if o["id"] == chain_id:
                        o.setdefault("hidden", []).append(tid)
                feed.save_feed(d)
                changed = True
                continue
            reply_to = next(
                (str(r.id) for r in (tweet.referenced_tweets or []) if r.type == "replied_to"), None
            )
            changed |= feed.record_visitor(
                chain_id,
                post_id=tid,
                visitor=visitor_number(tweet.author_id),
                text=tweet.text,
                reply_to=reply_to,
                at=tweet.created_at.isoformat(timespec="seconds"),
            )

    return changed


def poll_and_publish():
    if poll_once():
        feed.publish()
