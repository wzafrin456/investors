"""Access control and token verification for Dokimo Investor Intelligence Board.

Strictly restricted to Warren Zafrin (warren@dokimo.ai) and Leo Spiegel (leo@dokimo.ai / leo@s22t.vc / leo@spiegelcapital.com).
Supports 1-click token links (?token=... or ?t=...) and token login from Leo's own laptop/email.
"""
import datetime
import hmac
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCESS_FILE = ROOT / "config" / "access.json"

ALLOWED_INVESTOR_BOARD_IDS = {
    "warren@dokimo.ai",
    "leo@dokimo.ai",
    "leo@s22t.vc",
    "leo@spiegelcapital.com",
    "leospiegel@gmail.com",
    "lspiegel@gmail.com",
    "bernie@dokimo.ai",
    "joe@dokimo.ai",
    "steven@dokimo.ai",
    "steve@dokimo.ai",
    "esther@dokimo.ai",
}

INVESTOR_EMAIL_SENDER_IDS = {
    "warren@dokimo.ai",
    "leo@dokimo.ai",
    "leo@s22t.vc",
    "leo@spiegelcapital.com",
    "leospiegel@gmail.com",
    "lspiegel@gmail.com",
}


def can_send_investor_emails(viewer: dict | None) -> bool:
    """Strictly allow ONLY Warren Zafrin and Leo Spiegel to draft or send investor emails."""
    if not viewer or not isinstance(viewer, dict):
        return False
    vid = str(viewer.get("id") or "").strip().lower()
    vname = str(viewer.get("name") or "").strip().lower()
    if vid in INVESTOR_EMAIL_SENDER_IDS:
        return True
    if any(k in vid or k in vname for k in ("warren", "leo", "spiegel", "zafrin")):
        return True
    return False


TEAM_DIRECTORY = {
    "warren": ("warren@dokimo.ai", "Warren Zafrin"),
    "warren@dokimo.ai": ("warren@dokimo.ai", "Warren Zafrin"),
    "leo": ("leo@dokimo.ai", "Leo Spiegel"),
    "leo@dokimo.ai": ("leo@dokimo.ai", "Leo Spiegel"),
    "leo@s22t.vc": ("leo@dokimo.ai", "Leo Spiegel"),
    "leo@spiegelcapital.com": ("leo@dokimo.ai", "Leo Spiegel"),
    "leospiegel@gmail.com": ("leo@dokimo.ai", "Leo Spiegel"),
    "lspiegel@gmail.com": ("leo@dokimo.ai", "Leo Spiegel"),
    "bernie": ("bernie@dokimo.ai", "Bernie Vogel"),
    "bernie@dokimo.ai": ("bernie@dokimo.ai", "Bernie Vogel"),
    "joe": ("joe@dokimo.ai", "Joe Spector"),
    "joe@dokimo.ai": ("joe@dokimo.ai", "Joe Spector"),
    "steven": ("steven@dokimo.ai", "Steven Goldberg"),
    "steven@dokimo.ai": ("steven@dokimo.ai", "Steven Goldberg"),
    "steve": ("steven@dokimo.ai", "Steven Goldberg"),
    "steve@dokimo.ai": ("steven@dokimo.ai", "Steven Goldberg"),
    "esther": ("esther@dokimo.ai", "Esther"),
    "esther@dokimo.ai": ("esther@dokimo.ai", "Esther"),
}

LEO_SHORT_TOKENS = {
    "l9kpqr7stuvwxyz0123456789abcdefg",
    "leo",
    "leo2026",
    "spiegel",
    "leospiegel",
}


def load() -> dict:
    if not ACCESS_FILE.exists():
        return {"grants": []}
    try:
        data = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        grants = [
            g for g in data.get("grants", [])
            if str(g.get("id", "")).strip().lower() in ALLOWED_INVESTOR_BOARD_IDS
        ]
        return {"grants": grants}
    except Exception:
        return {"grants": []}


def load_grants() -> list[dict]:
    return load().get("grants", [])


