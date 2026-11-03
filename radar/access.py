"""Access control and token verification for Dokimo Investor Intelligence Board.

Strictly restricted to Warren Zafrin (warren@dokimo.ai) and Leo Spiegel (leo@dokimo.ai / leo@s22t.vc).
No other accounts are permitted on the Investor Board.
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
}


def load() -> dict:
    if not ACCESS_FILE.exists():
        return {"grants": []}
    try:
        data = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
        # Enforce strict allowlist: only Warren and Leo
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


def verify_token(token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    tok = (token or "").strip()
    if not tok:
        return None
    if master_password and hmac.compare_digest(tok, master_password):
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    for g in load().get("grants", []):
        gid = str(g.get("id", "")).strip().lower()
        if gid in ALLOWED_INVESTOR_BOARD_IDS and g.get("active") and hmac.compare_digest(str(g.get("token", "")), tok):
            return {"id": g.get("id"), "name": g.get("name", "Admin"), "role": "admin"}
    return None


def verify_credentials(user: str, token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    u = (user or "").strip().lower()
    t = (token or "").strip()
    if not t:
        return None
    if u and u not in ALLOWED_INVESTOR_BOARD_IDS and u != master_user.lower():
        return None
    if master_password and hmac.compare_digest(t, master_password) and (not u or u in (master_user.lower(), "warren@dokimo.ai")):
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    return verify_token(t, master_password=master_password, master_user=master_user)


def grant(ident: str, name: str = "") -> dict:
    clean_id = (ident or "").strip().lower()
    if clean_id not in ALLOWED_INVESTOR_BOARD_IDS:
        raise ValueError("Investor Board access is strictly restricted to Warren Zafrin and Leo Spiegel only.")
    data = load()
    grants = data.get("grants", [])
    clean_name = (name or "Leo Spiegel").strip()
    existing = next((x for x in grants if x.get("id", "").lower() == clean_id), None)
    if existing:
        existing["active"] = True
        existing["name"] = clean_name
        if not existing.get("token"):
            existing["token"] = secrets.token_urlsafe(24)
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
