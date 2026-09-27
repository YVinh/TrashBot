"""Shared helper for keeping generated X captions under the character limit.

X counts any http(s) URL as a fixed 23 characters toward the 280-char limit,
regardless of its real length (t.co auto-shortening). This must never truncate
or otherwise mutate a trailing URL — a chopped link is a dead link.
"""

from __future__ import annotations

import random
import re

from anthropic import Anthropic

MAX_CAPTION_CHARS = 280
TWITTER_URL_LENGTH = 23
SHORTEN_ATTEMPTS = 3

_URL_RE = re.compile(r"(https?://\S+)\s*$")
_MENTION_RE = re.compile(r"@\w+")


def _split_trailing_url(text: str) -> tuple[str, str | None]:
    text = text.rstrip()
    match = _URL_RE.search(text)
    if not match:
        return text, None
    return text[: match.start()].rstrip(), match.group(1)


def _effective_length(body: str, url: str | None) -> int:
    length = len(body)
    if url:
        length += 1 + TWITTER_URL_LENGTH  # newline + X's fixed link length
    return length


def ensure_under_limit(client: Anthropic | None, model: str | None, text: str, voice_note: str) -> str:
    """Shrink `text` under MAX_CAPTION_CHARS while keeping its voice.

    A trailing URL (if any) is split off first and never sent to the shortening
    model or the hard-truncate fallback — only the surrounding text is touched.
    With client=None the local writer model does the shortening.
    """
    body, url = _split_trailing_url(text)

    for _ in range(SHORTEN_ATTEMPTS):
        if _effective_length(body, url) <= MAX_CAPTION_CHARS:
            break
        body = _shorten(client, model, body, voice_note)

    if _effective_length(body, url) > MAX_CAPTION_CHARS:
        budget = MAX_CAPTION_CHARS - (1 + TWITTER_URL_LENGTH if url else 0) - 1
        body = _truncate_preserving_mentions(body, max(budget, 0))

    return f"{body}\n{url}" if url else body


def _truncate_preserving_mentions(body: str, budget: int) -> str:
    """Hard-truncate as a last resort, but never cut through an @mention —
    a chopped mention breaks X's reply-permission rule for whoever it named."""
    mentions = _MENTION_RE.findall(body)
    if not mentions:
        return body[:budget].rstrip() + "…"

    mentions_str = " ".join(mentions)
    reserved = len(mentions_str) + 2  # +2 for the "… " joining the truncated part
    remaining = max(budget - reserved, 0)

    rest = _MENTION_RE.sub("", body)
    rest = re.sub(r"\s{2,}", " ", rest).strip()
    truncated_rest = rest[:remaining].rstrip()

    if truncated_rest:
        return f"{truncated_rest}… {mentions_str}"
    return mentions_str


def _shorten(client: Anthropic | None, model: str | None, body: str, voice_note: str) -> str:
    system = _shorten_system(voice_note)
    user = (f"Ce texte fait {len(body)} caractères, il en faut moins de {MAX_CAPTION_CHARS}. "
            f"Raccourcis-le sans perdre le ton ni les hashtags :\n\n{body}")
    if client is None:
        import local_llm

        try:
            return local_llm.chat(model or local_llm.writer_model(), [
                {"role": "system", "content": system}, {"role": "user", "content": user},
            ], max_tokens=150, temperature=0.3)
        except local_llm.LocalLLMError:
            return body  # the hard-truncate fallback in ensure_under_limit takes over
    response = client.messages.create(
        model=model,
        max_tokens=150,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def enforce_tags(text: str, required_mentions: list[str], hashtag_pool: list[str],
                 want_hashtags: int = 0) -> str:
    """Make mentions/hashtags exact in code: drop any @handle or #tag that isn't allowed (local
    models mangle handles), append a missing required mention, and top up hashtags from the pool."""
    allowed = {m.lower(): m for m in required_mentions}
    pool = {h.lower(): h for h in hashtag_pool}
    text = _MENTION_RE.sub(lambda m: allowed.get(m.group().lower(), ""), text)
    text = re.sub(r"#\w+", lambda m: pool.get(m.group().lower(), ""), text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    missing = [m for m in required_mentions if m not in text]
    have = [h for h in hashtag_pool if h in text]
    extra = random.sample([h for h in hashtag_pool if h not in have],
                          min(max(want_hashtags - len(have), 0), len(hashtag_pool) - len(have)))
    if missing or extra:
        text = f"{text} {' '.join(missing + extra)}"
    return text


def finish_local(text: str, voice_note: str, mentions: list[str], hashtag_pool: list[str],
                 want_hashtags: int = 0, url: str | None = None) -> str:
    """Final text for a local-model post: exact tags, under the limit, mentions guaranteed,
    and the (code-chosen) URL alone on the last line."""
    text = re.sub(r"https?://\S+", "", text).strip()  # only a code-chosen URL may appear
    body = enforce_tags(text, mentions, hashtag_pool, want_hashtags)
    full = f"{body}\n{url}" if url else body
    short_body, _ = _split_trailing_url(ensure_under_limit(None, None, full, voice_note))
    short_body = re.sub(r"https?://\S+", "", short_body).strip()
    if any(m not in short_body for m in mentions) or _effective_length(short_body, url) > MAX_CAPTION_CHARS:
        budget = MAX_CAPTION_CHARS - (1 + TWITTER_URL_LENGTH if url else 0) - 1
        short_body = _truncate_preserving_mentions(body, budget)
    return f"{short_body}\n{url}" if url else short_body


def _shorten_system(voice_note: str) -> str:
    return (
        f"Tu raccourcis des posts X qui dépassent la limite de caractères, en gardant "
        f"EXACTEMENT le même ton ({voice_note}) et tous les hashtags. Garde CHAQUE "
        f"mention @handle EXACTEMENT telle quelle, caractère pour caractère (une "
        f"mention tronquée casse la permission de répondre de la personne visée) — "
        f"tu peux couper ailleurs dans le texte mais jamais dans une mention. Ne "
        f"corrige AUCUNE faute de grammaire ou d'orthographe présente dans le texte "
        f"d'origine — si tu dois reformuler un passage, garde le même niveau de "
        f"fautes. Réponds UNIQUEMENT avec le texte raccourci, sans explication. Il "
        f"n'y a pas de lien dans ce texte — n'en ajoute pas."
    )
