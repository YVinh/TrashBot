"""Marc on the owner's iPhone (House Node app): photo -> vision description -> Marc punchline.

Talks to the phone directly (OpenAI-compatible), not through the gateway. Fail fast: any problem
raises PhoneError with a message fit for Telegram. Nothing here ever posts or falls back to another model.
The phone holds ONE model at a time (a photo costs two swaps), so calls are serialised by a lock."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import threading
import urllib.error
import urllib.request

from PIL import Image, ImageOps

from heic_utils import is_heic, open_heic

DEFAULT_URL = "http://192.168.178.183:8080"
VISION_MODEL = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
MARC_MODEL = "local/marc-v4-step200"
VISION_EDGE = 640  # the app caps images at ~0.5 MP

# Swappable: set PHONE_VISION_PROMPT in .env (use \n for newlines) to drop in a better prompt.
DEFAULT_VISION_PROMPT = (
    "Look at this photo of litter on a street. Answer in exactly 4 lines, nothing else:\n"
    "ITEMS: ...\n"
    "AMOUNT: one of: single item / a few items / a pile\n"
    "PLACE: ...\n"
    "SUMMARY_FR: one French sentence"
)

MARC_SYSTEM = ("Tu es Marc, retraité désabusé qui rage contre la saleté à Bruxelles. On te donne la description "
               "d'une photo. Écris UNE punchline en français, 200 caractères maximum, sans hashtag, sans @, sans lien.")
MARC_TRIES = 3
MARC_MAX_CHARS = 200

_phone_lock = threading.Lock()  # one photo at a time


class PhoneError(Exception):
    pass


def _url() -> str:
    return os.getenv("PHONE_URL", DEFAULT_URL).rstrip("/")


def vision_prompt() -> str:
    return os.getenv("PHONE_VISION_PROMPT", "").replace("\\n", "\n").strip() or DEFAULT_VISION_PROMPT


def _token() -> str:
    tok = os.getenv("HOUSENODE_TOKEN", "").strip()
    if not tok:
        raise PhoneError("the House Node token (HOUSENODE_TOKEN) is not set in the bot's .env")
    return tok


def _request(path: str, payload: dict | None, timeout: float) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(_url() + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise PhoneError(f"the phone answered HTTP {e.code} ({e.read().decode(errors='replace')[:120]})") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PhoneError(f"the phone did not answer ({type(e).__name__}) — is the House Node app open, "
                         f"the phone awake and the address {_url()} still right?") from e


def check_health() -> dict:
    h = _request("/health", None, timeout=float(os.getenv("PHONE_HEALTH_TIMEOUT", "6")))
    if h.get("status") != "ok":
        raise PhoneError(f"the phone is not ready (status {h.get('status')!r})")
    return h


def _chat(model: str, messages: list[dict], *, max_tokens: int, temperature: float, timeout: float) -> str:
    data = _request("/v1/chat/completions", {"model": model, "messages": messages, "max_tokens": max_tokens,
                                              "temperature": temperature}, timeout)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise PhoneError(f"unexpected answer from the phone: {str(data)[:150]}") from e


def image_data_url(image_path: str) -> str:
    img = open_heic(image_path) if is_heic(image_path) else Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((VISION_EDGE, VISION_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


_AMOUNTS = ("single item", "a few items", "a pile")


def parse_description(text: str) -> dict:
    """KEY: value lines -> the facts JSON Marc was trained on. Raises PhoneError if unusable."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*[-*]?\s*\**(ITEMS|AMOUNT|PLACE|SUMMARY_FR|IRONIC(?:_DETAILS)?)\**\s*:\s*(.+)", line, re.I)
        if m:
            fields.setdefault(m.group(1).upper().replace("_DETAILS", ""), m.group(2).strip())
    items = [i.strip(" .") for i in re.split(r"[,;]", fields.get("ITEMS", "")) if i.strip(" .")]
    summary = fields.get("SUMMARY_FR", "")
    if not items or not summary:
        raise PhoneError(f"the phone's photo description was unusable: {text[:150]!r}")
    amount = next((a for a in _AMOUNTS if a in fields.get("AMOUNT", "").lower()), "a few items")
    ironic = [i.strip() for i in re.split(r"[;|]", fields.get("IRONIC", "")) if i.strip() and i.strip().lower() != "none"]
    return {"items": items, "amount": amount, "place": fields.get("PLACE", "").strip(" ."),
            "ironic_details": ironic, "summary_fr": summary}


VISION_TRIES = 2


def describe_photo(image_path: str) -> dict:
    """Vision step (swappable): photo in, facts out. Caller holds the phone lock."""
    content = [{"type": "text", "text": vision_prompt()},
               {"type": "image_url", "image_url": {"url": image_data_url(image_path)}}]
    last = None
    for _ in range(VISION_TRIES):
        text = _chat(VISION_MODEL, [{"role": "user", "content": content}], max_tokens=300, temperature=0.2,
                     timeout=float(os.getenv("PHONE_VISION_TIMEOUT", "240")))
        try:
            return parse_description(text)
        except PhoneError as e:
            last = e
    raise last


def bad_punchline(text: str) -> str | None:
    if not text:
        return "empty"
    if len(text) > MARC_MAX_CHARS:
        return f"too long ({len(text)})"
    if re.search(r"#|@|https?://|www\.", text):
        return "hashtag, @ or link"
    return None


def write_marc(facts: dict) -> str:
    """Marc step: up to MARC_TRIES tries, retrying on empty / >200 chars / hashtag, @, link."""
    user = "Description de la photo :\n" + json.dumps(
        {k: facts.get(k) for k in ("items", "amount", "place", "ironic_details", "summary_fr")}, ensure_ascii=False)
    problems = []
    for _ in range(MARC_TRIES):
        text = _chat(MARC_MODEL, [{"role": "system", "content": MARC_SYSTEM}, {"role": "user", "content": user}],
                     max_tokens=80, temperature=0.7, timeout=float(os.getenv("PHONE_MARC_TIMEOUT", "180")))
        text = text.strip().strip('"').strip("«»").strip()
        why = bad_punchline(text)
        if not why:
            return text
        problems.append(why)
    raise PhoneError(f"Marc gave no usable line after {MARC_TRIES} tries ({', '.join(problems)})")


def marc_for_photo(image_path: str) -> tuple[str, dict]:
    """Photo -> (punchline, facts). One photo at a time; a waiting photo queues on the lock."""
    with _phone_lock:
        check_health()
        facts = describe_photo(image_path)
        return write_marc(facts), facts
