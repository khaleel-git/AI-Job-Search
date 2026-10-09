"""Outreach campaigns: render templates per lead, pace sends, respect the window and daily cap.

Port of email_sender.py, with dry-run as the default so nothing leaves the machine by accident.
"""
import json
import os
import random
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

from . import db, filters, secrets_store
from .config import ATTACHMENTS_DIR
from .providers import api_providers


def pick_email(lead_id, priority):
    emails = db.rows("SELECT email FROM emails WHERE lead_id=? AND kept=1", (lead_id,))
    if not emails:
        return None
    return sorted((e["email"] for e in emails), key=lambda e: (filters.priority_rank(e, priority), e))[0]


def render(template, lead, email, sender_name):
    fn = filters.first_name(email or "")
    values = {
        "company": lead.get("name") or "", "district": lead.get("district") or "",
        "website": lead.get("domain") or "", "first_name": fn, "first_name_sp": f" {fn}" if fn else "",
        "sender_name": sender_name or "",
    }

    def fill(text):
        for k, v in values.items():
            text = text.replace("{" + k + "}", v)
        return text

    return fill(template["subject"]), fill(template["body"])


def build_message(sender, sender_name, to, subject, body, attachments):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender}>" if sender_name else sender
    msg["To"] = to
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body, "plain", "utf-8"))
    html = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n"))
    alt.attach(MIMEText(f"<html><body>{html}</body></html>", "html", "utf-8"))
    msg.attach(alt)
    for name in attachments:
        path = os.path.join(ATTACHMENTS_DIR, os.path.basename(name))
        if not os.path.exists(path):
            continue
        part = MIMEBase("application", "octet-stream")
        with open(path, "rb") as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(name)}"')
        msg.attach(part)
    return msg


def smtp_connect(cfg):
    sender, password = secrets_store.get("SENDER_EMAIL"), secrets_store.get("APP_PASSWORD").replace(" ", "")
    if not sender or not password:
        raise RuntimeError("SENDER_EMAIL and APP_PASSWORD are not set (Outreach → SMTP account).")
    server = smtplib.SMTP_SSL(cfg.get("smtp_host", "smtp.gmail.com"), int(cfg.get("smtp_port", 465)),
                              context=ssl.create_default_context(), timeout=30)
    server.login(sender, password)
    return server


def in_window(cfg, now=None):
    now = now or datetime.now()
    if cfg.get("weekdays_only") and now.weekday() >= 5:
        return False
    hhmm = now.strftime("%H:%M")
    return cfg.get("window_start", "00:00") <= hhmm <= cfg.get("window_end", "23:59")


def sent_today():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return db.row("SELECT COUNT(*) n FROM sent_log WHERE result='sent' AND dry_run=0 AND ts LIKE ?",
                  (today + "%",))["n"]


def plan_recipients(lead_ids, settings):
    """Resolve leads → (lead, email) pairs, applying sent-log and one-per-domain rules."""
    priority = settings["filters"].get("priority", [])
    already = {r["email"] for r in db.rows("SELECT email FROM sent_log WHERE result='sent' AND dry_run=0")}
    out, skipped, domains = [], [], set()
    for lid in lead_ids:
        lead = db.row("SELECT * FROM leads WHERE id=?", (lid,))
        if not lead or lead["excluded"]:
            continue
        email = pick_email(lid, priority)
        if not email:
            skipped.append((lid, "no kept email"))
            continue
        if email in already:
            skipped.append((lid, "already emailed"))
            continue
        if settings["outreach"].get("one_per_domain", True):
            if lead["domain"] in domains:
                skipped.append((lid, "domain already in campaign"))
                continue
            domains.add(lead["domain"])
        out.append((lead, email))
    return out, skipped


