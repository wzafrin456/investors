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
SESSION_TTL = 86400 * 30
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
        if data.get("role") != "admin":
            grants = access.load().get("grants", [])
            g = next((x for x in grants if x.get("id", "").lower() == data.get("id", "").lower()), None)
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
    <a class="dk-nav-brand" href="/">🏛️ Dokimo Investor Watch &amp; Gemini VC Fit Board</a>
    <div class="dk-nav-links">
      <a href="/" class="__ACT_BOARD__">1. VC Fit &amp; Priority Board (/)</a>
      <a href="/report" class="__ACT_REPORT__">2. Executive VC Report (/report)</a>
      <a href="/outreach" class="__ACT_OUTREACH__">3. Outreach Studio (/outreach)</a>
      <a href="/digest" class="__ACT_DIGEST__">4. Pipeline Digest &amp; Follow-Up (/digest)</a>
      <a href="/chat" class="__ACT_CHAT__">5. Ask Gemini VC Strategist (/chat)</a>
      <a href="/api/investors/export.csv">⬇ Export CSV</a>
    </div>
  </div>
  <div class="dk-nav-user">
    <a href="/access" class="__ACT_ACC__" style="margin-right:8px">Access</a>
    <span>Signed in: <b>__VIEWER__</b></span>
    <a href="/logout">Sign out</a>
  </div>
</div>
"""


def inject_nav(page_html: str, viewer: dict, active_tab: str = "board") -> str:
    nav = (
        NAV_BAR_HTML.replace("__VIEWER__", html.escape(viewer.get("name") or viewer.get("id") or "User"))
        .replace("__ACT_BOARD__", "active" if active_tab == "board" else "")
        .replace("__ACT_REPORT__", "active" if active_tab == "report" else "")
        .replace("__ACT_OUTREACH__", "active" if active_tab == "outreach" else "")
        .replace("__ACT_DIGEST__", "active" if active_tab == "digest" else "")
        .replace("__ACT_CHAT__", "active" if active_tab == "chat" else "")
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
.box{width:100%;max-width:410px;background:#ffffff;border:1px solid #dde3ea;border-radius:12px;padding:28px;box-shadow:0 8px 24px rgba(15,23,42,.06)}
.badge{display:inline-block;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;margin-bottom:10px}
h1{margin:0 0 6px;font-size:21px;color:#0f172a}
p.sub{margin:0 0 20px;color:#526071;font-size:13.5px}
label{display:block;font-size:13px;color:#334155;margin:12px 0 5px;font-weight:600}
input{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:8px;border:1px solid #cbd5e1;background:#f8fafc;color:#0f172a;font:inherit}
button{width:100%;margin-top:18px;padding:11px;border:0;border-radius:8px;background:#161a21;color:#fff;font-weight:600;font-size:15px;cursor:pointer}
button:hover{background:#2c5f7c}
.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:9px 12px;border-radius:8px;font-size:13px;margin-bottom:12px}
.foot{margin-top:16px;font-size:12px;color:#64748b;text-align:center}
</style></head><body>
<div class="box">
  <span class="badge">DOKIMO.AI · INVESTOR INTELLIGENCE</span>
  <h1>VC Research &amp; Fit Board</h1>
  <p class="sub">Sign in with your personal access token provided by Warren Zafrin or Leo.</p>
  __ERROR__
  <form method="POST" action="/login">
    <input type="hidden" name="next" value="__NEXT__">
    <label>Email or Username (optional if using a personal token)</label>
    <input type="text" name="user" placeholder="warren@dokimo.ai or leo@dokimo.ai" autocomplete="username">
    <label>Access Token or Password</label>
    <input type="password" name="token" placeholder="Paste your access token or password" required autocomplete="current-password">
    <button type="submit">Access Investor Board →</button>
  </form>
  <div class="foot">Need access? Email warren@dokimo.ai</div>
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
table.btable thead th{text-align:left;font-size:9.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);font-weight:700;padding:8px 8px;border-bottom:1px solid var(--rule2);background:var(--sunk);position:sticky;top:0}
table.btable tbody td{padding:9px 8px;border-bottom:1px solid var(--rule);vertical-align:top;font-size:12px;word-wrap:break-word;overflow-wrap:break-word}
table.btable tbody tr:hover td{background:#fafbfc}
.tier{font-family:ui-monospace,monospace;font-size:10.5px;padding:2px 6px;border-radius:3px;white-space:nowrap;font-weight:700;display:inline-block}
.t-S{background:var(--quiet-soft);color:var(--quiet);border:1px solid #b7e4c7}
.t-A{background:var(--accent-soft);color:var(--accent);border:1px solid #bfdbfe}
.t-B{background:var(--warning-soft);color:var(--warning);border:1px solid #fde68a}
.t-C{background:var(--critical-soft);color:var(--critical);border:1px solid #fecaca}
.chip{font-family:ui-monospace,monospace;font-size:10px;padding:2px 6px;border-radius:3px;background:var(--sunk);color:var(--ink2);display:inline-block;margin:2px 3px 2px 0}
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
.modal-bg{display:none;position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:999;align-items:center;justify-content:center;padding:18px}
.modal-box{background:#fff;border:1px solid var(--rule2);border-radius:8px;max-width:860px;width:100%;max-height:90vh;overflow-y:auto;padding:20px;box-shadow:0 20px 50px rgba(0,0,0,.25)}
pre.memo{white-space:pre-wrap;background:var(--ground);border:1px solid var(--rule);padding:12px;border-radius:6px;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink);margin:8px 0}
"""


