import json
import urllib.error

import pytest

import local_llm
import trash_agent
from trash_agent import GISELLE_HANDLE, YOUSUF_HANDLE, assemble, tag_line


def test_tag_line_without_gps_is_just_the_two_mentions(monkeypatch):
    monkeypatch.setattr(trash_agent, "extract_gps_coordinates", lambda p: None)
    assert sorted(tag_line("x.jpg").split()) == sorted([GISELLE_HANDLE, YOUSUF_HANDLE])


def test_tag_line_with_brussels_gps_adds_two_hashtags(monkeypatch):
    monkeypatch.setattr(trash_agent, "extract_gps_coordinates", lambda p: (50.85, 4.35))
    parts = tag_line("x.jpg").split()
    assert GISELLE_HANDLE in parts and YOUSUF_HANDLE in parts
    assert len([p for p in parts if p.startswith("#")]) == 2


def test_assemble_stays_under_280_and_keeps_mentions_intact():
    tags = f"#AlerteDéchets {GISELLE_HANDLE} #PropretéUrbaine {YOUSUF_HANDLE}"
    caption = assemble("mot " * 100, tags)
    assert len(caption) <= 280
    assert caption.endswith(tags)
    assert caption.split("\n")[0].endswith("…")


def test_punchline_is_stripped_of_tags_links_and_quotes(monkeypatch):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: '"encore des crasses #Bxl partout @someone pfff https://x.io/a"')
    assert trash_agent.write_punchline({"items": ["bag"]}) == "encore des crasses partout pfff"


def test_local_draft_carries_the_belongings_warning(monkeypatch):
    facts = {"items": ["duvet"], "possibly_someones_belongings": True, "belongings_reason": "bedding laid flat"}
    monkeypatch.setattr(trash_agent, "see", lambda p: facts)
    monkeypatch.setattr(trash_agent, "write_punchline", lambda f, n=None: "de la saleté partout")
    monkeypatch.setattr(trash_agent, "extract_gps_coordinates", lambda p: None)
    draft = trash_agent.generate_post_draft("x.jpg", backend="local")
    assert draft.backend == "local"
    assert draft.belongings_warning == "bedding laid flat"
    assert draft.caption.startswith("de la saleté partout\n")


def test_backend_switch_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setattr(trash_agent, "_anthropic_draft", lambda p, n=None: "opus caption")
    monkeypatch.setattr(trash_agent, "_local_draft", lambda p, n: pytest.fail("local must not run"))
    assert trash_agent.generate_post_draft("x.jpg").caption == "opus caption"


def test_chat_without_gateway_key_fails_fast(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_KEY", raising=False)
    with pytest.raises(local_llm.LocalLLMError, match="LLM_GATEWAY_KEY"):
        local_llm.chat("mbp-writer", [{"role": "user", "content": "hi"}])


def test_chat_turns_network_errors_into_local_llm_error(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_KEY", "k")

    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(local_llm.urllib.request, "urlopen", boom)
    with pytest.raises(local_llm.LocalLLMError, match="unreachable"):
        local_llm.chat("mbp-writer", [{"role": "user", "content": "hi"}])


def test_chat_json_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "not json")
    with pytest.raises(local_llm.LocalLLMError, match="invalid JSON"):
        local_llm.chat_json("mbp-writer", [], {"type": "object"})


def test_chat_sends_schema_and_no_thinking(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_KEY", "k")
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{\"a\": 1}"}}]}).encode()

    def fake_urlopen(req, timeout):
        sent.update(json.loads(req.data))
        return Resp()

    monkeypatch.setattr(local_llm.urllib.request, "urlopen", fake_urlopen)
    assert local_llm.chat_json("mbp-writer", [], {"type": "object"}) == {"a": 1}
    assert sent["reasoning_effort"] == "none"
    assert sent["response_format"]["type"] == "json_schema"
    sent.clear()
    local_llm.chat_json("free-gemini-flash", [], {"type": "object"})
    assert "reasoning_effort" not in sent


from datetime import datetime, timezone


@pytest.mark.parametrize("hhmm,busy", [("21:29", False), ("21:30", True), ("02:00", True),
                                       ("04:29", True), ("04:30", False), ("12:00", False)])
def test_m5_busy_window_wraps_midnight(monkeypatch, hhmm, busy):
    monkeypatch.delenv("M5_BUSY_UTC", raising=False)
    h, m = map(int, hhmm.split(":"))
    assert local_llm.m5_busy(datetime(2026, 9, 26, h, m, tzinfo=timezone.utc)) is busy


def test_vision_chain_order_and_night_skip(monkeypatch):
    monkeypatch.delenv("LOCAL_VISION_MODEL", raising=False)
    monkeypatch.delenv("LOCAL_VISION_CHAIN", raising=False)
    monkeypatch.delenv("M5_BUSY_UTC", raising=False)
    noon = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    night = datetime(2026, 9, 26, 23, 0, tzinfo=timezone.utc)
    assert local_llm.vision_chain(noon) == ["mbp-writer"]
    monkeypatch.setenv("LOCAL_VISION_CHAIN", "mac-vision-3, phone-vision ,mbp-writer")
    assert local_llm.vision_chain(noon) == ["mac-vision-3", "phone-vision", "mbp-writer"]
    assert local_llm.vision_chain(night) == ["phone-vision", "mbp-writer"]


@pytest.mark.parametrize("text", ['```json\n{"a": 1}\n```', '{\n 2025-04-05 12:34:56 UTC\n\n{"a": 1}'])
def test_chat_json_finds_the_object_in_chatter(monkeypatch, text):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: text)
    assert local_llm.chat_json("phone-vision", [], {"type": "object"}) == {"a": 1}


def test_chat_json_rejects_answers_missing_required_fields(monkeypatch):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: '{"a": 1}')
    with pytest.raises(local_llm.LocalLLMError, match="lacks b"):
        local_llm.chat_json("phone-vision", [], {"type": "object", "required": ["a", "b"]})


def test_vision_json_walks_the_chain_to_ct210(monkeypatch):
    monkeypatch.setattr(local_llm, "vision_chain", lambda: ["mac-vision-3", "phone-vision", "mbp-writer"])
    calls = []

    def fake(model, messages, schema, **kw):
        calls.append((model, kw["timeout"]))
        if model != "mbp-writer":
            raise local_llm.LocalLLMError(f"{model} unreachable")
        return {"items": ["chair"]}

    monkeypatch.setattr(local_llm, "chat_json", fake)
    assert local_llm.vision_json([], {}) == ({"items": ["chair"]}, "mbp-writer")
    assert calls == [("mac-vision-3", local_llm.EARLY_TIMEOUT), ("phone-vision", local_llm.EARLY_TIMEOUT),
                     ("mbp-writer", local_llm.DEFAULT_TIMEOUT)]


def test_vision_json_raises_with_both_errors_and_never_goes_paid(monkeypatch):
    monkeypatch.setattr(local_llm, "vision_chain", lambda: ["mac-vision-3", "mbp-writer"])

    def fail(model, *a, **k):
        raise local_llm.LocalLLMError(f"{model} down")

    monkeypatch.setattr(local_llm, "chat_json", fail)
    with pytest.raises(local_llm.LocalLLMError, match="mac-vision-3 down / mbp-writer down"):
        local_llm.vision_json([], {})
