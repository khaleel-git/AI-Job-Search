"""MapLeads web app: FastAPI backend + static UI. Run with ``python -m webapp`` from Google-Map/."""
import asyncio
import csv
import io
import json
import os
import re
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, filters, jobs, outreach, secrets_store
from .providers import CATALOG, PROVIDERS, api_providers

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
API = "/api/v1"

@asynccontextmanager
async def lifespan(_):
    db.init()
    jobs.manager.recover()
    os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
    yield


app = FastAPI(title="MapLeads", version="1.0", lifespan=lifespan)


@app.exception_handler(ValueError)
async def value_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(api_providers.ProviderError)
async def provider_error(_, exc):
    return JSONResponse({"detail": str(exc)}, status_code=502)


def _404(what):
    raise HTTPException(404, f"{what} not found")


# ---------- dashboard ----------
@app.get(API + "/stats")
def stats():
    one = lambda sql, p=(): db.row(sql, p)["n"]  # noqa: E731
    per_day = db.rows("SELECT substr(created_at,1,10) d, COUNT(*) n FROM leads "
                      "WHERE created_at >= date('now','-13 days') GROUP BY d ORDER BY d")
    districts = db.rows("SELECT l.district, COUNT(DISTINCT e.email) n FROM emails e JOIN leads l ON l.id=e.lead_id "
                        "WHERE e.kept=1 AND l.district IS NOT NULL GROUP BY l.district ORDER BY n DESC LIMIT 6")
    return {
        "leads": one("SELECT COUNT(*) n FROM leads"),
        "listings": one("SELECT COALESCE(SUM(listings),0) n FROM jobs"),
        "websites": one("SELECT COUNT(*) n FROM leads WHERE domain IS NOT NULL"),
        "emails_found": one("SELECT COUNT(*) n FROM emails"),
        "emails_kept": one("SELECT COUNT(*) n FROM emails WHERE kept=1"),
        "leads_with_email": one("SELECT COUNT(DISTINCT lead_id) n FROM emails WHERE kept=1"),
        "sent": one("SELECT COUNT(*) n FROM sent_log WHERE result='sent' AND dry_run=0"),
        "replied": one("SELECT COUNT(*) n FROM leads WHERE status='replied'"),
        "per_day": per_day,
        "districts": districts,
        "jobs": db.rows("SELECT id, name, source, status, emails_kept, created_at FROM jobs ORDER BY id DESC LIMIT 6"),
    }


# ---------- settings ----------
@app.get(API + "/config")
def get_config():
    return db.get_settings()


@app.put(API + "/config")
def put_config(data: dict = Body(...)):
    merged = config.deep_merge(db.get_settings(), data)
    db.save_settings(merged)
    return merged


@app.post(API + "/config/reset")
def reset_config(section: str = None):
    current = db.get_settings()
    defaults = config.default_config()
    if section:
        if section not in defaults:
            raise ValueError(f"Unknown section {section}")
        current[section] = defaults[section]
    else:
        current = defaults
    db.save_settings(current)
    return current


# ---------- email filters ----------
@app.get(API + "/filters/email")
def filter_layers():
    counts = {r["layer"]: r["n"] for r in db.rows("SELECT layer, COUNT(*) n FROM emails WHERE kept=0 GROUP BY layer")}
    f = db.get_settings()["filters"]
    return {"layers": [{"n": n, "name": name, "list": filters.LAYER_LISTS.get(n),
                        "rules": len(f["lists"].get(filters.LAYER_LISTS.get(n), [])) if n in filters.LAYER_LISTS else None,
                        "enabled": f["layers"].get(str(n), True), "blocked": counts.get(n, 0)}
                       for n, name in filters.LAYER_NAMES.items()],
            "lists": f["lists"], "priority": f["priority"]}


@app.post(API + "/filters/test")
def filter_test(payload: dict = Body(...)):
    f = db.get_settings()["filters"]
    out = []
    for raw in payload.get("emails", [])[:500]:
        email, layer, reason = filters.check_email(raw, f)
        out.append({"input": raw, "kept": bool(email), "email": email, "layer": layer, "reason": reason})
    return out


