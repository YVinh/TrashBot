"""Multi-account X (Twitter) client factory.

Marc keeps using the original unprefixed X_* env vars (backward compatible with
twitter_poster.py). Giselle and Yousuf use prefixed vars, e.g. GISELLE_X_API_KEY,
so all three accounts' credentials can live side by side in one .env.
"""

from __future__ import annotations

import os

import tweepy


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
    response = client.create_tweet(text=text, in_reply_to_tweet_id=in_reply_to_tweet_id)
    post_id = response.data["id"]
    return {"post_id": post_id, "post_url": f"https://x.com/i/web/status/{post_id}"}
