"""Files a real report with FixMyStreet Brussels (fixmystreet.brussels), the
Region's incident platform, for a photo the owner approved.

The site has no public write API; this speaks to the same backend its own web
app uses, in the same order the "Send" button does:

    GET  /gis/localize/from-xy          photo GPS -> nearest address (UrbIS)
    GET  /gis/localize/?address=        address   -> Lambert-72 point the report needs
    POST /api/incidents                 create (category, point, reporter)
    POST /api/incidents/{id}/attachments?type=COMMENT
    POST /api/incidents/{id}/attachments?type=FILE
    PUT  /api/incidents/{id}/ack        finalise ("Send")

What gets reported is decided by a separate, sober look at the photo: Claude
picks the best-fitting leaf of the site's own "Propreté publique" category
tree, writes a short polite French description, and may decline (a lone
wrapper next to a bin is not an illegal dump). The report is filed under the
owner's real name and email (FMS_REPORTER_*): a report to a public
administration is not the place for a persona.

Fail-soft: every failure raises FixMyStreetError with a readable message; the
caller decides what to tell the owner. Nothing here ever blocks the X post."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time

import requests
from anthropic import Anthropic
from PIL import Image

from heic_utils import is_heic, open_heic

logger = logging.getLogger(__name__)

BASE = "https://fixmystreet.brussels"
USER_AGENT = "TrashBot/1.0 (+https://trashbotvillage.com; citizen reports approved one by one)"
TIMEOUT = 30
MODEL = "claude-opus-5"
ROOT_CATEGORY_FR = "Propreté publique"
MAX_UPLOAD_EDGE = 1600
_CATEGORY_CACHE: dict = {"at": 0.0, "leaves": []}
CATEGORY_TTL = 24 * 3600


class FixMyStreetError(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


# ---------------------------------------------------------------- location

def reverse_geocode(lat: float, lon: float) -> dict:
    """Nearest house address for a WGS-84 point. The UrbIS proxy takes
    x=latitude, y=longitude when SRS_In is 4326 (EPSG axis order)."""
    params = {"json": json.dumps({"language": "fr", "point": {"x": lat, "y": lon}, "SRS_In": 4326})}
    r = _session().get(f"{BASE}/gis/localize/from-xy", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("error") or not data.get("result"):
        raise FixMyStreetError(f"Pas d'adresse trouvée pour {lat:.5f},{lon:.5f}")
    a = data["result"]["address"]
    return {
        "street": a["street"]["name"],
        "number": a.get("number") or "",
        "postCode": a["street"]["postCode"],
        "municipality": a["street"]["municipality"],
    }


def geocode(address: dict) -> dict:
    """The site's own forward geocode (what the address dropdown does): gives
    the Lambert-72 point the incident must be created with."""
    text = f"{address['street']} {address['number']}, {address['postCode']} {address['municipality']}".strip()
    params = {"language": "fr", "address": text, "spatialReference": 31370}
    r = _session().get(f"{BASE}/gis/localize/", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    results = r.json().get("result") or []
    if not results:
        raise FixMyStreetError(f"Adresse non reconnue par FixMyStreet : {text}")
    best = results[0]
    return {"x": best["point"]["x"], "y": best["point"]["y"], "label": text}


def locate(lat: float, lon: float) -> dict:
    address = reverse_geocode(lat, lon)
    point = geocode(address)
    return {**address, **point}


# -------------------------------------------------------------- categories

def cleanliness_categories() -> list[dict]:
    """Assignable leaves under 'Propreté publique', from the live category
    tree (cached a day). Each: {id, path, mandatoryComment}."""
    if _CATEGORY_CACHE["leaves"] and time.time() - _CATEGORY_CACHE["at"] < CATEGORY_TTL:
        return _CATEGORY_CACHE["leaves"]
    r = _session().get(f"{BASE}/api/categories", timeout=TIMEOUT)
    r.raise_for_status()
    leaves: list[dict] = []

    def walk(node, path):
        path = path + [node["nameFr"]]
        kids = node.get("subCategories") or []
        if not kids and node.get("assignable") and node.get("active") and node.get("public"):
            leaves.append({"id": node["id"], "path": " > ".join(path[1:]), "mandatoryComment": bool(node.get("mandatoryComment"))})
        for k in kids:
            walk(k, path)

    for root in r.json()["response"]["categories"]:
        if root["nameFr"] == ROOT_CATEGORY_FR:
            walk(root, [])
    if not leaves:
        raise FixMyStreetError("Catégories FixMyStreet introuvables")
    _CATEGORY_CACHE.update(at=time.time(), leaves=leaves)
    return leaves


# -------------------------------------------------------------- assessment

ASSESS_SYSTEM = """Tu aides un habitant de Bruxelles à signaler un problème de propreté à la Région \
via FixMyStreet. Tu regardes la photo avec le sérieux d'un agent communal : factuel, sans humour, \
sans exagération.

Décide d'abord si la photo montre un problème de propreté RÉEL sur l'espace public, qui justifie \
un signalement : dépôt clandestin, sacs éventrés ou non collectés, corbeille ou bulle débordante, \
matériaux abandonnés, tags, voirie non balayée, etc. Un détail insignifiant (un papier isolé, une \
poubelle normale) ne justifie PAS de signalement : dans ce cas reportable = false.

Si c'est justifié, choisis la catégorie la plus précise dans la liste fournie (uniquement un id de \
cette liste) et rédige une description en français : 1 à 2 phrases, polie, professionnelle, brève, \
qui nomme concrètement les objets abandonnés. Minimum 15 caractères, pas de formule de politesse \
finale, pas de majuscules d'insistance.

