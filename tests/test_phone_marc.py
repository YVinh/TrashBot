import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image

import phone_marc


class Fake(BaseHTTPRequestHandler):
    marc_replies: list = []
    calls: list = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"status": "ok"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.calls.append((self.headers["Authorization"], req))
        if req["model"] == phone_marc.VISION_MODEL:
            text = ("ITEMS: deep fryer, white plastic bag\nAMOUNT: a few items\nPLACE: next to glass banks\n"
                    "SUMMARY_FR: Une friteuse abandonnée au pied des bulles à verre.")
        else:
            text = Fake.marc_replies.pop(0)
        self._send({"choices": [{"message": {"content": text}}]})


@pytest.fixture
def phone(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("PHONE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("HOUSENODE_TOKEN", "test-token")
    Fake.calls = []
    img = tmp_path / "p.jpg"
    Image.new("RGB", (2000, 1500), "gray").save(img)
    yield str(img)
    srv.shutdown()


def test_retries_bad_lines_then_succeeds(phone):
    Fake.marc_replies = ["", "x" * 250, "Une friteuse au pied des bulles, bravo."]
    line, facts = phone_marc.marc_for_photo(phone)
    assert line.startswith("Une friteuse")
    assert facts["items"] == ["deep fryer", "white plastic bag"] and facts["amount"] == "a few items"


def test_gives_up_after_three(phone):
    Fake.marc_replies = ["", "@x", "y" * 300, "never asked"]
    with pytest.raises(phone_marc.PhoneError, match="3 tries"):
        phone_marc.marc_for_photo(phone)
    assert Fake.marc_replies == ["never asked"]


def test_request_shape(phone):
    Fake.marc_replies = ["Ok bien."]
    phone_marc.marc_for_photo(phone)
    auth, vision = Fake.calls[0]
    assert auth == "Bearer test-token"
    assert vision["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    marc = Fake.calls[1][1]
    assert (marc["model"], marc["temperature"], marc["max_tokens"]) == ("local/marc-v4-step200", 0.7, 80)
    assert marc["messages"][1]["content"].startswith("Description de la photo :\n{")


def test_phone_unreachable(monkeypatch):
    monkeypatch.setenv("PHONE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("HOUSENODE_TOKEN", "t")
    with pytest.raises(phone_marc.PhoneError, match="did not answer"):
        phone_marc.marc_for_photo("unused")


def test_missing_token(monkeypatch):
    monkeypatch.delenv("HOUSENODE_TOKEN", raising=False)
    with pytest.raises(phone_marc.PhoneError, match="HOUSENODE_TOKEN"):
        phone_marc.check_health()


def test_unusable_description():
    with pytest.raises(phone_marc.PhoneError):
        phone_marc.parse_description("1 2 3 4 5 6")
