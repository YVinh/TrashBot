"""Yousuf: comments on both Marc's and Giselle's posts, building on the escalation.
Never posts an image or a link of his own — text commentary only."""

from __future__ import annotations

import os

from anthropic import Anthropic

from local_llm import use_local
from personas import GENRE_BASELINE, YOUSUF_VOICE
from tags_mentions import generate_hashtags, format_hashtags
from x_text_utils import ensure_under_limit, finish_local

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


# EXACT system prompt of the Yousuf LoRA training set (homelab#112, ~/trashbot-writer/yousuf_train/dataset).
# The adapter was trained only with this prompt and the two user shapes built in generate_comments; do not reword.
TRAINING_SYSTEM_PROMPT = (
    "Tu es Yousuf, jeune, sec et sarcastique, sur la saleté à Bruxelles. On te donne le post de Marc et parfois la "
    "réaction de Giselle. Écris UN commentaire en français, 180 caractères maximum, sans hashtag, sans @, sans lien.")


def _phone_text(adapter: str, user: str) -> str:
    """One comment from the phone adapter. LocalLLMError propagates: no gateway, no paid fallback."""
    import local_llm

    text = local_llm.housenode_chat(adapter, [
        {"role": "system", "content": TRAINING_SYSTEM_PROMPT}, {"role": "user", "content": user}])
    return text.strip().strip('"').strip("«»").strip()


def _local_text(system: str, user: str, max_tokens: int) -> str:
    import local_llm

    text = local_llm.chat(local_llm.writer_model(), [
        {"role": "system", "content": system}, {"role": "user", "content": user},
    ], max_tokens=max_tokens, temperature=0.9)
    return text.strip().strip('"').strip("«»").strip()


def _comment(client: Anthropic | None, context: str, target_label: str, extra_instruction: str = "",
             mentions: list[str] | None = None, phone_adapter: str = "") -> str:
    user = f"{context}\n\nÉcris ton commentaire en réponse {target_label}, selon tes instructions."
    if client is None and phone_adapter:
        text = _phone_text(phone_adapter, user)  # hashtag + @mention only from code, below
        return finish_local(text, "jeune, sec, contrariant", mentions or [], HASHTAG_POOL.split(),
                            want_hashtags=1)
    if client is None:
        text = _local_text(SYSTEM_PROMPT + extra_instruction, user, 220)
        return finish_local(text, "jeune, sec, contrariant", mentions or [], HASHTAG_POOL.split(),
                            want_hashtags=1)
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
    if use_local():
        client = None
    else:
        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            raise ValueError("CLAUDE_API_KEY not found in environment variables.")
        client = Anthropic(api_key=api_key)

    import local_llm

    # Phone adapter (LLM_BACKEND=local + HOUSENODE_TOKEN): the two training shapes. Marc's comment sees
    # Marc only; the comment on Giselle sees Marc + her reaction. Off => the old writer path, unchanged.
    adapter = local_llm.housenode_adapter("yousuf") if client is None else ""
    marc_only = f"Post de Marc :\n{marc_post_text}"
    context = (
        f"Post de Marc :\n{marc_post_text}\n\n"
        f"Réponse de Giselle à ce post :\n{giselle_post_text}"
    )

    comment_on_marc = _comment(client, marc_only if adapter else context, "au post original de Marc",
                               phone_adapter=adapter)
    comment_on_giselle = _comment(
        client,
        context,
        "à la réponse de Giselle",
        extra_instruction=(
            f"\n\nQuelque part dans ce commentaire précis (jamais en début de phrase comme "
            f'une adresse directe), glisse "{GISELLE_HANDLE}" — obligatoire pour que X '
            "compte ça comme une vraie mention, mais ça doit passer inaperçu."
        ),
        mentions=[GISELLE_HANDLE],
        phone_adapter=adapter,
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


def generate_followup(giselle_text: str, marc_text: str = "") -> str:
    """A short comment-section-style reply to Giselle's latest follow-up, for the
    optional extra back-and-forth rounds.

    Phone path (LLM_BACKEND=local + HOUSENODE_TOKEN, homelab#112): the trained shape "Post de Marc +
    Réponse de Giselle" with her latest text, so `marc_text` is required; errors raise LocalLLMError,
    no gateway or paid fallback. Off => the old writer path, unchanged."""
    if use_local():
        import local_llm

        adapter = local_llm.housenode_adapter("yousuf")
        if adapter:
            if not marc_text:
                raise local_llm.LocalLLMError("yousuf follow-up needs marc_text for the trained prompt")
            user = (f"Post de Marc :\n{marc_text}\n\nRéponse de Giselle à ce post :\n{giselle_text}\n\n"
                    "Écris ton commentaire en réponse à la réponse de Giselle, selon tes instructions.")
            text = _phone_text(adapter, user)  # the @mention only from code, below
            return finish_local(text, "jeune, sec, contrariant", [GISELLE_HANDLE], [])
        text = _local_text(FOLLOWUP_SYSTEM_PROMPT, f"Giselle vient d'écrire :\n\n{giselle_text}\n\nRéponds-lui.", 160)
        return finish_local(text, "jeune, sec, contrariant", [GISELLE_HANDLE], [])
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
