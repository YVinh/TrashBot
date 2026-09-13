"""Shared helper for keeping generated X captions under the character limit.

X counts any http(s) URL as a fixed 23 characters toward the 280-char limit,
regardless of its real length (t.co auto-shortening). This must never truncate
or otherwise mutate a trailing URL — a chopped link is a dead link.
"""

from __future__ import annotations

import re

from anthropic import Anthropic

MAX_CAPTION_CHARS = 280
TWITTER_URL_LENGTH = 23
SHORTEN_ATTEMPTS = 2

TYPO_INSTRUCTION = (
    'De temps en temps (pas à chaque fois), glisse une faute de grammaire courante '
    "du français écrit vite, notamment confondre un participe passé en \"-é\" avec "
    'un infinitif en "-er" (ex : "j\'ai oublier" au lieu de "j\'ai oublié", "il a '
    'manger" au lieu de "il a mangé"). Reste crédible — une personne qui tape vite '
    "sur X, pas quelqu'un qui ne maîtrise pas le français."
)

_URL_RE = re.compile(r"(https?://\S+)\s*$")


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


def ensure_under_limit(client: Anthropic, model: str, text: str, voice_note: str) -> str:
    """Shrink `text` under MAX_CAPTION_CHARS while keeping its voice.

    A trailing URL (if any) is split off first and never sent to the shortening
    model or the hard-truncate fallback — only the surrounding text is touched.
    """
    body, url = _split_trailing_url(text)

    for _ in range(SHORTEN_ATTEMPTS):
        if _effective_length(body, url) <= MAX_CAPTION_CHARS:
            break
        body = _shorten(client, model, body, voice_note)

    if _effective_length(body, url) > MAX_CAPTION_CHARS:
        budget = MAX_CAPTION_CHARS - (1 + TWITTER_URL_LENGTH if url else 0) - 1
        body = body[: max(budget, 0)].rstrip() + "…"

    return f"{body}\n{url}" if url else body


def _shorten(client: Anthropic, model: str, body: str, voice_note: str) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=150,
        system=(
            f"Tu raccourcis des posts X qui dépassent la limite de caractères, en gardant "
            f"EXACTEMENT le même ton ({voice_note}) et tous les hashtags. Ne corrige "
            f"AUCUNE faute de grammaire ou d'orthographe présente dans le texte d'origine "
            f"— si tu dois reformuler un passage, garde le même niveau de fautes. Réponds "
            f"UNIQUEMENT avec le texte raccourci, sans explication. Il n'y a pas de lien "
            f"dans ce texte — n'en ajoute pas."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Ce texte fait {len(body)} caractères, il en faut moins de "
                    f"{MAX_CAPTION_CHARS}. Raccourcis-le sans perdre le ton ni les "
                    f"hashtags :\n\n{body}"
                ),
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()
