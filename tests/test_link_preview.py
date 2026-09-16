import link_preview
import feed_publisher as feed

HTML = """<html><head><title>Fallback title</title>
<meta property="og:title" content="Propreté : les plaintes explosent à Bruxelles">
<meta property="og:description" content="Les dépôts clandestins ont doublé en un an.">
<meta property="og:site_name" content="Le Journal">
<meta property="og:image" content="/img/poubelle.jpg">
</head><body>...</body></html>"""


def test_parse_og_reads_open_graph_and_resolves_relative_image():
    card = link_preview.parse_og(HTML, "https://www.lejournal.example/article/123")
    assert card["title"] == "Propreté : les plaintes explosent à Bruxelles"
    assert card["description"].startswith("Les dépôts")
    assert card["site"] == "Le Journal"
    assert card["image"] == "https://www.lejournal.example/img/poubelle.jpg"


def test_parse_og_falls_back_to_title_tag_and_hostname():
    card = link_preview.parse_og("<html><head><title>Plain page</title></head></html>", "https://www.example.org/x")
    assert card == {"title": "Plain page", "description": "", "site": "example.org", "image": ""}


def test_record_post_survives_card_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "SITE_DIR", tmp_path)
    monkeypatch.setattr(link_preview, "fetch_card", lambda *a, **k: None)
    assert feed.record_post("1", post_id="2", author="giselle", text="Quel drame\nhttps://example.org/a", reply_to="1")
    post = feed.load_feed()["observations"][0]["posts"][0]
    assert post["source_url"] == "https://example.org/a" and "source_card" not in post


def test_record_post_stores_card(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "SITE_DIR", tmp_path)
    monkeypatch.setattr(link_preview, "fetch_card", lambda url, media, pid: {"title": "T", "description": "", "site": "s", "image": f"media/{pid}-card.jpg"})
    feed.record_post("1", post_id="2", author="giselle", text="Quel drame\nhttps://example.org/a", reply_to="1")
    post = feed.load_feed()["observations"][0]["posts"][0]
    assert post["source_card"]["image"] == "media/2-card.jpg"
