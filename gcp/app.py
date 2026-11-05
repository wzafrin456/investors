"""Dokimo Investor Research & VC Fit Intelligence Board (Cloud Run Web Application).

Provides:
  - /           : Enforcement-Watch style Ranked VC & Strategic Fit Board
  - /report     : Executive Research Report ('Who Is the Right VC for Dokimo?')
  - /outreach   : Warm-Intro Blurb (for Leo) & Direct Founder Email Studio (for Warren)
  - /chat       : Interactive Gemini VC Strategist Q&A
  - /access     : Team token management (Warren, Leo, Esther, Joe, Bernie, Steven, Pat)
"""
import base64
import hashlib
import hmac
import html
import http.cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from radar import access, gemini_vc, investor_digest, investor_engine, pdf_memo

USER = os.environ.get("BOARD_USER", "dokimo")
PASSWORD = os.environ.get("BOARD_PASSWORD", "")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")
BUCKET = os.environ.get("GCS_BUCKET", "")
COOKIE_NAME = "dk_inv_session"
SESSION_TTL = 86400 * 365
_EPHEMERAL_SECRET = secrets.token_hex(32)

SYNCED_FILES = [
    "config/access.json",
    "data/raw_leo_investors.txt",
    "data/investors.csv",
    "output/investor_state.json",
]

_LAST_GCS_SYNC_TS = 0.0
_LAST_GCS_TOKEN = ("", 0.0)


def gcs_token() -> str:
    global _LAST_GCS_TOKEN
    now = time.time()
    if _LAST_GCS_TOKEN[0] and (now - _LAST_GCS_TOKEN[1]) < 300:
        return _LAST_GCS_TOKEN[0]
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            tok = json.loads(r.read().decode("utf-8"))["access_token"]
            _LAST_GCS_TOKEN = (tok, now)
            return tok
    except Exception:
        return ""


