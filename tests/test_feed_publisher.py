import json

from PIL import Image

import feed_publisher as feed


def _use_tmp_site(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "SITE_DIR", tmp_path)
    return tmp_path


def test_record_post_archives_image_without_metadata(monkeypatch, tmp_path):
    site = _use_tmp_site(monkeypatch, tmp_path)
    photo = tmp_path / "photo.jpg"
    img = Image.new("RGB", (2000, 1500), "red")
    exif = img.getexif()
    exif[0x010E] = "shot at 50.85N 4.35E"  # any EXIF at all must not survive
    img.save(photo, exif=exif.tobytes())

    assert feed.record_post("1", post_id="1", author="marc", text="dedju", image_path=str(photo), url="u")

    data = json.loads((site / "feed.json").read_text())
    post = data["observations"][0]["posts"][0]
    assert post["image"] == "media/1.jpg"
    archived = Image.open(site / "media" / "1.jpg")
    assert max(archived.size) <= feed.MAX_IMAGE_EDGE
    assert not archived.getexif()


def test_sample_feed_is_replaced_by_first_real_post(monkeypatch, tmp_path):
    site = _use_tmp_site(monkeypatch, tmp_path)
    (site / "feed.json").write_text(json.dumps({"sample": True, "observations": [{"id": "x", "posts": []}]}))

    feed.record_post("1", post_id="1", author="marc", text="t")

    data = json.loads((site / "feed.json").read_text())
    assert "sample" not in data
    assert [o["id"] for o in data["observations"]] == ["1"]


def test_giselle_source_url_and_idempotent_record(monkeypatch, tmp_path):
    site = _use_tmp_site(monkeypatch, tmp_path)
    text = "Quel drame !!!\n#Bruxelles @yousufbxlpropre\nhttps://example.org/article"
    assert feed.record_post("1", post_id="2", author="giselle", text=text, reply_to="1")
    assert not feed.record_post("1", post_id="2", author="giselle", text=text, reply_to="1")

    posts = json.loads((site / "feed.json").read_text())["observations"][0]["posts"]
    assert len(posts) == 1
    assert posts[0]["source_url"] == "https://example.org/article"


def test_visitor_and_metrics(monkeypatch, tmp_path):
    site = _use_tmp_site(monkeypatch, tmp_path)
    feed.record_post("1", post_id="1", author="marc", text="t")
    assert feed.record_visitor("1", post_id="9", visitor="0417", text="Vous allez bien ?", reply_to="1", at="2026-09-14T15:58:29+02:00")
    assert feed.set_metrics("1", "1", {"likes": 2, "reposts": 0, "replies": 6, "impressions": 148})
    assert not feed.set_metrics("1", "nope", {})

    posts = json.loads((site / "feed.json").read_text())["observations"][0]["posts"]
    assert posts[1]["author"] == "public" and "handle" not in posts[1]
    assert posts[0]["metrics"]["impressions"] == 148 and "fetched_at" in posts[0]["metrics"]


def test_publish_without_command_only_writes(monkeypatch, tmp_path):
    _use_tmp_site(monkeypatch, tmp_path)
    monkeypatch.setattr(feed, "PUBLISH_CMD", "")
    feed.publish()  # copies the page + avatars from the source tree, runs nothing
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "media" / "avatar-marc.jpg").exists()