def render_board_html() -> str:
    rows = investor_engine.get_all_investors(persist_csv=True)
    m = investor_engine.build_summary_metrics(rows)
    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
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

<div style="margin-top:12px;background:#eff6ff;border:1px solid #bfdbfe;border-left:4px solid #1e40af;border-radius:6px;padding:11px 14px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px">
  <div>
    <div style="font-size:12.5px;font-weight:700;color:#1e3a8a">🔑 Grant Access to Leo &amp; Team — 1-Click Direct Login Link</div>
    <div style="font-size:11.5px;color:#334155;margin-top:2px">
      Leo's 1-Click Link: <code id="leo-link-code" style="background:#fff;padding:2px 6px;border:1px solid #cbd5e1;border-radius:4px;font-weight:700;color:#0f172a">{html.escape(leo_url)}</code>
    </div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">
    <button class="btn-sm pri" onclick="navigator.clipboard.writeText(document.getElementById('leo-link-code').textContent);this.textContent='✓ Copied Leo Link!'">📋 Copy Leo's 1-Click Link</button>
    <a class="btn-sm ok" href="{html.escape(leo_gmail, quote=True)}" target="_blank" rel="noopener">✉️ Open Gmail to Send Leo Access</a>
    <input id="grant-leo-email" type="email" placeholder="Or enter Leo's email to send invite..." style="padding:4px 8px;border:1px solid #93c5fd;border-radius:4px;font-size:12px;width:220px;background:#fff">
    <button class="btn-sm" style="background:#1e40af;color:#fff;border-color:#1e40af;font-weight:600" onclick="grantAndEmailLeo()">🔑 Grant &amp; Email Link</button>
    <a class="btn-sm" href="/access">Manage All Team Access →</a>
    <span id="grant-leo-msg" style="font-size:11.5px;font-weight:700;color:#15803d"></span>
  </div>
</div>