class Campaign(threading.Thread):
    def __init__(self, campaign_id, template, recipients, settings, dry_run):
        super().__init__(daemon=True, name=f"campaign-{campaign_id}")
        self.cid, self.template, self.recipients = campaign_id, template, recipients
        self.cfg, self.dry_run = settings["outreach"], dry_run
        self.stop_event = threading.Event()

    def _sleep(self, seconds):
        self.stop_event.wait(seconds)

    def run(self):
        server = None
        sender_name = self.cfg.get("sender_name") or secrets_store.get("SENDER_NAME")
        try:
            if not self.dry_run:
                server = smtp_connect(self.cfg)
            for i, (lead, email) in enumerate(self.recipients):
                if self.stop_event.is_set():
                    break
                while not self.dry_run and not in_window(self.cfg) and not self.stop_event.is_set():
                    self._sleep(60)
                if not self.dry_run and sent_today() >= int(self.cfg.get("daily_cap", 60)):
                    db.execute("UPDATE campaigns SET status='paused (daily cap)' WHERE id=?", (self.cid,))
                    while sent_today() >= int(self.cfg.get("daily_cap", 60)) and not self.stop_event.is_set():
                        self._sleep(300)
                    db.execute("UPDATE campaigns SET status='running' WHERE id=?", (self.cid,))
                result, error = self._send_one(server, lead, email, sender_name)
                if result == "reconnect":
                    server = smtp_connect(self.cfg)
                    result, error = self._send_one(server, lead, email, sender_name)
                col = "sent" if result in ("sent", "dry-run") else "failed"
                db.execute(f"UPDATE campaigns SET {col} = {col} + 1 WHERE id=?", (self.cid,))
                db.execute("INSERT INTO sent_log (campaign_id, lead_id, email, template, result, error, dry_run, ts) "
                           "VALUES (?,?,?,?,?,?,?,?)", (self.cid, lead["id"], email, self.template["name"],
                                                        result, error, 1 if self.dry_run else 0, db.now()))
                if result == "sent":
                    db.execute("UPDATE leads SET status='sent', updated_at=? WHERE id=?", (db.now(), lead["id"]))
                elif result == "bounced":
                    db.execute("UPDATE leads SET status='bounced', updated_at=? WHERE id=?", (db.now(), lead["id"]))
                if i < len(self.recipients) - 1 and not self.dry_run:
                    self._sleep(random.uniform(float(self.cfg.get("delay_min", 120)), float(self.cfg.get("delay_max", 240))))
            status = "stopped" if self.stop_event.is_set() else "done"
            db.execute("UPDATE campaigns SET status=?, finished_at=? WHERE id=?", (status, db.now(), self.cid))
        except Exception as e:
            db.execute("UPDATE campaigns SET status=?, finished_at=? WHERE id=?",
                       (f"failed: {type(e).__name__}: {e}"[:200], db.now(), self.cid))
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass
            campaigns.pop(self.cid, None)

    def _send_one(self, server, lead, email, sender_name):
        if self.cfg.get("verify_hunter"):
            try:
                if api_providers.hunter_verify(email) == "invalid":
                    return "bounced", "Hunter: invalid"
            except Exception:
                pass
        subject, body = render(self.template, lead, email, sender_name)
        if self.dry_run:
            return "dry-run", None
        msg = build_message(secrets_store.get("SENDER_EMAIL"), sender_name, email, subject, body,
                            json.loads(self.template.get("attachments") or "[]"))
        try:
            server.sendmail(secrets_store.get("SENDER_EMAIL"), [email], msg.as_string())
            return "sent", None
        except smtplib.SMTPRecipientsRefused as e:
            return "bounced", str(e)[:200]
        except (smtplib.SMTPServerDisconnected, OSError):
            return "reconnect", None
        except smtplib.SMTPException as e:
            return "failed", str(e)[:200]


campaigns = {}


def launch(template_id, lead_ids, settings, dry_run):
    template = db.row("SELECT * FROM templates WHERE id=?", (template_id,))
    if not template:
        raise ValueError("Template not found")
    recipients, skipped = plan_recipients(lead_ids, settings)
    if not recipients:
        raise ValueError("No sendable recipients (" + ", ".join(sorted({r for _, r in skipped})) + ")")
    cid = db.execute("INSERT INTO campaigns (template_id, status, dry_run, total, created_at) VALUES (?,?,?,?,?)",
                     (template_id, "running", 1 if dry_run else 0, len(recipients), db.now()))
    if not dry_run:
        ids = [lead["id"] for lead, _ in recipients]
        db.execute(f"UPDATE leads SET status='queued' WHERE id IN ({','.join('?' * len(ids))})", ids)
    c = Campaign(cid, template, recipients, settings, dry_run)
    campaigns[cid] = c
    c.start()
    return cid, len(recipients), len(skipped)


def send_test(template_id, lead_id, settings):
    template = db.row("SELECT * FROM templates WHERE id=?", (template_id,))
    lead = db.row("SELECT * FROM leads WHERE id=?", (lead_id,)) if lead_id else {"name": "Example GmbH", "district": "Mitte", "domain": "example.de"}
    me = secrets_store.get("SENDER_EMAIL")
    sender_name = settings["outreach"].get("sender_name") or secrets_store.get("SENDER_NAME")
    email = pick_email(lead_id, settings["filters"]["priority"]) if lead_id else ""
    subject, body = render(template, lead, email or "", sender_name)
    server = smtp_connect(settings["outreach"])
    try:
        msg = build_message(me, sender_name, me, "[TEST] " + subject, body, json.loads(template.get("attachments") or "[]"))
        server.sendmail(me, [me], msg.as_string())
    finally:
        server.quit()
    return me
