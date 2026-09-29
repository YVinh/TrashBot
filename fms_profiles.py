"""FixMyStreet reporter details for chat members other than the owner.

A report to the Region is filed in a real person's name, so a group member who
wants to report their own photo does it with their own name/email/phone, which
they give the bot once in a private chat (/fms_profile). Stored on disk next to
the code, mode 0600, keyed by Telegram user_id; /fms_forget deletes it.

Also keeps a per-user count of reports filed today, so one member can't turn
the bot into a report cannon (FMS_USER_DAILY_MAX, default 5)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

PROFILES_FILE = Path(__file__).parent / "fms_profiles.json"

_EMAIL = re.compile(r"^[^@\s;]+@[^@\s;]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[0-9][0-9 ./-]{5,19}$")

USAGE = (
    "Send your details in one line, separated by « ; » (phone optional):\n"
    "/fms_profile Firstname Lastname; you@example.com; +32 470 12 34 56"
)


class ProfileError(ValueError):
    pass


def daily_max() -> int:
    return int(os.getenv("FMS_USER_DAILY_MAX", "5") or 5)


def parse(args: str) -> dict:
    """'Name; email[; phone]' -> {"name", "email", "phone"}. Raises ProfileError."""
    parts = [p.strip() for p in (args or "").split(";")]
    if len(parts) < 2 or len(parts) > 3:
        raise ProfileError(USAGE)
    name, email = parts[0], parts[1]
    phone = parts[2] if len(parts) == 3 and parts[2] else None
    if not 2 <= len(name) <= 80 or any(c in name for c in "\n\r<>"):
        raise ProfileError("The name should be 2–80 characters.")
    if not _EMAIL.match(email) or len(email) > 120:
        raise ProfileError("That email address doesn't look right.")
    if phone and not _PHONE.match(phone):
        raise ProfileError("That phone number doesn't look right (digits, spaces, optional +).")
    return {"name": name, "email": email, "phone": phone}


def _load_all() -> dict:
    try:
        return json.loads(PROFILES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict):
    tmp = PROFILES_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PROFILES_FILE)


def get(user_id: int) -> dict | None:
    p = _load_all().get(str(user_id))
    return p if p and p.get("name") and p.get("email") else None


def save(user_id: int, profile: dict):
    data = _load_all()
    old = data.get(str(user_id)) or {}
    data[str(user_id)] = {**profile, "reports": old.get("reports", [])}
    _save_all(data)


def forget(user_id: int) -> bool:
    data = _load_all()
    existed = data.pop(str(user_id), None) is not None
    _save_all(data)
    return existed


def reports_today(user_id: int) -> int:
    since = time.time() - 24 * 3600
    return sum(1 for t in (_load_all().get(str(user_id)) or {}).get("reports", []) if t > since)


def record_report(user_id: int):
    data = _load_all()
    p = data.get(str(user_id))
    if not p:
        return
    since = time.time() - 24 * 3600
    p["reports"] = [t for t in p.get("reports", []) if t > since] + [time.time()]
    _save_all(data)


def masked(profile: dict) -> str:
    """'Jean D., j…@example.com' — enough to recognise, not enough to harvest."""
    first, *rest = profile["name"].split()
    name = f"{first} {rest[-1][0]}." if rest else first
    local, _, domain = profile["email"].partition("@")
    return f"{name}, {local[:1]}…@{domain}"
