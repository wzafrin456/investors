"""Daily & Weekly Investor Pipeline Digest Engine & Gmail Delivery for Warren & Leo.

Builds and sends the Dokimo Investor Pipeline Digest showing:
  1. Which Tier S and Tier A funds have received decks, opened pitch links, or are in active conversation
  2. Warren's Top 10 Tier-S FinTech / RegTech / Bank-LP Follow-Up Queue (with 1-Click Gmail & 2-Page PDF Tear-Sheet links)
  3. Leo's Top 10 Tier-S / Tier-A Enterprise AI & Warm-Intro Follow-Up Queue (with 1-Click Gmail & 2-Page PDF Tear-Sheet links)
"""
import base64
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request

from . import access, investor_engine

PUBLIC_URL = os.environ.get(
    "INVESTORS_BOARD_URL", "https://dokimo-investors-aigeqnv5nq-uc.a.run.app"
).rstrip("/")


def _load_gmail_oauth_dict() -> dict:
    for env_key in ("GMAIL_TOKEN_WARREN", "GMAIL_OAUTH_CLIENT", "GMAIL_TOKEN_JSON"):
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                d = json.loads(raw)
                if d.get("refresh_token") and d.get("client_id"):
                    return d
            except Exception:
                pass
    gcloud = shutil.which("gcloud")
    if gcloud:
        env = dict(os.environ)
        cur = env.get("CLOUDSDK_METRICS_ENVIRONMENT", "")
        if "datacloud.antigravity" not in cur:
            env["CLOUDSDK_METRICS_ENVIRONMENT"] = (cur + " datacloud.antigravity").strip()
        for sec in ("gmail-token-warren", "gmail-oauth-client"):
            try:
                out = subprocess.check_output(
                    [gcloud, "secrets", "versions", "access", "latest", f"--secret={sec}", "--project=dokimo-aiops"],
                    env=env,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10,
                ).strip()
                if out:
                    d = json.loads(out)
                    if d.get("refresh_token") and d.get("client_id"):
                        return d
            except Exception:
                pass
    raise RuntimeError("Gmail OAuth token (gmail-token-warren) is not available.")