@app.post(API + "/filters/reapply")
def filter_reapply():
    """Re-run current rules over every stored address (after editing lists)."""
    f = db.get_settings()["filters"]
    changed = 0
    for e in db.rows("SELECT e.id, e.email, e.kept, l.domain FROM emails e LEFT JOIN leads l ON l.id=e.lead_id"):
        email, layer, reason = filters.check_email(e["email"], f, e["domain"])
        kept = 1 if email else 0
        if kept != e["kept"]:
            changed += 1
        db.execute("UPDATE emails SET kept=?, layer=?, reason=? WHERE id=?", (kept, layer, reason, e["id"]))
    return {"changed": changed}


# ---------- jobs ----------
def _job_view(j):
    j = dict(j)
    queries = json.loads(j.pop("queries") or "[]")
    cfg = json.loads(j.pop("config") or "{}")
    j["queries"] = [q["q"] for q in queries]
    j["districts"] = [q["district"] for q in queries]
    j["total_queries"] = len(queries)
    j["search"] = cfg.get("search", {})
    j["live"] = jobs.manager.is_live(j["id"])
    return j


@app.post(API + "/jobs")
def create_job(payload: dict = Body(...)):
    settings = db.get_settings()
    cfg = config.deep_merge(settings, {"search": payload.get("search", {})})
    source = payload.get("source", "selenium_maps")
    name = payload.get("name") or f"{', '.join(cfg['search']['keywords'][:2])} × {len(cfg['search']['locations']) or 1} locations"
    job_id = jobs.manager.create(name, source, cfg)
    if payload.get("start", True):
        try:
            jobs.manager.start(job_id)
        except RuntimeError as e:
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
            raise HTTPException(409, str(e))
    return _job_view(db.row("SELECT * FROM jobs WHERE id=?", (job_id,)))


@app.get(API + "/jobs")
def list_jobs():
    return [_job_view(j) for j in db.rows("SELECT * FROM jobs ORDER BY id DESC LIMIT 100")]


@app.get(API + "/jobs/{job_id}")
def get_job(job_id: int):
    j = db.row("SELECT * FROM jobs WHERE id=?", (job_id,)) or _404("Job")
    return _job_view(j)


@app.post(API + "/jobs/{job_id}/{action}")
def job_action(job_id: int, action: str):
    j = db.row("SELECT * FROM jobs WHERE id=?", (job_id,)) or _404("Job")
    if action == "pause":
        jobs.manager.pause(job_id, True)
    elif action == "resume":
        if jobs.manager.is_live(job_id):
            jobs.manager.pause(job_id, False)
        elif j["status"] in ("stopped", "interrupted", "failed", "queued"):
            try:
                jobs.manager.start(job_id)
            except RuntimeError as e:
                raise HTTPException(409, str(e))
        else:
            raise ValueError(f"Job is {j['status']}")
    elif action == "stop":
        jobs.manager.stop(job_id)
    else:
        _404("Action")
    return get_job(job_id)


@app.delete(API + "/jobs/{job_id}")
def delete_job(job_id: int):
    if jobs.manager.is_live(job_id):
        raise HTTPException(409, "Stop the job first")
    db.execute("DELETE FROM job_logs WHERE job_id=?", (job_id,))
    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return {"ok": True}


@app.get(API + "/jobs/{job_id}/logs")
def job_logs(job_id: int, after: int = 0, limit: int = 500):
    return db.rows("SELECT id, ts, level, message FROM job_logs WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
                   (job_id, after, min(limit, 2000)))


@app.get(API + "/jobs/{job_id}/stream")
async def job_stream(job_id: int, request: Request, after: int = 0):
    """Server-sent events: log lines plus a job snapshot whenever something changes."""
    async def events():
        last = after
        while not await request.is_disconnected():
            logs = db.rows("SELECT id, ts, level, message FROM job_logs WHERE job_id=? AND id>? ORDER BY id LIMIT 500",
                           (job_id, last))
            job = db.row("SELECT * FROM jobs WHERE id=?", (job_id,))
            if not job:
                return
            if logs:
                last = logs[-1]["id"]
            yield f"data: {json.dumps({'logs': logs, 'job': _job_view(job)})}\n\n"
            if job["status"] not in ("running", "paused", "queued") and not jobs.manager.is_live(job_id) and not logs:
                return
            await asyncio.sleep(1)
    return StreamingResponse(events(), media_type="text/event-stream")