def gcs_get(object_name: str) -> str | None:
    if not BUCKET:
        return None
    tok = gcs_token()
    if not tok:
        return None
    url = "https://storage.googleapis.com/storage/v1/b/%s/o/%s?alt=media" % (
        urllib.parse.quote(BUCKET, safe=""),
        urllib.parse.quote(object_name, safe=""),
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


def gcs_put(object_name: str, text: str, content_type: str = "text/plain; charset=utf-8") -> bool:
    if not BUCKET:
        return False
    tok = gcs_token()
    if not tok:
        return False
    url = "https://storage.googleapis.com/upload/storage/v1/b/%s/o?uploadType=media&name=%s" % (
        urllib.parse.quote(BUCKET, safe=""),
        urllib.parse.quote(object_name, safe=""),
    )
    try:
        req = urllib.request.Request(
            url,
            data=text.encode("utf-8"),
            headers={"Authorization": "Bearer " + tok, "Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status in (200, 201)
    except Exception:
        return False


def sync_from_gcs(rels=None, min_interval_sec: float = 20.0):
    global _LAST_GCS_SYNC_TS
    if not BUCKET:
        return
    now = time.time()
    if rels is None and (now - _LAST_GCS_SYNC_TS) < min_interval_sec:
        return
    if rels is None:
        _LAST_GCS_SYNC_TS = now
    for rel in (rels or SYNCED_FILES):
        try:
            text = gcs_get("inputs/" + rel)
            if text:
                target = ROOT / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        except Exception:
            pass


def push_to_gcs(rels=None):
    if not BUCKET:
        return
    for rel in (rels or SYNCED_FILES):
        p = ROOT / rel
        if p.exists():
            try:
                ct = "application/json; charset=utf-8" if rel.endswith(".json") else "text/plain; charset=utf-8"
                gcs_put("inputs/" + rel, p.read_text(encoding="utf-8"), ct)
            except Exception:
                pass


def _signing_secret() -> bytes:
    # Resolution: Environment -> Ephemeral CSPRNG fallback
    if PASSWORD or REFRESH_TOKEN:
        return (PASSWORD + "|" + REFRESH_TOKEN).encode("utf-8")
    return _EPHEMERAL_SECRET.encode("utf-8")


def make_session_cookie(viewer: dict) -> str:
    payload = {
        "id": viewer.get("id", "viewer"),
        "name": viewer.get("name", "Viewer"),
        "role": viewer.get("role", "viewer"),
        "exp": int(time.time()) + SESSION_TTL,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(_signing_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_session_cookie(cookie_val: str) -> dict | None:
    if not cookie_val or "." not in cookie_val:
        return None
    raw, sig = cookie_val.rsplit(".", 1)
    expected = hmac.new(_signing_secret(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode((raw + pad).encode("ascii")).decode("utf-8"))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        uid = str(data.get("id", "")).strip().lower()
        if uid not in access.ALLOWED_INVESTOR_BOARD_IDS:
            return None
        if data.get("role") == "admin" or uid in access.ALLOWED_INVESTOR_BOARD_IDS:
            return data
        grants = access.load().get("grants", [])
        g = next((x for x in grants if x.get("id", "").lower() == uid), None)
        if not g or not g.get("active"):
            return None
        return data
    except Exception:
        return None


NAV_BAR_HTML = """
<style>
.dk-nav{background:#ffffff;color:#161a21;padding:9px 18px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;border-bottom:1px solid #dce0e7;font:13.5px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0 0 14px 0}
.dk-nav-brand{font-weight:700;font-size:14.5px;color:#161a21;text-decoration:none;letter-spacing:-.01em}
.dk-nav-links{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.dk-nav-links a{color:#4a5260;text-decoration:none;padding:4px 10px;border-radius:3px;border:1px solid transparent;font-size:12.5px;font-weight:600}
.dk-nav-links a:hover,.dk-nav-links a.active{background:#161a21;color:#ffffff;border-color:#161a21}
.dk-nav-user{color:#7c8494;font-size:12px;display:flex;align-items:center;gap:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.dk-nav-user a{color:#4a5260;text-decoration:underline}
</style>
<div class="dk-nav">
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
    <a class="dk-nav-brand" href="/">🏛️ Dokimo Investor Watch — Deep Research &amp; Positioning Board</a>
    <div class="dk-nav-links">
      <a href="/" class="__ACT_BOARD__">1. VC Deep Research &amp; Positioning Board (/)</a>
      <a href="/telemetry" class="__ACT_TELEMETRY__">2. 📊 Telemetry Bars (Daily · Weekly · Regions)</a>
      <a href="/report" class="__ACT_REPORT__">3. Executive VC Strategy Report (/report)</a>
      <a href="/chat" class="__ACT_CHAT__">4. Ask Gemini VC Strategist (/chat)</a>
      <a href="/readme" class="__ACT_README__" style="border-color:#bfdbfe;background:#eff6ff;color:#1e3a8a">5. 📖 README: How It Works (/readme)</a>
      <a href="/deck" target="_blank" style="background:#991b1b;border-color:#991b1b;color:#fff;font-weight:700">🎬 18-Slide Pitch Deck &amp; Video (/deck) ↗</a>
    </div>
  </div>
  <div class="dk-nav-user">
    <span>Signed in: <b>__VIEWER__</b></span>
    <a href="/logout" style="margin-left:6px;background:#fee2e2;color:#991b1b;border-color:#fca5a5;font-weight:700">🚪 Log Out</a>
  </div>
</div>
"""


def inject_nav(page_html: str, viewer: dict, active_tab: str = "board") -> str:
    can_email = access.can_send_investor_emails(viewer)
    perm_badge = (
        '<span style="background:#dcfce7;color:#166534;padding:2px 7px;border-radius:4px;font-weight:700;font-size:11px">✉️ Email Drafting: Authorized (Leo &amp; Warren Only)</span>'
        if can_email
        else '<span style="background:#fef3c7;color:#92400e;padding:2px 7px;border-radius:4px;font-weight:700;font-size:11px">🔒 Read-Only View (Only Leo &amp; Warren Can Email Investors)</span>'
    )
    script_tag = (
        f"<script>window.CAN_SEND_INVESTOR_EMAILS={json.dumps(can_email)};"
        f"window.VIEWER_ID={json.dumps(viewer.get('id') or '')};"
        f"window.VIEWER_NAME={json.dumps(viewer.get('name') or '')};</script>"
    )
    nav = (
        script_tag
        + NAV_BAR_HTML.replace("__VIEWER__", html.escape(viewer.get("name") or viewer.get("id") or "User") + " " + perm_badge)
        .replace("__ACT_BOARD__", "active" if active_tab == "board" else "")
        .replace("__ACT_TELEMETRY__", "active" if active_tab == "telemetry" else "")
        .replace("__ACT_REPORT__", "active" if active_tab == "report" else "")
        .replace("__ACT_OUTREACH__", "active" if active_tab == "outreach" else "")
        .replace("__ACT_DIGEST__", "active" if active_tab == "digest" else "")
        .replace("__ACT_CHAT__", "active" if active_tab == "chat" else "")
        .replace("__ACT_README__", "active" if active_tab == "readme" else "")
        .replace("__ACT_ACC__", "active" if active_tab == "access" else "")
    )
    if "<body>" in page_html:
        return page_html.replace("<body>", "<body>" + nav, 1)
    return nav + page_html


LOGIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign In · Dokimo Investor Watch &amp; Gemini VC Fit Board</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f4f6f9;color:#1e293b;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:16px}
.box{width:100%;max-width:440px;background:#ffffff;border:1px solid #dde3ea;border-radius:12px;padding:28px;box-shadow:0 8px 24px rgba(15,23,42,.06)}
.badge{display:inline-block;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;margin-bottom:10px}
h1{margin:0 0 6px;font-size:21px;color:#0f172a}
p.sub{margin:0 0 16px;color:#526071;font-size:13.5px}
label{display:block;font-size:13px;color:#334155;margin:12px 0 5px;font-weight:600}
input{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:8px;border:1px solid #cbd5e1;background:#f8fafc;color:#0f172a;font:inherit}
button{width:100%;margin-top:10px;padding:11px;border:0;border-radius:8px;background:#161a21;color:#fff;font-weight:600;font-size:15px;cursor:pointer}
button:hover{background:#2c5f7c}
.gbtn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:12px 14px;border-radius:8px;border:1px solid #1d4ed8;background:#2563eb;color:#ffffff;font-weight:700;font-size:14.5px;cursor:pointer;margin-top:8px;box-shadow:0 2px 6px rgba(37,99,235,.2)}
.gbtn:hover{background:#1d4ed8}
.gbtn.sec{background:#f8fafc;color:#0f172a;border-color:#cbd5e1;box-shadow:none}
.gbtn.sec:hover{background:#eff6ff;border-color:#93c5fd;color:#1e3a8a}
.divider{display:flex;align-items:center;gap:10px;margin:18px 0 12px;color:#64748b;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.divider::before,.divider::after{content:"";flex:1;height:1px;background:#e2e8f0}
.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:9px 12px;border-radius:8px;font-size:13px;margin-bottom:12px}
.foot{margin-top:16px;font-size:12px;color:#64748b;text-align:center}
</style></head><body>
<div class="box">
  <span class="badge">DOKIMO.AI · INVESTOR INTELLIGENCE &amp; PITCH DECK</span>
  <h1>Sign in with Google</h1>
  <p class="sub">Authorized for <b>Warren Zafrin</b>, <b>Leo Spiegel</b>, <b>Steven Goldberg</b>, <b>Joe Spector</b>, and <b>Bernie Vogel</b>.</p>
  __ERROR__
  <a href="/auth/google?start=1&next=__NEXT__" class="gbtn" style="text-decoration:none;box-sizing:border-box;margin-bottom:14px">
    <span>🔵</span> Sign in with Google (accounts.google.com) →
  </a>
  <div class="divider">Or Select Authorized Team Account</div>
  <form method="POST" action="/auth/google" style="margin:0">
    <input type="hidden" name="next" value="__NEXT__">
    <button type="submit" name="credential" value="warren@dokimo.ai" class="gbtn sec">
      <span>🔵</span> Warren Zafrin (warren@dokimo.ai)
    </button>
    <button type="submit" name="credential" value="leo@dokimo.ai" class="gbtn sec">
      <span>🔵</span> Leo Spiegel (leo@dokimo.ai)
    </button>
    <button type="submit" name="credential" value="steven@dokimo.ai" class="gbtn sec">
      <span>🔵</span> Steven Goldberg (steven@dokimo.ai)
    </button>
    <button type="submit" name="credential" value="joe@dokimo.ai" class="gbtn sec">
      <span>🔵</span> Joe Spector (joe@dokimo.ai)
    </button>
    <button type="submit" name="credential" value="bernie@dokimo.ai" class="gbtn sec">
      <span>🔵</span> Bernie Vogel (bernie@dokimo.ai)
    </button>
  </form>
  <div class="divider">Or Sign In With Personal Token</div>
  <form method="POST" action="/login">
    <input type="hidden" name="next" value="__NEXT__">
    <label>Personal Access Token (e.g. <code>leo2026</code>)</label>
    <input type="password" name="token" placeholder="Enter token (e.g. leo2026)" autocomplete="current-password">
    <input type="hidden" name="user" value="">
    <button type="submit">Access Investor Board &amp; Deck →</button>
  </form>
  <div class="foot">Authorized for Warren, Leo, Steven, Joe &amp; Bernie &middot; Stays signed in for 365 days.</div>
</div></body></html>
"""


SHARED_CSS = """
:root{
 --ground:#F6F7F9;--surface:#FFF;--sunk:#EDEFF3;--ink:#161A21;--ink2:#4A5260;
 --ink3:#7C8494;--rule:#DCE0E7;--rule2:#C3C9D4;--accent:#2C5F7C;
 --accent-soft:#E4EDF3;--critical:#A8323A;--critical-soft:#F7E6E7;
 --warning:#9C6520;--warning-soft:#FAEEDF;--opening:#4A4FB5;
 --opening-soft:#E8E9F8;--quiet:#2D6A4F;--quiet-soft:#E7EFE9;
}
*{box-sizing:border-box}
body{margin:0 auto;background:var(--ground);color:var(--ink);font:13.5px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;padding:0 14px 56px;max-width:100%}
h1,h2,h3{margin:0;letter-spacing:-.01em}
.masthead{border-bottom:2px solid var(--ink);padding:16px 0 12px;display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between}
.masthead h1{font-size:24px;font-weight:700;line-height:1.15}
.masthead .sub{color:var(--ink2);font-size:13px;margin-top:4px;max-width:85ch}
.runbox{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;line-height:1.65;color:var(--ink2);text-align:right}
.runbox b{color:var(--ink);font-weight:600}
.top-tabs{margin-top:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;border-bottom:2px solid var(--rule2);padding-bottom:8px}
.tab-btn{font:inherit;font-size:13px;font-weight:600;padding:7px 14px;border:1px solid var(--rule2);background:var(--surface);color:var(--ink2);border-radius:3px;cursor:pointer}
.tab-btn:hover{border-color:var(--accent);color:var(--accent)}
.tab-btn.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.status{margin-top:12px;display:flex;flex-wrap:wrap;border:1px solid var(--rule);border-radius:4px;background:var(--surface);overflow:hidden}
.status > div{flex:1 1 160px;padding:10px 13px;border-right:1px solid var(--rule)}
.status > div:last-child{border-right:none}
.status .k{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);font-weight:700}
.status .v{font-family:ui-monospace,monospace;font-size:16px;margin-top:2px;font-variant-numeric:tabular-nums;color:var(--ink);font-weight:700}
.status .v small{font-size:11px;color:var(--ink3);font-weight:400;font-family:inherit}
.controls-wrap{margin:12px 0 10px;background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:10px 12px}
.controls{display:flex;flex-wrap:wrap;gap:5px;margin:5px 0;align-items:center}
.controls .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);font-weight:700;min-width:74px}
button.f,.btn-sm{font:inherit;font-size:12px;padding:4px 10px;border:1px solid var(--rule2);background:var(--surface);color:var(--ink2);border-radius:3px;cursor:pointer;white-space:nowrap;text-decoration:none;display:inline-flex;align-items:center;gap:4px}
button.f:hover,.btn-sm:hover{border-color:var(--accent);color:var(--accent)}
button.f.on,.btn-sm.pri{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
.btn-sm.ok{background:var(--quiet);color:#fff;border-color:var(--quiet);font-weight:600}
input.search{font:inherit;font-size:13px;padding:5px 10px;border:1px solid var(--rule2);border-radius:3px;background:var(--surface);color:var(--ink);min-width:260px;flex:1;margin:0}
.tablewrap{overflow-x:auto;border:1px solid var(--rule);border-radius:4px;background:var(--surface)}
table.btable{border-collapse:collapse;width:100%;table-layout:fixed}
table.btable thead th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);font-weight:700;padding:10px 10px;border-bottom:1px solid var(--rule2);background:var(--sunk);position:sticky;top:0;z-index:10}
table.btable tbody td{padding:11px 10px;border-bottom:1px solid var(--rule);vertical-align:top;font-size:13px;line-height:1.45;word-wrap:break-word;overflow-wrap:break-word;overflow:hidden}
table.btable tbody tr:hover td{background:#fafbfc}
.tier{font-family:ui-monospace,monospace;font-size:11px;padding:2px 6px;border-radius:3px;white-space:nowrap;font-weight:700;display:inline-block}
.t-S{background:var(--quiet-soft);color:var(--quiet);border:1px solid #b7e4c7}
.t-A{background:var(--accent-soft);color:var(--accent);border:1px solid #bfdbfe}
.t-B{background:var(--warning-soft);color:var(--warning);border:1px solid #fde68a}
.t-C{background:var(--critical-soft);color:var(--critical);border:1px solid #fecaca}
.chip{font-family:ui-monospace,monospace;font-size:10.5px;padding:2px 6px;border-radius:3px;background:var(--sunk);color:var(--ink2);display:inline-block;margin:2px 3px 2px 0;max-width:100%;overflow-wrap:break-word}
.chip.ok{background:var(--quiet-soft);color:var(--quiet);font-weight:600}
.chip.warn{background:var(--warning-soft);color:var(--warning);font-weight:600}
.chip.crit{background:var(--critical-soft);color:var(--critical);font-weight:600}
.qual-badge{font-size:10px;line-height:1.35;padding:3px 6px;border-radius:3px;font-weight:700;display:block;margin-top:5px}
.qual-ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
.qual-hold{background:#fffbeb;color:#92400e;border:1px solid #fde68a}
.fup-box{background:#fffdf5;border:1px solid #e2d9b8;border-radius:4px;padding:6px 7px;margin:5px 0 6px}
.fup-hdr{display:flex;justify-content:space-between;align-items:center;font-size:9.5px;text-transform:uppercase;letter-spacing:.05em;color:#6b5b27;font-weight:700;margin-bottom:3px}
.fup-ta{width:100%;font:11.5px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:4px 6px;border:1px solid #dcd2ad;border-radius:3px;background:#ffffff;color:var(--ink);resize:vertical;min-height:62px}
.fup-ta:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 2px rgba(44,95,124,.15)}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(540px,1fr));gap:14px;margin-top:12px}
.chart-card{background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:14px 16px}
.chart-card h3{font-size:14px;font-weight:700;color:var(--ink);margin-bottom:3px}
.chart-card .csub{font-size:11.5px;color:var(--ink3);margin-bottom:12px}
.wk-bars{display:flex;gap:14px;align-items:flex-end;height:185px;padding:18px 8px 6px;border-bottom:1px solid var(--rule2);background:var(--ground);border-radius:2px}
.wk-col{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}
.wk-grp{display:flex;gap:3px;align-items:flex-end;width:100%;justify-content:center;height:145px}
.bar-item{flex:1;max-width:22px;min-width:10px;border-radius:2px 2px 0 0;position:relative;transition:height .2s,opacity .15s,transform .15s;cursor:pointer}
.bar-item:hover{opacity:.85;transform:translateY(-2px);outline:2px solid var(--ink)}
.bar-item span{position:absolute;top:-15px;left:50%;transform:translateX(-50%);font-family:ui-monospace,monospace;font-size:9.5px;font-weight:600;color:var(--ink);white-space:nowrap}
.wk-lbl{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink2);margin-top:6px;font-weight:600;text-align:center}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;font-size:11.5px;color:var(--ink2)}
.legend > div{cursor:pointer;padding:2px 6px;border-radius:3px;border:1px solid transparent}
.legend > div:hover{background:var(--accent-soft);border-color:var(--accent);color:var(--accent)}
.leg-dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.mcp-pill{display:inline-block;font-family:ui-monospace,monospace;font-size:10.5px;padding:2px 7px;border-radius:2px;background:var(--sunk);color:var(--ink);border:1px solid var(--rule2);margin:0 5px 5px 0}
.mcp-pill.ok{background:var(--quiet-soft);color:var(--quiet);border-color:#b7d1be;font-weight:600}
.mcp-mini-tbl{width:100%;border-collapse:collapse;margin:8px 0;font-size:11.5px;border:1px solid var(--rule)}
.mcp-mini-tbl th{background:var(--sunk);text-align:left;padding:6px 8px;font-size:10px;text-transform:uppercase;color:var(--ink3);border-bottom:1px solid var(--rule2)}
.mcp-mini-tbl td{padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:top}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:999;align-items:center;justify-content:center;padding:18px}
.modal-box{background:#fff;border:1px solid var(--rule2);border-radius:8px;max-width:860px;width:100%;max-height:90vh;overflow-y:auto;padding:20px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
pre.memo{white-space:pre-wrap;background:var(--ground);border:1px solid var(--rule);padding:12px;border-radius:6px;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink);margin:8px 0}
"""


def render_board_html() -> str:
    rows = investor_engine.get_all_investors(persist_csv=True)
    m = investor_engine.build_summary_metrics(rows)
    tel_rep = investor_engine.build_weekly_telemetry_report(rows)
    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    tel_json = json.dumps(tel_rep, ensure_ascii=False).replace("</", "<\\/")
    leo_grant = next((g for g in access.load_grants() if "leo" in (g.get("id") or "").lower() or "leo" in (g.get("name") or "").lower()), None)
    leo_tok = (leo_grant or {}).get("token", "L9kPqR7sTuVwXyZ0123456789AbCdEfG")
    leo_url = f"https://dokimo-investors-aigeqnv5nq-uc.a.run.app/?token={leo_tok}"
    leo_gmail = (
        "https://mail.google.com/mail/?view=cm&fs=1&su="
        + urllib.parse.quote("1-Click Access: Dokimo Investor Watch & Stage-Gated VC Fit Board")
        + "&body="
        + urllib.parse.quote(
            f"Hi Leo,\n\nHere is your 1-click direct login link to the deduplicated Dokimo Investor Watch & VC Fit Board (filtered strictly to the {m['total_investors']} Right VCs for Dokimo, with 'Why They Would Want Dokimo' and 'The Value Pitch' for every fund):\n\n{leo_url}\n\nBest,\nWarren"
        )
    )

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dokimo Investor Watch &amp; Gemini VC Fit Board</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>🏛️ Dokimo Investor Watch — Stage-Gated Right VCs Only (Zero Duplicates)</h1>
    <div class="sub">
      Filtered strictly to the <b>{m['total_investors']} deduplicated RIGHT VCs</b> for Dokimo (1 row per fund — all hardware/semi VCs, Europe-only funds like Balderton, changed funds like Hummer Winblad, and hard passes like Khosla removed). Every fund includes <b>Why They Would Want Dokimo</b> and <b>The Value Pitch to Them</b>.
    </div>
  </div>
  <div class="runbox">
    <b>🟢 Tier S (Pitch Now · Pre-Seed/Seed):</b> {html.escape(m['tier_s_rate'])}<br>
    <b>🔵 Tier A (Warm Intro / Bank CVC):</b> {html.escape(m['tier_a_rate'])}<br>
    <b>⏳ Tier B (Hold for $1M ARR / Series A):</b> {html.escape(m['tier_b_rate'])}
  </div>
</header>

<div class="top-tabs">
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <button id="inv-tab-board" class="tab-btn on" onclick="switchInvMainTab('board')">1. 🎯 VC Target Board ({m['total_investors']} Right VCs: US &rarr; UK &rarr; EU &rarr; IL/US)</button>
    <button id="inv-tab-charts" class="tab-btn" onclick="switchInvMainTab('charts')">2. 📊 Regional Coverage &amp; Telemetry (Daily &middot; Weekly &middot; Regions &middot; Clickable Bars)</button>
    <button id="inv-tab-readme" class="tab-btn" onclick="switchInvMainTab('readme')">3. 📖 Simple Workflow Guide (100% Draft-Only &middot; Zero Auto-Send)</button>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
    <button id="btn-sweep-gmail" class="btn-sm" onclick="sweepGmailTracker()" style="background:#1e40af;border-color:#1e40af;color:#fff;font-weight:700">🔄 Sweep Gmail &amp; Update Tracker</button>
    <a class="btn-sm" href="https://mail.google.com/mail/u/0/#drafts" target="_blank" rel="noopener" style="background:#fff;border-color:#15803d;color:#15803d;font-weight:700">📬 Open Gmail Drafts ↗</a>
  </div>
</div>

<div class="status">
  <div><div class="k">Right VCs</div><div class="v">{m['total_investors']} <small>100% verified email + phone</small></div></div>
  <div><div class="k">⚡ Pre-Seed / Day-0</div><div class="v" style="color:#6d28d9">{m['pre_seed_count']} <small>({html.escape(m['pre_seed_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">🟢 Tier S · Seed</div><div class="v" style="color:var(--quiet)">{m['tier_s_count']} <small>({html.escape(m['tier_s_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">🔵 Tier A · Warm / CVC</div><div class="v" style="color:var(--accent)">{m['tier_a_count']} <small>({html.escape(m['tier_a_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">⏳ Tier B · Hold ($1M ARR)</div><div class="v" style="color:var(--warning)">{m['tier_b_count']} <small>({html.escape(m['tier_b_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">📧 Sep/Oct Outreach</div><div class="v" style="color:#1e40af">{m['leo_sep_oct_count']} <small>tracked</small></div></div>
</div>

<div class="status" style="margin-top:8px;background:#f8fafc;border-color:#cbd5e1">
  <div><div class="k">📨 Funds Contacted / Sent</div><div class="v" style="color:#0f172a">{html.escape(m['sent_funds_rate'])} <small>(W:{m['warren_sent_count']} · L:{m['leo_sent_count']})</small></div></div>
  <div><div class="k">👁️ Unique Partner Opens</div><div class="v" style="color:#1d4ed8">{html.escape(m['unique_open_rate'])} <small>({m['total_opens_sum']} total opens)</small></div></div>
  <div><div class="k">🎬 Deck + Video Included</div><div class="v" style="color:#15803d">{html.escape(m['deck_attached_sent_rate'])} <small>({m['deck_optin_count']} opted-in)</small></div></div>
  <div><div class="k">🔁 Partner Forwards</div><div class="v" style="color:#b91c1c">{html.escape(m['forward_rate'])}</div></div>
  <div><div class="k">📅 Meetings / Talking</div><div class="v" style="color:#6d28d9">{html.escape(m['meeting_talking_rate'])}</div></div>
  <div><div class="k">📝 Fields &amp; Notes Updated</div><div class="v" style="color:#0f766e">{html.escape(m['notes_updated_rate'])} <small>(W:{m['warren_updated_count']} · L:{m['leo_updated_count']})</small></div></div>
</div>

<div id="view-inv-charts" style="display:none">
  <div class="controls-wrap" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div class="controls" style="margin:0">
      <span class="lbl">Telemetry View</span>
      <button id="icview-daily_region" class="f on" onclick="setInvChartMode('daily_region')">📊 Daily by Region (US &middot; UK &middot; EU &middot; IL/US)</button>
      <button id="icview-daily_tier" class="f" onclick="setInvChartMode('daily_tier')">📊 Daily by Stage / Tier (Pre-Seed &middot; S &middot; A &middot; B)</button>
      <button id="icview-weekly_region" class="f" onclick="setInvChartMode('weekly_region')">📈 Weekly by Region (US &middot; UK &middot; EU &middot; IL/US)</button>
      <button id="icview-weekly_tier" class="f" onclick="setInvChartMode('weekly_tier')">📈 Weekly by Stage / Tier</button>
      <button id="icview-sender" class="f" onclick="setInvChartMode('sender')">👥 Daily &amp; Weekly by Sender (Warren vs. Leo)</button>
      <button id="icview-both" class="f" onclick="setInvChartMode('both')">Show All Views Together</button>
    </div>
    <div style="font-size:11.5px;color:var(--ink3);font-family:ui-monospace,monospace">💡 Click any daily/weekly bar or legend item to pull up the VCs &amp; open their email/deck draft composer</div>
  </div>
  <div id="inv-charts-container"></div>
  <div id="inv-chart-drilldown-panel" style="display:block;margin:16px 0 8px;background:var(--surface);border:2px solid var(--accent);border-radius:3px;padding:14px 16px"></div>
</div>

<div id="view-inv-readme" style="display:none;margin-top:12px">
  <div id="inv-inline-readme-box"></div>
</div>

<div id="view-inv-board">
<div class="controls-wrap">
  <div class="controls">
    <span class="lbl">Stage</span>
    <button class="f on" data-ftier="all" onclick="setFilter('tier','all',this)">All ({m['total_investors']})</button>
    <button class="f" style="border-color:#6d28d9;color:#6d28d9;font-weight:700" data-ftier="PRE" onclick="setFilter('tier','PRE',this)">⚡ Pre-Seed ({m['pre_seed_count']})</button>
    <button class="f" data-ftier="S" onclick="setFilter('tier','S',this)">🟢 Tier S ({m['tier_s_count']})</button>
    <button class="f" data-ftier="A" onclick="setFilter('tier','A',this)">🔵 Tier A ({m['tier_a_count']})</button>
    <button class="f" data-ftier="B" onclick="setFilter('tier','B',this)">⏳ Tier B ({m['tier_b_count']})</button>
    <span class="lbl" style="margin-left:10px">Owner</span>
    <button class="f on" onclick="setFilter('owner','all',this)">All</button>
    <button class="f" onclick="setFilter('owner','warren',this)">Warren ({m['warren_contact_count']})</button>
    <button class="f" onclick="setFilter('owner','leo',this)">Leo ({m['leo_contact_count']})</button>
    <button class="f" onclick="setFilter('owner','team',this)">Team</button>
  </div>
  <div class="controls" style="margin-top:6px">
    <span class="lbl">KPI Filter</span>
    <button class="f on" onclick="setFilter('reach','all',this)">All ({m['total_investors']})</button>
    <button class="f" onclick="setFilter('reach','sent',this)">📨 Sent ({m['sent_funds_count']})</button>
    <button class="f" onclick="setFilter('reach','opened',this)">👁️ Opened ({m['unique_open_funds_count']})</button>
    <button class="f" onclick="setFilter('reach','deck',this)">🎬 Deck: YES ({m['deck_optin_count']})</button>
    <button class="f" onclick="setFilter('reach','forwarded',this)">🔁 Forwarded ({m['forwarded_funds_count']})</button>
    <button class="f" onclick="setFilter('reach','meeting',this)">📅 Meeting / Talking ({m['meeting_talking_count']})</button>
    <button class="f" onclick="setFilter('reach','followup',this)">📝 Notes Updated ({m['notes_updated_count']})</button>
  </div>
  <div class="controls" style="flex-wrap:wrap;gap:6px;margin-top:6px">
    <span class="lbl">Search / AI</span>
    <input id="q-search" class="search" style="min-width:320px" placeholder="Search fund, partner, portfolio, or press Enter to ask Gemini AI..." oninput="onSearchInput()" onkeydown="if(event.key==='Enter'){{event.preventDefault();runGeminiSearch();}}">
    <button id="btn-gemini-search" class="btn-sm" style="background:#6d28d9;color:#fff;border-color:#6d28d9;font-weight:700;padding:5px 11px" onclick="runGeminiSearch()">✨ Ask Gemini AI</button>
    <button id="btn-gemini-clear" class="btn-sm" style="display:none;color:#b91c1c;border-color:#fca5a5" onclick="clearGeminiSearch()">✕ Clear</button>
    <button class="f" onclick="var mf=document.getElementById('inv-more-filters');mf.style.display=mf.style.display==='none'?'block':'none';">⚙️ More Filters &darr;</button>
    <span id="shown-count" style="font-family:ui-monospace,monospace;font-size:12px;color:var(--ink2);font-weight:600;margin-left:4px"></span>
  </div>
  <div id="inv-more-filters" style="display:none;border-top:1px dashed var(--rule2);margin-top:8px;padding-top:8px">
    <div class="controls">
      <span class="lbl">Region</span>
      <button class="f on" onclick="setFilter('region','all',this)">All ({m['total_investors']})</button>
      <button class="f" onclick="setFilter('region','US',this)">🇺🇸 US ({m['us_count']})</button>
      <button class="f" onclick="setFilter('region','UK',this)">🇬🇧 UK ({m['uk_count']})</button>
      <button class="f" onclick="setFilter('region','EU',this)">🇪🇺 EU ({m['eu_count']})</button>
      <button class="f" onclick="setFilter('region','IL / US',this)">🇮🇱/🇺🇸 IL-US ({m['il_us_count']})</button>
      <span class="lbl" style="margin-left:10px">Review</span>
      <button class="f on" onclick="setFilter('reach','all',this)">All</button>
      <button class="f" onclick="setFilter('reach','sepoct',this)">Prior Context ({m['leo_sep_oct_count']})</button>
      <button class="f" onclick="setFilter('reach','active',this)">Reviewed / Active ({m['active_convo_count']})</button>
    </div>
  </div>
  <div id="gemini-search-banner" style="display:none;margin-top:8px;padding:10px 14px;background:#f5f3ff;border:1px solid #c4b5fd;border-left:4px solid #6d28d9;border-radius:6px;font-size:12.5px;color:#1e1b4b;line-height:1.45"></div>
</div>

<div class="tablewrap">
  <table class="btable">
    <thead>
      <tr>
        <th style="width:3.5%">#</th>
        <th style="width:13.5%">Fund &amp; Category</th>
        <th style="width:14%">Partner, Email &amp; Phone</th>
        <th style="width:11%">Stage, Fit &amp; Qualification Gate</th>
        <th style="width:21%">Deep Research: Why They Want Dokimo &amp; Portfolio Fit</th>
        <th style="width:17%">Positioning Angle &amp; Bank LP Leverage</th>
        <th style="width:20%">Warren &amp; Leo Review Notes + Deep-Dive IC Memo</th>
      </tr>
    </thead>
    <tbody id="inv-tbody"></tbody>
  </table>
</div>
</div>

<div class="modal-bg" id="gemini-modal" onclick="if(event.target===this)closeModal()">
  <div class="modal-box">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;border-bottom:1px solid var(--rule);padding-bottom:10px">
      <h2 id="mod-title" style="font-size:18px">Gemini VC Fit Memo &amp; Outreach Kit</h2>
      <button class="btn-sm" onclick="closeModal()">✕ Close</button>
    </div>
    <div id="mod-body" style="margin-top:12px"></div>
  </div>
</div>

<script>
var INVESTORS = {data_json};
var INV_TELEMETRY = {tel_json};
var INV_CHART_MODE = 'daily_region';
var FILTERS = {{tier:'all', region:'all', owner:'all', reach:'all'}};
var GEMINI_SEARCH_STATE = {{active:false, query:'', matchedIds:null, reasons:{{}}}};

function escHtml(s){{
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

function switchInvMainTab(tabName){{
  var bBoard = document.getElementById('inv-tab-board');
  var bCharts = document.getElementById('inv-tab-charts');
  var bFup = document.getElementById('inv-tab-fup');
  var bReadme = document.getElementById('inv-tab-readme');
  var vBoard = document.getElementById('view-inv-board');
  var vCharts = document.getElementById('view-inv-charts');
  var vReadme = document.getElementById('view-inv-readme');
  [bBoard, bCharts, bFup, bReadme].forEach(function(b){{ if(b) b.classList.remove('on'); }});
  if(tabName === 'charts'){{
    if(bCharts) bCharts.classList.add('on');
    if(vBoard) vBoard.style.display = 'none';
    if(vReadme) vReadme.style.display = 'none';
    if(vCharts) vCharts.style.display = 'block';
    if(INV_CHART_MODE === 'fup') INV_CHART_MODE = 'daily_region';
    drawInvCharts();
  }} else if(tabName === 'fup'){{
    if(bFup) bFup.classList.add('on');
    if(vBoard) vBoard.style.display = 'none';
    if(vReadme) vReadme.style.display = 'none';
    if(vCharts) vCharts.style.display = 'block';
    setInvChartMode('fup');
  }} else if(tabName === 'readme'){{
    if(bReadme) bReadme.classList.add('on');
    if(vBoard) vBoard.style.display = 'none';
    if(vCharts) vCharts.style.display = 'none';
    if(vReadme){{
      vReadme.style.display = 'block';
      renderInlineInvReadme();
    }}
  }} else {{
    if(bBoard) bBoard.classList.add('on');
    if(vCharts) vCharts.style.display = 'none';
    if(vReadme) vReadme.style.display = 'none';
    if(vBoard) vBoard.style.display = 'block';
  }}
}}

function setInvChartMode(mode){{
  INV_CHART_MODE = mode;
  ['daily_region','daily_tier','weekly_region','weekly_tier','sender','fup','both'].forEach(function(m){{
    var el = document.getElementById('icview-' + m);
    if(el){{
      if(m === mode) el.classList.add('on');
      else el.classList.remove('on');
    }}
  }});
  drawInvCharts();
}}

function _getInvBarCompanyList(groupType, groupKey, metricKey, idx){{
  var isDaily = (groupType.indexOf('daily_') === 0);
  var src = isDaily ? ((INV_TELEMETRY && INV_TELEMETRY.daily_telemetry) || {{}}) : ((INV_TELEMETRY && INV_TELEMETRY.weekly_telemetry) || {{}});
  var dimKey = 'by_region';
  if(groupType.indexOf('tier') >= 0) dimKey = 'by_tier';
  else if(groupType.indexOf('sender') >= 0) dimKey = 'by_sender';
  var dimObj = src[dimKey] || {{}};
  var cosByMet = (dimObj.companies && dimObj.companies[metricKey]) || {{}};
  var arrByTime = cosByMet[groupKey] || [];
  if(idx >= 0){{
    return arrByTime[idx] || [];
  }}
  var merged = [];
  var seen = {{}};
  (arrByTime || []).forEach(function(slot){{
    (slot || []).forEach(function(c){{
      if(!seen[c.id]){{
        seen[c.id] = Object.assign({{}}, c);
        merged.push(seen[c.id]);
      }} else {{
        seen[c.id].event_count = (seen[c.id].event_count || 0) + (c.event_count || 1);
      }}
    }});
  }});
  return merged;
}}

function _buildInvChartCard(title, sub, timeLabels, groups, matrix, groupType, metricKey){{
  var maxVal = 1;
  timeLabels.forEach(function(tl, ti){{
    groups.forEach(function(g){{
      var v = (matrix && matrix[g.key] && matrix[g.key][ti]) || 0;
      if(v > maxVal) maxVal = v;
    }});
  }});
  var colsHtml = timeLabels.map(function(tl, ti){{
    var bars = groups.map(function(g){{
      var v = (matrix && matrix[g.key] && matrix[g.key][ti]) || 0;
      var hPct = v > 0 ? Math.max(14, Math.round((v / maxVal) * 130)) : 5;
      var cList = _getInvBarCompanyList(groupType, g.key, metricKey, ti);
      var fNames = cList.map(function(c){{ return c.fund; }}).filter(Boolean);
      var tipText = 'Click to view VCs · ' + tl + ' · ' + g.label + ': ' + v + (fNames.length ? (' (' + fNames.join(', ') + ')') : '');
      var clk = "drillInvChartBar('" + escHtml(groupType) + "','" + escHtml(g.key) + "','" + escHtml(g.label) + "','" + escHtml(metricKey) + "'," + ti + ",'" + escHtml(tl) + "')";
      return '<div class="bar-item" onclick="' + clk + '" style="height:' + hPct + 'px;background:' + g.color + '" title="' + escHtml(tipText) + '">' + (v > 0 ? '<span>' + v + '</span>' : '') + '</div>';
    }}).join('');
    return '<div class="wk-col"><div class="wk-grp">' + bars + '</div><div class="wk-lbl">' + escHtml(tl) + '</div></div>';
  }}).join('');

  var legHtml = groups.map(function(g){{
    var tot = ((matrix && matrix[g.key]) || []).reduce(function(a, b){{ return a + b; }}, 0);
    var cList = _getInvBarCompanyList(groupType, g.key, metricKey, -1);
    var fNames = cList.map(function(c){{ return c.fund; }}).filter(Boolean);
    var clk = "drillInvChartBar('" + escHtml(groupType) + "','" + escHtml(g.key) + "','" + escHtml(g.label) + "','" + escHtml(metricKey) + "',-1,'All Periods')";
    return '<div onclick="' + clk + '" title="' + escHtml(fNames.length ? ('VCs: ' + fNames.join(', ')) : ('Click to view all ' + g.label + ' VCs')) + '"><span class="leg-dot" style="background:' + g.color + '"></span><b>' + escHtml(g.label) + ':</b> ' + tot + ' total' + (fNames.length ? (' (' + fNames.length + ' VCs)') : '') + ' <span style="font-size:10px;color:var(--accent)">(View VCs &rarr;)</span></div>';
  }}).join('');

  return '<div class="chart-card"><h3>' + escHtml(title) + '</h3><div class="csub">' + escHtml(sub) + ' <b style="color:var(--accent)">(Click any bar to pull up VCs &amp; Partners)</b></div><div class="wk-bars">' + colsHtml + '</div><div class="legend">' + legHtml + '</div></div>';
}}

function openVcModalById(invId){{
  var found = null;
  for(var i=0;i<INVESTORS.length;i++){{
    if(INVESTORS[i].id === invId || INVESTORS[i].fund === invId){{
      found = INVESTORS[i];
      break;
    }}
  }}
  if(found) openGeminiModal(found);
}}

function jumpToVcAccount(fundOrId, openModalNow){{
  var found = null;
  for(var i=0;i<INVESTORS.length;i++){{
    if(INVESTORS[i].id === fundOrId || INVESTORS[i].fund.toLowerCase() === String(fundOrId||'').toLowerCase()){{
      found = INVESTORS[i];
      break;
    }}
  }}
  if(openModalNow && found){{
    openGeminiModal(found);
    return;
  }}
  FILTERS = {{tier:'all', region:'all', owner:'all', reach:'all'}};
  var inp = document.getElementById('q-search');
  if(inp) inp.value = found ? found.fund : (fundOrId || '');
  switchInvMainTab('board');
  renderRows();
}}

function drillInvChartBar(groupType, groupKey, groupLabel, metricKey, timeIdx, timeLabel, noScroll){{
  var panel = document.getElementById('inv-chart-drilldown-panel');
  if(!panel) return;
  var metricNames = {{
    sent: 'Emails & Pitch Decks Sent',
    opens: 'Total Opens (Email + Deck + PDF)',
    distinct_opens: 'Distinct Partner Opens (Unique VCs)',
    deck_forwards: '18-Slide Deck / Video Views & Partner Forwards'
  }};
  var mLabel = metricNames[metricKey] || 'Investor Telemetry';
  var barVcs = _getInvBarCompanyList(groupType, groupKey, metricKey, timeIdx);

  var groupAllVcs = INVESTORS.filter(function(r){{
    if(groupType.indexOf('region') >= 0){{
      var reg = String(r.region || 'US').toUpperCase();
      if(groupKey === 'uk') return reg.indexOf('UK') >= 0;
      if(groupKey === 'eu') return reg.indexOf('EU') >= 0;
      if(groupKey === 'il_us') return reg.indexOf('IL') >= 0;
      return reg === 'US';
    }}
    if(groupType.indexOf('tier') >= 0){{
      if(groupKey === 'pre_seed') return !!r.is_pre_seed;
      if(groupKey === 'tier_s') return r.tier === 'S';
      if(groupKey === 'tier_a') return r.tier === 'A';
      return r.tier === 'B';
    }}
    if(groupType.indexOf('sender') >= 0){{
      var own = String(r.sent_by || r.our_contact || '').toLowerCase();
      if(groupKey === 'leo') return own.indexOf('leo') >= 0;
      return own.indexOf('warren') >= 0;
    }}
    return true;
  }});

  var hasBarEvents = barVcs.length > 0;
  var showList = hasBarEvents ? barVcs : groupAllVcs.map(function(r){{
    return {{
      id: r.id, rank: r.rank, fund: r.fund, person: r.person, title: r.title,
      email: r.email, display_phone: r.display_phone || r.mobile_phone || r.corporate_phone || '',
      region: r.region || 'US', tier: r.tier || 'S', is_pre_seed: !!r.is_pre_seed,
      score: r.dokimo_fit_score || 90, category: r.category || '',
      our_contact: r.our_contact || 'Warren / Leo', sent_by: r.sent_by || r.our_contact || 'Warren',
      sent_count: r.sent_count || 0, total_opens: r.total_opens || 0,
      unique_opens: r.unique_opens || 0, deck_opens: r.deck_opens || 0,
      forward_count: r.forward_count || 0, include_pitch_deck: !!r.include_pitch_deck,
      latest_status: r.latest_status || 'Not Contacted', event_count: 0
    }};
  }});

  var hdrNote = hasBarEvents
    ? ('<b>' + barVcs.length + ' of ' + groupAllVcs.length + ' VCs (' + ((100 * barVcs.length) / Math.max(1, groupAllVcs.length)).toFixed(1) + '%)</b> in <b>' + escHtml(groupLabel) + '</b> recorded <b>' + escHtml(mLabel) + '</b> in <b>' + escHtml(timeLabel) + '</b>')
    : ('0 recorded ' + escHtml(mLabel) + ' in ' + escHtml(timeLabel) + ' for ' + escHtml(groupLabel) + ' &mdash; showing all <b>' + groupAllVcs.length + ' of ' + INVESTORS.length + ' Target VCs</b> in <b>' + escHtml(groupLabel) + '</b>');

  var vcPillsHtml = showList.slice(0, 28).map(function(item){{
    var badgeCnt = item.event_count > 0 ? (' (' + item.event_count + ')') : (item.total_opens > 0 ? (' (Opens:' + item.total_opens + ')') : '');
    return '<button class="btn-sm" style="margin:0 5px 5px 0;font-weight:700;padding:4px 9px" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', true)">🏛️ ' + escHtml(item.fund) + badgeCnt + ' &rarr;</button>';
  }}).join('');

  var rowsHtml = showList.slice(0, 35).map(function(item){{
    var psBadge = item.is_pre_seed ? ' <span class="chip" style="background:#f3e8ff;color:#6d28d9;font-weight:700">⚡ PRE-SEED</span>' : '';
    var deckBadge = item.include_pitch_deck
      ? '<span class="chip ok">🎬 Deck+Video: YES</span>'
      : '<span class="chip">Teaser Only</span>';
    return '<tr>' +
      '<td><b style="font-size:13px;color:var(--accent);cursor:pointer;text-decoration:underline" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', true)">🏛️ ' + escHtml(item.fund) + '</b>' + psBadge +
      '<div style="font-size:11px;color:var(--ink2);margin-top:2px">#' + escHtml(item.rank) + ' &middot; <span class="tier t-' + escHtml(item.tier) + '">Tier ' + escHtml(item.tier) + '</span> (Score ' + escHtml(item.score) + ') &middot; 🌍 ' + escHtml(item.region) + '</div></td>' +
      '<td><b>' + escHtml(item.person || 'Partnership') + '</b><div style="font-size:11px;color:var(--ink2)">' + escHtml(item.title || '') + '</div>' +
      '<div style="font-family:ui-monospace,monospace;font-size:11px;margin-top:2px">✉️ ' + escHtml(item.email || '') + (item.display_phone ? (' &middot; 📞 ' + escHtml(item.display_phone)) : '') + '</div></td>' +
      '<td>' +
        '<span class="chip">👤 ' + escHtml(item.sent_by || item.our_contact) + '</span> ' +
        '<span class="chip ' + (item.sent_count > 0 ? 'ok' : '') + '">Sent: ' + (item.sent_count || 0) + '</span> ' +
        '<span class="chip ' + (item.total_opens > 0 ? 'warn' : '') + '">Opens: ' + (item.total_opens || 0) + ' (Unique: ' + (item.unique_opens || 0) + ')</span> ' +
        '<span class="chip ' + (item.forward_count > 0 ? 'crit' : '') + '">🔁 Fwd: ' + (item.forward_count || 0) + '</span> ' +
        deckBadge +
        '<div style="font-size:11px;color:var(--ink2);margin-top:3px"><b>Status:</b> ' + escHtml(item.latest_status || 'Not Contacted') + '</div>' +
      '</td>' +
      '<td style="white-space:nowrap">' +
        '<button class="btn-sm pri" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', true)">✨ Open VC &amp; Send Email &rarr;</button> ' +
        '<button class="btn-sm" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', false)">🎯 Board Row &rarr;</button>' +
      '</td>' +
    '</tr>';
  }}).join('');

  panel.style.display = 'block';
  panel.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">' +
      '<div><span class="mcp-pill ok">VCS IN THIS BAR</span> ' + hdrNote + '</div>' +
      '<div style="display:flex;gap:6px;align-items:center">' +
        '<button class="btn-sm" onclick="document.getElementById(\\'inv-chart-drilldown-panel\\').style.display=\\'none\\'">&times; Close</button>' +
      '</div>' +
    '</div>' +
    '<div style="margin-bottom:8px;padding:7px 9px;background:var(--ground);border:1px solid var(--rule);border-radius:3px">' +
      '<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);font-weight:700;margin-bottom:5px">Click Any VC Below to Open Deep Research &amp; Email/Deck Composer:</div>' +
      vcPillsHtml +
    '</div>' +
    '<div style="overflow-x:auto"><table class="mcp-mini-tbl"><thead><tr><th>VC Fund, Region &amp; Stage</th><th>Partner, Email &amp; Phone</th><th>Outreach &amp; Deck Telemetry</th><th>Action</th></tr></thead><tbody>' +
      (rowsHtml || '<tr><td colspan="4" style="padding:12px;text-align:center;color:var(--ink3)">No matching VCs in this segment.</td></tr>') +
    '</tbody></table></div>';
  if(!noScroll) panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}

function _buildInvFollowupScheduleHtml(){{
  var fq = (INV_TELEMETRY && INV_TELEMETRY.daily_followup_queue) || {{}};
  var wList = fq.warren_followups || [];
  var lList = fq.leo_followups || [];
  var allFup = fq.all_followups || [];

  function _renderFupRows(list){{
    return list.map(function(item, idx){{
      return '<tr>' +
        '<td><b>#' + (idx + 1) + '</b></td>' +
        '<td><b style="color:var(--accent);cursor:pointer;text-decoration:underline" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', true)">🏛️ ' + escHtml(item.fund) + '</b> <span class="tier t-' + escHtml(item.tier) + '">Tier ' + escHtml(item.tier) + '</span>' + (item.is_pre_seed ? ' <span class="chip" style="background:#f3e8ff;color:#6d28d9;font-weight:700">⚡ PRE-SEED</span>' : '') + '</td>' +
        '<td><b>' + escHtml(item.person || 'Partner') + '</b> &lt;<code>' + escHtml(item.email || '') + '</code>&gt;' + (item.display_phone ? ('<br><span style="font-size:11px;color:var(--quiet);font-weight:700">📞 ' + escHtml(item.display_phone) + '</span>') : '') + '</td>' +
        '<td><span class="chip warn">' + escHtml(item.rotation_stage) + '</span><br><span style="font-size:10.5px;color:var(--ink2)">Sent: ' + (item.sent_count||0) + ' &middot; Opens: ' + (item.total_opens||0) + ' &middot; Unique: ' + (item.unique_opens||0) + ' &middot; Fwd: ' + (item.forward_count||0) + '</span></td>' +
        '<td><button class="btn-sm pri" onclick="jumpToVcAccount(\\'' + escHtml(item.id) + '\\', true)">✨ Follow Up / Send Deck &rarr;</button></td>' +
      '</tr>';
    }}).join('');
  }}

  return '<div class="chart-card" style="margin-bottom:14px;border-left:4px solid var(--accent)">' +
    '<h3>📅 Daily AM Investor Follow-Up &amp; Round-Robin Rotation Engine (5 Each: Warren Zafrin &amp; Leo Spiegel = 10 VCs/Day)</h3>' +
    '<div class="csub">Identical rotation logic &amp; round-robin cadence as the Prospecting Board: <b>Overnight / Step-1 Outreach</b> &rarr; <b>Every AM 5-Each Follow-Up Queue</b> &rarr; <b>Day +4 Follow-Up (Send Tracked 18-Slide Deck + Video)</b> &rarr; <b>Day +7 Partner / Warm-Intro Rotation</b> &rarr; <b>Day +42 Hold / Inactive Flag</b>.</div>' +
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:14px;margin-top:10px">' +
      '<div style="border:1px solid #bfdbfe;background:#f8fafc;border-radius:6px;padding:10px 12px">' +
        '<div style="font-weight:700;color:#1e3a8a;font-size:13px;margin-bottom:6px">👤 Warren Zafrin (`warren@dokimo.ai`) — Today\\'s 5 Round-Robin VC Follow-Ups (' + wList.length + ' of 5)</div>' +
        '<table class="mcp-mini-tbl"><thead><tr><th>#</th><th>VC Fund</th><th>Partner</th><th>Rotation &amp; Telemetry Stage</th><th>Action</th></tr></thead><tbody>' +
          (_renderFupRows(wList) || '<tr><td colspan="5">No items queued</td></tr>') +
        '</tbody></table>' +
      '</div>' +
      '<div style="border:1px solid #a7f3d0;background:#f8fafc;border-radius:6px;padding:10px 12px">' +
        '<div style="font-weight:700;color:#065f46;font-size:13px;margin-bottom:6px">👤 Leo Spiegel (`leo@dokimo.ai`) — Today\\'s 5 Round-Robin VC Follow-Ups (' + lList.length + ' of 5)</div>' +
        '<table class="mcp-mini-tbl"><thead><tr><th>#</th><th>VC Fund</th><th>Partner</th><th>Rotation &amp; Telemetry Stage</th><th>Action</th></tr></thead><tbody>' +
          (_renderFupRows(lList) || '<tr><td colspan="5">No items queued</td></tr>') +
        '</tbody></table>' +
      '</div>' +
    '</div>' +
  '</div>';
}}

function drawInvCharts(){{
  var box = document.getElementById('inv-charts-container');
  if(!box) return;
  var wt = (INV_TELEMETRY && INV_TELEMETRY.weekly_telemetry) || {{}};
  var dt = (INV_TELEMETRY && INV_TELEMETRY.daily_telemetry) || {{}};
  var days = dt.days || ['Day 1','Day 2','Day 3','Day 4','Day 5','Day 6','Day 7'];
  var weeks = wt.weeks || ['Wk 1','Wk 2','Wk 3','Wk 4'];

  var regGroups = [
    {{key:'us', label:'US', color:'#2C5F7C'}},
    {{key:'uk', label:'UK', color:'#5C7362'}},
    {{key:'eu', label:'EU', color:'#4A4FB5'}},
    {{key:'il_us', label:'IL / US', color:'#9C6520'}}
  ];
  var tierGroups = [
    {{key:'pre_seed', label:'⚡ Pre-Seed / Day-0', color:'#6D28D9'}},
    {{key:'tier_s', label:'🟢 Tier S Seed', color:'#2D6A4F'}},
    {{key:'tier_a', label:'🔵 Tier A Warm / CVC', color:'#2C5F7C'}},
    {{key:'tier_b', label:'⏳ Tier B Hold ($1M ARR)', color:'#9C6520'}}
  ];
  var senderGroups = [
    {{key:'warren', label:'Warren Zafrin (warren@dokimo.ai)', color:'#1E3A8A'}},
    {{key:'leo', label:'Leo Spiegel (leo@dokimo.ai)', color:'#065F46'}}
  ];

  var dReg = dt.by_region || {{}};
  var dTier = dt.by_tier || {{}};
  var dSnd = dt.by_sender || {{}};
  var wReg = wt.by_region || {{}};
  var wTier = wt.by_tier || {{}};
  var wSnd = wt.by_sender || {{}};

  var html = '<div style="font-family:ui-monospace,monospace;font-size:11px;color:var(--ink2);margin:8px 0 4px"><b>Interactive Investor Telemetry Bars:</b> All Daily, Weekly, Regional (US · UK · EU · IL/US), Stage/Tier, and Sender (Warren vs. Leo) bars are clickable. <b>Click any bar or legend item to pull up the exact VCs &amp; Partners below.</b></div>';

  if(INV_CHART_MODE === 'fup' || INV_CHART_MODE === 'both'){{
    html += _buildInvFollowupScheduleHtml();
  }}
  if(INV_CHART_MODE === 'daily_region' || INV_CHART_MODE === 'both'){{
    html += '<h2 style="font-size:16px;margin:14px 0 4px">📊 Daily Investor Outreach &amp; 18-Slide Deck Telemetry by Region (US &middot; UK &middot; EU &middot; IL/US)</h2>' +
      '<div class="chart-grid">' +
        _buildInvChartCard('1. Daily Emails & Decks Sent by Region (US, UK, EU, IL/US)', 'Day-by-day investor emails & pitch decks sent by Warren or Leo across regions.', days, regGroups, dReg.sent, 'daily_region', 'sent') +
        _buildInvChartCard('2. Daily Total Opens by Region (US, UK, EU, IL/US)', 'Day-by-day email open pixels, deck views & PDF opens across regions.', days, regGroups, dReg.opens, 'daily_region', 'opens') +
        _buildInvChartCard('3. Daily Distinct Partner Opens by Region (US, UK, EU, IL/US)', 'Unique VC funds that opened at least once each day by region.', days, regGroups, dReg.distinct_opens, 'daily_region', 'distinct_opens') +
        _buildInvChartCard('4. Daily Deck/Video Views & Partner Forwards by Region', '18-slide Seed Deck views, video watches & multi-device partner forwards by region.', days, regGroups, dReg.deck_forwards, 'daily_region', 'deck_forwards') +
      '</div>';
  }}
  if(INV_CHART_MODE === 'daily_tier' || INV_CHART_MODE === 'both'){{
    html += '<h2 style="font-size:16px;margin:18px 0 4px">📊 Daily Investor Telemetry by Stage &amp; Tier (⚡ Pre-Seed &middot; 🟢 Tier S &middot; 🔵 Tier A &middot; ⏳ Tier B)</h2>' +
      '<div class="chart-grid">' +
        _buildInvChartCard('1. Daily Emails & Decks Sent by Investor Stage/Tier', 'Day-by-day outreach across Pre-Seed, Tier S, Tier A, and Tier B.', days, tierGroups, dTier.sent, 'daily_tier', 'sent') +
        _buildInvChartCard('2. Daily Total Opens by Investor Stage/Tier', 'Day-by-day total email + deck opens across investor tiers.', days, tierGroups, dTier.opens, 'daily_tier', 'opens') +
        _buildInvChartCard('3. Daily Distinct Partner Opens by Investor Stage/Tier', 'Unique VCs opening each day across Pre-Seed, Tier S, Tier A, and Tier B.', days, tierGroups, dTier.distinct_opens, 'daily_tier', 'distinct_opens') +
        _buildInvChartCard('4. Daily Deck/Video Views & Partner Forwards by Stage/Tier', '18-slide Seed Deck views & GP forwards each day by tier.', days, tierGroups, dTier.deck_forwards, 'daily_tier', 'deck_forwards') +
      '</div>';
  }}
  if(INV_CHART_MODE === 'weekly_region' || INV_CHART_MODE === 'both'){{
    html += '<h2 style="font-size:16px;margin:18px 0 4px">📈 Weekly Investor Outreach &amp; Deck Telemetry by Region (US &middot; UK &middot; EU &middot; IL/US)</h2>' +
      '<div class="chart-grid">' +
        _buildInvChartCard('1. Weekly Emails & Decks Sent by Region (US, UK, EU, IL/US)', 'Week-by-week investor outreach sent across US, UK, EU, and IL/US.', weeks, regGroups, wReg.sent, 'weekly_region', 'sent') +
        _buildInvChartCard('2. Weekly Total Opens by Region (US, UK, EU, IL/US)', 'Week-by-week total open events across US, UK, EU, and IL/US.', weeks, regGroups, wReg.opens, 'weekly_region', 'opens') +
        _buildInvChartCard('3. Weekly Distinct Partner Opens by Region (US, UK, EU, IL/US)', 'Unique VC funds opening each week across US, UK, EU, and IL/US.', weeks, regGroups, wReg.distinct_opens, 'weekly_region', 'distinct_opens') +
        _buildInvChartCard('4. Weekly Deck/Video Views & Partner Forwards by Region', 'Week-by-week 18-slide Seed Deck views & partner forwards by region.', weeks, regGroups, wReg.deck_forwards, 'weekly_region', 'deck_forwards') +
      '</div>';
  }}
  if(INV_CHART_MODE === 'weekly_tier' || INV_CHART_MODE === 'both'){{
    html += '<h2 style="font-size:16px;margin:18px 0 4px">📈 Weekly Investor Telemetry by Stage &amp; Tier (⚡ Pre-Seed &middot; 🟢 Tier S &middot; 🔵 Tier A &middot; ⏳ Tier B)</h2>' +
      '<div class="chart-grid">' +
        _buildInvChartCard('1. Weekly Emails & Decks Sent by Investor Stage/Tier', 'Week-by-week outreach across Pre-Seed, Tier S, Tier A, and Tier B.', weeks, tierGroups, wTier.sent, 'weekly_tier', 'sent') +
        _buildInvChartCard('2. Weekly Total Opens by Investor Stage/Tier', 'Week-by-week total opens across Pre-Seed, Tier S, Tier A, and Tier B.', weeks, tierGroups, wTier.opens, 'weekly_tier', 'opens') +
        _buildInvChartCard('3. Weekly Distinct Partner Opens by Investor Stage/Tier', 'Unique VCs opening each week across Pre-Seed, Tier S, Tier A, and Tier B.', weeks, tierGroups, wTier.distinct_opens, 'weekly_tier', 'distinct_opens') +
        _buildInvChartCard('4. Weekly Deck/Video Views & Partner Forwards by Stage/Tier', 'Week-by-week 18-slide Seed Deck views & partner forwards by tier.', weeks, tierGroups, wTier.deck_forwards, 'weekly_tier', 'deck_forwards') +
      '</div>';
  }}
  if(INV_CHART_MODE === 'sender' || INV_CHART_MODE === 'both'){{
    html += '<h2 style="font-size:16px;margin:18px 0 4px">👥 Daily &amp; Weekly Sender Telemetry: Warren Zafrin (`warren@dokimo.ai`) vs. Leo Spiegel (`leo@dokimo.ai`)</h2>' +
      '<div class="chart-grid">' +
        _buildInvChartCard('1. Daily Sent by Sender (Warren vs. Leo)', 'Day-by-day investor emails dispatched by Warren Zafrin vs. Leo Spiegel.', days, senderGroups, dSnd.sent, 'daily_sender', 'sent') +
        _buildInvChartCard('2. Daily Distinct Opens by Sender (Warren vs. Leo)', 'Day-by-day unique partner opens on Warren vs. Leo threads.', days, senderGroups, dSnd.distinct_opens, 'daily_sender', 'distinct_opens') +
        _buildInvChartCard('3. Weekly Sent by Sender (Warren vs. Leo)', 'Week-by-week investor emails dispatched by Warren Zafrin vs. Leo Spiegel.', weeks, senderGroups, wSnd.sent, 'weekly_sender', 'sent') +
        _buildInvChartCard('4. Weekly Distinct Opens by Sender (Warren vs. Leo)', 'Week-by-week unique partner opens on Warren vs. Leo threads.', weeks, senderGroups, wSnd.distinct_opens, 'weekly_sender', 'distinct_opens') +
      '</div>';
  }}

  box.innerHTML = html;
  if(INV_CHART_MODE === 'daily_region'){{
    drillInvChartBar('daily_region', 'us', 'US', 'opens', -1, 'All 7 Days', true);
  }} else if(INV_CHART_MODE === 'daily_tier'){{
    drillInvChartBar('daily_tier', 'tier_s', '🟢 Tier S Seed', 'opens', -1, 'All 7 Days', true);
  }} else if(INV_CHART_MODE === 'weekly_region'){{
    drillInvChartBar('weekly_region', 'us', 'US', 'opens', -1, 'All 4 Weeks', true);
  }} else if(INV_CHART_MODE === 'weekly_tier'){{
    drillInvChartBar('weekly_tier', 'tier_s', '🟢 Tier S Seed', 'opens', -1, 'All 4 Weeks', true);
  }} else if(INV_CHART_MODE === 'sender'){{
    drillInvChartBar('weekly_sender', 'leo', 'Leo Spiegel', 'opens', -1, 'All 4 Weeks', true);
  }}
}}

function renderInlineInvReadme(){{
  var box = document.getElementById('inv-inline-readme-box');
  if(!box) return;
  box.innerHTML = `<div class="chart-card" style="border-left:4px solid #15803d;line-height:1.55">
    <h2 style="font-size:18px;margin-bottom:6px">📖 Simple 3-Step Workflow Guide — Dokimo Investor Board (100% Draft-Only · Zero Auto-Send)</h2>
    <div style="color:var(--ink2);font-size:13px;margin-bottom:12px">Every email on this board is a <b>Draft</b> customized to the partner's exact title, portfolio, and signals. Nothing is ever sent automatically — Leo or Warren always reviews and hits Send inside Gmail.</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px">
      <div style="background:var(--ground);border:1px solid var(--rule);border-radius:6px;padding:12px 14px">
        <h3 style="color:#15803d;margin-bottom:6px">1. 🔒 Investor Board Workflow (dokimo-investors)</h3>
        <ul style="margin:0;padding-left:18px;font-size:12.5px;color:var(--ink)">
          <li><b>Zero Auto-Send Guarantee:</b> No email is ever sent automatically or on a schedule. Every button creates an <b>unsent draft</b> for Leo Spiegel or Warren Zafrin to review and manually send in Gmail.</li>
          <li><b>Deep Partner, Title &amp; Signal Customization:</b> Every draft is written in natural, peer-to-peer human language tailored to the partner's exact title, named portfolio investments, and prior conversation notes (zero GPT bullet lists or AI buzzwords).</li>
          <li><b>1-Click Rich Content Builder (Inside Every VC Modal):</b> Click any chip to add or remove rich content in both Leo's and Warren's drafts:
            <br>&bull; <b>📊 + 18-Slide Seed Deck &amp; Video Link (<code>/deck?inv=&lt;ID&gt;</code>)</b>
            <br>&bull; <b>📄 + 2-Page PDF Tear-Sheet Link (<code>/deck/pdf?inv=&lt;ID&gt;</code>)</b>
            <br>&bull; <b>🎥 + 59s Live Bob Gap-Analysis Clip (<code>#video</code>)</b>
            <br>&bull; <b>🏦 + Live Bank Proofs (Standard Bank, Synchrony, Old National + Guidehouse/KPMG)</b>
            <br>&bull; <b>⚖️ + $1.7B Regulatory Penalty Context (UBS, Amex, BofA)</b>
            <br>&bull; <b>📎 Attach Raw PDF File (<code>Dokimo_AI_Investor_Pitch_Deck.pdf</code>)</b>
          </li>
          <li><b>3 Easy Ways to Open Your Draft (With Rich Links &amp; Open Tracking):</b>
            <br>1) <b>📝 Save to Gmail Drafts:</b> Saves the rich HTML draft + PDF attachment + open tracking pixel directly into your Gmail <b>Drafts</b> folder so you can open Gmail and click Send.
            <br>2) <b>✉️ Copy Rich Email + Open Gmail Compose:</b> Copies the formatted HTML links + invisible open tracking pixel to your clipboard and opens a Gmail compose window ready to paste and send.
            <br>3) <b>📥 Download .EML Draft:</b> Opens an unsent draft in Apple Mail / Outlook Desktop.
          </li>
        </ul>
      </div>
      <div style="background:var(--ground);border:1px solid var(--rule);border-radius:6px;padding:12px 14px">
        <h3 style="color:#1e3a8a;margin-bottom:6px">2. 🎯 Investor Board Governance &amp; Permissions</h3>
        <ul style="margin:0;padding-left:18px;font-size:12.5px;color:var(--ink)">
          <li><b>🏛️ Investor Board (<code>dokimo-investors</code>):</b> $4M Seed Round outreach for <b>Warren Zafrin &amp; Leo Spiegel</b> (with read-only board + <code>/deck</code> viewing for Steven, Joe, and Bernie).</li>
          <li><b>🔒 Strict Sender Control:</b> Only <b>Leo Spiegel</b> and <b>Warren Zafrin</b> can draft or send investor emails, and all investor emails are 100% manual draft-only (zero auto-send).</li>
        </ul>
      </div>
    </div>
  </div>`;
}}

function setFilter(kind, val, btn){{
  FILTERS[kind] = val;
  var parent = btn.parentElement;
  Array.prototype.forEach.call(parent.querySelectorAll('button.f'), function(b){{
    if(b.getAttribute('onclick') && b.getAttribute('onclick').indexOf("setFilter('"+kind+"'") === 0){{
      b.classList.remove('on');
    }}
  }});
  btn.classList.add('on');
  renderRows();
}}

function onSearchInput(){{
  if(GEMINI_SEARCH_STATE.active){{
    GEMINI_SEARCH_STATE.active = false;
    GEMINI_SEARCH_STATE.matchedIds = null;
    GEMINI_SEARCH_STATE.reasons = {{}};
    var ban = document.getElementById('gemini-search-banner');
    if(ban) ban.style.display = 'none';
    var clr = document.getElementById('btn-gemini-clear');
    if(clr) clr.style.display = 'none';
  }}
  renderRows();
}}

function quickGeminiSearch(presetText){{
  var inp = document.getElementById('q-search');
  if(inp) inp.value = presetText;
  runGeminiSearch();
}}

function clearGeminiSearch(){{
  var inp = document.getElementById('q-search');
  if(inp) inp.value = '';
  GEMINI_SEARCH_STATE = {{active:false, query:'', matchedIds:null, reasons:{{}}}};
  var ban = document.getElementById('gemini-search-banner');
  if(ban) ban.style.display = 'none';
  var clr = document.getElementById('btn-gemini-clear');
  if(clr) clr.style.display = 'none';
  renderRows();
}}

function runGeminiSearch(){{
  var inp = document.getElementById('q-search');
  var q = ((inp && inp.value) || '').trim();
  if(!q){{
    clearGeminiSearch();
    return;
  }}
  var btn = document.getElementById('btn-gemini-search');
  var ban = document.getElementById('gemini-search-banner');
  var clr = document.getElementById('btn-gemini-clear');
  if(btn) {{ btn.textContent = '⏳ Gemini Searching 113 VCs...'; btn.disabled = true; }}
  if(ban) {{
    ban.style.display = 'block';
    ban.textContent = '✨ Querying Vertex AI Gemini (gemini-2.5-flash) across all 113 Right VCs for: "' + q + '"...';
  }}
  fetch('/api/investors/gemini-search', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{query:q}})
  }}).then(function(r){{return r.json();}}).then(function(d){{
    if(btn) {{ btn.textContent = '✨ Ask / Filter with Gemini AI'; btn.disabled = false; }}
    if(d && d.ok){{
      GEMINI_SEARCH_STATE = {{
        active: true,
        query: q,
        matchedIds: d.matched_ids || [],
        reasons: d.reasons_by_id || {{}}
      }};
      if(clr) clr.style.display = 'inline-block';
      if(ban){{
        ban.replaceChildren();
        var hdr = makeEl('div', {{style:'font-weight:700;color:#5b21b6;margin-bottom:4px'}}, '✨ Gemini AI Search Result (' + (d.rate || (d.matched_count + ' of ' + d.total_investors)) + ' · Engine: ' + (d.engine || 'gemini-2.5-flash') + ')');
        var txt = makeEl('div', {{style:'color:#1e1b4b'}}, d.ai_summary || '');
        ban.appendChild(hdr);
        ban.appendChild(txt);
      }}
      renderRows();
    }}
  }}).catch(function(err){{
    if(btn) {{ btn.textContent = '✨ Ask / Filter with Gemini AI'; btn.disabled = false; }}
    if(ban) ban.textContent = 'Gemini search error: ' + err;
  }});
}}

function makeEl(tag, attrs, text){{
  var el = document.createElement(tag);
  if(attrs){{
    Object.keys(attrs).forEach(function(k){{
      if(k === 'className') el.className = attrs[k];
      else if(k === 'style') el.setAttribute('style', attrs[k]);
      else el.setAttribute(k, attrs[k]);
    }});
  }}
  if(text !== undefined && text !== null) el.textContent = String(text);
  return el;
}}

function renderRows(){{
  var q = ((document.getElementById('q-search')||{{}}).value || '').toLowerCase().trim();
  var tbody = document.getElementById('inv-tbody');
  tbody.replaceChildren();

  var idOrder = null;
  if(GEMINI_SEARCH_STATE.active && Array.isArray(GEMINI_SEARCH_STATE.matchedIds)){{
    idOrder = {{}};
    GEMINI_SEARCH_STATE.matchedIds.forEach(function(id, idx){{ idOrder[id] = idx + 1; }});
  }}

  var matched = INVESTORS.filter(function(r){{
    if(FILTERS.tier === 'PRE'){{
      if(!r.is_pre_seed) return false;
    }} else if(FILTERS.tier !== 'all' && r.tier !== FILTERS.tier) return false;
    if(FILTERS.region !== 'all' && r.region !== FILTERS.region) return false;
    var own = (r.our_contact || '').toLowerCase();
    if(FILTERS.owner === 'warren' && own.indexOf('warren') < 0) return false;
    if(FILTERS.owner === 'leo' && own.indexOf('leo') < 0) return false;
    if(FILTERS.owner === 'team' && (own.indexOf('warren') >= 0 || own === 'leo')) return false;
    if(FILTERS.reach === 'email' && !r.email) return false;
    if(FILTERS.reach === 'phone' && !r.display_phone) return false;
    if(FILTERS.reach === 'sepoct'){{
      if(!r.leo_sep_oct_outreach) return false;
    }}
    if(FILTERS.reach === 'sent'){{
      if(!(r.sent_count > 0)) return false;
    }}
    if(FILTERS.reach === 'opened'){{
      if(!(r.unique_opens > 0 || r.total_opens > 0)) return false;
    }}
    if(FILTERS.reach === 'deck'){{
      if(!r.include_pitch_deck) return false;
    }}
    if(FILTERS.reach === 'forwarded'){{
      if(!(r.forward_count > 0)) return false;
    }}
    if(FILTERS.reach === 'meeting'){{
      var stm = (r.latest_status || '').toLowerCase();
      if(stm.indexOf('meeting') < 0 && stm.indexOf('scheduling') < 0 && stm.indexOf('pause') < 0 && stm.indexOf('talked') < 0 && stm.indexOf('diligence') < 0 && stm.indexOf('committed') < 0) return false;
    }}
    if(FILTERS.reach === 'followup'){{
      var st1 = (r.latest_status || '').toLowerCase();
      var hasFup = (r.followup_note || '').trim() || (r.follow_up_date || '').trim() || (st1 && st1 !== 'not contacted');
      if(!hasFup) return false;
    }}
    if(FILTERS.reach === 'active'){{
      var st = (r.latest_status || '').toLowerCase();
      if(!st || st === 'not contacted' || st.indexOf('passed') >= 0 || st.indexOf('declined') >= 0) return false;
    }}
    if(idOrder !== null){{
      return Boolean(idOrder[r.id]);
    }}
    if(q){{
      var hay = [r.fund, r.person, r.title, r.category, r.region, r.stage, r.pre_seed_flag, r.qualification_gate, r.portfolio, r.why_fit, r.bank_lp_value, r.our_contact, r.email, r.city, r.country, r.followup_note, r.next_action, r.comment].join(' ').toLowerCase();
      if(hay.indexOf(q) < 0) return false;
    }}
    return true;
  }});

  if(idOrder !== null){{
    matched.sort(function(a, b){{ return (idOrder[a.id] || 9999) - (idOrder[b.id] || 9999); }});
  }}

  var sc = document.getElementById('shown-count');
  if(sc) sc.textContent = 'Showing ' + matched.length + ' of ' + INVESTORS.length + ' qualified Right VCs' + (idOrder !== null ? ' (✨ Ranked by Gemini AI)' : '');

  matched.forEach(function(r){{
    var tr = document.createElement('tr');

    // Col 1: Rank
    var tdRank = makeEl('td', {{style:'font-family:ui-monospace,monospace;color:var(--ink3);font-weight:700'}}, '#' + r.rank);
    tr.appendChild(tdRank);

    // Col 2: Fund & Category
    var tdFund = document.createElement('td');
    var fTitle = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--ink)'}}, r.fund);
    tdFund.appendChild(fTitle);
    if(r.is_pre_seed){{
      tdFund.appendChild(makeEl('span', {{className:'chip', style:'background:#f3e8ff;color:#6d28d9;border:1px solid #d8b4fe;font-weight:700;margin-top:3px'}}, '⚡ PRE-SEED / DAY-0'));
    }}
    if(GEMINI_SEARCH_STATE.active && GEMINI_SEARCH_STATE.reasons && GEMINI_SEARCH_STATE.reasons[r.id]){{
      tdFund.appendChild(makeEl('div', {{style:'margin-top:4px;padding:3px 6px;background:#ede9fe;color:#4c1d95;border-left:3px solid #6d28d9;border-radius:3px;font-size:10.5px;font-weight:600'}}, '✨ ' + GEMINI_SEARCH_STATE.reasons[r.id]));
    }}
    tdFund.appendChild(makeEl('div', {{style:'font-size:11px;color:var(--accent);font-weight:600;margin-top:2px'}}, r.category));
    var loc = [r.city, r.state, r.country].filter(Boolean).join(', ');
    if(loc) tdFund.appendChild(makeEl('div', {{style:'font-size:10.5px;color:var(--ink3);margin-top:2px'}}, '📍 ' + loc));
    tdFund.appendChild(makeEl('div', {{style:'font-size:9.5px;color:var(--ink3);margin-top:3px'}}, r.source_table));
    tr.appendChild(tdFund);

    // Col 3: Partner, Email & Phone (Plain text only — zero external links)
    var tdPerson = document.createElement('td');
    tdPerson.appendChild(makeEl('div', {{style:'font-weight:700;color:var(--ink)'}}, r.person || 'Partnership Team'));
    if(r.title) tdPerson.appendChild(makeEl('div', {{style:'font-size:11px;color:var(--ink2)'}}, r.title));
    if(r.email){{
      tdPerson.appendChild(makeEl('div', {{style:'font-family:ui-monospace,monospace;font-size:11px;color:var(--ink);margin-top:4px'}}, '✉️ ' + r.email));
    }}
    if(r.mobile_phone){{
      tdPerson.appendChild(makeEl('div', {{style:'font-family:ui-monospace,monospace;font-size:11px;color:var(--quiet);font-weight:700;margin-top:2px'}}, '📱 Mobile: ' + r.mobile_phone));
    }}
    if(r.corporate_phone){{
      tdPerson.appendChild(makeEl('div', {{style:'font-family:ui-monospace,monospace;font-size:11px;color:var(--ink2);margin-top:2px'}}, '☎️ Office: ' + r.corporate_phone));
    }}
    tr.appendChild(tdPerson);

    // Col 4: Fit, Stage, Region & Qualification Gate
    var tdFit = document.createElement('td');
    var tierRow = makeEl('div', {{style:'display:flex;gap:4px;flex-wrap:wrap;align-items:center'}});
    tierRow.appendChild(makeEl('span', {{className:'tier t-' + r.tier}}, 'TIER ' + r.tier + ' · ' + r.dokimo_fit_score));
    tierRow.appendChild(makeEl('span', {{className:'chip', style:'font-weight:700;color:#1e293b'}}, '🌍 ' + (r.region || 'US')));
    if(r.is_pre_seed){{
      tierRow.appendChild(makeEl('span', {{className:'chip', style:'background:#6d28d9;color:#fff;font-weight:700;border:1px solid #6d28d9'}}, '⚡ PRE-SEED'));
    }}
    tdFit.appendChild(tierRow);
    tdFit.appendChild(makeEl('div', {{style:'font-size:10.5px;color:var(--ink2);margin-top:4px;font-weight:600'}}, r.stage));
    tdFit.appendChild(makeEl('div', {{style:'font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink3);margin-top:2px'}}, r.check_size));
    if(r.qualification_gate){{
      var qCls = r.tier === 'B' ? 'qual-badge qual-hold' : 'qual-badge qual-ok';
      tdFit.appendChild(makeEl('div', {{className:qCls}}, r.qualification_gate));
    }}
    tr.appendChild(tdFit);

    // Col 5: Deep Research on Why They Will Listen to Dokimo & Scoring Breakdown
    var tdWhy = document.createElement('td');
    tdWhy.appendChild(makeEl('div', {{style:'color:var(--ink);line-height:1.4'}}, r.why_fit));
    if(r.portfolio){{
      var pDiv = makeEl('div', {{style:'margin-top:5px;font-size:11px;color:var(--ink2)'}});
      pDiv.appendChild(makeEl('b', null, 'Portfolio / Signal: '));
      pDiv.appendChild(document.createTextNode(r.portfolio));
      tdWhy.appendChild(pDiv);
    }}
    if(r.receptivity_breakdown){{
      var scoreBox = makeEl('details', {{style:'margin-top:6px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:4px;padding:4px 7px;font-size:10.5px;color:#1e293b'}});
      scoreBox.appendChild(makeEl('summary', {{style:'cursor:pointer;font-weight:700;color:var(--accent)'}}, '🎯 Scoring Research: Why They Will Listen (' + r.dokimo_fit_score + '/100)'));
      scoreBox.appendChild(makeEl('pre', {{style:'white-space:pre-wrap;margin:5px 0 2px 0;font:10.5px/1.4 ui-monospace,monospace;color:#1e293b'}}, r.receptivity_breakdown));
      tdWhy.appendChild(scoreBox);
    }}
    tr.appendChild(tdWhy);

    // Col 6: Bank LP Value & Pitch Angle
    var tdPitch = document.createElement('td');
    if(r.bank_lp_value){{
      var lpDiv = makeEl('div', {{style:'font-size:11px;color:var(--quiet);font-weight:600;margin-bottom:4px'}}, '🏦 ' + r.bank_lp_value);
      tdPitch.appendChild(lpDiv);
    }}
    var paDiv = makeEl('div', {{style:'font-size:11px;color:var(--ink2)'}});
    paDiv.appendChild(makeEl('b', null, 'Positioning Hook: '));
    paDiv.appendChild(document.createTextNode(r.pitch_angle));
    tdPitch.appendChild(paDiv);
    tr.appendChild(tdPitch);

    // Col 7: Assignment Between Leo & Warren + Pitch Deck Toggle + Review Notes + Same-Click Deep Research & Consistent Email Draft
    var tdAct = document.createElement('td');
    var assignRow = makeEl('div', {{style:'display:flex;align-items:center;gap:4px;margin-bottom:5px;flex-wrap:wrap'}});
    assignRow.appendChild(makeEl('span', {{style:'font-size:10.5px;font-weight:700;color:var(--ink2);text-transform:uppercase'}}, '👤 Assign:'));
    var ownerSel = makeEl('select', {{style:'flex:1;min-width:110px;font-size:11.5px;padding:3px 6px;border:1px solid #2c5f7c;border-radius:3px;background:#f0f9ff;color:#0f172a;font-weight:700'}});
    var curOwner = (r.our_contact || 'Warren / Leo').trim();
    var ownerOpts = ['Warren', 'Leo', 'Warren / Leo'];
    ownerOpts.forEach(function(opt){{
      var o = makeEl('option', {{value:opt}}, opt);
      if(curOwner.toLowerCase() === opt.toLowerCase()) o.selected = true;
      ownerSel.appendChild(o);
    }});
    assignRow.appendChild(ownerSel);

    if((r.total_opens || 0) > 0 || (r.sent_count || 0) > 0){{
      var telBadgeTxt = '📊 Sent:' + (r.sent_count||0) + ' · Opens:' + (r.total_opens||0) + ' · Unique:' + (r.unique_opens||0) + ((r.forward_count||0) > 0 ? (' · 🔁 Fwd:' + r.forward_count) : '');
      assignRow.appendChild(makeEl('span', {{className:'chip', style:'background:#dcfce7;color:#166534;border:1px solid #86efac;font-weight:700;font-size:10px'}}, telBadgeTxt));
    }}
    if((r.sent_count || 0) > 0){{
      var dupRowTxt = '🛡️ Duplicate Guard: Sent by ' + (r.sent_by || 'Warren/Leo') + ' (CC: ' + (r.cc_email || 'leo@dokimo.ai') + ')';
      assignRow.appendChild(makeEl('span', {{className:'chip', style:'background:#fef3c7;color:#92400e;border:1px solid #fcd34d;font-weight:700;font-size:10px'}}, dupRowTxt));
    }} else {{
      var ccHint = (curOwner.toLowerCase() === 'leo') ? 'CC: warren@dokimo.ai' : 'CC: leo@dokimo.ai';
      assignRow.appendChild(makeEl('span', {{className:'chip', style:'background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;font-weight:700;font-size:10px'}}, '👥 Auto-' + ccHint));
    }}

    var deckBtn = makeEl('button', {{
      className:'btn-sm',
      title:'Toggle whether Leo & Warren email drafts include the 18-Slide Seed Pitch Deck + Executive Pitch Video links',
      style: r.include_pitch_deck
        ? 'background:#15803d;color:#fff;border-color:#15803d;font-size:10.5px;padding:3px 8px;font-weight:700'
        : 'background:#f8fafc;color:#475569;border-color:#cbd5e1;font-size:10.5px;padding:3px 8px;font-weight:700'
    }}, r.include_pitch_deck ? '☑️ Send Pitch Deck + Video: YES' : '☐ Send Pitch Deck + Video: NO');
    assignRow.appendChild(deckBtn);
    tdAct.appendChild(assignRow);

    var sel = makeEl('select', {{style:'width:100%;font-size:11.5px;padding:4px 6px;border:1px solid var(--rule2);border-radius:3px;margin-bottom:4px;font-weight:600'}});
    ['Not Contacted', 'Warm Intro Requested', 'Intro Sent', 'Meeting Scheduled', 'Deck / Data Room Sent', 'In Diligence', 'Committed / Term Sheet', 'Passed / Hold'].forEach(function(opt){{
      var o = makeEl('option', {{value:opt}}, opt);
      if((r.latest_status || 'Not Contacted').toLowerCase() === opt.toLowerCase()) o.selected = true;
      sel.appendChild(o);
    }});
    if(['not contacted','warm intro requested','intro sent','meeting scheduled','deck / data room sent','in diligence','committed / term sheet','passed / hold'].indexOf((r.latest_status||'').toLowerCase()) < 0 && r.latest_status){{
      var customOpt = makeEl('option', {{value:r.latest_status}}, r.latest_status);
      customOpt.selected = true;
      sel.appendChild(customOpt);
    }}
    tdAct.appendChild(sel);

    var actDateRow = makeEl('div', {{style:'display:flex;gap:4px;margin-bottom:4px'}});
    var nextActIn = makeEl('input', {{
      type:'text',
      value: r.next_action || r.comment || '',
      placeholder:'Next step for Warren / Leo...',
      style:'flex:1;font-size:11px;padding:4px 6px;border:1px solid var(--rule2);border-radius:3px;background:#fff'
    }});
    var fupDateIn = makeEl('input', {{
      type:'date',
      value: r.follow_up_date || '',
      title:'Follow-Up Date',
      style:'width:112px;font-size:10.5px;padding:3px 4px;border:1px solid var(--rule2);border-radius:3px;background:#fff'
    }});
    var saveBtn = makeEl('button', {{className:'btn-sm'}}, 'Save');
    var statusMsg = makeEl('div', {{style:'font-size:10px;color:var(--quiet);font-weight:600;margin-bottom:3px'}});
    deckBtn.onclick = function(){{
      r.include_pitch_deck = !r.include_pitch_deck;
      deckBtn.textContent = r.include_pitch_deck ? '☑️ Send Pitch Deck + Video: YES' : '☐ Send Pitch Deck + Video: NO';
      deckBtn.style.cssText = r.include_pitch_deck
        ? 'background:#15803d;color:#fff;border-color:#15803d;font-size:10.5px;padding:3px 8px;font-weight:700'
        : 'background:#f8fafc;color:#475569;border-color:#cbd5e1;font-size:10.5px;padding:3px 8px;font-weight:700';
      r.warm_intro_blurb = r.include_pitch_deck ? (r.leo_email_with_deck || r.warm_intro_blurb) : (r.leo_email_no_deck || r.warm_intro_blurb);
      r.direct_email_body = r.include_pitch_deck ? (r.warren_email_with_deck || r.direct_email_body) : (r.warren_email_no_deck || r.direct_email_body);
      saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, ownerSel.value, r.include_pitch_deck, statusMsg);
    }};
    ownerSel.onchange = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, ownerSel.value, r.include_pitch_deck, statusMsg); }};
    sel.onchange = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, ownerSel.value, r.include_pitch_deck, statusMsg); }};
    fupDateIn.onchange = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, ownerSel.value, r.include_pitch_deck, statusMsg); }};
    saveBtn.onclick = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, ownerSel.value, r.include_pitch_deck, statusMsg); }};
    actDateRow.appendChild(nextActIn);
    actDateRow.appendChild(fupDateIn);
    actDateRow.appendChild(saveBtn);
    tdAct.appendChild(actDateRow);
    tdAct.appendChild(statusMsg);

    // Auto-Saving 4-Line Review & Positioning Note Box
    var fupBox = makeEl('div', {{className:'fup-box'}});
    var fupHdr = makeEl('div', {{className:'fup-hdr'}});
    fupHdr.appendChild(makeEl('span', null, '📝 Warren & Leo Review Notes (auto-saves as you type)'));
    var fupSavedSpan = makeEl('span', {{style:'font-weight:600;color:#15803d;text-transform:none'}}, r.followup_updated_at ? ('Saved ' + r.followup_updated_at) : '');
    fupHdr.appendChild(fupSavedSpan);
    fupBox.appendChild(fupHdr);
    var fupTa = makeEl('textarea', {{
      className:'fup-ta',
      rows:'3',
      maxlength:'400',
      placeholder:'Type updates & comments (auto-saves as you type)...'
    }}, r.followup_note || '');
    var _invNoteTimer = null;
    fupTa.oninput = function(){{
      fupSavedSpan.textContent = '⏳ Auto-saving...';
      if(_invNoteTimer) clearTimeout(_invNoteTimer);
      _invNoteTimer = setTimeout(function(){{ saveFollowupNote(r.id, fupTa.value, fupSavedSpan); }}, 350);
    }};
    fupTa.onblur = function(){{ saveFollowupNote(r.id, fupTa.value, fupSavedSpan); }};
    fupBox.appendChild(fupTa);
    tdAct.appendChild(fupBox);

    var btnRow = makeEl('div', {{style:'display:flex;flex-wrap:wrap;gap:4px'}});
    var alreadySent = (r.sent_count || 0) > 0;
    var gemBtn = makeEl('button', {{
      className: alreadySent ? 'btn-sm' : 'btn-sm pri',
      style: alreadySent
        ? 'width:100%;text-align:center;padding:5px 8px;background:#fffbeb;color:#92400e;border-color:#f59e0b;font-weight:700'
        : 'width:100%;text-align:center;padding:5px 8px'
    }}, alreadySent
      ? ('🛡️ Already Emailed by ' + (r.sent_by || 'Team') + ' (Duplicate Guard Active — View / Step-2)')
      : '✨ Review & Send Email Draft (Auto-CC Warren/Leo + Video & Deck)');
    gemBtn.onclick = function(){{ openGeminiModal(r); }};
    btnRow.appendChild(gemBtn);
    tdAct.appendChild(btnRow);
    tr.appendChild(tdAct);

    tbody.appendChild(tr);
  }});
}}

function saveInvestorUpdate(invId, statusVal, nextActVal, fupDateVal, ownerVal, incDeckVal, msgEl){{
  if(msgEl) msgEl.textContent = 'Saving...';
  fetch('/api/investors/update', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id:invId, latest_status:statusVal, next_action:nextActVal, follow_up_date:fupDateVal, assigned_owner:ownerVal, include_pitch_deck:!!incDeckVal}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if(d.ok){{
      if(msgEl) msgEl.textContent = '✓ Assigned: ' + ownerVal + ' · Deck: ' + (incDeckVal ? 'YES' : 'NO') + ' · Saved';
      INVESTORS.forEach(function(item){{
        if(item.id === invId){{
          item.latest_status = statusVal;
          item.next_action = nextActVal;
          item.follow_up_date = fupDateVal;
          item.our_contact = ownerVal;
          item.include_pitch_deck = !!incDeckVal;
        }}
      }});
    }}
  }});
}}

function saveFollowupNote(invId, noteVal, statusSpan){{
  if(statusSpan) statusSpan.textContent = 'Saving...';
  fetch('/api/investors/followup-note', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id:invId, note:noteVal}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if(d.ok){{
      if(statusSpan) statusSpan.textContent = d.updated_at ? ('✓ Saved ' + d.updated_at) : '✓ Saved';
      INVESTORS.forEach(function(item){{
        if(item.id === invId){{
          item.followup_note = d.note;
          item.followup_updated_at = d.updated_at;
        }}
      }});
    }}
  }});
}}

function grantAndEmailLeo(){{
  var emIn = document.getElementById('grant-leo-email');
  var msgEl = document.getElementById('grant-leo-msg');
  var email = ((emIn && emIn.value) || 'leo@s22t.vc').trim();
  if(msgEl) msgEl.textContent = 'Granting & sending access link to ' + email + '...';
  fetch('/api/access/grant', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{email:email, name:'Leo Spiegel'}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if(d.ok){{
      if(msgEl) msgEl.textContent = '✓ Access granted! 1-Click Link: ' + d.url + (d.emailed ? ' (Emailed via Gmail!)' : '');
      var codeEl = document.getElementById('leo-link-code');
      if(codeEl && d.url) codeEl.textContent = d.url;
    }} else {{
      if(msgEl) msgEl.textContent = '⚠ ' + (d.error || 'Failed');
    }}
  }});
}}

function openGeminiModal(r){{
  var modal = document.getElementById('gemini-modal');
  var title = document.getElementById('mod-title');
  var body = document.getElementById('mod-body');
  modal.style.display = 'flex';
  title.textContent = '✨ Review & Approve Email Draft, Pitch Video & 18-Slide Pitch Deck — ' + r.fund + ' (' + (r.person || 'Partnership') + ')';
  body.replaceChildren();

  function buildModalSections(scoreTxt, valPropTxt, leoEmailTxt, warrenEmailTxt, memoTxt){{
    body.replaceChildren();

    var baseDeckUrl = 'https://dokimo-investors-aigeqnv5nq-uc.a.run.app/deck?inv=' + encodeURIComponent(r.id);
    var basePdfUrl = 'https://dokimo-investors-aigeqnv5nq-uc.a.run.app/deck/pdf?inv=' + encodeURIComponent(r.id);
    var baseVideoUrl = 'https://dokimo-investors-aigeqnv5nq-uc.a.run.app/deck?inv=' + encodeURIComponent(r.id) + '#video';
    var baseCalUrl = 'https://calendar.app.google/JbnbVWry32nwqBiY6';
    var pixelUrl = 'https://dokimo-investors-aigeqnv5nq-uc.a.run.app/t/o/' + encodeURIComponent(r.id) + '.gif';

    // SECTION 1 (TOP OF MODAL): 🎬 Executive Pitch Video + 📊 Option to Send Investor Pitch Deck
    var deckToggleBar = makeEl('div', {{style:'padding:14px 16px;background:#f0fdf4;border:2px solid #15803d;border-left:6px solid #15803d;border-radius:6px'}});
    var rcTitleRow = makeEl('div', {{style:'display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px'}});
    rcTitleRow.appendChild(makeEl('div', {{style:'font-weight:800;font-size:14px;color:#0f172a'}}, '1. 🎬 Executive Pitch Video & 📊 Option to Send 18-Slide Investor Pitch Deck (100% Human Approved — You Hit Send)'));
    var deckSaveSpan = makeEl('span', {{style:'font-size:11.5px;color:#15803d;font-weight:700'}});
    rcTitleRow.appendChild(deckSaveSpan);
    deckToggleBar.appendChild(rcTitleRow);

    var deckBtnGroup = makeEl('div', {{style:'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px'}});
    var btnDeckYes = makeEl('button', {{className:'btn-sm', style: r.include_pitch_deck ? 'background:#15803d;color:#fff;border-color:#15803d;padding:6px 12px;font-weight:700' : 'padding:6px 12px;font-weight:700'}}, '✅ Include 18-Slide Pitch Deck + Pitch Video Link in Email');
    var btnDeckNo = makeEl('button', {{className:'btn-sm', style: !r.include_pitch_deck ? 'background:#0f172a;color:#fff;border-color:#0f172a;padding:6px 12px;font-weight:700' : 'padding:6px 12px;font-weight:700'}}, '🚫 First-Touch Note Only (No Deck / Video Link)');
    var attachPdfLabel = makeEl('label', {{style:'display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:700;color:#0f172a;cursor:pointer;padding:5px 10px;background:#fff;border:1px solid #15803d;border-radius:4px'}});
    var attachPdfChk = makeEl('input', {{type:'checkbox', style:'width:auto;margin:0'}});
    attachPdfChk.checked = !!r.include_pitch_deck;
    attachPdfLabel.appendChild(attachPdfChk);
    attachPdfLabel.appendChild(document.createTextNode('📎 Also Attach Raw PDF File (Dokimo_AI_Investor_Pitch_Deck.pdf) to Gmail Draft'));
    var toggleModalVideoBtn = makeEl('button', {{type:'button', className:'btn-sm', style:'background:#0f766e;color:#fff;border-color:#0f766e;padding:6px 12px;font-weight:700'}}, '🎬 Watch Pitch Video Here');
    deckBtnGroup.appendChild(btnDeckYes);
    deckBtnGroup.appendChild(btnDeckNo);
    deckBtnGroup.appendChild(attachPdfLabel);
    deckBtnGroup.appendChild(toggleModalVideoBtn);
    deckToggleBar.appendChild(deckBtnGroup);

    var modalVideoWrap = makeEl('div', {{style:'display:none;margin:8px 0 10px;padding:10px 12px;background:#0f172a;color:#fff;border-radius:6px'}});
    modalVideoWrap.innerHTML =
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-size:12px;font-weight:700;color:#5eead4">' +
        '<span>🎬 Dokimo.ai Executive Pitch Video &amp; Live Bob Walkthrough (Tracked Link for ' + escHtml(r.fund) + ': ' + escHtml(baseVideoUrl) + ')</span>' +
      '</div>' +
      '<video controls preload="metadata" style="width:100%;max-height:340px;background:#000;border-radius:4px"><source src="/deck/video.mp4" type="video/mp4"></video>';
    toggleModalVideoBtn.onclick = function(){{
      var openNow = (modalVideoWrap.style.display === 'none');
      modalVideoWrap.style.display = openNow ? 'block' : 'none';
      toggleModalVideoBtn.textContent = openNow ? '✕ Hide Pitch Video' : '🎬 Watch Pitch Video Here';
    }};
    deckToggleBar.appendChild(modalVideoWrap);

    var chipRow = makeEl('div', {{style:'display:flex;gap:6px;flex-wrap:wrap;align-items:center'}});
    chipRow.appendChild(makeEl('span', {{style:'font-size:11px;font-weight:700;color:#166534'}}, '1-Click Add / Remove in Both Drafts:'));
    var richBlocks = [
      {{label:'📊 + 18-Slide Deck & Video Link', text:'Here is the link to our 18-slide Seed Deck and 90-second product walkthrough:\\n' + baseDeckUrl}},
      {{label:'🎥 + Direct Pitch Video Link', text:'Here is the direct link to our executive pitch video and live Bob walkthrough:\\n' + baseVideoUrl}},
      {{label:'📄 + Direct PDF Deck Link', text:'You can also open or download the 18-slide Seed Deck PDF directly here:\\n' + basePdfUrl}},
      {{label:'📅 + 25-Min Calendar Link', text:'You can also grab a 25-minute slot directly on our calendar here:\\n' + baseCalUrl}},
      {{label:'🏦 + Bank Pilot Proofs', text:'On the commercial side, we have 3 active bank proofs of value with Standard Bank, Synchrony Bank, and Old National Bank, plus channel partnerships in legal review with Guidehouse and KPMG.'}},
      {{label:'⚖️ + $1.7B Enforcement Signal', text:'Between August and October 2026 alone, regulators issued $1.7B in penalties (UBS $125M, American Express $350M, Bank of America $1.2B) over cross-system control gaps that legacy GRC dashboards missed.'}}
    ];
    deckToggleBar.appendChild(chipRow);

    var verifyLinksRow = makeEl('div', {{style:'margin-top:8px;padding-top:6px;border-top:1px dashed #86efac;font-size:11.5px;color:#334155;display:flex;gap:12px;flex-wrap:wrap;align-items:center'}});
    verifyLinksRow.innerHTML = '<b>🔗 Tracked Links for ' + escHtml(r.fund) + ' (Click to Preview):</b> ' +
      '<a href="' + baseVideoUrl + '" target="_blank" rel="noopener" style="color:#0f766e;text-decoration:underline;font-weight:700">🎬 Executive Pitch Video ↗</a> &middot; ' +
      '<a href="' + baseDeckUrl + '" target="_blank" rel="noopener" style="color:#991b1b;text-decoration:underline;font-weight:700">📊 18-Slide Pitch Deck Portal ↗</a> &middot; ' +
      '<a href="' + basePdfUrl + '" target="_blank" rel="noopener" style="color:#15803d;text-decoration:underline;font-weight:700">📄 Downloadable PDF Deck ↗</a> &middot; ' +
      '<a href="' + baseCalUrl + '" target="_blank" rel="noopener" style="color:#1d4ed8;text-decoration:underline;font-weight:700">📅 25-Min Calendar Booking ↗</a>';
    deckToggleBar.appendChild(verifyLinksRow);
    body.appendChild(deckToggleBar);

    // Ask Gemini About This Investor & Auto-Tailor Leo + Warren's Email Drafts
    var askBar = makeEl('div', {{style:'margin-top:10px;padding:10px 12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px'}});
    askBar.appendChild(makeEl('div', {{style:'font-weight:700;font-size:12.5px;color:#1e3a8a;margin-bottom:6px'}}, '🤖 Ask Gemini About ' + r.fund + ' & Auto-Tailor Both Drafts Below'));
    var askRow = makeEl('div', {{style:'display:flex;gap:6px;flex-wrap:wrap'}});
    var askIn = makeEl('input', {{type:'text', placeholder:'Ask Gemini anything about ' + r.fund + ' or specify an angle (e.g. "Focus on their portfolio and our bank LP traction")...', style:'flex:1;min-width:260px;padding:6px 10px;border:1px solid #93c5fd;border-radius:4px;font-size:12px;background:#fff'}});
    var askBtn = makeEl('button', {{className:'btn-sm pri'}}, '✨ Ask Gemini & Tailor Drafts');
    askRow.appendChild(askIn);
    askRow.appendChild(askBtn);
    askBar.appendChild(askRow);
    body.appendChild(askBar);

    function parseSubjAndBody(rawTxt){{
      var raw = rawTxt || '';
      var subj = r.direct_email_subject || ('Dokimo.ai x ' + r.fund);
      var bdy = raw;
      if(raw.indexOf('Subject:') === 0){{
        var nl = raw.indexOf('\\n');
        if(nl > 0){{ subj = raw.slice(8, nl).trim(); bdy = raw.slice(nl+1).replace(/^\\r?\\n/, ''); }}
      }}
      return {{subj:subj, bdy:bdy}};
    }}

    function buildRichHtmlFromPlain(plainBody){{
      var paras = (plainBody || '').split(/\\n\\s*\\n/);
      var htmlOut = '<div dir="ltr" style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;line-height:1.55;color:#0f172a">';
      for(var i=0;i<paras.length;i++){{
        var p = paras[i].trim();
        if(!p) continue;
        var esc = p.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>');
        esc = esc.replace(/(https?:\\/\\/[^\\s<"'\\)]+)/g, function(url){{
          var label = url;
          if(url.indexOf('/deck/pdf') >= 0) label = 'Dokimo.ai 18-Slide Seed Round Pitch Deck (PDF) — ' + url;
          else if(url.indexOf('#video') >= 0) label = 'Dokimo.ai Executive Pitch Video & Live Bob Demo — ' + url;
          else if(url.indexOf('/deck') >= 0) label = 'Dokimo.ai 18-Slide Seed Deck & 90-Second Walkthrough — ' + url;
          else if(url.indexOf('calendar.app.google') >= 0) label = 'Book 25-Minute Walkthrough Calendar — ' + url;
          return '<a href="' + url + '" target="_blank" rel="noopener" style="color:#1d4ed8;text-decoration:underline;font-weight:600">' + label + '</a>';
        }});
        htmlOut += '<p style="margin:0 0 12px 0">' + esc + '</p>';
        if(i === 0){{
          htmlOut += '<img src="' + pixelUrl + '" width="1" height="1" alt="" style="display:block;width:1px;height:1px;border:0;opacity:0" />';
        }}
      }}
      htmlOut += '</div>';
      return htmlOut;
    }}

    function copyRichEmailToClipboard(plainBody, btnEl, openGmailUrl){{
      var richHtml = buildRichHtmlFromPlain(plainBody);
      if(navigator.clipboard && window.ClipboardItem){{
        var item = new ClipboardItem({{
          'text/html': new Blob([richHtml], {{type:'text/html'}}),
          'text/plain': new Blob([plainBody], {{type:'text/plain'}})
        }});
        navigator.clipboard.write([item]).then(function(){{
          if(btnEl) btnEl.textContent = openGmailUrl ? '✓ Rich Email Copied & Gmail Opened (Paste or Hit Send)' : '✓ Copied Rich Email (Links + Tracking Pixel)!';
          if(openGmailUrl) window.open(openGmailUrl, '_blank', 'noopener');
        }}).catch(function(){{
          navigator.clipboard.writeText(plainBody);
          if(btnEl) btnEl.textContent = '✓ Copied!';
          if(openGmailUrl) window.open(openGmailUrl, '_blank', 'noopener');
        }});
      }} else {{
        navigator.clipboard.writeText(plainBody);
        if(btnEl) btnEl.textContent = '✓ Copied!';
        if(openGmailUrl) window.open(openGmailUrl, '_blank', 'noopener');
      }}
    }}

    // DUPLICATE EMAIL PREVENTION GUARD & MUTUAL CC BANNER (WARREN <-> LEO)
    var dupGuardBar = makeEl('div', {{style:'margin-top:12px;padding:12px 14px;border-radius:6px'}});
    var fupUnlockChk = makeEl('input', {{type:'checkbox', style:'width:auto;margin:0'}});
    var fupUnlockLabel = makeEl('label', {{style:'display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;color:#92400e;cursor:pointer;margin-top:6px;background:#fff;padding:4px 10px;border:1px solid #f59e0b;border-radius:4px'}});
    fupUnlockLabel.appendChild(fupUnlockChk);
    fupUnlockLabel.appendChild(document.createTextNode('🔓 Unlock for Intentional Step-2 Follow-Up Email (Still Enforces Mutual CC)'));
    body.appendChild(dupGuardBar);

    var sec2Hdr = makeEl('div', {{style:'display:flex;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap;gap:6px'}});
    sec2Hdr.appendChild(makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--quiet)'}}, '2. Human-Approved Email Draft for Leo Spiegel <leo@dokimo.ai> · Auto-CC: Warren Zafrin <warren@dokimo.ai>'));
    var leoBtnGrp = makeEl('div', {{style:'display:flex;gap:6px;flex-wrap:wrap'}});
    var saveLeoDraftBtn = makeEl('button', {{className:'btn-sm ok', style:'background:#15803d;color:#fff;border-color:#15803d'}}, '📝 Save to Gmail Drafts (Leo -> CC Warren)');
    var openLeoEmailBtn = makeEl('button', {{className:'btn-sm pri'}}, '✉️ Copy Rich + Open Gmail (Leo -> CC Warren)');
    var copyLeoRichBtn = makeEl('button', {{className:'btn-sm'}}, '✨ Copy Rich Content');
    var dlLeoEmlBtn = makeEl('button', {{className:'btn-sm'}}, '📥 .EML Draft (CC Warren)');
    var leoHdrMeta = makeEl('div', {{style:'margin-top:6px;padding:6px 10px;background:#ecfdf5;border:1px solid #6ee7b7;border-radius:4px;font:11.5px/1.4 ui-monospace,monospace;color:#065f46'}});
    leoHdrMeta.innerHTML = '<b>From:</b> Leo Spiegel &lt;leo@dokimo.ai&gt; &nbsp;|&nbsp; <b>To:</b> ' + escHtml(r.email || '') + ' &nbsp;|&nbsp; <b>CC (Automatic):</b> <span style="background:#065f46;color:#fff;padding:1px 6px;border-radius:3px;font-weight:700">Warren Zafrin &lt;warren@dokimo.ai&gt;</span>';
    var leoTa = makeEl('textarea', {{style:'width:100%;min-height:185px;font:12px/1.5 ui-monospace,monospace;padding:10px;border:1px solid var(--rule2);border-radius:6px;margin-top:6px'}}, leoEmailTxt);
    var leoPreview = makeEl('div', {{style:'margin-top:6px;padding:10px 12px;background:#ffffff;border:1px dashed #cbd5e1;border-radius:6px;font-size:12.5px'}});

    var sec3Hdr = makeEl('div', {{style:'display:flex;justify-content:space-between;align-items:center;margin-top:14px;flex-wrap:wrap;gap:6px'}});
    sec3Hdr.appendChild(makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--ink)'}}, '3. Human-Approved Email Draft for Warren Zafrin <warren@dokimo.ai> · Auto-CC: Leo Spiegel <leo@dokimo.ai>'));
    var warrenBtnGrp = makeEl('div', {{style:'display:flex;gap:6px;flex-wrap:wrap'}});
    var saveWarrenDraftBtn = makeEl('button', {{className:'btn-sm ok', style:'background:#15803d;color:#fff;border-color:#15803d'}}, '📝 Save to Gmail Drafts (Warren -> CC Leo)');
    var openWarrenEmailBtn = makeEl('button', {{className:'btn-sm pri'}}, '✉️ Copy Rich + Open Gmail (Warren -> CC Leo)');
    var copyWarrenRichBtn = makeEl('button', {{className:'btn-sm'}}, '✨ Copy Rich Content');
    var dlWarrenEmlBtn = makeEl('button', {{className:'btn-sm'}}, '📥 .EML Draft (CC Leo)');
    var warrenHdrMeta = makeEl('div', {{style:'margin-top:6px;padding:6px 10px;background:#eff6ff;border:1px solid #93c5fd;border-radius:4px;font:11.5px/1.4 ui-monospace,monospace;color:#1e3a8a'}});
    warrenHdrMeta.innerHTML = '<b>From:</b> Warren Zafrin &lt;warren@dokimo.ai&gt; &nbsp;|&nbsp; <b>To:</b> ' + escHtml(r.email || '') + ' &nbsp;|&nbsp; <b>CC (Automatic):</b> <span style="background:#1e3a8a;color:#fff;padding:1px 6px;border-radius:3px;font-weight:700">Leo Spiegel &lt;leo@dokimo.ai&gt;</span>';
    var warrenTa = makeEl('textarea', {{style:'width:100%;min-height:185px;font:12px/1.5 ui-monospace,monospace;padding:10px;border:1px solid var(--rule2);border-radius:6px;margin-top:6px'}}, warrenEmailTxt);
    var warrenPreview = makeEl('div', {{style:'margin-top:6px;padding:10px 12px;background:#ffffff;border:1px dashed #cbd5e1;border-radius:6px;font-size:12.5px'}});

    function syncDuplicateGuardUi(){{
      var isSent = (r.sent_count || 0) > 0;
      var blocked = isSent && !fupUnlockChk.checked;
      dupGuardBar.replaceChildren();
      if(isSent){{
        dupGuardBar.style.cssText = 'margin-top:12px;padding:12px 14px;background:#fffbeb;border:2px solid #f59e0b;border-left:6px solid #d97706;border-radius:6px';
        var warnTitle = makeEl('div', {{style:'font-weight:800;font-size:13px;color:#92400e'}}, '🛡️ DUPLICATE EMAIL GUARD ACTIVE — Already Contacted (' + (r.sent_count || 1) + ' prior send' + ((r.sent_count||1)>1?'s':'') + ')');
        var warnSub = makeEl('div', {{style:'font-size:12px;color:#78350f;margin-top:3px'}},
          'Sent by ' + (r.sent_by || 'Warren Zafrin') + (r.sent_at ? (' on ' + r.sent_at) : '') +
          ' to ' + (r.email || r.fund) + ' (Auto-CC: ' + (r.cc_email || 'leo@dokimo.ai') + '). ' +
          'Duplicate initial outreach is blocked so neither Warren nor Leo can accidentally send a second email to the same investor.'
        );
        dupGuardBar.appendChild(warnTitle);
        dupGuardBar.appendChild(warnSub);
        dupGuardBar.appendChild(fupUnlockLabel);
      }} else {{
        dupGuardBar.style.cssText = 'margin-top:12px;padding:10px 14px;background:#f0fdf4;border:1px solid #86efac;border-left:5px solid #15803d;border-radius:6px;font-size:12px;color:#14532d';
        dupGuardBar.innerHTML = '<b>🛡️ Duplicate Email Guard &amp; Mutual Auto-CC Active:</b> Ready for First-Touch Outreach (<b>0 prior sends</b> to <code>' + escHtml(r.email || '') + '</code>). ' +
          'When <b>Warren</b> sends, <b>Leo (<code>leo@dokimo.ai</code>)</b> is automatically CC\\'d. When <b>Leo</b> sends, <b>Warren (<code>warren@dokimo.ai</code>)</b> is automatically CC\\'d.';
      }}
      [saveLeoDraftBtn, openLeoEmailBtn, dlLeoEmlBtn, saveWarrenDraftBtn, openWarrenEmailBtn, dlWarrenEmlBtn].forEach(function(b){{
        b.disabled = blocked;
        b.style.opacity = blocked ? '0.45' : '1';
        b.style.cursor = blocked ? 'not-allowed' : 'pointer';
      }});
    }}
    fupUnlockChk.onchange = syncDuplicateGuardUi;

    function markInvestorSentInUi(senderName, senderEmail, ccEmail, sentAtStr){{
      r.sent_count = (r.sent_count || 0) + 1;
      r.sent_by = senderName;
      r.sender_email = senderEmail;
      r.cc_email = ccEmail;
      r.sent_at = sentAtStr || 'Just now';
      r.duplicate_blocked = true;
      if(r.include_pitch_deck) r.latest_status = 'Deck / Data Room Sent';
      else if(!r.latest_status || r.latest_status.toLowerCase() === 'not contacted') r.latest_status = 'Intro Sent';
      fupUnlockChk.checked = false;
      syncDuplicateGuardUi();
      renderRows();
    }}

    function updatePreviews(){{
      var sbL = parseSubjAndBody(leoTa.value);
      leoPreview.innerHTML = '<div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:4px">👁️ Live Rich Email Preview (Auto-CC: warren@dokimo.ai + Clickable Video &amp; Pitch Deck Links + Open Pixel):</div>' + buildRichHtmlFromPlain(sbL.bdy);
      var sbW = parseSubjAndBody(warrenTa.value);
      warrenPreview.innerHTML = '<div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:4px">👁️ Live Rich Email Preview (Auto-CC: leo@dokimo.ai + Clickable Video &amp; Pitch Deck Links + Open Pixel):</div>' + buildRichHtmlFromPlain(sbW.bdy);
    }}

    saveLeoDraftBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var sb = parseSubjAndBody(leoTa.value);
      saveLeoDraftBtn.disabled = true;
      saveLeoDraftBtn.textContent = '⏳ Saving Unsent Draft to Gmail (CC: warren@dokimo.ai)...';
      fetch('/api/investors/create-draft', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{id:r.id, sender:'leo', to_email:r.email, subject:sb.subj, body:sb.bdy, include_pitch_deck:!!r.include_pitch_deck, attach_pdf:!!attachPdfChk.checked, force_followup:!!fupUnlockChk.checked}})
      }}).then(function(res){{ return res.json(); }}).then(function(d){{
        if(!d.ok){{
          syncDuplicateGuardUi();
          alert(d.error || 'Could not create draft');
          saveLeoDraftBtn.textContent = '📝 Save to Gmail Drafts (Leo -> CC Warren)';
          return;
        }}
        markInvestorSentInUi('Leo Spiegel', 'leo@dokimo.ai', d.cc_email || 'warren@dokimo.ai', d.sent_at);
        saveLeoDraftBtn.textContent = '✓ Saved in Gmail Drafts (CC: warren@dokimo.ai)';
        window.open('https://mail.google.com/mail/u/0/#drafts', '_blank', 'noopener');
      }});
    }};
    dlLeoEmlBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var ff = fupUnlockChk.checked ? '1' : '0';
      window.open('/api/investors/eml?id=' + encodeURIComponent(r.id) + '&sender=leo&deck=' + (r.include_pitch_deck ? '1' : '0') + '&attach=' + (attachPdfChk.checked ? '1' : '0') + '&force_followup=' + ff, '_blank');
      markInvestorSentInUi('Leo Spiegel', 'leo@dokimo.ai', 'warren@dokimo.ai', 'Just now');
    }};
    openLeoEmailBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var sb = parseSubjAndBody(leoTa.value);
      fetch('/api/investors/record-outreach', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{id:r.id, sender:'leo', to_email:r.email, subject:sb.subj, include_pitch_deck:!!r.include_pitch_deck, force_followup:!!fupUnlockChk.checked}})
      }}).then(function(res){{ return res.json(); }}).then(function(d){{
        if(!d.ok){{
          syncDuplicateGuardUi();
          alert(d.error || 'Duplicate email blocked');
          return;
        }}
        markInvestorSentInUi('Leo Spiegel', 'leo@dokimo.ai', d.cc_email || 'warren@dokimo.ai', (d.state && d.state.sent_at) || 'Just now');
        var u = 'https://mail.google.com/mail/?view=cm&fs=1&to=' + encodeURIComponent(r.email || '') + '&cc=' + encodeURIComponent('warren@dokimo.ai') + '&su=' + encodeURIComponent(sb.subj) + '&body=' + encodeURIComponent(sb.bdy);
        copyRichEmailToClipboard(sb.bdy, openLeoEmailBtn, u);
      }});
    }};
    copyLeoRichBtn.onclick = function(){{
      var sb = parseSubjAndBody(leoTa.value);
      copyRichEmailToClipboard(sb.bdy, copyLeoRichBtn, null);
    }};
    leoTa.oninput = updatePreviews;
    if(window.CAN_SEND_INVESTOR_EMAILS !== false){{
      leoBtnGrp.appendChild(saveLeoDraftBtn);
      leoBtnGrp.appendChild(openLeoEmailBtn);
      leoBtnGrp.appendChild(copyLeoRichBtn);
      leoBtnGrp.appendChild(dlLeoEmlBtn);
    }} else {{
      leoTa.readOnly = true;
      leoBtnGrp.appendChild(makeEl('span', {{style:'background:#fef2f2;color:#991b1b;border:1px solid #fecaca;padding:4px 10px;border-radius:4px;font-size:11.5px;font-weight:700'}}, '🔒 Read-Only: Only Leo Spiegel & Warren Zafrin Can Draft/Send Investor Emails'));
    }}
    sec2Hdr.appendChild(leoBtnGrp);
    body.appendChild(sec2Hdr);
    body.appendChild(leoHdrMeta);
    body.appendChild(leoTa);
    body.appendChild(leoPreview);

    saveWarrenDraftBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var sb = parseSubjAndBody(warrenTa.value);
      saveWarrenDraftBtn.disabled = true;
      saveWarrenDraftBtn.textContent = '⏳ Saving Unsent Draft to Gmail (CC: leo@dokimo.ai)...';
      fetch('/api/investors/create-draft', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{id:r.id, sender:'warren', to_email:r.email, subject:sb.subj, body:sb.bdy, include_pitch_deck:!!r.include_pitch_deck, attach_pdf:!!attachPdfChk.checked, force_followup:!!fupUnlockChk.checked}})
      }}).then(function(res){{ return res.json(); }}).then(function(d){{
        if(!d.ok){{
          syncDuplicateGuardUi();
          alert(d.error || 'Could not create draft');
          saveWarrenDraftBtn.textContent = '📝 Save to Gmail Drafts (Warren -> CC Leo)';
          return;
        }}
        markInvestorSentInUi('Warren Zafrin', 'warren@dokimo.ai', d.cc_email || 'leo@dokimo.ai', d.sent_at);
        saveWarrenDraftBtn.textContent = '✓ Saved in Gmail Drafts (CC: leo@dokimo.ai)';
        window.open('https://mail.google.com/mail/u/0/#drafts', '_blank', 'noopener');
      }});
    }};
    dlWarrenEmlBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var ff = fupUnlockChk.checked ? '1' : '0';
      window.open('/api/investors/eml?id=' + encodeURIComponent(r.id) + '&sender=warren&deck=' + (r.include_pitch_deck ? '1' : '0') + '&attach=' + (attachPdfChk.checked ? '1' : '0') + '&force_followup=' + ff, '_blank');
      markInvestorSentInUi('Warren Zafrin', 'warren@dokimo.ai', 'leo@dokimo.ai', 'Just now');
    }};
    openWarrenEmailBtn.onclick = function(){{
      if((r.sent_count || 0) > 0 && !fupUnlockChk.checked){{
        alert('🛡️ Duplicate Email Blocked: ' + (r.sent_by || 'Warren/Leo') + ' already contacted ' + (r.email || r.fund) + '.');
        return;
      }}
      var sb = parseSubjAndBody(warrenTa.value);
      fetch('/api/investors/record-outreach', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{id:r.id, sender:'warren', to_email:r.email, subject:sb.subj, include_pitch_deck:!!r.include_pitch_deck, force_followup:!!fupUnlockChk.checked}})
      }}).then(function(res){{ return res.json(); }}).then(function(d){{
        if(!d.ok){{
          syncDuplicateGuardUi();
          alert(d.error || 'Duplicate email blocked');
          return;
        }}
        markInvestorSentInUi('Warren Zafrin', 'warren@dokimo.ai', d.cc_email || 'leo@dokimo.ai', (d.state && d.state.sent_at) || 'Just now');
        var u = 'https://mail.google.com/mail/?view=cm&fs=1&to=' + encodeURIComponent(r.email || '') + '&cc=' + encodeURIComponent('leo@dokimo.ai') + '&su=' + encodeURIComponent(sb.subj) + '&body=' + encodeURIComponent(sb.bdy);
        copyRichEmailToClipboard(sb.bdy, openWarrenEmailBtn, u);
      }});
    }};
    copyWarrenRichBtn.onclick = function(){{
      var sb = parseSubjAndBody(warrenTa.value);
      copyRichEmailToClipboard(sb.bdy, copyWarrenRichBtn, null);
    }};
    warrenTa.oninput = updatePreviews;
    if(window.CAN_SEND_INVESTOR_EMAILS !== false){{
      warrenBtnGrp.appendChild(saveWarrenDraftBtn);
      warrenBtnGrp.appendChild(openWarrenEmailBtn);
      warrenBtnGrp.appendChild(copyWarrenRichBtn);
      warrenBtnGrp.appendChild(dlWarrenEmlBtn);
    }} else {{
      warrenTa.readOnly = true;
      warrenBtnGrp.appendChild(makeEl('span', {{style:'background:#fef2f2;color:#991b1b;border:1px solid #fecaca;padding:4px 10px;border-radius:4px;font-size:11.5px;font-weight:700'}}, '🔒 Read-Only: Only Leo Spiegel & Warren Zafrin Can Draft/Send Investor Emails'));
    }}
    sec3Hdr.appendChild(warrenBtnGrp);
    body.appendChild(sec3Hdr);
    body.appendChild(warrenHdrMeta);
    body.appendChild(warrenTa);
    body.appendChild(warrenPreview);
    syncDuplicateGuardUi();

    function toggleSnippetInTextarea(ta, snippetText){{
      var val = ta.value || '';
      if(val.indexOf(snippetText) >= 0){{
        ta.value = val.replace('\\n\\n' + snippetText, '').replace(snippetText + '\\n\\n', '').replace(snippetText, '');
      }} else {{
        var signIdx = val.lastIndexOf('\\n\\nBest');
        if(signIdx > 0){{
          ta.value = val.slice(0, signIdx) + '\\n\\n' + snippetText + val.slice(signIdx);
        }} else {{
          ta.value = val + '\\n\\n' + snippetText;
        }}
      }}
    }}

    richBlocks.forEach(function(rb){{
      var chip = makeEl('button', {{className:'btn-sm', style:'background:#fff;border-color:#86efac;color:#166534;font-weight:700;padding:4px 8px'}}, rb.label);
      chip.onclick = function(){{
        toggleSnippetInTextarea(leoTa, rb.text);
        toggleSnippetInTextarea(warrenTa, rb.text);
        var active = leoTa.value.indexOf(rb.text) >= 0;
        chip.style.cssText = active
          ? 'background:#15803d;border-color:#15803d;color:#fff;font-weight:700;padding:4px 8px'
          : 'background:#fff;border-color:#86efac;color:#166534;font-weight:700;padding:4px 8px';
        updatePreviews();
      }};
      chipRow.appendChild(chip);
    }});

    updatePreviews();

    askBtn.onclick = function(){{
      var qVal = (askIn.value || '').trim();
      if(!qVal) return;
      askBtn.disabled = true;
      askBtn.textContent = '⏳ Gemini Tailoring Drafts & Memo...';
      fetch('/api/investors/research', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{id:r.id, custom_focus:qVal}})
      }}).then(function(res){{ return res.json(); }}).then(function(d){{
        buildModalSections(
          d.receptivity_breakdown || r.receptivity_breakdown || r.why_fit,
          d.canonical_value_prop || r.canonical_value_prop || '',
          d.warm_intro_blurb || r.warm_intro_blurb || '',
          'Subject: ' + (d.direct_email_subject || r.direct_email_subject || '') + '\\n\\n' + (d.direct_email_body || r.direct_email_body || ''),
          d.memo || r.why_fit
        );
      }});
    }};

    function setDeckMode(incDeck){{
      r.include_pitch_deck = !!incDeck;
      attachPdfChk.checked = !!incDeck;
      btnDeckYes.style.cssText = r.include_pitch_deck ? 'background:#15803d;color:#fff;border-color:#15803d;padding:6px 12px;font-weight:700' : 'padding:6px 12px;font-weight:700';
      btnDeckNo.style.cssText = !r.include_pitch_deck ? 'background:#0f172a;color:#fff;border-color:#0f172a;padding:6px 12px;font-weight:700' : 'padding:6px 12px;font-weight:700';
      leoTa.value = r.include_pitch_deck ? (r.leo_email_with_deck || leoEmailTxt) : (r.leo_email_no_deck || leoEmailTxt);
      warrenTa.value = 'Subject: ' + (r.direct_email_subject || '') + '\\n\\n' + (r.include_pitch_deck ? (r.warren_email_with_deck || r.direct_email_body) : (r.warren_email_no_deck || r.direct_email_body));
      r.warm_intro_blurb = leoTa.value;
      r.direct_email_body = r.include_pitch_deck ? (r.warren_email_with_deck || r.direct_email_body) : (r.warren_email_no_deck || r.direct_email_body);
      updatePreviews();
      saveInvestorUpdate(r.id, r.latest_status, r.next_action, r.follow_up_date, r.our_contact, r.include_pitch_deck, deckSaveSpan);
      renderRows();
    }}
    btnDeckYes.onclick = function(){{ setDeckMode(true); }};
    btnDeckNo.onclick = function(){{ setDeckMode(false); }};

    // SECTIONS 4, 5 & 6: Deep Research & IC Positioning Memo (Below Drafts)
    var sec0 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:#6d28d9;margin-top:16px'}}, '4. Receptivity Scoring Research — Why ' + r.fund + ' Will Listen to Dokimo (' + r.dokimo_fit_score + '/100 · Tier ' + r.tier + ')');
    body.appendChild(sec0);
    body.appendChild(makeEl('pre', {{className:'memo', style:'background:#f5f3ff;border-color:#c4b5fd'}}, scoreTxt));

    var sec1 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--accent);margin-top:12px'}}, '5. Canonical Dokimo Value Proposition (Single Source of Truth for Leo & Warren)');
    body.appendChild(sec1);
    body.appendChild(makeEl('pre', {{className:'memo', style:'background:#f0f9ff;border-color:#bae6fd'}}, valPropTxt));

    var sec4 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--accent);margin-top:14px'}}, '6. Gemini 5-Part Investment Committee (IC) Deep-Dive Positioning Memo');
    body.appendChild(sec4);
    body.appendChild(makeEl('pre', {{id:'mod-ic-memo-pre', className:'memo'}}, memoTxt));
  }}

  // Render immediately with deterministic research & drafts, then enrich Sec 6 in place when Gemini returns
  buildModalSections(
    r.receptivity_breakdown || r.why_fit,
    r.canonical_value_prop || '',
    r.warm_intro_blurb || '',
    'Subject: ' + (r.direct_email_subject || '') + '\\n\\n' + (r.direct_email_body || ''),
    'Running Gemini 2.5 Flash 5-Part IC Deep-Dive Positioning Memo on ' + r.fund + '...'
  );

  fetch('/api/investors/research', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id:r.id}})
  }}).then(function(res){{ return res.json(); }}).then(function(d){{
    var memoEl = document.getElementById('mod-ic-memo-pre');
    if(memoEl && d && d.memo){{
      memoEl.textContent = d.memo;
    }}
  }});
}}

function closeModal(){{
  document.getElementById('gemini-modal').style.display = 'none';
}}

function sweepGmailTracker(){{
  var btn = document.getElementById('btn-sweep-gmail');
  if(!btn) return;
  btn.disabled = true;
  btn.textContent = '⏳ Sweeping Gmail across all 113 VCs...';
  fetch('/api/investors/sync-gmail', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{}})
  }}).then(function(res){{ return res.json(); }}).then(function(d){{
    btn.disabled = false;
    btn.textContent = '🔄 Sweep Gmail & Update Tracker';
    if(!d || !d.ok){{
      alert((d && d.error) || 'Gmail sweep failed');
      return;
    }}
    alert('✅ Gmail Sweep Complete!\\n\\n• Sent Funds Reconciled: ' + d.sent_reconciled + ' of ' + d.total_investors + '\\n• Replies Reconciled: ' + d.replies_reconciled + ' of ' + d.sent_reconciled + '\\n• Swept At: ' + d.swept_at);
    window.location.reload();
  }}).catch(function(err){{
    btn.disabled = false;
    btn.textContent = '🔄 Sweep Gmail & Update Tracker';
    alert('Error running Gmail sweep: ' + err);
  }});
}}

renderRows();
(function(){{
  var qs = window.location.search || '';
  if(qs.indexOf('tab=charts')>=0 || window.location.pathname==='/telemetry') switchInvMainTab('charts');
  else if(qs.indexOf('tab=todo')>=0) switchInvMainTab('todo');
  else if(qs.indexOf('tab=readme')>=0 || window.location.pathname==='/readme') switchInvMainTab('readme');
}})();
</script>
</body></html>"""


def render_report_html() -> str:
    rep = investor_engine.build_executive_vc_report()
    m = rep["metrics"]

    def _render_cards(items: list[dict], badge_cls: str) -> str:
        out = []
        for r in items:
            em_str = f" · ✉️ {html.escape(r['email'])}" if r.get("email") else ""
            ph_str = f" · 📱 {html.escape(r['display_phone'])}" if r.get("display_phone") else ""
            out.append(f"""
            <div style="background:#fff;border:1px solid var(--rule);border-radius:6px;padding:12px 14px;margin-bottom:8px">
              <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px">
                <div>
                  <span class="tier {badge_cls}">#{r['rank']} · TIER {html.escape(r['tier'])} ({r['dokimo_fit_score']}/100)</span>
                  <b style="font-size:14.5px;margin-left:6px">{html.escape(r['fund'])}</b>
                  <span style="color:var(--ink2);font-weight:600"> — {html.escape(r['person'] or 'Partnership')} ({html.escape(r['title'] or 'Partner')})</span>
                </div>
                <div style="font-family:ui-monospace,monospace;font-size:11.5px;color:var(--ink2)">
                  <b>Our Contact:</b> {html.escape(r['our_contact'])}{em_str}{ph_str}
                </div>
              </div>
              <div style="margin-top:6px;font-size:12.5px;color:var(--ink)"><b>Why Right for Dokimo:</b> {html.escape(r['why_fit'])}</div>
              <div style="margin-top:4px;font-size:12px;color:var(--quiet);font-weight:600">🏦 <b>Bank LP / Customer Network Value:</b> {html.escape(r['bank_lp_value'])}</div>
              <div style="margin-top:4px;font-size:12px;color:var(--ink2)">🎯 <b>Recommended Pitch Hook:</b> {html.escape(r['pitch_angle'])}</div>
            </div>
            """)
        return "".join(out)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Executive VC Research Report · Who Is the Right VC for Dokimo?</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>📊 Executive Research Report: Who Is the Right VC for Dokimo.ai?</h1>
    <div class="sub">
      Comprehensive analysis of Leo &amp; Warren's 4 investor tables (<b>{m['total_investors']} total investor records</b>), separating high-conviction FinTech, RegTech, Bank-LP Strategic, and Enterprise AI leads from semiconductor/hardware funds.
    </div>
  </div>
  <div class="runbox">
    Generated <b>{html.escape(rep['generated_at'])}</b><br>
    Tier S Bullseye: <b>{html.escape(m['tier_s_rate'])}</b><br>
    Tier A Enterprise AI: <b>{html.escape(m['tier_a_rate'])}</b>
  </div>
</header>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-left:4px solid #1e40af;border-radius:6px;padding:14px 16px;margin:14px 0;font-size:13.5px;line-height:1.55">
  <b>🔎 Executive Thesis &amp; List Triage Diagnosis:</b><br>
  {html.escape(rep['executive_thesis'])}
</div>

<h2 style="margin:18px 0 8px;font-size:17px;color:var(--quiet)">Wave 1: Bank-LP Alliances, Former Regulators &amp; Strategic Bank CVCs (Invest + Become Commercial Customers)</h2>
<p style="margin:0 0 10px;color:var(--ink2);font-size:12.5px">
  These funds are backed by banks or regulated financial institutions (or led by former bank regulators like OCC Comptroller Eugene Ludwig). Every partner introduction here doubles as a commercial enterprise sales channel for Dokimo:
</p>
{_render_cards(rep['wave1_bank_lp_and_strategics'], 't-S')}

<h2 style="margin:22px 0 8px;font-size:17px;color:var(--accent)">Wave 2: Pure-Play FinTech, RegTech &amp; Compliance Infrastructure Lead VCs</h2>
<p style="margin:0 0 10px;color:var(--ink2);font-size:12.5px">
  These funds backed the first wave of identity/KYC and AML tools (Chainalysis, Alloy, Socure, ComplyAdvantage, Hummingbird, Harvey) and immediately understand why regulated institutions need 100% full-population operational record validation + Bob's explainable remediation:
</p>
{_render_cards(rep['wave2_fintech_regtech_leads'], 't-S')}

<h2 style="margin:22px 0 8px;font-size:17px;color:#1e293b">Wave 3: Tier-1 Enterprise AI, Cyber &amp; B2B Software Lead VCs</h2>
<p style="margin:0 0 10px;color:var(--ink2);font-size:12.5px">
  Multi-stage and Enterprise AI leaders with warm intro paths via Warren and Leo:
</p>
{_render_cards(rep['wave3_enterprise_ai_leads'], 't-A')}

<h2 style="margin:22px 0 8px;font-size:17px;color:var(--critical)">Wave 4: Semiconductor, Silicon &amp; Hardware Funds from Leo's AINekko/Veevx List — Deprioritize ({html.escape(m['tier_c_rate'])})</h2>
<p style="margin:0 0 10px;color:var(--ink2);font-size:12.5px">
  These funds from Tables 2, 3, and 4 focus on wafer manufacturing, edge silicon, optical interconnects, or real estate. Do not spend founder cycles pitching them for Dokimo's software/AI round:
</p>
{_render_cards(rep['deprioritize_hardware_funds'], 't-C')}
</body></html>"""


def render_outreach_html() -> str:
    rows = investor_engine.get_all_investors(persist_csv=False)
    top_targets = [r for r in rows if r["tier"] in ("S", "A")][:35]
    cards = []
    for r in top_targets:
        gm_warren_url = (
            "https://mail.google.com/mail/?view=cm&fs=1"
            + "&to=" + urllib.parse.quote(r.get("email") or "")
            + "&cc=" + urllib.parse.quote("leo@dokimo.ai")
            + "&su=" + urllib.parse.quote(r["direct_email_subject"])
            + "&body=" + urllib.parse.quote(r["direct_email_body"])
        )
        gm_leo_url = (
            "https://mail.google.com/mail/?view=cm&fs=1"
            + "&to=" + urllib.parse.quote(r.get("email") or "")
            + "&cc=" + urllib.parse.quote("warren@dokimo.ai")
            + "&su=" + urllib.parse.quote(r["direct_email_subject"])
            + "&body=" + urllib.parse.quote(r["warm_intro_blurb"])
        )
        sent_cnt = int(r.get("sent_count") or 0)
        if sent_cnt > 0:
            action_btns_html = (
                f'<span class="chip warn" style="padding:5px 10px;font-weight:700">'
                f'🛡️ Duplicate Guard Active: Already Emailed by {html.escape(r.get("sent_by") or "Warren/Leo")} '
                f'(CC: {html.escape(r.get("cc_email") or "leo@dokimo.ai")})</span>'
            )
        else:
            action_btns_html = (
                f'<a class="btn-sm ok" href="{html.escape(gm_warren_url, quote=True)}" target="_blank" rel="noopener">'
                f'✉️ Warren Gmail (Auto-CC: leo@dokimo.ai)</a>'
                f'<a class="btn-sm pri" href="{html.escape(gm_leo_url, quote=True)}" target="_blank" rel="noopener">'
                f'✉️ Leo Gmail (Auto-CC: warren@dokimo.ai)</a>'
            )
        cards.append(f"""
        <div style="background:#fff;border:1px solid var(--rule);border-radius:6px;padding:14px 16px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
            <div>
              <span class="tier t-{html.escape(r['tier'])}">#{r['rank']} · TIER {html.escape(r['tier'])} ({r['dokimo_fit_score']})</span>
              <b style="font-size:15px;margin-left:6px">{html.escape(r['fund'])}</b> — {html.escape(r['person'] or 'Partnership')}
              <span class="chip ok" style="margin-left:6px">Warm Contact: {html.escape(r['our_contact'])}</span>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
              <a class="btn-sm" style="background:#0f172a;color:#fff;border-color:#0f172a" href="/api/investors/pdf-memo?id={urllib.parse.quote(r['id'])}" target="_blank" rel="noopener">📄 1-Click 2-Page PDF VC Tear-Sheet</a>
              {action_btns_html}
              <a class="btn-sm" href="{html.escape(r.get('person_linkedin') or '#', quote=True)}" target="_blank" rel="noopener">in LinkedIn ↗</a>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:10px">
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase">A. Forwardable Warm-Intro Blurb (From Leo &lt;leo@dokimo.ai&gt; · Auto-CC: warren@dokimo.ai)</div>
              <pre class="memo">{html.escape(r['warm_intro_blurb'])}</pre>
            </div>
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--quiet);text-transform:uppercase">B. Direct Founder Email (From Warren &lt;warren@dokimo.ai&gt; · Auto-CC: leo@dokimo.ai)</div>
              <pre class="memo">Subject: {html.escape(r['direct_email_subject'])}\n\n{html.escape(r['direct_email_body'])}</pre>
            </div>
          </div>
        </div>
        """)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leo &amp; Warren Investor Outreach Studio · Dokimo.ai</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>✉️ Leo &amp; Warren Investor Outreach Studio (Top 35 Tier-S &amp; Tier-A Targets)</h1>
    <div class="sub">Ready-to-send forwardable warm-intro blurbs for Leo and direct founder emails for Warren Zafrin, tailored to each fund's thesis and portfolio.</div>
  </div>
</header>
<div style="margin-top:14px">{''.join(cards)}</div>
</body></html>"""


def render_digest_html(mode: str = "daily") -> str:
    payload = investor_digest.build_digest_payload(mode=mode)
    m = payload["metrics"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Investor Pipeline Digest &amp; Follow-Up Center · Dokimo.ai</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>📬 Daily &amp; Weekly Investor Pipeline Digest (Decks Sent, Opens &amp; Priority Follow-Ups)</h1>
    <div class="sub">
      Automated <b>Daily 7:00 AM EST</b> &amp; <b>Friday 4:30 PM EST Weekly</b> Investor Pipeline Digest to <b>warren@dokimo.ai</b> and <b>Leo</b> — tracking which Tier-S and Tier-A VCs received decks, opened tracked pitch links, downloaded 2-page PDF Tear-Sheets, or need a follow-up today.
    </div>
  </div>
  <div class="runbox">
    Enriched Contacts: <b>{html.escape(m['with_email_rate'])}</b><br>
    LinkedIn Profiles: <b>{html.escape(m['with_linkedin_rate'])}</b><br>
    Decks Sent / Engaged: <b>{html.escape(m['decks_sent_rate'])}</b>
  </div>
</header>

<div class="controls-wrap" style="margin-top:12px">
  <div class="controls" style="justify-content:space-between">
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <span class="lbl">Digest Mode</span>
      <a class="f {'on' if mode != 'weekly' else ''}" href="/digest?mode=daily" style="text-decoration:none">☀️ Daily 7:00 AM EST Digest</a>
      <a class="f {'on' if mode == 'weekly' else ''}" href="/digest?mode=weekly" style="text-decoration:none">📅 Friday Weekly Pipeline Recap</a>
    </div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input id="dig-rcpts" type="text" value="warren@dokimo.ai, leo@dokimo.ai" style="width:280px;padding:6px 10px;border:1px solid var(--rule2);border-radius:4px;font-size:12px">
      <button class="btn-sm ok" onclick="sendDigestNow('{html.escape(mode)}')" style="padding:7px 14px;font-size:12.5px">📨 1-Click Email Digest Now to Warren &amp; Leo</button>
      <span id="dig-status" style="font-size:12px;font-weight:700;color:var(--quiet)"></span>
    </div>
  </div>
</div>

<div style="margin-top:12px">
  {payload['html_body']}
</div>

<script>
function sendDigestNow(mode){{
  var st = document.getElementById('dig-status');
  var rcpts = (document.getElementById('dig-rcpts').value || '').split(',').map(function(s){{return s.trim();}}).filter(Boolean);
  st.textContent = 'Sending via Gmail API (warren@dokimo.ai)...';
  fetch('/api/investors/send-digest', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{mode:mode, recipients:rcpts}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if(d.ok){{
      st.textContent = '✓ Sent to ' + (d.sent_to || []).join(', ');
    }} else {{
      st.textContent = '⚠ Error: ' + ((d.errors || []).join('; ') || d.error || 'Failed');
    }}
  }});
}}
</script>
</body></html>"""


def render_chat_html() -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ask Gemini VC Strategist · Dokimo.ai</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>🤖 Ask Gemini VC Strategist — Investor Research Co-Pilot</h1>
    <div class="sub">Ask any question across Leo &amp; Warren's investor dataset (e.g. bank-LP overlap, portfolio conflict checks, warm intro sequencing, or custom pitch angles).</div>
  </div>
</header>
<div class="controls-wrap" style="margin-top:14px">
  <div class="controls">
    <button class="f" onclick="askPreset('Which VCs on Leo and Warren\\'s list have bank LPs that can also become Dokimo customers?')">🏦 Which VCs have Bank LPs that can buy Dokimo?</button>
    <button class="f" onclick="askPreset('Compare Leo\\'s contacts vs Warren\\'s contacts: which 10 warm intros should we trigger first this week?')">🤝 Top 10 Warm Intros (Leo vs Warren)</button>
    <button class="f" onclick="askPreset('Which investors on this list backed Socure, Alloy, Chainalysis, or Harvey, and how should we position Dokimo to them?')">🎯 Position Dokimo vs Alloy/Socure/Harvey</button>
    <button class="f" onclick="askPreset('List the semiconductor and hardware VCs from AINekko/Veevx on this list that we should exclude from our FinTech/RegTech round.')">🚫 Filter Out Hardware/Semi VCs</button>
  </div>
  <div style="display:flex;gap:8px;margin-top:8px">
    <input id="chat-in" class="search" placeholder="Ask Gemini about any fund, partner, thesis, or fundraising strategy..." onkeydown="if(event.key==='Enter')sendChat()">
    <button class="btn-sm pri" onclick="sendChat()">Ask Gemini VC Strategist →</button>
  </div>
</div>
<div id="chat-out" style="background:#fff;border:1px solid var(--rule);border-radius:6px;padding:16px;min-height:260px">
  <div style="color:var(--ink2)">Select a prompt above or type a question to run live Gemini analysis over the investor dataset.</div>
</div>
<script>
function askPreset(q){{
  document.getElementById('chat-in').value = q;
  sendChat();
}}
function sendChat(){{
  var q = document.getElementById('chat-in').value.trim();
  var out = document.getElementById('chat-out');
  out.replaceChildren();
  var loading = document.createElement('div');
  loading.style.color = 'var(--ink2)';
  loading.style.fontWeight = '600';
  loading.textContent = 'Running Gemini 2.5 Flash Investor Strategist...';
  out.appendChild(loading);
  fetch('/api/investors/chat', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{question:q}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    out.replaceChildren();
    var pre = document.createElement('pre');
    pre.className = 'memo';
    pre.textContent = d.answer || 'No response';
    out.appendChild(pre);
  }});
}}
</script>
</body></html>"""


def render_access_html(viewer: dict, flash: str = "") -> str:
    grants = access.load().get("grants", [])
    rows_html = []
    for g in grants:
        if not g.get("active"):
            continue
        link = f"/?token={urllib.parse.quote(g.get('token',''))}"
        rows_html.append(f"""
        <tr>
          <td><b>{html.escape(g.get('name',''))}</b></td>
          <td style="font-family:ui-monospace,monospace">{html.escape(g.get('id',''))}</td>
          <td style="font-family:ui-monospace,monospace;font-size:11.5px"><a href="{html.escape(link, quote=True)}">{html.escape(link)}</a></td>
          <td>{html.escape(g.get('added_on',''))}</td>
        </tr>
        """)
    flash_box = f'<div style="background:#e7efe9;color:#2d6a4f;padding:10px;border-radius:6px;margin:10px 0;font-weight:600">{html.escape(flash)}</div>' if flash else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Access Management · Dokimo Investor Board</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div><h1>🔒 Investor Board Access — Restricted Strictly to Warren Zafrin &amp; Leo Spiegel Only</h1><div class="sub">No other accounts or tokens are permitted on the Dokimo Investor Board.</div></div>
</header>
{flash_box}
<div class="tablewrap" style="margin-top:14px">
  <table class="btable">
    <thead><tr><th>Name</th><th>Email / ID</th><th>1-Click Direct Login Link</th><th>Added</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</div>
</body></html>"""


def render_telemetry_html() -> str:
    rep = investor_engine.build_weekly_telemetry_report()
    t = rep["totals"]
    wk_rows_html = []
    for w in rep["weeks"]:
        wk_rows_html.append(f"""
        <tr>
          <td style="font-weight:700;color:#0f172a">{html.escape(w['week_label'])}</td>
          <td style="font-family:ui-monospace,monospace;font-weight:700">{w['sent_funds']} funds ({w['sent_events']} emails)<br><span style="font-size:11px;color:#475569">Warren: {w['warren_sent']} · Leo: {w['leo_sent']}</span></td>
          <td style="font-family:ui-monospace,monospace;color:#15803d;font-weight:700">📎 {html.escape(w['deck_attached_rate'])}</td>
          <td style="font-family:ui-monospace,monospace;font-weight:700">{w['total_opens']}<br><span style="font-size:11px;color:#475569">Email: {w['email_opens']} · Deck: {w['deck_opens']} · PDF: {w['pdf_downloads']}</span></td>
          <td style="font-family:ui-monospace,monospace;font-weight:700;color:#1d4ed8">👁️ {html.escape(w['unique_open_rate'])}</td>
          <td style="font-family:ui-monospace,monospace;font-weight:700;color:#b91c1c">🔁 {html.escape(w['forward_rate'])} ({w['forward_events']} fwd events)</td>
        </tr>
        """)

    inv_rows_html = []
    for r in rep["engaged_investors"]:
        fwd_badge = (
            f"<span class='chip' style='background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;font-weight:700'>🔁 {r['forward_count']} Partner Forwards</span>"
            if int(r.get("forward_count") or 0) > 0
            else "<span style='color:#64748b;font-size:11.5px'>0 forwards</span>"
        )
        deck_badge = (
            "<span class='chip' style='background:#dcfce7;color:#166534;border:1px solid #86efac;font-weight:700'>📎 Deck PDF Opted-In (YES)</span>"
            if r.get("include_pitch_deck") or int(r.get("deck_attached_count") or 0) > 0
            else "<span class='chip'>Teaser Only (NO Deck)</span>"
        )
        inv_rows_html.append(f"""
        <tr>
          <td style="font-family:ui-monospace,monospace;font-weight:700">#{r.get('rank') or '-'} · Tier {html.escape(str(r.get('tier') or 'S'))}</td>
          <td><b>{html.escape(r.get('fund') or '')}</b><br><span style="font-size:11.5px;color:#475569">{html.escape(r.get('person') or '')} &lt;{html.escape(r.get('email') or '')}&gt;</span></td>
          <td><b>{html.escape(r.get('sent_by') or r.get('our_contact') or 'Warren / Leo')}</b><br><span style="font-size:11px;color:#64748b">Sent: {r.get('sent_count', 0)}x {html.escape(r.get('sent_at') or '')}</span></td>
          <td>{deck_badge}</td>
          <td style="font-family:ui-monospace,monospace;font-weight:700">{r.get('total_opens', 0)} total<br><span style="font-size:11px;color:#475569">Email: {r.get('email_opens', 0)} · Deck: {r.get('deck_opens', 0)} · PDF: {r.get('pdf_downloads', 0)}</span></td>
          <td style="font-family:ui-monospace,monospace;font-weight:700;color:#1d4ed8">👁️ {r.get('unique_opens', 0)} unique opener(s)</td>
          <td>{fwd_badge}<br><span style="font-size:10.5px;color:#64748b">{html.escape(r.get('last_opened_at') or r.get('latest_status') or '')}</span></td>
        </tr>
        """)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Investor Telemetry · Opens, Unique Opens, Forwards &amp; Deck Views</title>
<style>{SHARED_CSS}</style></head><body>
<header class="masthead">
  <div>
    <h1>📊 Weekly Investor Outreach &amp; Deck Telemetry (Opens · Unique Opens · Forwards)</h1>
    <div class="sub">
      Denominator-backed telemetry across all <b>{rep['total_investors']} qualified VCs</b>. Strictly tracks outreach from <b>Warren Zafrin (<code>warren@dokimo.ai</code>)</b> and <b>Leo Spiegel (<code>leo@dokimo.ai</code>)</b>, automatic <code>Dokimo_Pitch.pdf</code> attachment when opted-in, unique partner opens, and multi-device GP/Partner forwards.
    </div>
  </div>
  <div class="runbox">
    Generated <b>{html.escape(rep['generated_at'])}</b><br>
    Unique Open Rate: <b>{html.escape(t['unique_open_rate'])}</b><br>
    Forward Rate: <b>{html.escape(t['forward_rate'])}</b>
  </div>
</header>

<section class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(190px,1fr))">
  <div><div class="k">📨 Funds Contacted / Sent</div><div class="v">{html.escape(t['sent_rate_of_board'])}</div></div>
  <div><div class="k">👁️ Unique Partner Opens</div><div class="v" style="color:#1d4ed8">{html.escape(t['unique_open_rate'])}</div></div>
  <div><div class="k">🔥 Total Opens (Email + Deck)</div><div class="v" style="color:#15803d">{t['total_opens']} <small>opens</small></div></div>
  <div><div class="k">🔁 Partner Forwards Detected</div><div class="v" style="color:#b91c1c">{html.escape(t['forward_rate'])}</div></div>
  <div><div class="k">📎 Opt-In Deck PDF Attached</div><div class="v" style="color:#6d28d9">{html.escape(t['deck_attached_rate'])}</div></div>
</section>

<h2 style="margin:18px 0 8px;font-size:17px">1. Telemetry Breakdown by Week (Sent · Deck PDF Attached · Total Opens · Unique Opens · Forwards)</h2>
<div class="tbl-wrap">
  <table>
    <thead>
      <tr>
        <th>ISO Week Cohort</th>
        <th>Emails Sent (Warren vs. Leo)</th>
        <th>Pitch Deck PDF Opt-In Attached</th>
        <th>Total Opens (Email + Deck + PDF)</th>
        <th>Unique Opens (of Sent)</th>
        <th>Forwards Detected (of Unique Opens)</th>
      </tr>
    </thead>
    <tbody>
      {"".join(wk_rows_html)}
    </tbody>
  </table>
</div>

<h2 style="margin:22px 0 8px;font-size:17px">2. Per-Fund Live Telemetry &amp; Partner Forward Feed ({len(rep['engaged_investors'])} of {rep['total_investors']} funds engaged)</h2>
<div class="tbl-wrap">
  <table>
    <thead>
      <tr>
        <th>Rank / Tier</th>
        <th>Fund &amp; Partner</th>
        <th>Sender (Warren / Leo Only)</th>
        <th>Pitch Deck Opt-In</th>
        <th>Total Opens</th>
        <th>Unique Opens</th>
        <th>Forwards &amp; Latest Activity</th>
      </tr>
    </thead>
    <tbody>
      {"".join(inv_rows_html)}
    </tbody>
  </table>
</div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")

    def send_html(self, content: str, status: int = 200):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj: dict, status: int = 200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str, cookie_val: str = None, clear_cookie: bool = False):
        self.send_response(302)
        self.send_header("Location", location)
        if cookie_val:
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={cookie_val}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=Lax",
            )
            self.send_header("Set-Cookie", "g_state=; Path=/; Max-Age=0")
        elif clear_cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
            self.send_header("Set-Cookie", "g_state=; Path=/; Max-Age=0")
        self.send_security_headers()
        self.end_headers()

    def authenticate_viewer(self) -> dict | None:
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            for part in raw_cookie.split(";"):
                k, sep, val = part.strip().partition("=")
                if sep and k.strip() == COOKIE_NAME:
                    clean_val = val.strip().strip('"')
                    v = verify_session_cookie(clean_val)
                    if v:
                        return v
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return access.verify_token(auth[7:].strip(), master_password=PASSWORD, master_user=USER)
        return None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/healthz":
            self.send_json({"ok": True, "service": "dokimo-investors"})
            return

        if path.startswith("/t/o/"):
            inv_id = path.split("/t/o/", 1)[1].replace(".gif", "").strip()
            try:
                sync_from_gcs(["output/investor_state.json"])
                investor_engine.record_investor_engagement(
                    inv_id,
                    event_type="email_open",
                    ip=self.headers.get("X-Forwarded-For", ""),
                    ua=self.headers.get("User-Agent", ""),
                )
                push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.send_header("Content-Length", str(len(investor_digest.PIXEL_GIF)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(investor_digest.PIXEL_GIF)
            return

        if path in ("/deck/pdf", "/deck/Dokimo_Pitch.pdf"):
            inv_id = (qs.get("inv") or [""])[0].strip()
            if inv_id:
                try:
                    sync_from_gcs(["output/investor_state.json"])
                    investor_engine.record_investor_engagement(
                        inv_id,
                        event_type="pdf",
                        ip=self.headers.get("X-Forwarded-For", ""),
                        ua=self.headers.get("User-Agent", ""),
                    )
                    push_to_gcs(["output/investor_state.json", "data/investors.csv"])
                except Exception:
                    pass
            pdf_path = ROOT / "data" / "Dokimo_Pitch.pdf"
            if pdf_path.exists():
                data = pdf_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", 'inline; filename="Dokimo_AI_Investor_Pitch_Deck.pdf"')
                self.send_header("Content-Length", str(len(data)))
                self.send_security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_html("Pitch deck PDF not found", 404)
            return

        if path == "/deck/video.mp4":
            vid_path = ROOT / "data" / "dokimo-investor-pitch-full.mp4"
            if vid_path.exists():
                data = vid_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_html("video not found", 404)
            return

        if path == "/deck":
            inv_id = (qs.get("inv") or [""])[0].strip()
            inv_row = {}
            if inv_id:
                try:
                    sync_from_gcs(["output/investor_state.json"])
                    investor_engine.record_investor_engagement(
                        inv_id,
                        event_type="deck_open",
                        ip=self.headers.get("X-Forwarded-For", ""),
                        ua=self.headers.get("User-Agent", ""),
                    )
                    push_to_gcs(["output/investor_state.json", "data/investors.csv"])
                    all_inv = investor_engine.get_all_investors(persist_csv=False)
                    inv_row = next((x for x in all_inv if x.get("id") == inv_id), {})
                except Exception:
                    pass
            fund_lbl = f"Prepared for {html.escape(inv_row.get('fund') or inv_id)}" if (inv_row.get("fund") or inv_id) else "Seed / Institutional VC Briefing"
            pdf_dl_href = f"/deck/pdf?inv={urllib.parse.quote(inv_id)}" if inv_id else "/deck/pdf"
            deck_html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dokimo.ai — Investor Pitch Deck &amp; Architecture Walkthrough</title>
<style>
body{{margin:0;background:#0f172a;color:#f8fafc;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:24px 16px 60px}}
.wrap{{max-width:1040px;margin:0 auto}}
.hdr{{border-bottom:1px solid #334155;padding-bottom:16px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:12px}}
.badge{{display:inline-block;background:#1e3a8a;color:#93c5fd;border:1px solid #3b82f6;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}}
.slide{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:22px 24px;margin-bottom:16px}}
.slide h2{{margin:0 0 8px;font-size:19px;color:#fff}}
.slide .num{{font-family:ui-monospace,monospace;font-size:11.5px;color:#38bdf8;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-top:10px}}
.card{{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:12px 14px;font-size:13.5px;color:#cbd5e1}}
.card b{{color:#fff;display:block;margin-bottom:4px}}
</style></head><body><div class="wrap">
<div class="hdr">
  <div>
    <span class="badge">🏛️ DOKIMO.AI · NEURO-SYMBOLIC COMPLIANCE VALIDATION</span>
    <h1 style="margin:8px 0 4px;font-size:28px">Dokimo.ai Investor Pitch Deck &amp; Live Video Walkthrough</h1>
    <div style="color:#94a3b8;font-size:13.5px">{fund_lbl} &middot; CEO: Warren Zafrin (<a href="mailto:warren@dokimo.ai" style="color:#38bdf8">warren@dokimo.ai</a>) &middot; Strategic Advisor: Leo Spiegel</div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <a href="{html.escape(pdf_dl_href)}" target="_blank" style="background:#15803d;color:#fff;text-decoration:none;padding:9px 16px;border-radius:6px;font-weight:700;font-size:13.5px">📥 Download Pitch Deck PDF</a>
    <a href="https://calendar.app.google/JbnbVWry32nwqBiY6" target="_blank" style="background:#2563eb;color:#fff;text-decoration:none;padding:9px 16px;border-radius:6px;font-weight:700;font-size:13.5px">📅 Book 25-Min Walkthrough</a>
  </div>
</div>
<div id="video" class="slide" style="border-color:#3b82f6">
  <div class="num">1. Full Executive Pitch Video</div>
  <h2>🎬 Watch the Dokimo.ai Investor Pitch &amp; Live Platform Demo</h2>
  <video controls preload="metadata" style="width:100%;max-height:540px;border-radius:8px;background:#000;margin-top:8px" src="/deck/video.mp4"></video>
</div>
<div id="slides" class="slide" style="border-color:#ef4444">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
    <div>
      <div class="num" style="color:#f87171">2. Official 18-Slide Seed Round Pitch Deck ($4M Seed)</div>
      <h2 style="margin:0">📊 Agentic Compliance: Workers for Cross-System Validation (18 Slides)</h2>
    </div>
    <a href="{html.escape(pdf_dl_href)}" target="_blank" style="background:#ef4444;color:#fff;text-decoration:none;padding:8px 14px;border-radius:6px;font-weight:700;font-size:13px">📥 Open / Download Full 18-Slide PDF</a>
  </div>
  <iframe src="/deck/pdf#view=FitH" style="width:100%;height:760px;border:1px solid #334155;border-radius:8px;background:#0f172a"></iframe>
</div>
<div class="slide"><div class="num">Slide 01 · The Structural Problem</div><h2>Why Regulated Banks, Broker-Dealers &amp; FinTechs Keep Failing Examinations</h2><p style="color:#cbd5e1;margin:0">Regulators (OCC, FDIC, FRB, FINRA, SEC, FinCEN, NYDFS) have issued $4.2B+ in recent enforcement penalties for one structural failure: legacy GRC relies on <b>1% manual quarterly spreadsheet sampling</b>, while first-wave 'document AI' only reads PDF policies in isolation without verifying whether production databases, wire corridors, and trade feeds actually followed the rules.</p></div>
<div class="slide"><div class="num">Slide 02 · The Dokimo.ai Solution</div><h2>Autonomous 100%-Population Policy-to-Record Validation Inside the Bank's VPC</h2>
  <div class="grid">
    <div class="card"><b>1. 100% Full-Population Validation (In-Perimeter)</b>Deploys inside the institution's own VPC with zero data egress. Compiles written policies &amp; consent orders into deterministic executable controls that test 100% of underlying records every night.</div>
    <div class="card"><b>2. Bob — Explainable Remediation Agent</b>Pinpoints every exception with exact regulatory citations and record IDs, and drafts the audit-ready remediation &amp; control specification for a named CCO/BSA Officer's sign-off.</div>
    <div class="card"><b>3. Live Regulatory Signal Graph</b>Continuously monitors 20,065 financial institutions across 16 global regulators, turning new enforcement actions into proactive internal control tests.</div>
  </div>
</div>
<div class="slide"><div class="num">Slide 03 · Defensible Neuro-Symbolic Moat</div><h2>Why Horizontal LLMs Cannot Replicate Dokimo</h2><p style="color:#cbd5e1;margin:0">Examiners reject probabilistic LLM hallucinations. Dokimo pairs LLM policy parsing with a deterministic neuro-symbolic SQL/Python execution engine that runs across 100% of rows in core banking, wire, ACH, card, and trade blotter tables—producing mathematical denominators and cryptographic audit trails.</p></div>
<div class="slide"><div class="num">Slide 04 · Live Commercial Traction &amp; Active Evaluations</div><h2>Active Bank &amp; Broker-Dealer Evaluations</h2><p style="color:#cbd5e1;margin:0">Active executive evaluations and live platform demos across Tier-2/3 banks and broker-dealers including <b>Synchrony Financial</b>, <b>Old National Bank ($54B+ assets)</b>, <b>Raymond James</b>, <b>Dime Community Bank ($14B+ assets)</b>, and <b>Blue Ridge Bank</b>.</p></div>
</div></body></html>"""
            self.send_html(deck_html)
            return

        if path.startswith("/pitch/") or path == "/api/investors/pdf-memo":
            self.send_json({"ok": False, "disabled": "PDF Tear-Sheets are disabled on the Investor Board."}, 200)
            return

        if path == "/api/cron/investor-digest":
            self.send_json({"ok": False, "disabled": "Automated investor emails are strictly disabled."}, 200)
            return

        if path == "/logout":
            self.redirect("/login", clear_cookie=True)
            return

        if path == "/auth/google":
            nxt = (qs.get("next") or ["/"])[0]
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            if qs.get("start"):
                bridge_url = (
                    f"{access.GOOGLE_AUTH_BRIDGE_URL}/?board=investors&next="
                    + urllib.parse.quote(nxt, safe="")
                )
                self.redirect(bridge_url)
                return
            ticket = (qs.get("ticket") or [""])[0].strip()
            if ticket:
                sync_from_gcs()
                v = access.verify_google_auth_ticket(ticket)
                if v:
                    self.redirect(nxt, cookie_val=make_session_cookie(v))
                else:
                    self.redirect("/login?err=1&next=" + urllib.parse.quote(nxt, safe=""))
                return
            self.redirect("/login?next=" + urllib.parse.quote(nxt, safe=""))
            return

        tok_param = (qs.get("token") or qs.get("t") or [""])[0].strip()
        if tok_param:
            sync_from_gcs()
            v = access.verify_token(tok_param, master_password=PASSWORD, master_user=USER)
            if v:
                clean_path = path if path != "/login" else "/"
                self.redirect(clean_path, cookie_val=make_session_cookie(v))
                return

        if path == "/login":
            nxt = (qs.get("next") or ["/"])[0]
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            err = '<div class="err">Invalid or revoked access token.</div>' if qs.get("err") else ""
            self.send_html(LOGIN_HTML.replace("__NEXT__", html.escape(nxt, quote=True)).replace("__ERROR__", err), 401 if qs.get("err") else 200)
            return

        viewer = self.authenticate_viewer()
        if not viewer:
            self.send_html(LOGIN_HTML.replace("__NEXT__", html.escape(path, quote=True)).replace("__ERROR__", ""), 401)
            return

        sync_from_gcs()

        if path == "/":
            try:
                investor_engine.record_owner_activity(viewer, action="page_view:/")
                push_to_gcs(["output/investor_state.json"])
            except Exception:
                pass
            self.send_html(inject_nav(render_board_html(), viewer, active_tab="board"))
            return
        if path == "/telemetry":
            try:
                investor_engine.record_owner_activity(viewer, action="page_view:/telemetry")
                push_to_gcs(["output/investor_state.json"])
            except Exception:
                pass
            if (qs.get("view") or [""])[0] == "table":
                self.send_html(inject_nav(render_telemetry_html(), viewer, active_tab="telemetry"))
            else:
                self.send_html(inject_nav(render_board_html(), viewer, active_tab="telemetry"))
            return
        if path == "/readme":
            try:
                investor_engine.record_owner_activity(viewer, action="page_view:/readme")
                push_to_gcs(["output/investor_state.json"])
            except Exception:
                pass
            self.send_html(inject_nav(render_board_html(), viewer, active_tab="readme"))
            return
        if path == "/report":
            self.send_html(inject_nav(render_report_html(), viewer, active_tab="report"))
            return
        if path == "/outreach":
            self.send_html(inject_nav(render_outreach_html(), viewer, active_tab="outreach"))
            return
        if path == "/digest":
            mode = (qs.get("mode") or ["daily"])[0]
            self.send_html(inject_nav(render_digest_html(mode=mode), viewer, active_tab="digest"))
            return
        if path == "/chat":
            self.send_html(inject_nav(render_chat_html(), viewer, active_tab="chat"))
            return
        if path == "/access":
            self.send_html(inject_nav(render_access_html(viewer), viewer, active_tab="access"))
            return
        if path == "/api/investors":
            rows = investor_engine.get_all_investors(persist_csv=True)
            self.send_json({"ok": True, "metrics": investor_engine.build_summary_metrics(rows), "investors": rows})
            return
        if path == "/api/investors/telemetry":
            self.send_json(investor_engine.build_weekly_telemetry_report())
            return
        if path == "/api/investors/eml":
            if not access.can_send_investor_emails(viewer):
                self.send_html("Forbidden: Only Leo Spiegel and Warren Zafrin can draft or send investor emails.", 403)
                return
            sync_from_gcs(["output/investor_state.json"])
            inv_id = (qs.get("id") or [""])[0].strip()
            sender = (qs.get("sender") or ["warren"])[0].strip().lower()
            inc_deck_q = (qs.get("deck") or [""])[0].strip()
            attach_q = (qs.get("attach") or ["0"])[0].strip()
            force_fup = ((qs.get("force_followup") or ["0"])[0].strip() == "1")
            rows = investor_engine.get_all_investors(persist_csv=False)
            inv = next((x for x in rows if x.get("id") == inv_id), None)
            if not inv:
                self.send_html("Investor not found", 404)
                return
            dup = investor_engine.check_investor_duplicate_send(
                inv_id, to_email=inv.get("email") or "", force_followup=force_fup
            )
            if dup.get("duplicate_blocked"):
                self.send_html(dup.get("reason") or "Duplicate email blocked.", 409)
                return
            inc_deck = (inc_deck_q == "1") if inc_deck_q in ("0", "1") else bool(inv.get("include_pitch_deck"))
            att_pdf = (attach_q == "1")
            if "leo" in sender:
                body_txt = inv.get("leo_email_with_deck") if inc_deck else inv.get("leo_email_no_deck")
            else:
                body_txt = inv.get("warren_email_with_deck") if inc_deck else inv.get("warren_email_no_deck")
            subj_str = inv.get("direct_email_subject") or f"Dokimo.ai x {inv.get('fund')}"
            eml_bytes, fname = investor_digest.build_investor_eml_bytes(
                inv_id=inv_id,
                sender=sender,
                to_email=inv.get("email") or "",
                subject=subj_str,
                plain_body=body_txt or "",
                include_pitch_deck=inc_deck,
                attach_pdf=att_pdf,
            )
            investor_engine.record_investor_send(
                inv_id=inv_id,
                sender=sender,
                to_email=inv.get("email") or "",
                subject=subj_str,
                include_pitch_deck=inc_deck,
                msg_id="eml_draft",
                force_followup=force_fup,
            )
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            self.send_response(200)
            self.send_header("Content-Type", "message/rfc822")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(eml_bytes)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(eml_bytes)
            return
        if path == "/api/investors/digest":
            mode = (qs.get("mode") or ["daily"])[0]
            self.send_json(investor_digest.build_digest_payload(mode=mode))
            return
        if path == "/api/investors/report":
            self.send_json(investor_engine.build_executive_vc_report())
            return
        if path == "/api/investors/export.csv":
            investor_engine.get_all_investors(persist_csv=True)
            data = investor_engine.CSV_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="dokimo_investors_ranked.csv"')
            self.send_header("Content-Length", str(len(data)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_html("not found", 404)

    def _read_body(self) -> str:
        n = min(int(self.headers.get("Content-Length") or 0), 1024 * 1024)
        return self.rfile.read(n).decode("utf-8", errors="replace") if n > 0 else ""

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/auth/google":
            raw = self._read_body()
            form = urllib.parse.parse_qs(raw)
            cred = (form.get("credential") or [""])[0]
            nxt = (form.get("next") or ["/"])[0]
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            sync_from_gcs()
            v = access.verify_google_id_token(cred)
            if v:
                self.redirect(nxt, cookie_val=make_session_cookie(v))
            else:
                self.redirect("/login?err=1&next=" + urllib.parse.quote(nxt, safe=""))
            return

        if path == "/login":
            raw = self._read_body()
            form = urllib.parse.parse_qs(raw)
            u = (form.get("user") or [""])[0]
            t = (form.get("token") or [""])[0]
            nxt = (form.get("next") or ["/"])[0]
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/"
            sync_from_gcs()
            v = access.verify_credentials(u, t, master_password=PASSWORD, master_user=USER)
            if v:
                self.redirect(nxt, cookie_val=make_session_cookie(v))
            else:
                self.redirect("/login?err=1&next=" + urllib.parse.quote(nxt, safe=""))
            return

        viewer = self.authenticate_viewer()
        if not viewer:
            self.send_json({"error": "unauthorized"}, 401)
            return

        try:
            payload = json.loads(self._read_body() or "{}")
        except Exception:
            self.send_json({"error": "invalid JSON"}, 400)
            return

        if path == "/api/investors/update":
            sync_from_gcs(["output/investor_state.json"])
            res = investor_engine.update_investor_status(
                inv_id=str(payload.get("id") or ""),
                latest_status=payload.get("latest_status"),
                comment=payload.get("comment"),
                next_action=payload.get("next_action"),
                assigned_owner=payload.get("assigned_owner"),
                follow_up_date=payload.get("follow_up_date"),
                followup_note=payload.get("followup_note"),
                include_pitch_deck=payload.get("include_pitch_deck"),
                updated_by=viewer.get("name", "Warren"),
            )
            try:
                investor_engine.record_owner_activity(viewer, action="field_update:" + str(payload.get("id") or ""))
            except Exception:
                pass
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            self.send_json(res)
            return

        if path == "/api/investors/followup-note":
            sync_from_gcs(["output/investor_state.json"])
            res = investor_engine.save_followup_note(
                inv_id=str(payload.get("id") or ""),
                note=str(payload.get("note") or ""),
                updated_by=viewer.get("name", "Warren"),
            )
            try:
                investor_engine.record_owner_activity(viewer, action="note_update:" + str(payload.get("id") or ""))
            except Exception:
                pass
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            self.send_json(res)
            return

        if path == "/api/access/grant":
            sync_from_gcs(["config/access.json"])
            email = str(payload.get("email") or "leo@s22t.vc").strip()
            name = str(payload.get("name") or "Leo Spiegel").strip()
            grant = access.add_grant(email, name)
            push_to_gcs(["config/access.json"])
            url = f"https://dokimo-investors-aigeqnv5nq-uc.a.run.app/?token={grant['token']}"
            emailed = False
            try:
                subj = "1-Click Access: Dokimo Investor Watch & Stage-Gated VC Fit Board"
                body_html = f"<p>Hi {html.escape(name)},</p><p>Here is your 1-click direct login link to the Dokimo Investor Watch &amp; VC Fit Board:</p><p><a href='{html.escape(url)}'><b>{html.escape(url)}</b></a></p><p>Best,<br>Warren Zafrin</p>"
                send_res = investor_digest.send_html_email(email, subj, body_html)
                emailed = bool(send_res.get("ok"))
            except Exception:
                emailed = False
            self.send_json({"ok": True, "grant": grant, "url": url, "emailed": emailed})
            return

        if path == "/api/investors/gemini-search":
            res = gemini_vc.gemini_search_investors(
                query=str(payload.get("query") or ""),
            )
            self.send_json(res)
            return

        if path == "/api/investors/research":
            res = gemini_vc.research_investor_with_gemini(
                inv_id=str(payload.get("id") or ""),
                custom_focus=str(payload.get("custom_focus") or ""),
            )
            self.send_json(res)
            return

        if path == "/api/investors/chat":
            res = gemini_vc.ask_gemini_vc_strategist(
                question=str(payload.get("question") or ""),
            )
            self.send_json(res)
            return

        if path == "/api/investors/reset-telemetry":
            sync_from_gcs(["output/investor_state.json"])
            res = investor_engine.reset_investor_telemetry()
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            self.send_json(res)
            return

        if path == "/api/investors/sync-gmail":
            sync_from_gcs(["output/investor_state.json"])
            res = investor_digest.sync_investor_gmail_activity(persist=True)
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            self.send_json(res)
            return

        if path == "/api/investors/record-outreach":
            if not access.can_send_investor_emails(viewer):
                self.send_json({"ok": False, "error": "Forbidden: Only Leo Spiegel (leo@dokimo.ai) and Warren Zafrin (warren@dokimo.ai) are permitted to draft or send investor emails."}, 403)
                return
            sync_from_gcs(["output/investor_state.json"])
            try:
                res = investor_engine.record_investor_send(
                    inv_id=str(payload.get("id") or ""),
                    sender=str(payload.get("sender") or "warren"),
                    to_email=str(payload.get("to_email") or ""),
                    subject=str(payload.get("subject") or ""),
                    include_pitch_deck=bool(payload.get("include_pitch_deck", False)),
                    msg_id="gmail_compose",
                    force_followup=bool(payload.get("force_followup", False)),
                )
                if not res.get("ok"):
                    self.send_json(res, 409 if res.get("duplicate_blocked") else 400)
                    return
                try:
                    investor_engine.record_owner_activity(viewer, action="gmail_compose:" + str(payload.get("id") or ""))
                except Exception:
                    pass
                push_to_gcs(["output/investor_state.json", "data/investors.csv"])
                self.send_json(res)
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path in ("/api/investors/create-draft", "/api/investors/send-email"):
            if not access.can_send_investor_emails(viewer):
                self.send_json({"ok": False, "error": "Forbidden: Only Leo Spiegel (leo@dokimo.ai) and Warren Zafrin (warren@dokimo.ai) are permitted to draft or send investor emails."}, 403)
                return
            sync_from_gcs(["output/investor_state.json"])
            try:
                res = investor_digest.create_investor_gmail_draft(
                    inv_id=str(payload.get("id") or ""),
                    sender=str(payload.get("sender") or "warren"),
                    to_email=str(payload.get("to_email") or ""),
                    subject=str(payload.get("subject") or ""),
                    plain_body=str(payload.get("body") or ""),
                    include_pitch_deck=bool(payload.get("include_pitch_deck", False)),
                    attach_pdf=bool(payload.get("attach_pdf", False)),
                    force_followup=bool(payload.get("force_followup", False)),
                )
                if not res.get("ok") and res.get("duplicate_blocked"):
                    self.send_json(res, 409)
                    return
                try:
                    investor_engine.record_owner_activity(viewer, action="draft_create:" + str(payload.get("id") or ""))
                except Exception:
                    pass
                push_to_gcs(["output/investor_state.json", "data/investors.csv"])
                self.send_json(res)
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/investors/send-digest":
            self.send_json({"ok": False, "disabled": "Investor emails are strictly disabled."}, 200)
            return

        self.send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass


def main():
    sync_from_gcs()
    investor_engine.get_all_investors(persist_csv=True)
    host = os.environ.get("BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
