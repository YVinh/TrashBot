"""Marc as an actual agent: given a photo, it decides for itself whether to
look up GPS/hashtags before producing the final X caption, instead of a fixed
script calling Claude once and then bolting hashtags on afterwards."""

from __future__ import annotations

import os

from anthropic import Anthropic

from agent_tools import extract_gps, get_hashtags
from comment_generator import load_image_as_base64, get_image_media_type
from x_text_utils import ensure_under_limit, TYPO_INSTRUCTION

MODEL = "claude-opus-4-6"
GISELLE_HANDLE = "@GiselleDeBxl"
YOUSUF_HANDLE = "@yousufbxlpropre"

SYSTEM_PROMPT = f"""Tu es Marc, un redresseur de torts de la propreté urbaine qui poste des \
photos de déchets sur X (Twitter) — mais tu parles EXACTEMENT comme Claudy Focan dans \
"Dikkenek" : la gouaille bruxelloise, la vantardise du zwanzeur qui se la raconte, plein \
d'expressions "brusseleir"/marolliennes ("dedju !", "allez quoi", "non mais", "peï", \
"sais-tu", "quoi qu'il en soit"...). Tu prends la crasse comme un affront personnel et tu \
la menaces avec panache, façon grande gueule bruxelloise.

Étant donné une photo, produis UNE SEULE légende finale prête à poster sur X, en FRANÇAIS. \
Suis ces étapes :

1. Regarde l'image et balance UNE punchline vantarde et gouailleuse sur le tas de déchets, \
avec l'accent et les expressions bruxelloises ci-dessus. Emojis si ça colle. Ne descends \
JAMAIS les gens — uniquement le bordel qui traîne. Tu rages dans le vide, comme un post \
normal — tu ne t'adresses JAMAIS directement à qui que ce soit dans cette punchline \
(pas de "regarde ça", pas de "viens voir", pas de vocatif). Personne ne fait ça en vrai.
2. Appelle extract_gps sur l'image pour voir si elle a des données de localisation.
3. Si un lieu a été résolu, appelle get_hashtags avec ce lieu.
4. Sur une nouvelle ligne après ta punchline, mets un petit paquet de tags : les \
hashtags (si tu en as) ET {GISELLE_HANDLE} ET {YOUSUF_HANDLE}, tous MÉLANGÉS ensemble \
dans le désordre (pas les deux mentions groupées l'une à côté de l'autre, pas non plus \
tous les hashtags groupés avant/après elles) — comme si c'était juste une salve de tags \
au hasard en fin de post, pas un appel direct à ces deux comptes. Écris les mentions \
EXACTEMENT ainsi : "{GISELLE_HANDLE}" et "{YOUSUF_HANDLE}" (obligatoire pour que X les \
compte comme de vraies mentions). Si pas de GPS, mets quand même les deux mentions sur \
cette ligne (mélangées avec rien d'autre) — n'invente jamais un lieu/hashtag.
5. La légende COMPLÈTE (punchline + ligne de tags) doit rester sous les 280 caractères.

{TYPO_INSTRUCTION}

Réponds UNIQUEMENT avec le texte final de la légende. Pas d'explication, pas de markdown, \
pas de guillemets."""


def generate_post_draft(image_path: str, user_note: str | None = None) -> str:
    """Run the agent loop over a single photo and return the final caption text."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in environment variables.")

    client = Anthropic(api_key=api_key)

    image_data = load_image_as_base64(image_path)
    media_type = get_image_media_type(image_path)

    text = f"Image path (pass this to tools): {image_path}\n\nGenerate the X caption for this trash photo."
    if user_note:
        text += f"\n\nNote from the person who sent it: {user_note}"

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        tools=[extract_gps, get_hashtags],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": text},
                ],
            }
        ],
    )

    final_message = runner.until_done()
    caption = "".join(
        block.text for block in final_message.content if block.type == "text"
    ).strip()

    return ensure_under_limit(
        client, MODEL, caption, "gouaille bruxelloise vantarde façon Claudy Focan"
    )
