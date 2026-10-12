"""Back-and-forth follow-ups on the iPhone House Node adapters (homelab#112). HTTP is mocked: no live call."""
import asyncio
import io
import json
import urllib.error

import pytest

import giselle_agent
import local_llm
import yousuf_agent

GISELLE = "@GiselleDeBxl"
YOUSUF = "@yousufbxlpropre"
Y_SYSTEM = yousuf_agent.TRAINING_SYSTEM_PROMPT
G_SYSTEM = giselle_agent.TRAINING_SYSTEM_PROMPT


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("HOUSENODE_TOKEN", "test-token-not-real")
    monkeypatch.setenv("HOUSENODE_URL", "http://phone.invalid:8080")
    monkeypatch.delenv("YOUSUF_ADAPTER", raising=False)
    monkeypatch.delenv("GISELLE_ADAPTER", raising=False)
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: pytest.fail("gateway must not be used"))
    monkeypatch.setattr(yousuf_agent, "Anthropic", lambda *a, **k: pytest.fail("paid model must not be used"))
    monkeypatch.setattr(giselle_agent, "Anthropic", lambda *a, **k: pytest.fail("paid model must not be used"))


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(sent, text):
    def _open(req, timeout=None):
        sent.append({"auth": req.get_header("Authorization"), "body": json.loads(req.data)})
        return FakeResp(json.dumps({"choices": [{"message": {"content": text}}]}).encode())
    return _open


def check_phone_settings(body, adapter):
    assert (body["model"], body["adapter"], body["enable_thinking"], body["max_tokens"], body["temperature"]) == \
           ("mlx-community/Qwen3.5-4B-4bit", adapter, False, 80, 0.7)


def test_yousuf_followup_uses_trained_marc_plus_giselle_shape(phone, monkeypatch):
    sent = []
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen(sent, "askip c'est normal"))
    out = yousuf_agent.generate_followup("quelle honte", "matelas sur le trottoir")
    assert len(sent) == 1 and sent[0]["auth"] == "Bearer test-token-not-real"
    b = sent[0]["body"]
    check_phone_settings(b, "yousuf")
    assert b["messages"][0] == {"role": "system", "content": Y_SYSTEM}
    assert b["messages"][1]["content"] == (
        "Post de Marc :\nmatelas sur le trottoir\n\nRéponse de Giselle à ce post :\nquelle honte\n\n"
        "Écris ton commentaire en réponse à la réponse de Giselle, selon tes instructions.")
    assert GISELLE in out


def test_giselle_followup_uses_marc_post_and_no_article_not_yousuf_text(phone, monkeypatch):
    sent = []
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen(sent, "c'est une honte cette saleté"))
    out = giselle_agent.generate_followup("askip personne s'en occupe", "matelas sur le trottoir")
    b = sent[0]["body"]
    check_phone_settings(b, "giselle")
    assert b["messages"][0] == {"role": "system", "content": G_SYSTEM}
    assert b["messages"][1]["content"] == "Post de Marc :\nmatelas sur le trottoir\n\nPas d'article cette fois."
    assert "askip" not in json.dumps(b)  # Yousuf's text never reaches her untrained prompt
    assert YOUSUF in out


def test_followup_tags_come_from_code_only(phone, monkeypatch):
    sent = []
    monkeypatch.setattr(local_llm.urllib.request, "urlopen",
                        fake_urlopen(sent, "jsp #Paris https://fake.example @Giselle_Bxl mdr"))
    y = yousuf_agent.generate_followup("g", "m")
    assert GISELLE in y and "@Giselle_Bxl" not in y and "#Paris" not in y and "fake.example" not in y
    assert "#" not in y  # follow-ups carry no hashtag, as before
    monkeypatch.setattr(local_llm.urllib.request, "urlopen",
                        fake_urlopen(sent, "honte #Paris https://fake.example @Yousuf_Bxl"))
    g = giselle_agent.generate_followup("y", "m")
    assert YOUSUF in g and "@Yousuf_Bxl" not in g and "#Paris" not in g and "fake.example" not in g and "#" not in g


@pytest.mark.parametrize("fn", [yousuf_agent.generate_followup, giselle_agent.generate_followup])
def test_phone_down_raises_and_never_falls_back(phone, monkeypatch, fn):
    def down(req, timeout=None):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", down)
    with pytest.raises(local_llm.LocalLLMError):
        fn("dernier texte", "post de marc")


