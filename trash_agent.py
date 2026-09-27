"""Marc as an actual agent: given a photo, it decides for itself whether to
look up GPS/hashtags before producing the final X caption, instead of a fixed
script calling Claude once and then bolting hashtags on afterwards."""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass

from anthropic import Anthropic

import local_llm
from agent_tools import extract_gps, get_hashtags
from comment_generator import load_image_as_base64, get_image_media_type
from exif_extractor import extract_gps_coordinates
from personas import GENRE_BASELINE, MARC_VOICE
from tags_mentions import format_hashtags, generate_hashtags, get_location_from_coords
from x_text_utils import MAX_CAPTION_CHARS, ensure_under_limit

MODEL = "claude-opus-4-6"
GISELLE_HANDLE = "@GiselleDeBxl"
YOUSUF_HANDLE = "@yousufbxlpropre"

SYSTEM_PROMPT = f"""Tu es Marc, un habitant excédé par la saleté qui poste des photos de \
déchets sur X (Twitter).

{GENRE_BASELINE}

{MARC_VOICE}

Étant donné une photo, produis UNE SEULE légende finale prête à poster sur X, en FRANÇAIS. \
Suis ces étapes :

1. Regarde l'image et balance UNE punchline dans ta voix sur le tas de déchets. Ne \
descends JAMAIS une personne en particulier — uniquement le bordel qui traîne et \
l'incivilité en général (à l'occasion seulement, "les politiques"/le système). Tu rages dans le vide, comme un post \
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

Réponds UNIQUEMENT avec le texte final de la légende. Pas d'explication, pas de markdown, \
pas de guillemets."""


@dataclass
class Draft:
    caption: str
    backend: str
    belongings_warning: str | None = None
    seen_by: str | None = None
    facts: dict | None = None


def generate_post_draft(image_path: str, user_note: str | None = None, backend: str | None = None) -> Draft:
    """Caption for one photo, from the backend in LLM_BACKEND unless `backend` overrides it."""
    backend = backend or local_llm.backend()
    if backend == "local":
        return _local_draft(image_path, user_note)
    return Draft(_anthropic_draft(image_path, user_note), "anthropic")


# ------------------------------------------------------------ local (gemma4 sees + writes)

VISION_PROMPT = """You describe street photos for a Brussels litter-awareness account.
Report ONLY what you can actually see in this photo. Never guess, never add objects that are not clearly
visible. If you cannot tell what a dumped object is, call it "unclear dumped item" instead of guessing.
Parked bicycles, cars and scooters are not litter: leave them out.
Never report house numbers, street names, addresses or anything that identifies a specific home.
Answer in JSON with these fields:
- "items": the discarded objects, as short English nouns with colour or material when visible.
- "amount": one of "single item", "a few items", "a pile".
- "place": where the objects lie, in a few words, based on what is around them.
- "ironic_details": visible things nearby that make the dumping absurd (for example signage, containers or bins).
  Transcribe sign text word for word, except house numbers and addresses. Empty list if there is nothing like that.
- "possibly_someones_belongings": true ONLY if there are clear signs that a person sleeps or lives here
  (bedding laid out flat like a bed, a sleeping bag, cardboard used as a mattress, personal items arranged
  around a sleeping spot). Bags of clothes left at a donation container, furniture, appliances or bin bags
  are dumping, not belongings: false.
- "belongings_reason": one short sentence explaining that judgement.
- "summary_fr": one factual sentence in French describing the scene."""

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": {"type": "string"}},
        "amount": {"type": "string", "enum": ["single item", "a few items", "a pile"]},
        "place": {"type": "string"},
        "ironic_details": {"type": "array", "items": {"type": "string"}},
        "possibly_someones_belongings": {"type": "boolean"},
        "belongings_reason": {"type": "string"},
        "summary_fr": {"type": "string"},
    },
    "required": ["items", "amount", "place", "ironic_details", "possibly_someones_belongings",
                 "belongings_reason", "summary_fr"],
}

PUNCHLINE_MAX = 170