<div class="status">
  <div><div class="k">Right VCs (Deduplicated)</div><div class="v">{m['total_investors']} <small>1 row per fund</small></div></div>
  <div><div class="k">🟢 Tier S · Pitch Now (Seed)</div><div class="v" style="color:var(--quiet)">{m['tier_s_count']} <small>({html.escape(m['tier_s_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">🔵 Tier A · Warm / Bank CVC</div><div class="v" style="color:var(--accent)">{m['tier_a_count']} <small>({html.escape(m['tier_a_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">⏳ Tier B · Hold for $1M ARR</div><div class="v" style="color:var(--warning)">{m['tier_b_count']} <small>({html.escape(m['tier_b_rate'].split('(')[1].rstrip(')'))})</small></div></div>
  <div><div class="k">US / UK / EU Qualified</div><div class="v">{m['us_count']} US · {m['uk_count']} UK · {m['eu_count']} EU</div></div>
  <div><div class="k">📧 Sep/Oct Tracked Outreach</div><div class="v" style="color:#1e40af">{m['leo_sep_oct_count']} <small>of {m['total_investors']} VCs</small></div></div>
  <div><div class="k">Verified Emails &amp; LinkedIn</div><div class="v">{m['with_email_count']} <small>of {m['total_investors']} (100%)</small></div></div>
</div>

<div class="controls-wrap">
  <div class="controls">
    <span class="lbl">Stage &amp; Fit</span>
    <button class="f on" data-ftier="all" onclick="setFilter('tier','all',this)">All Right VCs ({m['total_investors']})</button>
    <button class="f" data-ftier="S" onclick="setFilter('tier','S',this)">🟢 Tier S: PITCH NOW — Pre-Seed &amp; Seed Check-Writers ({m['tier_s_count']})</button>
    <button class="f" data-ftier="A" onclick="setFilter('tier','A',this)">🔵 Tier A: Warm-Intro &amp; Strategic Bank CVCs ({m['tier_a_count']})</button>
    <button class="f" data-ftier="B" onclick="setFilter('tier','B',this)">⏳ Tier B: Hold for $1M ARR / 3+ Bank Logos — Avoid 'Too Early' ({m['tier_b_count']})</button>
  </div>
  <div class="controls">
    <span class="lbl">Region</span>
    <button class="f on" onclick="setFilter('region','all',this)">All Qualified Regions ({m['total_investors']})</button>
    <button class="f" onclick="setFilter('region','US',this)">🇺🇸 United States ({m['us_count']})</button>
    <button class="f" onclick="setFilter('region','UK',this)">🇬🇧 United Kingdom — Transatlantic Qualified ({m['uk_count']})</button>
    <button class="f" onclick="setFilter('region','EU',this)">🇪🇺 European Union — Transatlantic Qualified ({m['eu_count']})</button>
    <button class="f" onclick="setFilter('region','IL / US',this)">🇮🇱/🇺🇸 Israel-US Cyber/FinTech Seed ({m['il_us_count']})</button>
  </div>
  <div class="controls">
    <span class="lbl">Our Contact</span>
    <button class="f on" onclick="setFilter('owner','all',this)">All Contacts</button>
    <button class="f" onclick="setFilter('owner','warren',this)">Warren ({m['warren_contact_count']})</button>
    <button class="f" onclick="setFilter('owner','leo',this)">Leo ({m['leo_contact_count']})</button>
    <button class="f" onclick="setFilter('owner','team',this)">Roman / Tanya / Sasha / Bryan / Doug</button>
    <span class="lbl" style="margin-left:12px">Outreach &amp; Follow-Up</span>
    <button class="f on" onclick="setFilter('reach','all',this)">All</button>
    <button class="f" style="border-color:#1e40af;color:#1e40af;font-weight:600" onclick="setFilter('reach','sepoct',this)">📧 Leo &amp; Warren Sep/Oct Emails Tracked ({m['leo_sep_oct_count']})</button>
    <button class="f" style="border-color:#b45309;color:#b45309;font-weight:600" onclick="setFilter('reach','followup',this)">📅 Follow-Up &amp; Action Queue ({m['followup_queue_count']})</button>
    <button class="f" onclick="setFilter('reach','active',this)">Active Threads ({m['active_convo_count']})</button>
    <button class="f" onclick="setFilter('reach','phone',this)">Has Mobile / Phone ({m['with_phone_count']})</button>
  </div>
  <div class="controls">
    <span class="lbl">Search</span>
    <input id="q-search" class="search" placeholder="Search fund, partner, portfolio (e.g. Socure, Alloy, Harvey, Citi, Mayfield, Patrick Salyer, Arvind, Ed Sim, 13books, CommerzVentures), region, or follow-up note..." oninput="renderRows()">
    <span id="shown-count" style="font-family:ui-monospace,monospace;font-size:12px;color:var(--ink2);font-weight:600;margin-left:8px"></span>
  </div>
</div>

<div class="tablewrap">
  <table class="btable">
    <thead>
      <tr>
        <th style="width:3.5%">#</th>
        <th style="width:13.5%">Fund &amp; Category</th>
        <th style="width:14%">Partner, Email &amp; Phone</th>
        <th style="width:11%">Stage, Fit &amp; Qualification Gate</th>
        <th style="width:20%">Why They Would Want Dokimo &amp; Portfolio Fit</th>
        <th style="width:16%">The Value Pitch to Them &amp; Bank LP Leverage</th>
        <th style="width:22%">Follow-Up &amp; Next Action (Auto-Save) + 1-Click Outreach</th>
      </tr>
    </thead>
    <tbody id="inv-tbody"></tbody>
  </table>
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
var FILTERS = {{tier:'all', region:'all', owner:'all', reach:'all'}};

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

  var matched = INVESTORS.filter(function(r){{
    if(FILTERS.tier !== 'all' && r.tier !== FILTERS.tier) return false;
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
    if(FILTERS.reach === 'followup'){{
      var st1 = (r.latest_status || '').toLowerCase();
      var hasFup = (r.followup_note || '').trim() || (r.follow_up_date || '').trim() || (st1 && st1 !== 'not contacted');
      if(!hasFup) return false;
    }}
    if(FILTERS.reach === 'active'){{
      var st = (r.latest_status || '').toLowerCase();
      if(!st || st === 'not contacted' || st.indexOf('passed') >= 0 || st.indexOf('declined') >= 0) return false;
    }}
    if(q){{
      var hay = [r.fund, r.person, r.title, r.category, r.region, r.qualification_gate, r.portfolio, r.why_fit, r.bank_lp_value, r.our_contact, r.email, r.city, r.country, r.followup_note, r.next_action, r.comment].join(' ').toLowerCase();
      if(hay.indexOf(q) < 0) return false;
    }}
    return true;
  }});

  var sc = document.getElementById('shown-count');
  if(sc) sc.textContent = 'Showing ' + matched.length + ' of ' + INVESTORS.length + ' qualified Right VCs';

  matched.forEach(function(r){{
    var tr = document.createElement('tr');

    // Col 1: Rank
    var tdRank = makeEl('td', {{style:'font-family:ui-monospace,monospace;color:var(--ink3);font-weight:700'}}, '#' + r.rank);
    tr.appendChild(tdRank);

    // Col 2: Fund & Category
    var tdFund = document.createElement('td');
    var fTitle = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--ink)'}}, r.fund);
    tdFund.appendChild(fTitle);
    tdFund.appendChild(makeEl('div', {{style:'font-size:11px;color:var(--accent);font-weight:600;margin-top:2px'}}, r.category));
    var loc = [r.city, r.state, r.country].filter(Boolean).join(', ');
    if(loc) tdFund.appendChild(makeEl('div', {{style:'font-size:10.5px;color:var(--ink3);margin-top:2px'}}, '📍 ' + loc));
    var linksDiv = makeEl('div', {{style:'margin-top:4px;display:flex;gap:6px;flex-wrap:wrap'}});
    if(r.website){{
      var wUrl = r.website.indexOf('http') === 0 ? r.website : ('https://' + r.website);
      linksDiv.appendChild(makeEl('a', {{href:wUrl, target:'_blank', rel:'noopener', style:'font-size:10.5px;color:var(--accent)'}}, '🌐 Website ↗'));
    }}
    if(r.company_linkedin){{
      linksDiv.appendChild(makeEl('a', {{href:r.company_linkedin, target:'_blank', rel:'noopener', style:'font-size:10.5px;color:#0a66c2'}}, 'in Fund ↗'));
    }}
    tdFund.appendChild(linksDiv);
    tdFund.appendChild(makeEl('div', {{style:'font-size:9.5px;color:var(--ink3);margin-top:3px'}}, r.source_table));
    tr.appendChild(tdFund);

    // Col 3: Partner, Email & Phone
    var tdPerson = document.createElement('td');
    tdPerson.appendChild(makeEl('div', {{style:'font-weight:700;color:var(--ink)'}}, r.person || 'Partnership Team'));
    if(r.title) tdPerson.appendChild(makeEl('div', {{style:'font-size:11px;color:var(--ink2)'}}, r.title));
    if(r.person_linkedin){{
      var pLi = makeEl('a', {{href:r.person_linkedin, target:'_blank', rel:'noopener', style:'font-size:11px;color:#0a66c2;font-weight:600;display:inline-block;margin-top:2px'}}, 'in Partner LinkedIn ↗');
      tdPerson.appendChild(pLi);
    }}
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
    tdFit.appendChild(tierRow);
    tdFit.appendChild(makeEl('div', {{style:'font-size:10.5px;color:var(--ink2);margin-top:4px;font-weight:600'}}, r.stage));
    tdFit.appendChild(makeEl('div', {{style:'font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink3);margin-top:2px'}}, r.check_size));
    if(r.qualification_gate){{
      var qCls = r.tier === 'B' ? 'qual-badge qual-hold' : 'qual-badge qual-ok';
      tdFit.appendChild(makeEl('div', {{className:qCls}}, r.qualification_gate));
    }}
    tr.appendChild(tdFit);

    // Col 5: Why Fit & Portfolio
    var tdWhy = document.createElement('td');
    tdWhy.appendChild(makeEl('div', {{style:'color:var(--ink);line-height:1.4'}}, r.why_fit));
    if(r.portfolio){{
      var pDiv = makeEl('div', {{style:'margin-top:5px;font-size:11px;color:var(--ink2)'}});
      pDiv.appendChild(makeEl('b', null, 'Portfolio / Signal: '));
      pDiv.appendChild(document.createTextNode(r.portfolio));
      tdWhy.appendChild(pDiv);
    }}
    tr.appendChild(tdWhy);

    // Col 6: Bank LP Value & Pitch Angle
    var tdPitch = document.createElement('td');
    if(r.bank_lp_value){{
      var lpDiv = makeEl('div', {{style:'font-size:11px;color:var(--quiet);font-weight:600;margin-bottom:4px'}}, '🏦 ' + r.bank_lp_value);
      tdPitch.appendChild(lpDiv);
    }}
    var paDiv = makeEl('div', {{style:'font-size:11px;color:var(--ink2)'}});
    paDiv.appendChild(makeEl('b', null, 'Pitch Hook: '));
    paDiv.appendChild(document.createTextNode(r.pitch_angle));
    tdPitch.appendChild(paDiv);
    tr.appendChild(tdPitch);

    // Col 7: Prospecting-style Follow-Up & Next Action + 1-Click Outreach
    var tdAct = document.createElement('td');
    var topChips = makeEl('div', {{style:'margin-bottom:5px;display:flex;flex-wrap:wrap;gap:4px'}});
    topChips.appendChild(makeEl('span', {{className:'chip ok'}}, '👤 Contact: ' + (r.our_contact || 'Leo / Warren')));
    if(r.leo_sep_oct_outreach){{
      topChips.appendChild(makeEl('span', {{className:'chip', style:'background:#dbeafe;color:#1e40af;font-weight:700;border:1px solid #93c5fd'}}, '📧 Sep/Oct Gmail Tracked'));
    }}
    tdAct.appendChild(topChips);

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
      placeholder:'Next action (e.g. Follow up with partner)...',
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
    sel.onchange = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, statusMsg); }};
    fupDateIn.onchange = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, statusMsg); }};
    saveBtn.onclick = function(){{ saveInvestorUpdate(r.id, sel.value, nextActIn.value, fupDateIn.value, statusMsg); }};
    actDateRow.appendChild(nextActIn);
    actDateRow.appendChild(fupDateIn);
    actDateRow.appendChild(saveBtn);
    tdAct.appendChild(actDateRow);
    tdAct.appendChild(statusMsg);

    // Prospecting-Style Auto-Saving 4-Line Follow-Up & Action Note Box
    var fupBox = makeEl('div', {{className:'fup-box'}});
    var fupHdr = makeEl('div', {{className:'fup-hdr'}});
    fupHdr.appendChild(makeEl('span', null, '📝 Follow-Up & Action Log (4 lines · auto-saves)'));
    var fupSavedSpan = makeEl('span', {{style:'font-weight:600;color:#15803d;text-transform:none'}}, r.followup_updated_at ? ('Saved ' + r.followup_updated_at) : '');
    fupHdr.appendChild(fupSavedSpan);
    fupBox.appendChild(fupHdr);
    var fupTa = makeEl('textarea', {{
      className:'fup-ta',
      rows:'3',
      maxlength:'400',
      placeholder:'Record outreach dates, partner feedback, follow-up items & next steps (auto-saves on blur)...'
    }}, r.followup_note || '');
    fupTa.onblur = function(){{ saveFollowupNote(r.id, fupTa.value, fupSavedSpan); }};
    fupBox.appendChild(fupTa);
    tdAct.appendChild(fupBox);

    var btnRow = makeEl('div', {{style:'display:flex;flex-wrap:wrap;gap:4px'}});
    var gemBtn = makeEl('button', {{className:'btn-sm pri'}}, '✨ Gemini IC Memo');
    gemBtn.onclick = function(){{ openGeminiModal(r); }};
    btnRow.appendChild(gemBtn);

    var pdfUrl = '/api/investors/pdf-memo?id=' + encodeURIComponent(r.id);
    var pdfLink = makeEl('a', {{href:pdfUrl, target:'_blank', rel:'noopener', className:'btn-sm', style:'background:#0f172a;color:#fff;border-color:#0f172a'}}, '📄 2-Page PDF Tear-Sheet');
    btnRow.appendChild(pdfLink);

    if(r.email){{
      var gmUrl = 'https://mail.google.com/mail/?view=cm&fs=1&to=' + encodeURIComponent(r.email) + '&su=' + encodeURIComponent(r.direct_email_subject) + '&body=' + encodeURIComponent(r.direct_email_body);
      var emLink = makeEl('a', {{href:gmUrl, target:'_blank', rel:'noopener', className:'btn-sm ok'}}, '✉️ 1-Click Gmail');
      btnRow.appendChild(emLink);
    }}
    tdAct.appendChild(btnRow);
    tr.appendChild(tdAct);

    tbody.appendChild(tr);
  }});
}}