Réponds UNIQUEMENT avec un objet JSON :
{"reportable": true|false, "category_id": <int ou null>, "description": "<texte ou vide>", "reason": "<courte justification>"}"""


def _image_block(image_path: str) -> dict:
    from comment_generator import load_image_as_base64, get_image_media_type

    return {
        "type": "image",
        "source": {"type": "base64", "media_type": get_image_media_type(image_path), "data": load_image_as_base64(image_path)},
    }


def assess(image_path: str) -> dict:
    """Sober look at the photo: reportable?, which category, what to write."""
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise FixMyStreetError("CLAUDE_API_KEY manquante")
    leaves = cleanliness_categories()
    menu = "\n".join(f"{c['id']}: {c['path']}" for c in leaves)
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=ASSESS_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                _image_block(image_path),
                {"type": "text", "text": f"Catégories disponibles (id: chemin) :\n{menu}\n\nAnalyse la photo et réponds en JSON."},
            ],
        }],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError as e:
        raise FixMyStreetError(f"Réponse d'analyse illisible : {text[:120]}") from e
    if verdict.get("reportable"):
        ids = {c["id"] for c in leaves}
        if verdict.get("category_id") not in ids:
            raise FixMyStreetError(f"Catégorie hors liste : {verdict.get('category_id')}")
        if len((verdict.get("description") or "").strip()) < 15:
            raise FixMyStreetError("Description trop courte")
        verdict["category_path"] = next(c["path"] for c in leaves if c["id"] == verdict["category_id"])
    return verdict


# -------------------------------------------------------------- submission

def _reporter() -> dict:
    name = os.getenv("FMS_REPORTER_NAME", "").strip()
    email = os.getenv("FMS_REPORTER_EMAIL", "").strip()
    if not name or not email:
        raise FixMyStreetError("FMS_REPORTER_NAME / FMS_REPORTER_EMAIL manquants dans .env")
    return {
        "name": name,
        "actingAs": "RESIDENT",
        "contact": {
            "emailAddress": email,
            "phoneNumber": os.getenv("FMS_REPORTER_PHONE") or None,
            "language": {"user": "fr", "address": "fr"},
        },
    }


def _upload_jpeg(image_path: str) -> bytes:
    """JPEG copy without metadata (the GPS is already the report's location)."""
    img = open_heic(image_path) if is_heic(image_path) else Image.open(image_path)
    img = img.convert("RGB")
    img.thumbnail((MAX_UPLOAD_EDGE, MAX_UPLOAD_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


def submit(location: dict, category_id: int, description: str, image_path: str) -> dict:
    """Create the incident with comment and photo, then ack it ("Send")."""
    s = _session()
    reporter = _reporter()
    notify = os.getenv("FMS_NOTIFY", "1") != "0"

    payload = {
        "coordinates": {"x": location["x"], "y": location["y"]},
        "category": category_id,
        "source": "WEB",
        "notificationSubscription": notify,
        "severalOccurrence": False,
        "reporter": reporter,
    }
    r = s.post(f"{BASE}/api/incidents", json=payload, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise FixMyStreetError(f"Création refusée ({r.status_code}) : {r.text[:200]}")
    incident_id = r.json()["response"]["id"]

    r = s.post(
        f"{BASE}/api/incidents/{incident_id}/attachments",
        params={"type": "COMMENT"},
        json={"content": description, "incidentCreation": True, "reporter": reporter},
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise FixMyStreetError(f"Commentaire refusé ({r.status_code}) : {r.text[:200]}")

    files = {
        "file": ("photo.jpg", _upload_jpeg(image_path), "image/jpeg"),
        "reporter": (None, json.dumps(reporter), "application/json"),
        "caption": (None, "", "text/plain"),
        "incidentCreation": (None, "true", "text/plain"),
    }
    r = s.post(
        f"{BASE}/api/incidents/{incident_id}/attachments",
        params={"type": "FILE"},
        files=files,
        headers={"Content-type-auto": "true"},
        timeout=TIMEOUT * 2,
    )
    if r.status_code >= 400:
        raise FixMyStreetError(f"Photo refusée ({r.status_code}) : {r.text[:200]}")

    r = s.put(f"{BASE}/api/incidents/{incident_id}/ack", timeout=TIMEOUT)
    if r.status_code >= 400:
        raise FixMyStreetError(f"Envoi final refusé ({r.status_code}) : {r.text[:200]}")

    return {"id": incident_id, "url": f"{BASE}/incidents/{incident_id}"}


def report_trash(image_path: str, lat: float, lon: float, *, dry_run: bool = False) -> dict:
    """Whole flow. Returns {"filed": False, "reason": ...} when the photo
    doesn't warrant a report; with dry_run, {"filed": False, "dry_run": True,
    plus what would have been sent} without writing anything to the Region's
    system; else {"filed": True, "id", "url", "category", "description", "address"}."""
    verdict = assess(image_path)
    if not verdict.get("reportable"):
        return {"filed": False, "reason": verdict.get("reason", "")}
    location = locate(lat, lon)
    details = {
        "category_id": verdict["category_id"],
        "category": verdict["category_path"],
        "description": verdict["description"].strip(),
        "address": location["label"],
    }
    if dry_run:
        return {"filed": False, "dry_run": True, **details}
    result = submit(location, verdict["category_id"], details["description"], image_path)
    return {"filed": True, **result, **details}


def status(incident_id: int | str) -> dict | None:
    """Public incident detail — free, no auth. None if it can't be read."""
    try:
        r = _session().get(f"{BASE}/api/incidents/{incident_id}", timeout=TIMEOUT)
        if r.status_code >= 400:
            return None
        d = r.json()["response"]
        org = d.get("responsibleOrganisation") or {}
        return {"status": d.get("status"), "organisation": org.get("nameFr"), "updated": d.get("updateDate")}
    except (requests.RequestException, ValueError, KeyError):
        return None