WRITER_SYSTEM = f"""Tu es Marc, un habitant excédé par la saleté qui poste des photos de déchets sur X.

{GENRE_BASELINE}

{MARC_VOICE}

On te donne la description factuelle d'une photo (objets vus, quantité, lieu, détails ironiques). Écris UNE
SEULE punchline en français, dans ta voix, sur ce tas de déchets. Ne descends JAMAIS une personne en
particulier — uniquement le bordel qui traîne et l'incivilité en général. Tu rages dans le vide : jamais
d'adresse directe à qui que ce soit, pas de vocatif.
Nomme l'objet précis donné dans "items" (par exemple "cette chaise de bureau", "cette palette") : cette
description est déjà vérifiée, donc la règle "mot vague si pas sûr" de ton registre général ne s'applique
PAS aux objets listés ici. Seul un "unclear dumped item" devient un mot vague mais négatif ("des crasses",
"de la saleté", "des ordures").
S'il y a des "ironic_details" (panneau, interdiction, poubelle juste à côté...), sers-t'en quand ça sonne
naturel : reprendre le texte d'un panneau ou souligner l'ironie du lieu fait plus mouche qu'une plainte
générique.
Varie ton amorce d'une fois à l'autre : les amorces listées dans ta voix sont des exemples parmi d'autres,
pas des formules à répéter — évite de commencer par "Encore" ou "Pfff" à chaque fois.
N'invente rien qui ne soit pas dans la description. N'utilise que des mots français qui existent (les
fautes d'orthographe de ta voix, oui ; les mots inventés, non).
Pas de hashtag, pas de mention @, pas de lien : ils sont ajoutés automatiquement après.
Maximum {PUNCHLINE_MAX} caractères. Réponds UNIQUEMENT avec la punchline, sans guillemets ni explication."""

MENTIONS = [GISELLE_HANDLE, YOUSUF_HANDLE]


def see(image_path: str) -> dict:
    facts, model = local_llm.vision_json([{"role": "user", "content": [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": local_llm.image_data_url(image_path)}},
    ]}], VISION_SCHEMA, max_tokens=600)
    facts["seen_by"] = model
    return facts


def write_punchline(facts: dict, user_note: str | None = None) -> str:
    keep = {k: facts.get(k) for k in ("items", "amount", "place", "ironic_details", "summary_fr")}
    user = "Description de la photo :\n" + json.dumps(keep, ensure_ascii=False)
    if user_note:
        user += ("\n\nNote de la personne qui a envoyé la photo (contexte seulement, ne recopie jamais "
                 f"d'adresse ni de numéro) : {user_note}")
    text = local_llm.chat(local_llm.writer_model(), [
        {"role": "system", "content": WRITER_SYSTEM}, {"role": "user", "content": user},
    ], max_tokens=160, temperature=0.9)
    text = text.strip().strip('"').strip("«»").strip()
    text = re.sub(r"\s*(#\w+|@\w+|https?://\S+)", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def tag_line(image_path: str) -> str:
    tags: list[str] = []
    gps = extract_gps_coordinates(image_path)
    if gps:
        location = get_location_from_coords(*gps)
        pool = format_hashtags(generate_hashtags(location)[:4]).split()
        tags = random.sample(pool, min(2, len(pool)))
    line = tags + MENTIONS
    random.shuffle(line)
    return " ".join(line)


def assemble(punchline: str, tags: str) -> str:
    budget = MAX_CAPTION_CHARS - len(tags) - 1
    if len(punchline) > budget:
        punchline = punchline[: budget - 1].rsplit(" ", 1)[0] + "…"
    return f"{punchline}\n{tags}"


def _local_draft(image_path: str, user_note: str | None) -> Draft:
    facts = see(image_path)
    caption = assemble(write_punchline(facts, user_note), tag_line(image_path))
    warning = (facts.get("belongings_reason") or "flagged") if facts.get("possibly_someones_belongings") else None
    return Draft(caption, "local", warning, facts.get("seen_by"), facts)


# ------------------------------------------------------------ Anthropic (Opus agent)

def _anthropic_draft(image_path: str, user_note: str | None = None) -> str:
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
        client, MODEL, caption, "retraité désabusé, phrases-virgules qui s'enchaînent"
    )