# ---------- leads ----------
LEAD_SORT = {"name", "district", "rating", "reviews", "status", "created_at"}


def _lead_where(q=None, district=None, status=None, type=None, has_email=False, job_id=None, include_excluded=False):
    where, params = [], []
    if not include_excluded:
        where.append("l.excluded=0")
    if q:
        where.append("(l.name LIKE ? OR l.domain LIKE ? OR EXISTS (SELECT 1 FROM emails e WHERE e.lead_id=l.id AND e.email LIKE ?))")
        params += [f"%{q}%"] * 3
    if district:
        where.append("l.district=?")
        params.append(district)
    if status:
        where.append("l.status=?")
        params.append(status)
    if job_id:
        where.append("l.job_id=?")
        params.append(job_id)
    if has_email or type:
        sub = "EXISTS (SELECT 1 FROM emails e WHERE e.lead_id=l.id AND e.kept=1"
        if type:
            sub += " AND e.type=?"
            params.append(type)
        where.append(sub + ")")
    return ("WHERE " + " AND ".join(where)) if where else "", params


def _attach_best_email(leads):
    priority = db.get_settings()["filters"]["priority"]
    for l in leads:
        best = outreach.pick_email(l["id"], priority)
        l["email"] = best
        l["email_type"] = filters.email_type(best) if best else None
        l["found_on"] = db.row("SELECT found_on FROM emails WHERE lead_id=? AND email=?", (l["id"], best))["found_on"] if best else None
        l["tags"] = json.loads(l.get("tags") or "[]")
    return leads


@app.get(API + "/leads")
def list_leads(q: str = None, district: str = None, status: str = None, type: str = None,
               has_email: bool = False, job_id: int = None, sort: str = "created_at", order: str = "desc",
               page: int = 1, size: int = 50, include_excluded: bool = False):
    where, params = _lead_where(q, district, status, type, has_email, job_id, include_excluded)
    sort = sort if sort in LEAD_SORT else "created_at"
    direction = "ASC" if order == "asc" else "DESC"
    size = max(1, min(size, 500))
    total = db.row(f"SELECT COUNT(*) n FROM leads l {where}", params)["n"]
    items = db.rows(f"SELECT l.* FROM leads l {where} ORDER BY l.{sort} {direction}, l.id DESC LIMIT ? OFFSET ?",
                    (*params, size, (max(page, 1) - 1) * size))
    districts = [r["district"] for r in db.rows("SELECT DISTINCT district FROM leads WHERE district IS NOT NULL ORDER BY district")]
    return {"total": total, "page": page, "size": size, "items": _attach_best_email(items), "districts": districts}


@app.get(API + "/leads/export")
def export_leads(format: str = "csv", q: str = None, district: str = None, status: str = None,
                 type: str = None, has_email: bool = False):
    where, params = _lead_where(q, district, status, type, has_email)
    items = _attach_best_email(db.rows(f"SELECT l.* FROM leads l {where} ORDER BY l.name", params))
    cols = ["name", "domain", "website", "email", "email_type", "district", "address", "phone",
            "rating", "reviews", "category", "status", "source", "maps_url", "created_at"]
    if format == "json":
        return Response(json.dumps([{c: i.get(c) for c in cols} for i in items], ensure_ascii=False, indent=1),
                        media_type="application/json",
                        headers={"Content-Disposition": "attachment; filename=leads.json"})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for i in items:
        w.writerow([i.get(c) if i.get(c) is not None else "" for c in cols])
    # BOM so Excel opens umlauts correctly.
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=leads.csv"})


@app.get(API + "/leads/{lead_id}")
def get_lead(lead_id: int):
    lead = db.row("SELECT * FROM leads WHERE id=?", (lead_id,)) or _404("Lead")
    _attach_best_email([lead])
    lead["pages_crawled"] = json.loads(lead.get("pages_crawled") or "[]")
    lead["emails"] = db.rows("SELECT email, kept, layer, reason, found_on, type FROM emails WHERE lead_id=? ORDER BY kept DESC, email", (lead_id,))
    lead["sent"] = db.rows("SELECT email, template, result, dry_run, ts FROM sent_log WHERE lead_id=? ORDER BY id DESC", (lead_id,))
    return lead


