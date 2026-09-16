import json

import fixmystreet
import feed_publisher as feed


def test_reverse_geocode_axis_order_is_lat_then_lon(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"error": False, "result": {"address": {"street": {"name": "Rue Ducale", "postCode": "1000", "municipality": "Bruxelles"}, "number": "63"}}}

    class S:
        headers = {}
        def get(self, url, params=None, timeout=None):
            seen.update(json.loads(params["json"])); return R()
    monkeypatch.setattr(fixmystreet, "_session", lambda: S())
    a = fixmystreet.reverse_geocode(50.8467, 4.3676)
    assert seen["point"] == {"x": 50.8467, "y": 4.3676} and seen["SRS_In"] == 4326
    assert a == {"street": "Rue Ducale", "number": "63", "postCode": "1000", "municipality": "Bruxelles"}


def test_reporter_requires_name_and_email(monkeypatch):
    monkeypatch.delenv("FMS_REPORTER_NAME", raising=False)
    monkeypatch.delenv("FMS_REPORTER_EMAIL", raising=False)
    try:
        fixmystreet._reporter()
    except fixmystreet.FixMyStreetError:
        pass
    else:
        raise AssertionError("expected FixMyStreetError")
    monkeypatch.setenv("FMS_REPORTER_NAME", "Y P")
    monkeypatch.setenv("FMS_REPORTER_EMAIL", "y@example.org")
    r = fixmystreet._reporter()
    assert r["actingAs"] == "RESIDENT" and r["contact"]["emailAddress"] == "y@example.org"


def test_report_trash_skips_when_not_reportable(monkeypatch):
    monkeypatch.setattr(fixmystreet, "assess", lambda p: {"reportable": False, "reason": "papier isolé"})
    monkeypatch.setattr(fixmystreet, "locate", lambda lat, lon: (_ for _ in ()).throw(AssertionError("must not geocode")))
    assert fixmystreet.report_trash("x.jpg", 50.8, 4.3) == {"filed": False, "reason": "papier isolé"}


def test_feed_report_and_status_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(feed, "SITE_DIR", tmp_path)
    feed.record_post("1", post_id="1", author="marc", text="t")
    assert feed.set_report("1", "1", {"id": 42, "url": "u", "category": "c", "status": "PROCESSING"})
    assert feed.refresh_report_statuses(lambda i: {"status": "CLOSED", "organisation": "Ixelles"})
    post = feed.load_feed()["observations"][0]["posts"][0]
    assert post["report"]["status"] == "CLOSED" and post["report"]["organisation"] == "Ixelles"
    # closed reports are not looked up again
    assert not feed.refresh_report_statuses(lambda i: (_ for _ in ()).throw(AssertionError("looked up a closed report")))