@pytest.mark.parametrize("fn", [yousuf_agent.generate_followup, giselle_agent.generate_followup])
def test_phone_followup_without_marc_text_fails_fast(phone, monkeypatch, fn):
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no call expected"))
    with pytest.raises(local_llm.LocalLLMError):
        fn("dernier texte")


def test_phone_off_keeps_the_old_writer_path(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.delenv("HOUSENODE_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(local_llm, "chat", lambda model, msgs, **k: calls.append(msgs) or "remarque courte")
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", lambda *a, **k: pytest.fail("phone must not be called"))
    assert GISELLE in yousuf_agent.generate_followup("texte de giselle", "post marc")
    assert YOUSUF in giselle_agent.generate_followup("texte de yousuf", "post marc")
    assert "Giselle vient d'écrire" in calls[0][1]["content"] and "Yousuf vient d'écrire" in calls[1][1]["content"]


# ------------------------------------------------ bot.py: EXTRA_ROUNDS and what is passed to the follow-ups
@pytest.fixture
def chain(monkeypatch, tmp_path):
    bot = pytest.importorskip("bot")
    calls, posts = [], []

    async def nowait():
        return None

    class FakeBot:
        async def send_message(self, *a, **k):
            return None

    class App:
        bot = FakeBot()

    async def feed(*a, **k):
        return None

    monkeypatch.setattr(bot, "_wait_a_bit", nowait)
    monkeypatch.setattr(bot, "_to_feed", feed)
    monkeypatch.setattr(bot.random, "random", lambda: 0.0)  # always continue
    monkeypatch.setattr(bot.chain_state, "STATE_FILE", tmp_path / "chain_state.json")
    monkeypatch.setattr(bot, "giselle_followup", lambda t, m="": calls.append(("g", t, m)) or "g-follow")
    monkeypatch.setattr(bot, "yousuf_followup", lambda t, m="": calls.append(("y", t, m)) or "y-follow")
    monkeypatch.setattr(bot, "post_reply", lambda acc, rid, text: posts.append(acc) or
                        {"post_id": f"{len(posts)}", "post_url": "http://x/1"})
    state = {"stage": "pending_extra", "chat_id": 1, "marc_tweet_id": "m1", "marc_text": "POST MARC",
             "last_speaker": "YOUSUF", "last_text": "dernier yousuf", "last_reply_id": "r0", "extra_round": 0}
    return bot, App(), state, calls, posts


def test_extra_rounds_default_is_two_and_passes_marc_text(chain, monkeypatch):
    bot, app, state, calls, posts = chain
    monkeypatch.delenv("EXTRA_ROUNDS", raising=False)
    asyncio.run(bot._chain_giselle_and_yousuf(app, state))
    assert posts == ["GISELLE", "YOUSUF"]
    assert calls == [("g", "dernier yousuf", "POST MARC"), ("y", "g-follow", "POST MARC")]


def test_extra_rounds_zero_switches_it_off(chain, monkeypatch):
    bot, app, state, calls, posts = chain
    monkeypatch.setenv("EXTRA_ROUNDS", "0")
    asyncio.run(bot._chain_giselle_and_yousuf(app, state))
    assert calls == [] and posts == []


def test_extra_rounds_env_values(monkeypatch):
    bot = pytest.importorskip("bot")
    monkeypatch.setenv("EXTRA_ROUNDS", "1")
    assert bot.max_extra_rounds() == 1
    monkeypatch.setenv("EXTRA_ROUNDS", "junk")
    assert bot.max_extra_rounds() == 2
    monkeypatch.setenv("EXTRA_ROUNDS", "-3")
    assert bot.max_extra_rounds() == 0


def test_phone_error_stops_the_rounds_with_a_warning(chain, monkeypatch):
    bot, app, state, calls, posts = chain
    sent = []

    class FakeBot:
        async def send_message(self, chat_id, text, **k):
            sent.append(text)

    app.bot = FakeBot()
    def boom(t, m=""):
        raise local_llm.LocalLLMError("phone down")
    monkeypatch.setattr(bot, "giselle_followup", boom)
    asyncio.run(bot._chain_giselle_and_yousuf(app, state))
    assert posts == [] and any("Back-and-forth stopped early" in s and "phone down" in s for s in sent)
