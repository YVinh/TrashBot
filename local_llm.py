"""Client for the local models behind the homelab LiteLLM gateway (OpenAI-compatible).

Fail fast: any error raises LocalLLMError. Nothing here ever falls back to a paid
model — the caller (or the owner, via the Retry-with-Claude button) decides."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, time, timezone

from PIL import Image, ImageOps

from heic_utils import is_heic, open_heic

VISION_EDGE = 1024
# CPU inference on pve-mbp: a cold photo is ~1.5–2.5 min, and the model may first have to
# wait for another job on the same Ollama (one request at a time).
DEFAULT_TIMEOUT = 900


class LocalLLMError(Exception):
    pass


def backend() -> str:
    return os.getenv("LLM_BACKEND", "anthropic").strip().lower()


def use_local() -> bool:
    return backend() == "local"


def vision_model() -> str:
    return os.getenv("LOCAL_VISION_MODEL", "mbp-writer")


def m5_busy(now: datetime | None = None) -> bool:
    """True inside M5_BUSY_UTC (default 21:30-04:30): the M5 GPU belongs to the night lane then."""
    start_s, end_s = os.getenv("M5_BUSY_UTC", "21:30-04:30").split("-")
    start, end = time.fromisoformat(start_s.strip()), time.fromisoformat(end_s.strip())
    t = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).time()
    return start <= t < end if start <= end else (t >= start or t < end)


def vision_chain(now: datetime | None = None) -> list[str]:
    """Gateway aliases to try in order, from LOCAL_VISION_CHAIN (e.g. "mac-vision-3,phone-vision,mbp-writer").
    Aliases starting with "mac-" run on the M5 and are skipped inside M5_BUSY_UTC."""
    chain = [a.strip() for a in os.getenv("LOCAL_VISION_CHAIN", "").split(",") if a.strip()]
    if m5_busy(now):
        chain = [a for a in chain if not a.startswith("mac-")]
    return chain or [vision_model()]


# Per attempt before moving on; the last alias gets the caller's (long) timeout. A device that
# left the LAN fails in seconds; the phone's vision step takes ~1–2 min.
EARLY_TIMEOUT = 240


def vision_json(messages: list[dict], schema: dict, **kw) -> tuple[dict, str]:
    """chat_json over vision_chain(), first answer wins. Never a paid model.
    Returns (answer, alias that answered)."""
    errors = []
    chain = vision_chain()
    for i, model in enumerate(chain):
        timeout = EARLY_TIMEOUT if i < len(chain) - 1 else kw.get("timeout", DEFAULT_TIMEOUT)
        try:
            return chat_json(model, messages, schema, **{**kw, "timeout": timeout}), model
        except LocalLLMError as e:
            errors.append(str(e))
    raise LocalLLMError(" / ".join(errors))


def writer_model() -> str:
    return os.getenv("LOCAL_WRITER_MODEL", "mbp-writer")


def image_data_url(image_path: str) -> str:
    img = open_heic(image_path) if is_heic(image_path) else Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((VISION_EDGE, VISION_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def chat(model: str, messages: list[dict], *, max_tokens: int = 400, temperature: float = 0.7,
         schema: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """One chat completion; returns the message text (a JSON string when `schema` is set)."""
    url = os.getenv("LLM_GATEWAY_URL", "http://192.168.178.106:4000").rstrip("/")
    key = os.getenv("LLM_GATEWAY_KEY")
    if not key:
        raise LocalLLMError("LLM_GATEWAY_KEY missing in .env")
    payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if not model.startswith("free-"):  # Gemini's OpenAI endpoint rejects reasoning_effort "none" (400)
        payload["reasoning_effort"] = "none"
    if schema:
        payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise LocalLLMError(f"gateway {e.code} for {model}: {detail}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LocalLLMError(f"{model} unreachable: {e}") from e
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LocalLLMError(f"unexpected answer from {model}: {str(data)[:200]}") from e
    if not text:
        raise LocalLLMError(f"{model} returned an empty answer")
    return text


def chat_json(model: str, messages: list[dict], schema: dict, **kw) -> dict:
    text = chat(model, messages, schema=schema, temperature=kw.pop("temperature", 0.1), **kw)
    obj = _first_json_object(text)
    if obj is None:
        raise LocalLLMError(f"{model} returned invalid JSON: {text[:200]}")
    missing = [k for k in schema.get("required", []) if k not in obj]
    if missing:
        raise LocalLLMError(f"{model} answer lacks {', '.join(missing)}")
    return obj


def _first_json_object(text: str) -> dict | None:
    """Servers that ignore response_format (House Node) wrap the JSON in fences or chatter."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
