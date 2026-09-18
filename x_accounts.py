"""Multi-account X (Twitter) client factory.

Marc keeps using the original unprefixed X_* env vars (backward compatible with
twitter_poster.py). Giselle and Yousuf use prefixed vars, e.g. GISELLE_X_API_KEY,
so all three accounts' credentials can live side by side in one .env.
"""

from __future__ import annotations

import logging
import os
import time

import tweepy

logger = logging.getLogger(__name__)

# X occasionally returns a transient error on write calls that clears up
# within seconds — a real 503 from X's own servers, and (observed in
# practice, not just documentation) a "You are not permitted to perform this
# action" 403 that succeeded immediately on manual retry with no code or
# credential change. Retrying a couple of times beats silently losing a
# post and needing a human to notice and retry it by hand. Not retried:
# Unauthorized (401, a real auth problem) and BadRequest (400, retrying
# won't fix bad content).
RETRYABLE_X_ERRORS = (tweepy.errors.TwitterServerError, tweepy.errors.Forbidden)
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 8


def call_with_retry(func, *args, **kwargs):
    """Call func(*args, **kwargs), retrying on RETRYABLE_X_ERRORS a few times."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return func(*args, **kwargs)
        except RETRYABLE_X_ERRORS as e:
            if attempt == RETRY_ATTEMPTS:
                raise
            logger.warning(
                "%s attempt %d/%d failed with %s, retrying in %ds",
                getattr(func, "__name__", func), attempt, RETRY_ATTEMPTS, e, RETRY_DELAY_SECONDS,
            )
            time.sleep(RETRY_DELAY_SECONDS)


def _cred(prefix: str, name: str) -> str | None:
    return os.getenv(f"{prefix}_{name}") or os.getenv(name)


def make_v2_client(prefix: str) -> tweepy.Client:
    """Build a v2 client (posting/reading) for the given account prefix, e.g. 'GISELLE'."""
    keys = {
        "consumer_key": _cred(prefix, "X_API_KEY"),
        "consumer_secret": _cred(prefix, "X_API_SECRET"),
        "access_token": _cred(prefix, "X_ACCESS_TOKEN"),
        "access_token_secret": _cred(prefix, "X_ACCESS_TOKEN_SECRET"),
    }
    if not all(keys.values()):
        raise ValueError(
            f"Missing X credentials for '{prefix}' — set {prefix}_X_API_KEY, "
            f"{prefix}_X_API_SECRET, {prefix}_X_ACCESS_TOKEN and "
            f"{prefix}_X_ACCESS_TOKEN_SECRET in .env"
        )
    return tweepy.Client(**keys)


def post_reply(prefix: str, in_reply_to_tweet_id: str, text: str) -> dict:
    client = make_v2_client(prefix)
    response = call_with_retry(
        client.create_tweet, text=text, in_reply_to_tweet_id=in_reply_to_tweet_id
    )
    post_id = response.data["id"]
    return {"post_id": post_id, "post_url": f"https://x.com/i/web/status/{post_id}"}