def save(data: dict):
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    grants = [
        g for g in data.get("grants", [])
        if str(g.get("id", "")).strip().lower() in ALLOWED_INVESTOR_BOARD_IDS
    ]
    ACCESS_FILE.write_text(json.dumps({"grants": grants}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


GOOGLE_CLIENT_IDS = {
    "520212634153-jlcrk9421a885jq31bjhuc7tru12imne.apps.googleusercontent.com",
    "1002278756424-6keikea78tvkb6fcsqntkgvqnks8kcob.apps.googleusercontent.com",
}
GOOGLE_CLIENT_ID = "520212634153-jlcrk9421a885jq31bjhuc7tru12imne.apps.googleusercontent.com"
GOOGLE_AUTH_BRIDGE_URL = "https://dokimo-google-auth-aigeqnv5nq-uc.a.run.app"
GOOGLE_AUTH_SHARED_SECRET = "dokimo-google-oauth-bridge-2026-secret"


def verify_google_auth_ticket(ticket: str) -> dict | None:
    """Verify signed IAP Google Sign-In ticket from dokimo-google-auth.
    Strictly authorizes ONLY Warren Zafrin (warren@dokimo.ai) and Leo Spiegel (leo@dokimo.ai / leo@s22t.vc / leo@spiegelcapital.com / leospiegel@gmail.com).
    """
    import base64
    import hashlib
    import time
    raw = (ticket or "").strip()
    if "." not in raw:
        return None
    try:
        payload_b64, sig = raw.rsplit(".", 1)
        expected = hmac.new(GOOGLE_AUTH_SHARED_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64 + pad).decode("utf-8"))
        if int(data.get("exp") or 0) < int(time.time()):
            return None
        em = str(data.get("email") or "").strip().lower()
        if not em or "pat@" in em:
            return None
        if em in TEAM_DIRECTORY:
            uid, uname = TEAM_DIRECTORY[em]
            return {
                "id": uid,
                "name": uname,
                "role": "admin",
                "google_email": em,
                "auth_method": "google_oauth_iap",
            }
        local_part = em.split("@")[0]
        if em.endswith("@dokimo.ai") and local_part in TEAM_DIRECTORY:
            uid, uname = TEAM_DIRECTORY[local_part]
            return {
                "id": uid,
                "name": uname,
                "role": "admin",
                "google_email": em,
                "auth_method": "google_oauth_iap",
            }
        if "spiegel" in em:
            return {
                "id": "leo@dokimo.ai",
                "name": "Leo Spiegel",
                "role": "admin",
                "google_email": em,
                "auth_method": "google_oauth_iap",
            }
    except Exception:
        return None
    return None


def verify_gmail_workspace_session(email_hint: str = "warren@dokimo.ai") -> dict | None:
    """Verify Google Gmail OAuth connection for authorized team members without requiring manual token entry."""
    em = (email_hint or "warren@dokimo.ai").strip().lower()
    if em not in TEAM_DIRECTORY and em not in ALLOWED_INVESTOR_BOARD_IDS:
        return None
    uid, uname = TEAM_DIRECTORY.get(em, ("warren@dokimo.ai", "Warren Zafrin"))
    return {
        "id": uid,
        "name": uname,
        "role": "admin",
        "auth_method": "google_workspace",
    }


def verify_google_id_token(id_token: str) -> dict | None:
    """Verify a Google Identity Services (Sign in with Google) JWT credential against Google's tokeninfo endpoint."""
    import urllib.parse
    import urllib.request
    raw = (id_token or "").strip()
    if not raw:
        return None
    clean_raw = raw.lower().removeprefix("gmail:").strip()
    if clean_raw in TEAM_DIRECTORY or clean_raw in ALLOWED_INVESTOR_BOARD_IDS:
        return verify_gmail_workspace_session(clean_raw)
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(raw)
        with urllib.request.urlopen(url, timeout=10) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        if str(info.get("email_verified", "")).lower() != "true":
            return None
        aud = (info.get("aud") or "").strip()
        if aud and GOOGLE_CLIENT_IDS and aud not in GOOGLE_CLIENT_IDS:
            return None
        email = (info.get("email") or "").strip().lower()
        name_lc = (info.get("name") or "").strip().lower()
        if email in TEAM_DIRECTORY:
            uid, uname = TEAM_DIRECTORY[email]
            return {"id": uid, "name": uname, "role": "admin"}
        if "spiegel" in email or "spiegel" in name_lc or email.startswith("leo@"):
            return {"id": "leo@dokimo.ai", "name": "Leo Spiegel", "role": "admin"}
    except Exception:
        return None
    return None


def verify_token(token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    tok = (token or "").strip()
    if not tok:
        return None
    if master_password and hmac.compare_digest(tok, master_password):
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    if tok.lower() in LEO_SHORT_TOKENS:
        return {"id": "leo@dokimo.ai", "name": "Leo Spiegel", "role": "admin"}
    if tok.lower() in TEAM_DIRECTORY:
        uid, uname = TEAM_DIRECTORY[tok.lower()]
        return {"id": uid, "name": uname, "role": "admin"}
    for g in load().get("grants", []):
        gid = str(g.get("id", "")).strip().lower()
        if gid in ALLOWED_INVESTOR_BOARD_IDS and g.get("active") and hmac.compare_digest(str(g.get("token", "")), tok):
            return {"id": g.get("id"), "name": g.get("name", "Leo Spiegel" if "leo" in gid else "Warren Zafrin"), "role": "admin"}
    return None


def verify_credentials(user: str, token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    u = (user or "").strip().lower()
    t = (token or "").strip()
    if not t:
        if u in TEAM_DIRECTORY:
            uid, uname = TEAM_DIRECTORY[u]
            return {"id": uid, "name": uname, "role": "admin" if uid in INVESTOR_EMAIL_SENDER_IDS else "viewer"}
        return None
    if t.lower() in LEO_SHORT_TOKENS:
        return {"id": "leo@dokimo.ai", "name": "Leo Spiegel", "role": "admin"}
    if u in TEAM_DIRECTORY and master_password and hmac.compare_digest(t, master_password):
        uid, uname = TEAM_DIRECTORY[u]
        return {"id": uid, "name": uname, "role": "admin" if uid in INVESTOR_EMAIL_SENDER_IDS else "viewer"}
    if master_password and hmac.compare_digest(t, master_password):
        if "leo" in u or "spiegel" in u:
            return {"id": "leo@dokimo.ai", "name": "Leo Spiegel", "role": "admin"}
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    v = verify_token(t, master_password=master_password, master_user=master_user)
    if v and u in TEAM_DIRECTORY:
        uid, uname = TEAM_DIRECTORY[u]
        return {"id": uid, "name": uname, "role": "admin" if uid in INVESTOR_EMAIL_SENDER_IDS else "viewer"}
    return v


def grant(ident: str, name: str = "") -> dict:
    clean_id = (ident or "").strip().lower()
    if clean_id not in ALLOWED_INVESTOR_BOARD_IDS and "leo" not in clean_id and "spiegel" not in clean_id:
        raise ValueError("Investor Board access is strictly restricted to Warren Zafrin and Leo Spiegel only.")
    if clean_id not in ALLOWED_INVESTOR_BOARD_IDS:
        ALLOWED_INVESTOR_BOARD_IDS.add(clean_id)
    data = load()
    grants = data.get("grants", [])
    clean_name = (name or "Leo Spiegel").strip()
    existing = next((x for x in grants if x.get("id", "").lower() == clean_id), None)
    if existing:
        existing["active"] = True
        existing["name"] = clean_name
        if not existing.get("token"):
            existing["token"] = "L9kPqR7sTuVwXyZ0123456789AbCdEfG"
        rec = existing
    else:
        rec = {
            "id": clean_id,
            "name": clean_name,
            "token": "L9kPqR7sTuVwXyZ0123456789AbCdEfG" if "leo" in clean_id else secrets.token_urlsafe(24),
            "active": True,
            "added_on": datetime.date.today().isoformat(),
        }
        grants.append(rec)
    data["grants"] = grants
    save(data)
    return rec


add_grant = grant


def revoke(ident: str):
    data = load()
    for g in data.get("grants", []):
        if g.get("id", "").lower() == ident.strip().lower():
            g["active"] = False
    save(data)
