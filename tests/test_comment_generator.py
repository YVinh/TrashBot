import pytest

import comment_generator
from comment_generator import get_image_media_type


def test_get_image_media_type_known_extensions():
    assert get_image_media_type("photo.jpg") == "image/jpeg"
    assert get_image_media_type("photo.PNG") == "image/png"
    assert get_image_media_type("photo.webp") == "image/webp"


def test_get_image_media_type_heic_maps_to_jpeg():
    assert get_image_media_type("photo.heic") == "image/jpeg"
    assert get_image_media_type("photo.HEIF") == "image/jpeg"


def test_get_image_media_type_unknown_extension_defaults_to_jpeg():
    assert get_image_media_type("photo.bmp") == "image/jpeg"


def test_generate_sassy_comment_local_never_calls_anthropic(monkeypatch, tmp_path):
    """LLM_BACKEND=local must never construct an Anthropic client — no silent paid
    fallback (matches the fail-fast rule used by local_llm.py elsewhere)."""
    monkeypatch.setenv("LLM_BACKEND", "local")

    img = tmp_path / "t.jpg"
    img.write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 16)  # fake jpeg bytes, never opened

    monkeypatch.setattr(comment_generator.local_llm, "image_data_url", lambda *a, **k: "data:image/jpeg;base64,Zm9v")

    calls = {}

    def fake_chat(model, messages, **kw):
        calls["model"] = model
        calls["messages"] = messages
        return "Encore un tas de saletés, franchement."

    monkeypatch.setattr(comment_generator.local_llm, "chat", fake_chat)

    def fail_anthropic(*a, **k):
        raise AssertionError("Anthropic() must not be constructed when LLM_BACKEND=local")

    monkeypatch.setattr(comment_generator, "Anthropic", fail_anthropic)

    result = comment_generator.generate_sassy_comment(str(img))

    assert result == "Encore un tas de saletés, franchement."
    assert calls["model"] == comment_generator.local_llm.writer_model()


def test_generate_sassy_comment_local_fails_fast(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BACKEND", "local")
    img = tmp_path / "t.jpg"
    img.write_bytes(b"\xff\xd8\xff\xdb" + b"0" * 16)
    monkeypatch.setattr(comment_generator.local_llm, "image_data_url", lambda *a, **k: "data:image/jpeg;base64,Zm9v")

    def raise_error(*a, **k):
        raise comment_generator.local_llm.LocalLLMError("gateway down")

    monkeypatch.setattr(comment_generator.local_llm, "chat", raise_error)

    with pytest.raises(comment_generator.local_llm.LocalLLMError):
        comment_generator.generate_sassy_comment(str(img))


def test_generate_sassy_comment_missing_file(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    with pytest.raises(FileNotFoundError):
        comment_generator.generate_sassy_comment("/nonexistent/path.jpg")