function saveInvestorUpdate(invId, statusVal, nextActVal, fupDateVal, msgEl){{
  if(msgEl) msgEl.textContent = 'Saving...';
  fetch('/api/investors/update', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id:invId, latest_status:statusVal, next_action:nextActVal, follow_up_date:fupDateVal}})
  }}).then(function(r){{ return r.json(); }}).then(function(d){{
    if(d.ok){{
      if(msgEl) msgEl.textContent = '✓ Saved (' + (d.investor && d.investor.updated_at || 'now') + ')';
      INVESTORS.forEach(function(item){{
        if(item.id === invId){{
          item.latest_status = statusVal;
          item.next_action = nextActVal;
          item.follow_up_date = fupDateVal;
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
  title.textContent = '✨ Gemini IC Fit Memo & Outreach Kit — ' + r.fund + ' (' + (r.person || 'Partnership') + ')';
  body.replaceChildren();
  body.appendChild(makeEl('div', {{style:'padding:12px;color:var(--ink2);font-weight:600'}}, 'Running Gemini 2.5 Flash deep-dive research on ' + r.fund + '...'));

  fetch('/api/investors/research', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id:r.id}})
  }}).then(function(res){{ return res.json(); }}).then(function(d){{
    body.replaceChildren();
    var sec1 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--accent)'}}, '1. Gemini Investment Committee (IC) Fit Memo (Tier ' + r.tier + ' · Score ' + r.dokimo_fit_score + '/100)');
    body.appendChild(sec1);
    body.appendChild(makeEl('pre', {{className:'memo'}}, d.memo || r.why_fit));

    var sec2 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--quiet);margin-top:12px'}}, '2. Forwardable Warm-Intro Blurb (For ' + (r.our_contact || 'Leo') + ' to Send to ' + (r.person || r.fund) + ')');
    body.appendChild(sec2);
    body.appendChild(makeEl('pre', {{className:'memo'}}, d.warm_intro_blurb || r.warm_intro_blurb));

    var sec3 = makeEl('div', {{style:'font-weight:700;font-size:13px;color:var(--ink);margin-top:12px'}}, '3. Direct Founder Email from Warren Zafrin (warren@dokimo.ai)');
    body.appendChild(sec3);
    body.appendChild(makeEl('pre', {{className:'memo'}}, 'Subject: ' + (d.direct_email_subject || r.direct_email_subject) + '\\n\\n' + (d.direct_email_body || r.direct_email_body)));
  }});
}}

function closeModal(){{
  document.getElementById('gemini-modal').style.display = 'none';
}}

renderRows();
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
        gm_url = (
            "https://mail.google.com/mail/?view=cm&fs=1"
            + "&to=" + urllib.parse.quote(r.get("email") or "")
            + "&su=" + urllib.parse.quote(r["direct_email_subject"])
            + "&body=" + urllib.parse.quote(r["direct_email_body"])
        )
        cards.append(f"""
        <div style="background:#fff;border:1px solid var(--rule);border-radius:6px;padding:14px 16px;margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
            <div>
              <span class="tier t-{html.escape(r['tier'])}">#{r['rank']} · TIER {html.escape(r['tier'])} ({r['dokimo_fit_score']})</span>
              <b style="font-size:15px;margin-left:6px">{html.escape(r['fund'])}</b> — {html.escape(r['person'] or 'Partnership')}
              <span class="chip ok" style="margin-left:6px">Warm Contact: {html.escape(r['our_contact'])}</span>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">
              <a class="btn-sm" style="background:#0f172a;color:#fff;border-color:#0f172a" href="/api/investors/pdf-memo?id={urllib.parse.quote(r['id'])}" target="_blank" rel="noopener">📄 1-Click 2-Page PDF VC Tear-Sheet</a>
              <a class="btn-sm ok" href="{html.escape(gm_url, quote=True)}" target="_blank" rel="noopener">✉️ 1-Click Open in Gmail ({html.escape(r['email'] or 'Add Email')})</a>
              <a class="btn-sm" href="{html.escape(r.get('person_linkedin') or '#', quote=True)}" target="_blank" rel="noopener">in LinkedIn ↗</a>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:10px">
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--accent);text-transform:uppercase">A. Forwardable Warm-Intro Blurb (For {html.escape(r['our_contact'])} to Send)</div>
              <pre class="memo">{html.escape(r['warm_intro_blurb'])}</pre>
            </div>
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--quiet);text-transform:uppercase">B. Direct Founder Email from Warren Zafrin</div>
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
  <div><h1>🔑 Team Access &amp; 1-Click Login Links</h1><div class="sub">Manage access tokens for Warren, Leo, and the Dokimo team.</div></div>
</header>
{flash_box}
<div class="tablewrap" style="margin-top:14px">
  <table class="btable">
    <thead><tr><th>Name</th><th>Email / ID</th><th>1-Click Direct Login Link</th><th>Added</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
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
        elif clear_cookie:
            self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
        self.send_security_headers()
        self.end_headers()

    def authenticate_viewer(self) -> dict | None:
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            c = http.cookies.SimpleCookie()
            try:
                c.load(raw_cookie)
                if COOKIE_NAME in c:
                    v = verify_session_cookie(c[COOKIE_NAME].value)
                    if v:
                        return v
            except Exception:
                pass
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

        if path.startswith("/pitch/"):
            inv_id = urllib.parse.unquote(path[len("/pitch/"):].strip("/"))
            sync_from_gcs(["output/investor_state.json"])
            investor_engine.record_investor_engagement(inv_id, event_type="open")
            push_to_gcs(["output/investor_state.json", "data/investors.csv"])
            rows = investor_engine.get_all_investors(persist_csv=False)
            inv = next((r for r in rows if r["id"].upper() == inv_id.upper()), rows[0] if rows else {"id": inv_id, "fund": inv_id})
            pdf_bytes, fname = pdf_memo.generate_investor_tearsheet_pdf(inv)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{fname}"')
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(pdf_bytes)
            return

        if path == "/api/cron/investor-digest":
            cron_tok = (qs.get("key") or [""])[0] or self.headers.get("X-Refresh-Token", "")
            if REFRESH_TOKEN and cron_tok != REFRESH_TOKEN and not self.authenticate_viewer():
                self.send_json({"error": "unauthorized cron"}, 401)
                return
            sync_from_gcs()
            mode = (qs.get("mode") or ["daily"])[0]
            res = investor_digest.send_investor_digest_email(mode=mode)
            self.send_json(res)
            return

        if path == "/logout":
            self.redirect("/login", clear_cookie=True)
            return

        if "token" in qs and qs["token"]:
            sync_from_gcs()
            v = access.verify_token(qs["token"][0], master_password=PASSWORD, master_user=USER)
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
            self.send_html(inject_nav(render_board_html(), viewer, active_tab="board"))
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
        if path == "/api/investors/digest":
            mode = (qs.get("mode") or ["daily"])[0]
            self.send_json(investor_digest.build_digest_payload(mode=mode))
            return
        if path == "/api/investors/pdf-memo":
            inv_id = (qs.get("id") or ["INV-001"])[0].strip()
            rows = investor_engine.get_all_investors(persist_csv=False)
            inv = next((r for r in rows if r["id"].upper() == inv_id.upper()), None)
            if not inv:
                inv = next((r for r in rows if inv_id.lower() in r["fund"].lower()), rows[0])
            investor_engine.record_investor_engagement(inv["id"], event_type="pdf")
            push_to_gcs(["output/investor_state.json"])
            pdf_bytes, fname = pdf_memo.generate_investor_tearsheet_pdf(inv)
            dl = (qs.get("download") or ["0"])[0] == "1"
            disp = "attachment" if dl else "inline"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'{disp}; filename="{fname}"')
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(pdf_bytes)
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
                updated_by=viewer.get("name", "Warren"),
            )
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

        if path == "/api/investors/send-digest":
            mode = str(payload.get("mode") or "daily")
            rcpts = payload.get("recipients") or ["warren@dokimo.ai", "leo@dokimo.ai"]
            res = investor_digest.send_investor_digest_email(recipients=rcpts, mode=mode)
            self.send_json(res)
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
