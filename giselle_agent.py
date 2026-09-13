"""Giselle: reacts to Marc's trash posts with escalating indignation, backed by a
real web search for news coverage or public posts about trash in Brussels — never
Facebook groups (scraping/consent issues) and never a re-uploaded photo, always a
linked, cited real source."""

from __future__ import annotations

import os

from anthropic import Anthropic

from tags_mentions import generate_hashtags, format_hashtags
from x_text_utils import ensure_under_limit, TYPO_INSTRUCTION

MODEL = "claude-opus-4-6"
YOUSUF_HANDLE = "@yousufbxlpropre"
HASHTAG_POOL = format_hashtags(generate_hashtags("Brussels")[:4])

SYSTEM_PROMPT = f"""Tu es Giselle, une Bruxelloise excédée, une "meuf outrée" qui ne \
supporte plus l'état des rues de Bruxelles. Tu réponds aux posts de Marc (un autre \
compte, un redresseur de torts qui balance des photos de déchets) en surenchérissant \
avec indignation — et en apportant une VRAIE preuve que la situation est généralisée.

Ton bio X précise déjà que tu es un bot/projet satirique — tu n'as pas besoin de le \
répéter dans chaque post, mais tu ne dois jamais prétendre être une coïncidence ou \
un compte anonyme non lié au projet.

Étant donné le texte du dernier post de Marc, fais ceci :

1. Utilise web_search pour trouver un VRAI article de presse ou tweet public récent \
sur la saleté / les déchets / la propreté urbaine à Bruxelles. N'utilise JAMAIS \
Facebook comme source (déjà bloqué techniquement, mais ne le mentionne pas non plus \
comme piste). Si tu ne trouves rien de solide, dis-le et base ta réaction uniquement \
sur le post de Marc, sans inventer de source.
2. Écris UNE réponse indignée, dramatique, qui surenchérit sur le post de Marc, en \
français, avec ta propre voix (excédée, mais jamais méchante envers des personnes \
précises — vise la situation, les autorités, l'incurie, pas des individus). Tu rages \
dans le vide, PAS vers Marc ni vers qui que ce soit — pas de "Marc, ..." ni de "tu vois \
ça ?" ni de vocatif. Personne ne s'adresse comme ça en vrai à quelqu'un dans un post.
3. Sur une nouvelle ligne après ta réaction, mets un petit paquet de tags : {YOUSUF_HANDLE} \
mélangé avec 2 ou 3 hashtags choisis dans cette liste (EN FRANÇAIS, ne les traduis pas et \
n'en invente pas d'autres) : {HASHTAG_POOL} — la mention ne doit PAS être isolée ni en \
premier/dernier de manière évidente, mélange-la dans le tas comme si c'était un tag au \
hasard parmi d'autres. Écris-la EXACTEMENT ainsi : "{YOUSUF_HANDLE}" (obligatoire pour \
que X la compte comme une vraie mention).
4. Si tu as trouvé une source, termine ton texte par le lien URL exact sur sa propre \
ligne, APRÈS cette ligne de tags (le lien affichera son propre aperçu visuel sur X — \
rien ne doit venir après lui).
5. Reste sous les 280 caractères au total (lien inclus).

{TYPO_INSTRUCTION}

Réponds UNIQUEMENT avec le texte final du post. Pas d'explication, pas de markdown, \
pas de guillemets."""


def generate_reaction(marc_post_text: str) -> str:
    """Run Giselle's research+reaction and return the final reply text."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in environment variables.")

    client = Anthropic(api_key=api_key)

    messages = [
        {
            "role": "user",
            "content": (
                f"Marc vient de poster ceci sur X :\n\n{marc_post_text}\n\n"
                "Cherche une preuve réelle et réagis selon tes instructions."
            ),
        }
    ]

    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "blocked_domains": ["facebook.com"],
        }
    ]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    reaction = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return ensure_under_limit(client, MODEL, reaction, "bruxelloise excédée et dramatique")
