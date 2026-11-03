"""Access control and token verification for Dokimo Investor Intelligence Board."""
import datetime
import hmac
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCESS_FILE = ROOT / "config" / "access.json"


def load() -> dict:
    if not ACCESS_FILE.exists():
        return {"grants": []}
    try:
        return json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"grants": []}


def load_grants() -> list[dict]:
    return load().get("grants", [])


def save(data: dict):
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACCESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_token(token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    tok = (token or "").strip()
    if not tok:
        return None
    if master_password and hmac.compare_digest(tok, master_password):
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    for g in load().get("grants", []):
        if g.get("active") and hmac.compare_digest(str(g.get("token", "")), tok):
            role = "admin" if g.get("id", "").lower() in ("warren@dokimo.ai", "leo@dokimo.ai") else "viewer"
            return {"id": g.get("id", "viewer"), "name": g.get("name", "Viewer"), "role": role}
    return None


def verify_credentials(user: str, token: str, master_password: str = "", master_user: str = "dokimo") -> dict | None:
    u = (user or "").strip().lower()
    t = (token or "").strip()
    if not t:
        return None
    if master_password and hmac.compare_digest(t, master_password) and (not u or u in (master_user.lower(), "warren@dokimo.ai")):
        return {"id": "warren@dokimo.ai", "name": "Warren Zafrin", "role": "admin"}
    return verify_token(t, master_password=master_password, master_user=master_user)


def grant(ident: str, name: str = "") -> dict:
    data = load()
    grants = data.get("grants", [])
    clean_id = ident.strip()
    clean_name = (name or clean_id.split("@")[0].title()).strip()
    existing = next((x for x in grants if x.get("id", "").lower() == clean_id.lower()), None)
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
            "token": secrets.token_urlsafe(24),
            "active": True,
            "added_on": datetime.date.today().isoformat(),
        }
        grants.append(rec)
    data["grants"] = grants
    save(data)
    return rec


def revoke(ident: str):
    data = load()
    for g in data.get("grants", []):
        if g.get("id", "").lower() == ident.strip().lower():
            g["active"] = False
    save(data)