@app.patch(API + "/leads/{lead_id}")
def patch_lead(lead_id: int, payload: dict = Body(...)):
    db.row("SELECT 1 FROM leads WHERE id=?", (lead_id,)) or _404("Lead")
    allowed = {"status", "notes", "tags", "excluded", "name"}
    sets, params = [], []
    for k, v in payload.items():
        if k not in allowed:
            continue
        if k == "status" and v not in ("new", "queued", "sent", "replied", "bounced", "rejected"):
            raise ValueError("Invalid status")
        sets.append(f"{k}=?")
        params.append(json.dumps(v) if k == "tags" else (1 if v else 0) if k == "excluded" else v)
    if sets:
        db.execute(f"UPDATE leads SET {', '.join(sets)}, updated_at=? WHERE id=?", (*params, db.now(), lead_id))
    if payload.get("block_domain"):
        lead = db.row("SELECT domain FROM leads WHERE id=?", (lead_id,))
        s = db.get_settings()
        if lead["domain"] and lead["domain"] not in s["filters"]["lists"]["domains"]:
            s["filters"]["lists"]["domains"].append(lead["domain"])
            db.save_settings(s)
    return get_lead(lead_id)


@app.post(API + "/leads/bulk")
def bulk_leads(payload: dict = Body(...)):
    ids = [int(i) for i in payload.get("ids", [])][:5000]
    if not ids:
        raise ValueError("No leads selected")
    marks = ",".join("?" * len(ids))
    action = payload.get("action")
    if action == "delete":
        db.execute(f"DELETE FROM emails WHERE lead_id IN ({marks})", ids)
        db.execute(f"DELETE FROM leads WHERE id IN ({marks})", ids)
    elif action == "status":
        if payload.get("status") not in ("new", "queued", "sent", "replied", "bounced", "rejected"):
            raise ValueError("Invalid status")
        db.execute(f"UPDATE leads SET status=? WHERE id IN ({marks})", (payload["status"], *ids))
    elif action == "exclude":
        db.execute(f"UPDATE leads SET excluded=1 WHERE id IN ({marks})", ids)
    else:
        raise ValueError("Unknown action")
    return {"ok": True, "count": len(ids)}


@app.post(API + "/leads/{lead_id}/recrawl")
def recrawl_lead(lead_id: int):
    lead = db.row("SELECT * FROM leads WHERE id=?", (lead_id,)) or _404("Lead")
    if not lead["website"] and not lead["domain"]:
        raise ValueError("Lead has no website")
    lines = []
    kept, dropped = jobs.enrich_lead(lead_id, lead["website"] or f"https://{lead['domain']}", lead["domain"],
                                     db.get_settings(), lambda lvl, m: lines.append(m), lambda: False)
    return {"kept": kept, "filtered": dropped, "log": lines, "lead": get_lead(lead_id)}


