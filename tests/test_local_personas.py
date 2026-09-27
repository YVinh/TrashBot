import datetime as dt

import pytest

import feed_poller
import fixmystreet
import giselle_agent
import local_llm
import news_rss
import yousuf_agent
from x_text_utils import MAX_CAPTION_CHARS, TWITTER_URL_LENGTH, enforce_tags, finish_local

NOW = dt.datetime(2026, 9, 26, 12, tzinfo=dt.timezone.utc)
GISELLE, YOUSUF = "@GiselleDeBxl", "@yousufbxlpropre"
POOL = ["#bruxellespropreté", "#netbrussel", "#brugov", "#réformerBruxelles"]

RSS = b"""<rss><channel>
<item><title>La Ville triple le volume d'encombrants</title><link>https://www.dhnet.be/a</link>
 <pubDate>Tue, 22 Sep 2026 10:00:00 +0100</pubDate><description>Collecte gratuite.</description></item>
<item><title>La Ville triple le volume d encombrants !</title><link>https://www.lavenir.net/a</link>
 <pubDate>Tue, 22 Sep 2026 11:00:00 +0100</pubDate><description>Idem.</description></item>
<item><title>Un feu de d\xc3\xa9chets \xc3\xa0 Forest</title><link>https://www.dhnet.be/b</link>
 <pubDate>Tue, 22 Sep 2026 09:00:00 +0100</pubDate><description>Les pompiers.</description></item>
<item><title>Vieux d\xc3\xa9p\xc3\xb4t clandestin</title><link>https://www.dhnet.be/c</link>
 <pubDate>Mon, 01 Jun 2026 09:00:00 +0100</pubDate><description></description></item>
<item><title>Budget du logement social</title><link>https://www.dhnet.be/d</link>
 <pubDate>Sat, 26 Sep 2026 09:00:00 +0100</pubDate><description>Rien \xc3\xa0 voir.</description></item>
</channel></rss>"""


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setattr(news_rss, "USED_FILE", tmp_path / "used.json")


def test_rss_keeps_recent_litter_stories_once_and_drops_fires():
    items = news_rss.relevant(news_rss._parse(RSS, "dhnet.be"), now=NOW)
    assert [i["link"] for i in items] == ["https://www.lavenir.net/a"]


def test_rss_never_reuses_a_link(local):
    items = news_rss._parse(RSS, "dhnet.be")
    news_rss.mark_used("https://www.lavenir.net/a")
    assert news_rss.pick_article([i for i in items if i["link"] != "https://www.dhnet.be/c"]) is None


def test_enforce_tags_fixes_mangled_handles_and_foreign_hashtags():
    out = enforce_tags("quelle honte @GiselleDeBxI #Paris #netbrussel", [GISELLE], POOL, want_hashtags=2)
    assert "@GiselleDeBxI" not in out and GISELLE in out
    assert "#Paris" not in out and "#netbrussel" in out
    assert len([w for w in out.split() if w.startswith("#")]) == 2


def test_finish_local_drops_model_urls_and_keeps_mentions_when_shortener_loses_them(local, monkeypatch):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "raccourci sans mention")
    text = "franchement " * 40 + "https://invented.example/x " + YOUSUF
    out = finish_local(text, "voix", [YOUSUF], POOL, url="https://www.dhnet.be/a")
    body, url = out.rsplit("\n", 1)
    assert url == "https://www.dhnet.be/a"
    assert "invented.example" not in out and YOUSUF in body
    assert len(body) + 1 + TWITTER_URL_LENGTH <= MAX_CAPTION_CHARS


def test_giselle_local_link_comes_only_from_the_feed(local, monkeypatch):
    article = {"title": "Encombrants", "summary": "…", "link": "https://www.dhnet.be/a",
               "published": NOW, "site": "dhnet.be"}
    monkeypatch.setattr(news_rss, "pick_article", lambda: article)
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "Quel drame !! https://fake.example/news @GiselleDeBxl")
    out = giselle_agent.generate_reaction("encore des crasses")
    assert out.endswith("\nhttps://www.dhnet.be/a")
    assert "fake.example" not in out and GISELLE not in out and YOUSUF in out
    assert news_rss._used() == ["https://www.dhnet.be/a"]


def test_giselle_local_without_article_has_no_link(local, monkeypatch):
    monkeypatch.setattr(news_rss, "pick_article", lambda: None)
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "Quel drame, où va-t-on !")
    out = giselle_agent.generate_reaction("encore des crasses")
    assert "http" not in out and YOUSUF in out


def test_yousuf_local_comments_have_exact_mentions(local, monkeypatch):
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "askip c'est choquant @Giselle_Bxl mdr")
    on_marc, on_giselle = yousuf_agent.generate_comments("post marc", "post giselle")
    assert "@" not in on_marc and any(h in on_marc for h in POOL)
    assert GISELLE in on_giselle and "@Giselle_Bxl" not in on_giselle


def test_fms_local_rejects_category_outside_the_menu(local, monkeypatch):
    monkeypatch.setattr(fixmystreet, "cleanliness_categories", lambda: [{"id": 7, "path": "Dépôt", "mandatoryComment": False}])
    monkeypatch.setattr(fixmystreet, "_local_verdict", lambda p, l, m: {"reportable": True, "category_id": 99,
                                                                         "description": "Sacs abandonnés sur le trottoir.", "reason": ""})
    with pytest.raises(fixmystreet.FixMyStreetError, match="hors liste"):
        fixmystreet.assess("x.jpg")


def test_fms_local_schema_limits_categories(local, monkeypatch):
    seen = {}
    monkeypatch.setattr(local_llm, "image_data_url", lambda p: "data:image/jpeg;base64,")
    monkeypatch.setattr(local_llm, "chat_json", lambda m, msgs, schema, **k: seen.setdefault("s", schema) and
                        {"reportable": True, "category_id": 7, "description": "Sacs abandonnés sur le trottoir.", "reason": ""})
    monkeypatch.setattr(fixmystreet, "cleanliness_categories", lambda: [{"id": 7, "path": "Dépôt", "mandatoryComment": False}])
    assert fixmystreet.assess("x.jpg")["category_path"] == "Dépôt"
    assert seen["s"]["properties"]["category_id"]["anyOf"][0]["enum"] == [7]


def test_moderation_local_fails_closed(local, monkeypatch):
    def down(*a, **k):
        raise local_llm.LocalLLMError("down")

    monkeypatch.setattr(local_llm, "chat", down)
    assert feed_poller.fit_to_show("hello") is False
    monkeypatch.setattr(local_llm, "chat", lambda *a, **k: "SHOW")
    assert feed_poller.fit_to_show("hello") is True