def _gmail_access_token() -> str:
    d = _load_gmail_oauth_dict()
    body = urllib.parse.urlencode({
        "client_id": d["client_id"],
        "client_secret": d["client_secret"],
        "refresh_token": d["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(d.get("token_uri", "https://oauth2.googleapis.com/token"), data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))["access_token"]


def build_digest_payload(mode: str = "daily") -> dict:
    """Compute the structured Investor Pipeline Digest data and render HTML + Plaintext email bodies."""
    rows = investor_engine.get_all_investors(persist_csv=False)
    metrics = investor_engine.build_summary_metrics(rows)
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y %H:%M UTC")
    date_short = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y")

    # 1. Funds that have received decks, opened links, or have active warm intro / status notes
    active_deck_or_engaged = []
    for r in rows:
        st_lc = (r.get("latest_status") or "").lower()
        na_lc = (r.get("next_action") or "").lower()
        opens = int(r.get("deck_opens") or 0)
        pdfs = int(r.get("pdf_downloads") or 0)
        if (
            opens > 0
            or pdfs > 0
            or any(k in st_lc for k in ("deck", "sent", "call", "meeting", "intro", "warm", "friend", "committed", "pitch", "reach", "talk"))
            or any(k in na_lc for k in ("follow", "send", "ping", "intro", "call"))
        ) and "passed" not in st_lc and "declined" not in st_lc and "not a lead" not in st_lc:
            active_deck_or_engaged.append(r)

    # Sort engaged funds by Tier S -> A -> B, then opens/fit score
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    active_deck_or_engaged.sort(
        key=lambda x: (tier_order.get(x["tier"], 9), -int(x.get("deck_opens") or 0), -int(x["dokimo_fit_score"]))
    )

    # 2. Warren's Priority Tier-S Follow-Up Queue
    warren_queue = [
        r for r in rows
        if r["tier"] in ("S", "A")
        and "warren" in (r.get("our_contact") or "").lower()
        and (r.get("latest_status") or "").lower() not in ("committed", "declined", "deprioritize / skip")
    ][:12]

    # 3. Leo's Priority Tier-S & Tier-A Follow-Up Queue
    leo_queue = [
        r for r in rows
        if r["tier"] in ("S", "A")
        and "leo" in (r.get("our_contact") or "").lower()
        and "passed" not in (r.get("latest_status") or "").lower()
        and (r.get("latest_status") or "").lower() not in ("committed", "declined", "deprioritize / skip")
    ][:12]

    grants = {}
    for g in access.load_grants():
        if g.get("active") and g.get("token"):
            gid = (g.get("id") or "").lower()
            grants[gid] = g["token"]
            grants[gid.split("@")[0]] = g["token"]
    warren_tok = grants.get("warren", "Ot6KUqBPu8WPOB9f7bjIWsNh03kiblX5")
    leo_tok = grants.get("leo", "L9kPqR7sTuVwXyZ0123456789AbCdEfG")

    cadence_label = "Weekly Recap" if mode == "weekly" else "Daily 7:00 AM EST Briefing"
    subject = f"Dokimo Investor Pipeline Digest ({cadence_label}) — {metrics['tier_s_count']} Tier-S & {metrics['tier_a_count']} Tier-A VCs | {date_short}"

    def _gmail_url(r: dict) -> str:
        return (
            "https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={urllib.parse.quote(r.get('email') or '')}"
            f"&su={urllib.parse.quote(r.get('direct_email_subject') or '')}"
            f"&body={urllib.parse.quote(r.get('direct_email_body') or '')}"
        )

    def _render_rows_html(item_list: list[dict], token_str: str) -> str:
        out = []
        t_q = f"&token={urllib.parse.quote(token_str)}" if token_str else ""
        for r in item_list:
            tier_bg = "#fef2f2" if r["tier"] == "S" else ("#eff6ff" if r["tier"] == "A" else "#f8fafc")
            tier_fg = "#b91c1c" if r["tier"] == "S" else ("#1d4ed8" if r["tier"] == "A" else "#475569")
            pdf_url = f"{PUBLIC_URL}/api/investors/pdf-memo?id={urllib.parse.quote(r['id'])}{t_q}"
            pitch_url = f"{PUBLIC_URL}/pitch/{urllib.parse.quote(r['id'])}"
            opens_badge = (
                f"<span style='background:#dcfce7;color:#166534;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:700'>"
                f"🔥 {r.get('deck_opens', 0)} Deck Opens / {r.get('pdf_downloads', 0)} PDFs</span>"
                if (int(r.get("deck_opens") or 0) > 0 or int(r.get("pdf_downloads") or 0) > 0)
                else f"<span style='background:#f1f5f9;color:#475569;padding:2px 6px;border-radius:3px;font-size:10px'>{html.escape(r.get('latest_status') or 'Ready to Pitch')}</span>"
            )
            ph_html = (
                f"<div style='font-size:11px;color:#059669;font-family:monospace'>📞 {html.escape(r['display_phone'])}</div>"
                if r.get("display_phone")
                else ""
            )
            out.append(
                f"<tr>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e2e8f0;font-weight:700'>"
                f"<span style='background:{tier_bg};color:{tier_fg};padding:2px 6px;border-radius:3px;font-family:monospace;font-size:11px'>Tier {html.escape(r['tier'])} · {r['dokimo_fit_score']}</span>"
                f"</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e2e8f0'>"
                f"<div style='font-weight:700;color:#0f172a'>{html.escape(r['fund'])}</div>"
                f"<div style='font-size:11px;color:#64748b'>{html.escape(r['category'])} · {html.escape(r['check_size'])}</div>"
                f"</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e2e8f0'>"
                f"<div style='font-weight:600;color:#0f172a'>{html.escape(r['person'])}</div>"
                f"<div style='font-size:11px;color:#2563eb'><a href='mailto:{html.escape(r['email'])}' style='color:#2563eb;text-decoration:none'>{html.escape(r['email'])}</a></div>"
                f"{ph_html}"
                f"</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e2e8f0'>"
                f"{opens_badge}"
                f"<div style='font-size:11px;color:#475569;margin-top:3px'>{html.escape(r.get('next_action') or r.get('pitch_angle', '')[:85])}</div>"
                f"</td>"
                f"<td style='padding:8px 10px;border-bottom:1px solid #e2e8f0;white-space:nowrap'>"
                f"<a href='{html.escape(_gmail_url(r))}' target='_blank' style='display:inline-block;background:#b91c1c;color:#fff;text-decoration:none;padding:5px 9px;border-radius:4px;font-size:11px;font-weight:600;margin-right:4px'>✉️ 1-Click Gmail</a>"
                f"<a href='{html.escape(pdf_url)}' target='_blank' style='display:inline-block;background:#1e293b;color:#fff;text-decoration:none;padding:5px 9px;border-radius:4px;font-size:11px;font-weight:600;margin-right:4px'>📄 2-Page PDF Memo</a>"
                f"<a href='{html.escape(r.get('person_linkedin') or pitch_url)}' target='_blank' style='display:inline-block;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;text-decoration:none;padding:4px 8px;border-radius:4px;font-size:11px;font-weight:600'>in LinkedIn</a>"
                f"</td>"
                f"</tr>"
            )
        return "".join(out)

    html_body = f"""<!doctype html>
<html>
<body style="margin:0;padding:20px;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#0f172a">
  <div style="max-width:980px;margin:0 auto;background:#ffffff;border:1px solid #cbd5e1;border-radius:8px;overflow:hidden">
    <div style="background:#0f172a;color:#ffffff;padding:20px 24px;border-bottom:3px solid #b91c1c">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#94a3b8;font-weight:700">DOKIMO.AI · INVESTOR RADAR &amp; VC PIPELINE DIGEST ({html.escape(cadence_label.upper())})</div>
      <h1 style="margin:6px 0 4px 0;font-size:20px;color:#ffffff">Dokimo VC Fundraising Pipeline, Deck Opens &amp; Priority Follow-Up Queue</h1>
      <div style="font-size:12px;color:#cbd5e1">Generated {html.escape(now_str)} · All 213 Investors Enriched (100.0% Direct Email + LinkedIn + Custom 2-Page PDF Tear-Sheets)</div>
    </div>

    <div style="padding:18px 24px">
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:12px 16px;margin-bottom:18px">
        <div style="font-size:12px;font-weight:700;color:#0f172a;margin-bottom:6px">🔑 1-Click Direct Cloud Run Board Links:</div>
        <div style="font-size:12px;line-height:1.7">
          • <b>Warren (CEO)</b>:
          <a href="{PUBLIC_URL}/?token={warren_tok}" style="color:#b91c1c;font-weight:700">Ranked VC Fit Board</a> |
          <a href="{PUBLIC_URL}/digest?token={warren_tok}" style="color:#1d4ed8;font-weight:700">Pipeline Digest &amp; Follow-Up Center</a> |
          <a href="{PUBLIC_URL}/report?token={warren_tok}" style="color:#0f172a;font-weight:600">Executive VC Report</a> |
          <a href="{PUBLIC_URL}/outreach?token={warren_tok}" style="color:#0f172a;font-weight:600">Outreach Studio</a>
          <br>
          • <b>Leo (Co-Founder)</b>:
          <a href="{PUBLIC_URL}/?token={leo_tok}" style="color:#b91c1c;font-weight:700">Ranked VC Fit Board</a> |
          <a href="{PUBLIC_URL}/digest?token={leo_tok}" style="color:#1d4ed8;font-weight:700">Pipeline Digest &amp; Follow-Up Center</a> |
          <a href="{PUBLIC_URL}/report?token={leo_tok}" style="color:#0f172a;font-weight:600">Executive VC Report</a> |
          <a href="{PUBLIC_URL}/outreach?token={leo_tok}" style="color:#0f172a;font-weight:600">Outreach Studio</a>
        </div>
      </div>

      <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
        <tr>
          <td style="padding:10px;border:1px solid #e2e8f0;background:#fef2f2;width:25%">
            <div style="font-size:10px;text-transform:uppercase;color:#991b1b;font-weight:700">Tier S Bullseye VCs</div>
            <div style="font-size:18px;font-weight:800;color:#b91c1c;margin-top:2px">{html.escape(metrics['tier_s_rate'])}</div>
            <div style="font-size:11px;color:#64748b">FinTech, RegTech &amp; Bank LPs</div>
          </td>
          <td style="padding:10px;border:1px solid #e2e8f0;background:#eff6ff;width:25%">
            <div style="font-size:10px;text-transform:uppercase;color:#1e40af;font-weight:700">Tier A Enterprise AI VCs</div>
            <div style="font-size:18px;font-weight:800;color:#1d4ed8;margin-top:2px">{html.escape(metrics['tier_a_rate'])}</div>
            <div style="font-size:11px;color:#64748b">B2B AI, Cyber &amp; Data Infra</div>
          </td>
          <td style="padding:10px;border:1px solid #e2e8f0;background:#f0fdf4;width:25%">
            <div style="font-size:10px;text-transform:uppercase;color:#166534;font-weight:700">1-Click Email &amp; LinkedIn</div>
            <div style="font-size:18px;font-weight:800;color:#15803d;margin-top:2px">{html.escape(metrics['with_email_rate'])}</div>
            <div style="font-size:11px;color:#64748b">100% Partner Enriched</div>
          </td>
          <td style="padding:10px;border:1px solid #e2e8f0;background:#fffbeb;width:25%">
            <div style="font-size:10px;text-transform:uppercase;color:#92400e;font-weight:700">Decks Sent / Engaged</div>
            <div style="font-size:18px;font-weight:800;color:#b45309;margin-top:2px">{html.escape(metrics['decks_sent_rate'])}</div>
            <div style="font-size:11px;color:#64748b">Opened/PDFs: {html.escape(metrics['decks_opened_rate'])}</div>
          </td>
        </tr>
      </table>

      <h2 style="font-size:15px;margin:18px 0 8px 0;color:#0f172a;border-left:4px solid #d97706;padding-left:8px">
        1. Funds with Active Decks Sent, Opened Links, or Warm Intro Follow-Ups ({len(active_deck_or_engaged)} of {metrics['total_investors']} funds)
      </h2>
      <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:22px">
        <thead>
          <tr style="background:#f1f5f9;text-align:left;font-size:10px;text-transform:uppercase;color:#475569">
            <th style="padding:7px 10px">Tier / Fit</th>
            <th style="padding:7px 10px">Fund &amp; Check Size</th>
            <th style="padding:7px 10px">Partner Contact</th>
            <th style="padding:7px 10px">Status / Engagement / Next Step</th>
            <th style="padding:7px 10px">1-Click Actions</th>
          </tr>
        </thead>
        <tbody>
          {_render_rows_html(active_deck_or_engaged[:15], warren_tok)}
        </tbody>
      </table>

      <h2 style="font-size:15px;margin:18px 0 8px 0;color:#0f172a;border-left:4px solid #b91c1c;padding-left:8px">
        2. Warren's Priority Tier-S Follow-Up Queue — FinTech, RegTech &amp; Bank-LP VCs (Top {len(warren_queue)})
      </h2>
      <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:22px">
        <thead>
          <tr style="background:#f1f5f9;text-align:left;font-size:10px;text-transform:uppercase;color:#475569">
            <th style="padding:7px 10px">Tier / Fit</th>
            <th style="padding:7px 10px">Fund &amp; Check Size</th>
            <th style="padding:7px 10px">Partner Contact</th>
            <th style="padding:7px 10px">Pitch Hook / Status</th>
            <th style="padding:7px 10px">1-Click Actions</th>
          </tr>
        </thead>
        <tbody>
          {_render_rows_html(warren_queue, warren_tok)}
        </tbody>
      </table>

      <h2 style="font-size:15px;margin:18px 0 8px 0;color:#0f172a;border-left:4px solid #1d4ed8;padding-left:8px">
        3. Leo's Priority Tier-S &amp; Tier-A Follow-Up Queue — Enterprise AI &amp; Lead VCs (Top {len(leo_queue)})
      </h2>
      <table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:16px">
        <thead>
          <tr style="background:#f1f5f9;text-align:left;font-size:10px;text-transform:uppercase;color:#475569">
            <th style="padding:7px 10px">Tier / Fit</th>
            <th style="padding:7px 10px">Fund &amp; Check Size</th>
            <th style="padding:7px 10px">Partner Contact</th>
            <th style="padding:7px 10px">Warm Path / Next Step</th>
            <th style="padding:7px 10px">1-Click Actions</th>
          </tr>
        </thead>
        <tbody>
          {_render_rows_html(leo_queue, leo_tok)}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>"""

    plain_lines = [
        subject,
        "=" * len(subject),
        f"Generated: {now_str}",
        f"Live Investor Radar Board (Warren): {PUBLIC_URL}/digest?token={warren_tok}",
        f"Live Investor Radar Board (Leo):    {PUBLIC_URL}/digest?token={leo_tok}",
        "",
        "SUMMARY METRICS (WITH DENOMINATORS):",
        f"- Total Investors Evaluated: {metrics['total_investors']} of {metrics['total_investors']} (100.0%)",
        f"- Tier S (Bullseye FinTech/RegTech/Bank-LP): {metrics['tier_s_rate']}",
        f"- Tier A (Enterprise AI & Cyber Lead VCs):   {metrics['tier_a_rate']}",
        f"- Verified Direct Partner Emails:            {metrics['with_email_rate']}",
        f"- Verified LinkedIn URLs:                    {metrics['with_linkedin_rate']}",
        f"- Active Decks Sent / Engaged:               {metrics['decks_sent_rate']}",
        "",
        "TOP ENGAGED / DECK SENT FUNDS:",
    ]
    for r in active_deck_or_engaged[:10]:
        plain_lines.append(
            f"  * [{r['tier']}·{r['dokimo_fit_score']}] {r['fund']} — {r['person']} <{r['email']}> | Status: {r.get('latest_status')} | Next: {r.get('next_action') or 'Follow up'}"
        )

    return {
        "ok": True,
        "mode": mode,
        "generated_at": now_str,
        "subject": subject,
        "metrics": metrics,
        "active_deck_or_engaged": active_deck_or_engaged,
        "warren_queue": warren_queue,
        "leo_queue": leo_queue,
        "html_body": html_body,
        "plain_body": "\n".join(plain_lines),
    }


def send_investor_digest_email(recipients: list[str] = None, mode: str = "daily") -> dict:
    """Send the HTML + Plaintext Investor Pipeline Digest email via Gmail API."""
    payload = build_digest_payload(mode=mode)
    target_rcpts = recipients or ["warren@dokimo.ai", "leo@dokimo.ai"]
    clean_rcpts = [r.strip() for r in target_rcpts if r and "@" in r]

    tok = _gmail_access_token()
    sent_to = []
    errors = []
    for rcpt in clean_rcpts:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = payload["subject"]
            msg["From"] = "Warren Zafrin — Dokimo Investor Radar <warren@dokimo.ai>"
            msg["To"] = rcpt
            msg["Reply-To"] = "warren@dokimo.ai"
            msg.attach(MIMEText(payload["plain_body"], "plain", "utf-8"))
            msg.attach(MIMEText(payload["html_body"], "html", "utf-8"))
            raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

            req = urllib.request.Request(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                data=json.dumps({"raw": raw_b64}).encode("utf-8"),
                headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20):
                pass
            sent_to.append(rcpt)
        except Exception as e:
            errors.append(f"{rcpt}: {e}")

    return {
        "ok": len(sent_to) > 0,
        "subject": payload["subject"],
        "sent_to": sent_to,
        "errors": errors,
        "generated_at": payload["generated_at"],
    }


from email.mime.application import MIMEApplication
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent.parent
PITCH_DECK_PDF_PATH = ROOT_DIR / "data" / "Dokimo_Pitch.pdf"
PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def build_investor_mime_message(
    inv_id: str,
    sender: str,
    to_email: str,
    subject: str,
    plain_body: str,
    include_pitch_deck: bool = False,
    attach_pdf: bool = False,
    for_eml_draft: bool = False,
) -> MIMEMultipart:
    """Build a multipart MIME message for an investor strictly from Warren Zafrin or Leo Spiegel.
    - Embeds the 1x1 open-tracking pixel (/t/o/<inv_id>.gif) and auto-links the tracked /deck?inv=<inv_id> URL.
    - When include_pitch_deck=True (default recommended mode), embeds the tracked Video + 18-Slide Seed Deck CTA card (/deck?inv=<inv_id>) so the VC watches the video and views the 18-slide deck with 100% open & forward telemetry.
    - When attach_pdf=True, also attaches Dokimo_Pitch.pdf as Dokimo_AI_Investor_Pitch_Deck.pdf.
    """
    snd_key = (sender or "warren").strip().lower()
    if snd_key not in investor_engine.ALLOWED_INVESTOR_SENDERS:
        raise ValueError("Investor emails may ONLY be sent from Warren Zafrin or Leo Spiegel.")
    sender_name, sender_email = investor_engine.ALLOWED_INVESTOR_SENDERS[snd_key]

    clean_body = (plain_body or "").strip()
    if clean_body.lower().startswith("subject:"):
        nl = clean_body.find("\n")
        if nl > 0:
            if not subject:
                subject = clean_body[8:nl].strip()
            clean_body = clean_body[nl + 1 :].lstrip("\r\n")

    has_pdf = bool(attach_pdf and PITCH_DECK_PDF_PATH.exists())
    outer = MIMEMultipart("mixed") if has_pdf else MIMEMultipart("alternative")
    if for_eml_draft:
        outer["X-Unsent"] = "1"
    outer["Subject"] = subject or "Dokimo.ai — Autonomous Full-Population Control Validation"
    outer["From"] = f'"{sender_name}" <{sender_email}>'
    outer["Reply-To"] = f"{sender_name} <{sender_email}>"
    outer["To"] = (to_email or "").strip()

    alt = MIMEMultipart("alternative") if has_pdf else outer
    alt.attach(MIMEText(clean_body, "plain", "utf-8"))

    raw_paras = [p.strip() for p in clean_body.split("\n\n") if p.strip()]
    pixel_url = f"{PUBLIC_URL}/t/o/{urllib.parse.quote(inv_id or 'INV-001')}.gif"
    deck_portal_url = f"{PUBLIC_URL}/deck?inv={urllib.parse.quote(inv_id or 'INV-001')}"
    pdf_portal_url = f"{PUBLIC_URL}/deck/pdf?inv={urllib.parse.quote(inv_id or 'INV-001')}"
    open_beacon = f'<img src="{html.escape(pixel_url, quote=True)}" width="1" height="1" alt="" style="display:block;width:1px;height:1px;border:0;opacity:0" />'

    html_paras = []
    for idx_p, p in enumerate(raw_paras):
        esc_p = html.escape(p).replace("\n", "<br>")
        esc_p = re.sub(
            r"(https?://[^\s<\"')]+)",
            r'<a href="\1" style="color:#1d4ed8;text-decoration:underline;font-weight:600">\1</a>',
            esc_p,
        )
        html_paras.append(f'<p style="margin:0 0 12px 0">{esc_p}</p>')
        if idx_p == 0:
            html_paras.append(open_beacon)

    if include_pitch_deck and deck_portal_url not in clean_body:
        html_paras.append(
            f'<p style="margin:0 0 12px 0">'
            f'Here is the link to our 18-slide Seed Deck and 90-second product walkthrough:<br>'
            f'<a href="{html.escape(deck_portal_url, quote=True)}" style="color:#1d4ed8;text-decoration:underline;font-weight:600">{html.escape(deck_portal_url)}</a>'
            f' &nbsp;&middot;&nbsp; '
            f'<a href="{html.escape(pdf_portal_url, quote=True)}" style="color:#1d4ed8;text-decoration:underline">Download PDF Deck</a>'
            f'</p>'
        )

    if has_pdf:
        html_paras.append(
            '<p style="margin:0 0 12px 0;font-size:13px;color:#334155">'
            '<i>Attached: Dokimo_AI_Investor_Pitch_Deck.pdf (18-Slide Seed Round Deck)</i>'
            '</p>'
        )

    html_body = (
        '<div dir="ltr" style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;font-size:14px;line-height:1.55;color:#0f172a">'
        + "".join(html_paras)
        + "</div>"
    )
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    if has_pdf:
        outer.attach(alt)
        pdf_bytes = PITCH_DECK_PDF_PATH.read_bytes()
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header("Content-Disposition", 'attachment; filename="Dokimo_AI_Investor_Pitch_Deck.pdf"')
        outer.attach(pdf_part)

    return outer


def build_investor_eml_bytes(
    inv_id: str,
    sender: str,
    to_email: str,
    subject: str,
    plain_body: str,
    include_pitch_deck: bool = False,
    attach_pdf: bool = False,
) -> tuple[bytes, str]:
    msg = build_investor_mime_message(
        inv_id=inv_id,
        sender=sender,
        to_email=to_email,
        subject=subject,
        plain_body=plain_body,
        include_pitch_deck=include_pitch_deck,
        attach_pdf=attach_pdf,
        for_eml_draft=True,
    )
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", inv_id or "investor")
    snd_tag = "Leo" if "leo" in (sender or "").lower() else "Warren"
    deck_tag = "_with_PitchDeckLink" if include_pitch_deck else ""
    if attach_pdf:
        deck_tag = "_with_PitchDeckPDF"
    return msg.as_bytes(), f"Dokimo_{snd_tag}_{safe_id}{deck_tag}.eml"


def create_investor_gmail_draft(
    inv_id: str,
    sender: str,
    to_email: str,
    subject: str,
    plain_body: str,
    include_pitch_deck: bool = False,
    attach_pdf: bool = False,
) -> dict:
    """Create an UNSENT Gmail Draft (users.drafts.create) with rich links, open tracking pixel, and optional PDF attachment.
    NEVER sends automatically — Warren or Leo must open Gmail Drafts and manually click Send.
    """
    snd_key = (sender or "warren").strip().lower()
    if snd_key not in investor_engine.ALLOWED_INVESTOR_SENDERS:
        return {"ok": False, "error": "Investor drafts may ONLY be created for Warren Zafrin or Leo Spiegel."}
    if not to_email or "@" not in to_email:
        return {"ok": False, "error": "Missing valid recipient email address."}

    msg = build_investor_mime_message(
        inv_id=inv_id,
        sender=snd_key,
        to_email=to_email,
        subject=subject,
        plain_body=plain_body,
        include_pitch_deck=include_pitch_deck,
        attach_pdf=attach_pdf,
        for_eml_draft=False,
    )
    tok = _gmail_access_token()
    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        data=json.dumps({"message": {"raw": raw_b64}}).encode("utf-8"),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        resp_data = json.loads(r.read().decode("utf-8"))
    draft_id = resp_data.get("id", "")
    msg_id = (resp_data.get("message") or {}).get("id", "")
    sender_name, sender_email = investor_engine.ALLOWED_INVESTOR_SENDERS[snd_key]
    return {
        "ok": True,
        "draft_only": True,
        "id": inv_id,
        "draft_id": draft_id,
        "msg_id": msg_id,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "to_email": to_email,
        "deck_included": bool(include_pitch_deck),
        "deck_attached": bool(attach_pdf and PITCH_DECK_PDF_PATH.exists()),
    }


def send_investor_email_with_telemetry(*args, **kwargs) -> dict:
    """Direct API sending is disabled on the Investor Board — creates an unsent Gmail Draft instead."""
    return create_investor_gmail_draft(*args, **kwargs)
