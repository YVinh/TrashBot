import asyncio
import os
import stat
from types import SimpleNamespace

import pytest

import fixmystreet
import fms_profiles


@pytest.fixture(autouse=True)
def profiles_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fms_profiles, "PROFILES_FILE", tmp_path / "fms_profiles.json")
    return tmp_path / "fms_profiles.json"


def test_parse_valid_and_optional_phone():
    assert fms_profiles.parse("Jean Dupont; jean@example.be; +32 470 12 34 56") == {
        "name": "Jean Dupont", "email": "jean@example.be", "phone": "+32 470 12 34 56"}
    assert fms_profiles.parse("Jean Dupont;jean@example.be")["phone"] is None


@pytest.mark.parametrize("bad", ["", "Jean Dupont", "Jean; not-an-email", "J; j@example.be",
                                 "Jean Dupont; jean@example.be; call me", "a;b;c;d"])
def test_parse_rejects(bad):
    with pytest.raises(fms_profiles.ProfileError):
        fms_profiles.parse(bad)


def test_save_get_forget_and_file_is_private(profiles_file):
    fms_profiles.save(42, fms_profiles.parse("Jean Dupont; jean@example.be"))
    assert fms_profiles.get(42)["email"] == "jean@example.be"
    assert stat.S_IMODE(os.stat(profiles_file).st_mode) == 0o600
    assert fms_profiles.get(43) is None
    assert fms_profiles.forget(42) is True and fms_profiles.get(42) is None
    assert fms_profiles.forget(42) is False


def test_daily_count_survives_profile_update():
    fms_profiles.save(7, fms_profiles.parse("Ann Peeters; ann@example.be"))
    fms_profiles.record_report(7)
    fms_profiles.record_report(7)
    fms_profiles.save(7, fms_profiles.parse("Ann Peeters; ann.p@example.be"))
    assert fms_profiles.reports_today(7) == 2


def test_masked():
    assert fms_profiles.masked({"name": "Jean Van Dam", "email": "jean@example.be"}) == "Jean D., j…@example.be"
    assert fms_profiles.masked({"name": "Cher", "email": "c@x.org"}) == "Cher, c…@x.org"


def test_reporter_uses_member_profile_not_env(monkeypatch):
    monkeypatch.setenv("FMS_REPORTER_NAME", "Owner")
    monkeypatch.setenv("FMS_REPORTER_EMAIL", "owner@example.org")
    r = fixmystreet._reporter({"name": "Ann Peeters", "email": "ann@example.be", "phone": None})
    assert r["name"] == "Ann Peeters" and r["contact"]["emailAddress"] == "ann@example.be"
    assert r["contact"]["phoneNumber"] is None
    assert fixmystreet._reporter()["name"] == "Owner"


def test_prepare_returns_location_and_report_trash_still_works(monkeypatch):
    monkeypatch.setattr(fixmystreet, "assess", lambda p: {
        "reportable": True, "category_id": 3, "category_path": "Dépôts clandestins", "description": "Matelas abandonné sur le trottoir."})
    monkeypatch.setattr(fixmystreet, "locate", lambda lat, lon: {"x": 1, "y": 2, "label": "Rue X 1, 1000 Bruxelles"})
    d = fixmystreet.prepare("x.jpg", 50.8, 4.3)
    assert d["reportable"] and d["location"]["x"] == 1 and d["address"] == "Rue X 1, 1000 Bruxelles"
    seen = {}
    monkeypatch.setattr(fixmystreet, "submit", lambda loc, cat, desc, img, profile=None: seen.update(cat=cat) or {"id": 9, "url": "u"})
    r = fixmystreet.report_trash("x.jpg", 50.8, 4.3)
    assert r["filed"] and seen["cat"] == 3 and "location" not in r and "reportable" not in r
    assert fixmystreet.report_trash("x.jpg", 50.8, 4.3, dry_run=True)["dry_run"]


# ---------------------------------------------------------- bot member flow

class FakeQuery:
    def __init__(self, data, user_id):
        self.data, self.from_user = data, SimpleNamespace(id=user_id)
        self.answers, self.edits = [], []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeApp:
    def __init__(self):
        self.tasks, self.bot = [], SimpleNamespace(edit_message_text=self._edit)
        self.edits = []

    async def _edit(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.edits.append((text, reply_markup))

    def create_task(self, coro, update=None):
        self.tasks.append(coro)


def test_member_flow_only_submitter_can_act_and_needs_confirmation(monkeypatch, tmp_path):
    import bot

    img = tmp_path / "p-fmsu.jpg"
    img.write_bytes(b"x")
    monkeypatch.setattr(bot, "FMS_DRY_RUN", False)
    bot.FMS_PENDING.clear()
    bot.FMS_PENDING["tok"] = {"image_path": str(img), "gps": (50.8, 4.3), "user_id": 7, "first_name": "Ann",
                              "chat_id": -100, "message_id": 5, "ts": 0, "stage": "offered"}
    app = FakeApp()

    def run(data, user_id):
        q = FakeQuery(data, user_id)
        asyncio.run(bot._handle_member_report_callback(
            SimpleNamespace(callback_query=q), SimpleNamespace(application=app)))
        return q

    # someone else can't act on Ann's photo
    q = run("fmsu:prep:tok", 99)
    assert "own name" in q.answers[0] and bot.FMS_PENDING["tok"]["stage"] == "offered"
    # Ann without saved details is sent to set them up
    q = run("fmsu:prep:tok", 7)
    assert "private chat" in q.answers[0] and not app.tasks

    fms_profiles.save(7, fms_profiles.parse("Ann Peeters; ann@example.be"))
    monkeypatch.setattr(fixmystreet, "prepare", lambda p, lat, lon: {
        "reportable": True, "category_id": 3, "category": "Dépôts", "description": "Matelas abandonné.",
        "address": "Rue X 1", "location": {"x": 1, "y": 2}})
    run("fmsu:prep:tok", 7)
    asyncio.run(app.tasks.pop())
    assert bot.FMS_PENDING["tok"]["stage"] == "previewed"
    assert "Filed as: Ann P., a…@example.be" in app.edits[-1][0]

    sent = {}
    monkeypatch.setattr(fixmystreet, "submit", lambda loc, cat, desc, img, profile: sent.update(profile=profile) or {"id": 9, "url": "https://fms/9"})
    run("fmsu:send:tok", 7)
    asyncio.run(app.tasks.pop())
    assert sent["profile"]["email"] == "ann@example.be"
    assert "https://fms/9" in app.edits[-1][0]
    assert "tok" not in bot.FMS_PENDING and not img.exists()
    assert fms_profiles.reports_today(7) == 1


def test_member_flow_daily_limit(monkeypatch, tmp_path):
    import bot

    img = tmp_path / "p-fmsu.jpg"
    img.write_bytes(b"x")
    bot.FMS_PENDING.clear()
    bot.FMS_PENDING["tok"] = {"image_path": str(img), "gps": (50.8, 4.3), "user_id": 7, "first_name": "Ann",
                              "chat_id": -100, "message_id": 5, "ts": 0, "stage": "offered"}
    fms_profiles.save(7, fms_profiles.parse("Ann Peeters; ann@example.be"))
    monkeypatch.setenv("FMS_USER_DAILY_MAX", "1")
    fms_profiles.record_report(7)
    q = FakeQuery("fmsu:prep:tok", 7)
    asyncio.run(bot._handle_member_report_callback(
        SimpleNamespace(callback_query=q), SimpleNamespace(application=FakeApp())))
    assert "limit" in q.answers[0] and bot.FMS_PENDING["tok"]["stage"] == "offered"
