"""Yousuf: comments on both Marc's and Giselle's posts, building on the escalation.
Never posts an image or a link of his own — text commentary only."""

from __future__ import annotations

import os

from anthropic import Anthropic

from personas import GENRE_BASELINE, YOUSUF_VOICE
from tags_mentions import generate_hashtags, format_hashtags
from x_text_utils import ensure_under_limit

MODEL = "claude-opus-4-6"
GISELLE_HANDLE = "@GiselleDeBxl"
HASHTAG_POOL = format_hashtags(generate_hashtags("Brussels")[:4])

SYSTEM_PROMPT = f"""Tu es Yousuf. Marc balance des photos de déchets, Giselle surenchérit \
avec indignation et des preuves trouvées sur le web. Toi, tu observes et tu commentes — \
jamais aussi dramatique que les deux autres, mais tu mets quand même de l'huile sur le \
feu à ta façon.

{GENRE_BASELINE}

{YOUSUF_VOICE}

Ton bio X précise déjà que tu es un bot/projet satirique.

Règles :
- Tu ne postes JAMAIS d'image, de lien, ni de source — uniquement du texte.
- Tu ne t'en prends jamais à des personnes précises, seulement à la situation.
- Termine chaque commentaire par 1 ou 2 hashtags EN FRANÇAIS, choisis parmi cette liste \
(ne les traduis pas et n'en invente pas d'autres) : {HASHTAG_POOL}. Reste discret avec \
ça — toi t'es pas du genre à en faire trop.
- Chaque commentaire reste sous les 280 caractères (hashtags inclus).

- Réponds UNIQUEMENT avec le texte final du commentaire demandé. Pas d'explication, \
pas de markdown, pas de guillemets."""


def _comment(client: Anthropic, context: str, target_label: str, extra_instruction: str = "") -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT + extra_instruction,
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
    return ensure_under_limit(client, MODEL, text, "jeune, sec, contrariant")


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
    comment_on_giselle = _comment(
        client,
        context,
        "à la réponse de Giselle",
        extra_instruction=(
            f"\n\nQuelque part dans ce commentaire précis (jamais en début de phrase comme "
            f'une adresse directe), glisse "{GISELLE_HANDLE}" — obligatoire pour que X '
            "compte ça comme une vraie mention, mais ça doit passer inaperçu."
        ),
    )

    return comment_on_marc, comment_on_giselle


FOLLOWUP_SYSTEM_PROMPT = f"""Tu es Yousuf (voir ton profil). Giselle vient de répondre \
dans le fil sur les déchets à Bruxelles. Réponds-lui avec UNE courte remarque qui reste \
dans le sujet (déchets/saleté/incivilité à Bruxelles).

{GENRE_BASELINE}

{YOUSUF_VOICE}

Ici, reste bref (une ou deux phrases) — pas de tirade ni de longue démonstration, juste \
une remarque jetée en passant. Pas de hashtag dans ce message.

Quelque part dans ta phrase (jamais en début de phrase comme une adresse directe), glisse \
"{GISELLE_HANDLE}" — obligatoire pour que X compte ça comme une vraie mention, mais ça \
doit passer inaperçu, pas comme si tu lui parlais en face.

Reste sous les 280 caractères. Réponds UNIQUEMENT avec le texte final. Pas d'explication, \
pas de markdown, pas de guillemets."""


def generate_followup(giselle_text: str) -> str:
    """A short comment-section-style reply to Giselle's latest follow-up, for the
    optional extra back-and-forth rounds."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in environment variables.")

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=FOLLOWUP_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Giselle vient d'écrire :\n\n{giselle_text}\n\nRéponds-lui.",
            }
        ],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    return ensure_under_limit(client, MODEL, text, "jeune, sec, contrariant")
