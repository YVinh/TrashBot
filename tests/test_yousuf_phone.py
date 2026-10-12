"""Yousuf on the iPhone House Node (adapter "yousuf", homelab#112). HTTP is mocked: no live call."""
import io
import json
import urllib.error

import pytest

import local_llm
import yousuf_agent

GISELLE = "@GiselleDeBxl"
POOL = ["#bruxellespropreté", "#netbrussel", "#brugov", "#réformerBruxelles"]
TRAIN_SYSTEM = ("Tu es Yousuf, jeune, sec et sarcastique, sur la saleté à Bruxelles. On te donne le post de Marc et parfois la "
                "réaction de Giselle. Écris UN commentaire en français, 180 caractères maximum, sans hashtag, sans @, sans lien.")


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("HOUSENODE_TOKEN", "test-token-not-real")
    monkeypatch.setenv("HOUSENODE_URL", "http://phone.invalid:8080")
    monkeypatch.delenv("YOUSUF_ADAPTER", raising=False)
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: pytest.fail("gateway must not be used"))


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(sent, texts):
    def _open(req, timeout=None):
        sent.append({"url": req.full_url, "auth": req.get_header("Authorization"), "body": json.loads(req.data)})
        return FakeResp(json.dumps({"choices": [{"message": {"content": texts[len(sent) - 1]}}]}).encode())
    return _open


def test_two_user_shapes_and_request_body(phone, monkeypatch):
    sent = []
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen(sent, ["un matelas jsp", "askip c'est normal"]))
    yousuf_agent.generate_comments("matelas sur le trottoir", "quelle honte")
    assert [s["url"] for s in sent] == ["http://phone.invalid:8080/v1/chat/completions"] * 2
    for s in sent:
        b = s["body"]
        assert s["auth"] == "Bearer test-token-not-real"
        assert (b["model"], b["adapter"], b["enable_thinking"], b["max_tokens"], b["temperature"]) == \
               ("mlx-community/Qwen3.5-4B-4bit", "yousuf", False, 80, 0.7)
        assert b["messages"][0] == {"role": "system", "content": TRAIN_SYSTEM}
    assert sent[0]["body"]["messages"][1]["content"] == (
        "Post de Marc :\nmatelas sur le trottoir\n\n"
        "Écris ton commentaire en réponse au post original de Marc, selon tes instructions.")
    assert sent[1]["body"]["messages"][1]["content"] == (
        "Post de Marc :\nmatelas sur le trottoir\n\nRéponse de Giselle à ce post :\nquelle honte\n\n"
        "Écris ton commentaire en réponse à la réponse de Giselle, selon tes instructions.")


def test_hashtag_and_mention_come_from_code(phone, monkeypatch):
    sent = []
    # the model tries to add its own tags, a wrong handle and a link: all must be corrected by code
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen(
        sent, ["jsp #Paris https://fake.example @Marc_Bxl", "mdr @Giselle_Bxl #Paris"]))
    on_marc, on_giselle = yousuf_agent.generate_comments("post marc", "post giselle")
    assert "@" not in on_marc and "fake.example" not in on_marc and "#Paris" not in on_marc
    assert sum(h in on_marc for h in POOL) == 1
    assert GISELLE in on_giselle and "@Giselle_Bxl" not in on_giselle and "#Paris" not in on_giselle
    assert sum(h in on_giselle for h in POOL) == 1


def test_phone_unreachable_raises_and_never_falls_back(phone, monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", down)
    monkeypatch.setattr(yousuf_agent, "Anthropic", lambda *a, **k: pytest.fail("paid model must not be used"))
    with pytest.raises(local_llm.LocalLLMError):
        yousuf_agent.generate_comments("post marc", "post giselle")


def test_phone_path_off_without_token_keeps_old_writer(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.delenv("HOUSENODE_TOKEN", raising=False)
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "askip c'est choquant")
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", lambda *a, **k: pytest.fail("phone must not be called"))
    on_marc, on_giselle = yousuf_agent.generate_comments("post marc", "post giselle")
    assert on_marc and GISELLE in on_giselle
