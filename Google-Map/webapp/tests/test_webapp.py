import time

import pytest
from fastapi.testclient import TestClient

from webapp import config, crawler, db, filters, jobs, outreach, secrets_store
from webapp.providers import PROVIDERS

FILTERS = config.default_config()["filters"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPLEADS_DB", str(tmp_path / "t.sqlite3"))
    monkeypatch.setattr(config, "ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(outreach, "ATTACHMENTS_DIR", str(tmp_path / "att"))
    monkeypatch.setattr(secrets_store, "ENV_PATH", str(tmp_path / ".env"))
    from webapp.app import app
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("email,kept,layer", [
    ("jobs@datalab.berlin", True, 0),
    ("Karriere@Kiwi-AI.de", True, 0),
    ("noreply@company.de", False, 5),
    ("sdk@0.1.26-site.compat.min.js", False, 4),
    ("test123@startup.io", False, 8),
    ("a@shop.de", False, 9),
    ("no-at-sign.de", False, 10),
])
def test_filter_layers(email, kept, layer):
    result, got_layer, _ = filters.check_email(email, FILTERS)
    assert bool(result) is kept
    assert got_layer == layer


def test_filter_layer_can_be_disabled():
    cfg = {**FILTERS, "layers": {**FILTERS["layers"], "5": False}}
    assert filters.check_email("noreply@company.de", cfg)[0] is None  # still caught by contains/prefix rules
    assert filters.check_email("support@company.de", cfg)[0] == "support@company.de"


def test_filter_lists_come_from_main_py():
    assert "noreply" in FILTERS["lists"]["localparts"]
    assert len(FILTERS["lists"]["domains"]) > 5


def test_own_domain_layer_is_opt_in():
    assert filters.check_email("info@other.com", FILTERS, "acme.de")[0] == "info@other.com"
    cfg = {**FILTERS, "layers": {**FILTERS["layers"], "11": True}}
    assert filters.check_email("info@other.com", cfg, "acme.de")[1] == 11
    assert filters.check_email("jobs@mail.acme.de", cfg, "acme.de")[0] == "jobs@mail.acme.de"


def test_text_fragments_are_not_emails():
    found, _ = crawler.extract_emails("<p>ten year@lums.with honours, science@pucit.currently</p><p>hi@acme.berlin</p>")
    assert found == {"hi@acme.berlin"}


def test_email_type_and_first_name():
    assert filters.email_type("karriere@x.de") == "jobs/hr"
    assert filters.email_type("info@x.de") == "generic"
    assert filters.email_type("anna.schmidt@x.de") == "personal"
    assert filters.first_name("anna.schmidt@x.de") == "Anna"
    assert filters.first_name("info@x.de") == ""


def test_extract_emails_handles_obfuscation_and_mailto():
    html = '<a href="mailto:hr@acme.de?subject=x">mail</a><p>jobs [at] acme [dot] de</p><p>info@acme.de</p>'
    found, _ = crawler.extract_emails(html)
    assert {"hr@acme.de", "jobs@acme.de", "info@acme.de"} <= found


def test_rank_relevant_pages_prefers_impressum_and_skips_offsite():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup('<a href="/team">Team</a><a href="/impressum">Impressum</a>'
                         '<a href="https://other.de/kontakt">x</a><a href="/datenschutz">Kontakt Datenschutz</a>', "html.parser")
    ranked = crawler.rank_relevant_pages(soup, "https://acme.de", config.default_config()["crawl"])
    assert ranked[0] == "https://acme.de/impressum"
    assert all("other.de" not in u and "datenschutz" not in u for u in ranked)


def test_build_queries():
    qs = jobs.build_queries({"keywords": ["IT"], "locations": ["Mitte", "Wedding"], "city": "Berlin"})
    assert [q["q"] for q in qs] == ["IT in Mitte Berlin", "IT in Wedding Berlin"]


def test_render_template():
    subject, body = outreach.render({"subject": "Hi {company}", "body": "Hallo{first_name_sp}, {district}"},
                                    {"name": "Acme", "district": "Mitte", "domain": "acme.de"}, "anna.b@acme.de", "Me")
    assert subject == "Hi Acme" and body == "Hallo Anna, Mitte"


def test_config_roundtrip(client):
    cfg = client.get("/api/v1/config").json()
    assert cfg["crawl"]["max_relevant_pages"] == 8
    client.put("/api/v1/config", json={"crawl": {"max_relevant_pages": 3}})
    assert client.get("/api/v1/config").json()["crawl"]["max_relevant_pages"] == 3
    assert client.post("/api/v1/config/reset?section=crawl").json()["crawl"]["max_relevant_pages"] == 8


def test_filter_test_endpoint(client):
    r = client.post("/api/v1/filters/test", json={"emails": ["jobs@acme.de", "noreply@acme.de"]}).json()
    assert [x["kept"] for x in r] == [True, False]


def test_secrets_never_returned(client):
    r = client.put("/api/v1/secrets", json={"SERPAPI_KEY": "abc123"}).json()
    assert r["SERPAPI_KEY"] is True
    assert "abc123" not in client.get("/api/v1/secrets").text
    assert client.put("/api/v1/secrets", json={"PATH": "x"}).status_code == 400


def _fake_provider(query, ctx):
    yield {"name": "Acme GmbH", "website": "https://www.acme.de/", "rating": 4.5, "reviews": 20, "sponsored": False, "closed": False}
    yield {"name": "Ad Corp", "website": "https://ad.de", "sponsored": True}
    yield {"name": "No Site", "website": None}


def test_job_end_to_end(client, monkeypatch):
    monkeypatch.setitem(PROVIDERS, "selenium_maps", _fake_provider)
    monkeypatch.setattr(crawler, "crawl_site", lambda url, cfg, log, stop: ({"jobs@acme.de": "/karriere", "noreply@acme.de": "/"}, ["/", "/karriere"]))
    client.put("/api/v1/config", json={"providers": {"nominatim": {"enabled": False}}})
    job = client.post("/api/v1/jobs", json={"source": "selenium_maps", "search": {"keywords": ["software"], "locations": ["Mitte"], "city": "Berlin"}}).json()
    for _ in range(50):
        j = client.get(f"/api/v1/jobs/{job['id']}").json()
        if j["status"] == "done":
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    assert (j["listings"], j["websites"], j["emails_kept"], j["emails_filtered"]) == (3, 1, 1, 1)

    leads = client.get("/api/v1/leads?has_email=true").json()
    assert leads["total"] == 1 and leads["items"][0]["email"] == "jobs@acme.de"
    lead = client.get(f"/api/v1/leads/{leads['items'][0]['id']}").json()
    assert {e["email"]: e["kept"] for e in lead["emails"]} == {"jobs@acme.de": 1, "noreply@acme.de": 0}
    assert "jobs@acme.de" in client.get("/api/v1/leads/export?format=csv").text
    assert any("Skipped sponsored" in l["message"] for l in client.get(f"/api/v1/jobs/{job['id']}/logs").json())

    # Dry-run campaign logs but does not mark the lead as sent.
    tpl = client.get("/api/v1/templates").json()[0]
    camp = client.post("/api/v1/outreach/campaigns", json={"template_id": tpl["id"], "lead_ids": [lead["id"]], "dry_run": True}).json()
    for _ in range(30):
        if client.get("/api/v1/outreach/campaigns").json()[0]["status"] == "done":
            break
        time.sleep(0.1)
    sent = client.get("/api/v1/outreach/sent").json()
    assert sent[0]["result"] == "dry-run" and camp["recipients"] == 1
    assert client.get(f"/api/v1/leads/{lead['id']}").json()["status"] == "new"


def test_scrape_fills_in_imported_lead(client, monkeypatch):
    db.execute("INSERT INTO leads (name, domain, website, source, created_at, updated_at) VALUES "
               "('acme.de','acme.de','https://acme.de','import','x','x')")
    monkeypatch.setitem(PROVIDERS, "selenium_maps", _fake_provider)
    monkeypatch.setattr(crawler, "crawl_site", lambda *a: ({}, ["/"]))
    client.put("/api/v1/config", json={"providers": {"nominatim": {"enabled": False}}})
    job = client.post("/api/v1/jobs", json={"search": {"keywords": ["it"], "locations": ["Mitte"], "city": "Berlin",
                                                       "skip_tracked_websites": False}}).json()
    for _ in range(50):
        if client.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "done":
            break
        time.sleep(0.1)
    lead = db.row("SELECT * FROM leads WHERE domain='acme.de'")
    assert (lead["name"], lead["district"], lead["rating"], lead["job_id"]) == ("Acme GmbH", "Mitte", 4.5, job["id"])


def test_reapply_drops_text_fragments():
    assert filters.check_email("year@lums.with", FILTERS)[1] == 10
    assert filters.check_email("more@www.ness.com", FILTERS)[1] == 10


def test_stop_and_resume(client, monkeypatch):
    def slow(query, ctx):
        for i in range(100):
            if ctx.should_stop():
                return
            time.sleep(0.02)
            yield {"name": f"X{i}", "website": None}
    monkeypatch.setitem(PROVIDERS, "selenium_maps", slow)
    client.put("/api/v1/config", json={"providers": {"nominatim": {"enabled": False}}})
    job = client.post("/api/v1/jobs", json={"search": {"keywords": ["a", "b"], "locations": [], "city": "Berlin"}}).json()
    time.sleep(0.2)
    assert client.post(f"/api/v1/jobs/{job['id']}/stop").status_code == 200
    for _ in range(50):
        if client.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "stopped":
            break
        time.sleep(0.1)
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "stopped"


def test_attachment_upload_rejects_bad_names(client):
    assert client.post("/api/v1/attachments?name=cv.pdf", content=b"%PDF").status_code == 200
    assert client.post("/api/v1/attachments?name=evil.exe", content=b"x").status_code == 400
    assert client.get("/api/v1/attachments").json()[0]["name"] == "cv.pdf"
