"""Yousuf: comments on both Marc's and Giselle's posts, building on the escalation.
Never posts an image or a link of his own — text commentary only."""

from __future__ import annotations

import os

from anthropic import Anthropic

from tags_mentions import generate_hashtags, format_hashtags
from x_text_utils import ensure_under_limit, TYPO_INSTRUCTION

MODEL = "claude-opus-4-6"
HASHTAG_POOL = format_hashtags(generate_hashtags("Brussels")[:4])

SYSTEM_PROMPT = f"""Tu es Yousuf, le commentateur pince-sans-rire du trio. Marc balance \
des photos de déchets avec la gouaille de Claudy Focan, Giselle surenchérit avec \
indignation et des preuves trouvées sur le web. Toi, tu observes et tu commentes, avec \
un humour sec, un peu détaché, jamais aussi dramatique que les deux autres — comme le \
pote qui reste calme pendant que tout le monde s'énerve, mais qui met quand même de \
l'huile sur le feu à sa façon.

Ton bio X précise déjà que tu es un bot/projet satirique.

Règles :
- Tu ne postes JAMAIS d'image, de lien, ni de source — uniquement du texte.
- Tu ne t'en prends jamais à des personnes précises, seulement à la situation.
- Termine chaque commentaire par 1 ou 2 hashtags EN FRANÇAIS, choisis parmi cette liste \
(ne les traduis pas et n'en invente pas d'autres) : {HASHTAG_POOL}. Reste discret avec \
ça — toi t'es pas du genre à en faire trop.
- Chaque commentaire reste sous les 280 caractères (hashtags inclus).

{TYPO_INSTRUCTION}

- Réponds UNIQUEMENT avec le texte final du commentaire demandé. Pas d'explication, \
pas de markdown, pas de guillemets."""


def _comment(client: Anthropic, context: str, target_label: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{context}\n\nÉcris ton commentaire en réponse {target_label}, "
                    "selon tes instructions."
                ),
            }
        ],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return ensure_under_limit(client, MODEL, text, "détaché, pince-sans-rire")


def generate_comments(marc_post_text: str, giselle_post_text: str) -> tuple[str, str]:
    """Return (comment_on_marc, comment_on_giselle) — two separate reply texts."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in environment variables.")

    client = Anthropic(api_key=api_key)

    context = (
        f"Post de Marc :\n{marc_post_text}\n\n"
        f"Réponse de Giselle à ce post :\n{giselle_post_text}"
    )

    comment_on_marc = _comment(client, context, "au post original de Marc")
    comment_on_giselle = _comment(client, context, "à la réponse de Giselle")

    return comment_on_marc, comment_on_giselle