@app.post(API + "/leads/import")
def import_tracked():
    """Import the CLI scraper's tracked_websites.txt / tracked_emails.txt."""
    added_sites = added_emails = 0
    f = db.get_settings()["filters"]
    sites = os.path.join(config.GOOGLE_MAP_DIR, "tracked_websites.txt")
    if os.path.exists(sites):
        with open(sites, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                d = jobs.domain_of(line.strip()) if line.strip() else ""
                if d and "." in d:
                    before = db.row("SELECT 1 FROM leads WHERE domain=?", (d,))
                    if not before:
                        db.execute("INSERT INTO leads (name, domain, website, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                                   (d, d, f"https://{d}", "import", db.now(), db.now()))
                        added_sites += 1
    mails = os.path.join(config.GOOGLE_MAP_DIR, "tracked_emails.txt")
    if os.path.exists(mails):
        with open(mails, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                email, layer, reason = filters.check_email(line.strip(), f)
                if not email:
                    continue
                d = email.split("@", 1)[1]
                lead = db.row("SELECT id FROM leads WHERE domain=?", (d,))
                lid = lead["id"] if lead else db.execute(
                    "INSERT INTO leads (name, domain, website, source, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (d, d, f"https://{d}", "import", db.now(), db.now()))
                db.execute("INSERT OR IGNORE INTO emails (lead_id, email, kept, layer, reason, found_on, type, created_at) "
                           "VALUES (?,?,1,0,'kept','import',?,?)", (lid, email, filters.email_type(email), db.now()))
                added_emails += 1
    return {"websites": added_sites, "emails": added_emails}


# ---------- outreach ----------
@app.get(API + "/templates")
def list_templates():
    out = db.rows("SELECT * FROM templates ORDER BY id")
    for t in out:
        t["attachments"] = json.loads(t["attachments"] or "[]")
    return out


@app.post(API + "/templates")
def create_template(payload: dict = Body(...)):
    tid = db.execute("INSERT INTO templates (name, subject, body, attachments, updated_at) VALUES (?,?,?,?,?)",
                     (payload.get("name") or "Untitled", payload.get("subject", ""), payload.get("body", ""),
                      json.dumps(payload.get("attachments", [])), db.now()))
    return db.row("SELECT * FROM templates WHERE id=?", (tid,))


@app.put(API + "/templates/{tid}")
def update_template(tid: int, payload: dict = Body(...)):
    db.row("SELECT 1 FROM templates WHERE id=?", (tid,)) or _404("Template")
    db.execute("UPDATE templates SET name=?, subject=?, body=?, attachments=?, updated_at=? WHERE id=?",
               (payload.get("name"), payload.get("subject"), payload.get("body"),
                json.dumps(payload.get("attachments", [])), db.now(), tid))
    return {"ok": True}


@app.delete(API + "/templates/{tid}")
def delete_template(tid: int):
    db.execute("DELETE FROM templates WHERE id=?", (tid,))
    return {"ok": True}


SAFE_NAME = re.compile(r"^[\w\-. ()äöüÄÖÜß]{1,120}$")


@app.get(API + "/attachments")
def list_attachments():
    os.makedirs(config.ATTACHMENTS_DIR, exist_ok=True)
    return [{"name": n, "size": os.path.getsize(os.path.join(config.ATTACHMENTS_DIR, n))}
            for n in sorted(os.listdir(config.ATTACHMENTS_DIR))]


@app.post(API + "/attachments")
async def upload_attachment(request: Request, name: str):
    name = os.path.basename(name)
    if not SAFE_NAME.match(name) or not name.lower().endswith((".pdf", ".docx", ".doc", ".png", ".jpg", ".txt")):
        raise ValueError("Allowed: pdf, doc(x), png, jpg, txt with a simple file name")
    data = await request.body()
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Max 10 MB")
    with open(os.path.join(config.ATTACHMENTS_DIR, name), "wb") as f:
        f.write(data)
    return {"name": name, "size": len(data)}


@app.delete(API + "/attachments/{name}")
def delete_attachment(name: str):
    path = os.path.join(config.ATTACHMENTS_DIR, os.path.basename(name))
    if os.path.exists(path):
        os.remove(path)
    return {"ok": True}


@app.post(API + "/outreach/preview")
def preview(payload: dict = Body(...)):
    settings = db.get_settings()
    lead = db.row("SELECT * FROM leads WHERE id=?", (payload.get("lead_id"),)) if payload.get("lead_id") else None
    lead = lead or {"name": "Example GmbH", "district": "Mitte", "domain": "example.de", "id": 0}
    email = outreach.pick_email(lead["id"], settings["filters"]["priority"]) if lead.get("id") else "anna.schmidt@example.de"
    sender = settings["outreach"].get("sender_name") or secrets_store.get("SENDER_NAME")
    subject, body = outreach.render({"subject": payload.get("subject", ""), "body": payload.get("body", "")},
                                    lead, email or "", sender)
    return {"to": email, "subject": subject, "body": body}


@app.post(API + "/outreach/plan")
def plan(payload: dict = Body(...)):
    recipients, skipped = outreach.plan_recipients(payload.get("lead_ids", []), db.get_settings())
    return {"count": len(recipients), "skipped": len(skipped),
            "recipients": [{"lead_id": l["id"], "name": l["name"], "email": e} for l, e in recipients[:200]]}


@app.post(API + "/outreach/campaigns")
def create_campaign(payload: dict = Body(...)):
    settings = db.get_settings()
    dry = payload.get("dry_run", settings["outreach"].get("dry_run", True))
    cid, n, skipped = outreach.launch(payload["template_id"], payload.get("lead_ids", []), settings, bool(dry))
    return {"id": cid, "recipients": n, "skipped": skipped, "dry_run": bool(dry)}


@app.get(API + "/outreach/campaigns")
def list_campaigns():
    return db.rows("SELECT c.*, t.name template FROM campaigns c LEFT JOIN templates t ON t.id=c.template_id ORDER BY c.id DESC LIMIT 50")


@app.post(API + "/outreach/campaigns/{cid}/stop")
def stop_campaign(cid: int):
    c = outreach.campaigns.get(cid)
    if c:
        c.stop_event.set()
    return {"ok": True}


@app.get(API + "/outreach/sent")
def sent_log(limit: int = 200):
    return db.rows("SELECT s.*, l.name company FROM sent_log s LEFT JOIN leads l ON l.id=s.lead_id ORDER BY s.id DESC LIMIT ?",
                   (min(limit, 1000),))


@app.post(API + "/outreach/test-smtp")
def test_smtp():
    try:
        outreach.smtp_connect(db.get_settings()["outreach"]).quit()
    except Exception as e:
        raise HTTPException(400, f"SMTP login failed: {e}")
    return {"ok": True}


@app.post(API + "/outreach/send-test")
def send_test(payload: dict = Body(...)):
    try:
        to = outreach.send_test(payload["template_id"], payload.get("lead_id"), db.get_settings())
    except Exception as e:
        raise HTTPException(400, f"Test send failed: {e}")
    return {"sent_to": to}


@app.get(API + "/secrets")
def secrets_status():
    return secrets_store.status()


@app.put(API + "/secrets")
def put_secrets(payload: dict = Body(...)):
    for k, v in payload.items():
        secrets_store.set_value(k, v)
    return secrets_store.status()


# ---------- providers / geo ----------
@app.get(API + "/providers")
def providers():
    settings = db.get_settings()["providers"]
    return [{**p, "enabled": settings.get(p["id"], {}).get("enabled", False),
             "key_set": secrets_store.is_set(p["secret"]) if p["secret"] else None,
             "can_discover": p["id"] in PROVIDERS} for p in CATALOG]


@app.put(API + "/providers/{pid}")
def put_provider(pid: str, payload: dict = Body(...)):
    entry = next((p for p in CATALOG if p["id"] == pid), None) or _404("Provider")
    if "key" in payload and entry["secret"]:
        secrets_store.set_value(entry["secret"], payload["key"])
    if "enabled" in payload:
        s = db.get_settings()
        s["providers"].setdefault(pid, {})["enabled"] = bool(payload["enabled"])
        db.save_settings(s)
    return providers()


@app.post(API + "/providers/{pid}/test")
def test_provider(pid: str):
    api_providers.test_key(pid)
    return {"ok": True}


@app.get(API + "/geo/districts")
def districts(city: str):
    names = api_providers.suggest_districts(city)
    if not names:
        raise ValueError(f"No districts found for {city}")
    return {"city": city, "districts": names}


@app.get(API + "/geo/geocode")
def geocode(q: str):
    return api_providers.geocode(q) or _404("Place")


# ---------- presets ----------
@app.get(API + "/presets")
def list_presets():
    out = db.rows("SELECT * FROM presets ORDER BY is_default DESC, id")
    for p in out:
        p["search"] = json.loads(p["search"] or "{}")
    return out


@app.post(API + "/presets")
def create_preset(payload: dict = Body(...)):
    pid = db.execute("INSERT INTO presets (name, description, source, search, created_at) VALUES (?,?,?,?,?)",
                     (payload.get("name") or "Preset", payload.get("description", ""),
                      payload.get("source", "selenium_maps"), json.dumps(payload.get("search", {})), db.now()))
    return {"id": pid}


@app.delete(API + "/presets/{pid}")
def delete_preset(pid: int):
    db.execute("DELETE FROM presets WHERE id=?", (pid,))
    return {"ok": True}


# ---------- UI ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
