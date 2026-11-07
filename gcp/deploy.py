"""Deploy the Dokimo Investor Watch & Gemini VC Fit Board to Google Cloud Run (dokimo-investors & vc).

Merges live GCS state into output/investor_state.json, syncs gs://dokimo-aiops-investors/inputs/ in parallel,
builds container image via Cloud Build, and deploys Cloud Run services (`vc` and `dokimo-investors`) in parallel.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "dokimo-aiops")
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE = "vc"
LEGACY_SERVICE = "dokimo-investors"
REPO = "prospecting"
BUCKET = f"{PROJECT}-investors"
SA_EMAIL = f"prospecting-board@{PROJECT}.iam.gserviceaccount.com"
PW_SECRET = "prospecting-board-password"
TOK_SECRET = "prospecting-board-refresh-token"


def gcloud_bin() -> str:
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not found:
        raise SystemExit("gcloud CLI not found on PATH.")
    return found


def run(args: list[str], check: bool = True):
    env = dict(os.environ)
    cur = env.get("CLOUDSDK_METRICS_ENVIRONMENT", "")
    if "datacloud.antigravity" not in cur:
        env["CLOUDSDK_METRICS_ENVIRONMENT"] = (cur + " datacloud.antigravity").strip()
    cmd = [gcloud_bin()] + args
    r = subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and r.returncode != 0:
        raise SystemExit("Command failed:\n  %s\n%s" % (" ".join(cmd), r.stdout))
    return r.returncode == 0, (r.stdout or "").strip()


def _merge_live_investor_state():
    """Preserve live GCS investor_state.json edits before syncing local files."""
    rel = "output/investor_state.json"
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "investor_state.json"
        ok, _ = run(["storage", "cp", f"gs://{BUCKET}/inputs/{rel}", str(dest), "--project", PROJECT, "--quiet"], check=False)
        if not ok or not dest.exists():
            return
        local_p = ROOT / rel
        try:
            remote_data = json.loads(dest.read_text(encoding="utf-8"))
            local_data = json.loads(local_p.read_text(encoding="utf-8")) if local_p.exists() else {}
        except Exception:
            return
        if isinstance(remote_data, dict) and isinstance(local_data, dict):
            changed = False
            for k, rv in remote_data.items():
                if k not in local_data:
                    local_data[k] = rv
                    changed = True
                elif isinstance(rv, dict) and isinstance(local_data.get(k), dict):
                    lv = local_data[k]
                    for fk, fv in rv.items():
                        if fv and not lv.get(fk):
                            lv[fk] = fv
                            changed = True
            if changed:
                local_p.parent.mkdir(parents=True, exist_ok=True)
                local_p.write_text(json.dumps(local_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def deploy():
    print(f"1/4 Ensuring GCS bucket gs://{BUCKET} exists and syncing investor data in parallel...")
    run(["storage", "buckets", "create", f"gs://{BUCKET}", "--project", PROJECT, "--location", REGION], check=False)
    _merge_live_investor_state()
    files = [
        "config/access.json",
        "data/raw_leo_investors.txt",
        "data/investors.csv",
        "output/investor_state.json",
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [
            pool.submit(run, ["storage", "cp", str(ROOT / rel), f"gs://{BUCKET}/inputs/{rel}", "--project", PROJECT, "--quiet"])
            for rel in files if (ROOT / rel).exists()
        ]
        for f in as_completed(futs):
            f.result()

    image = f"{REGION}-docker.pkg.dev/{PROJECT}/{REPO}/{LEGACY_SERVICE}:latest"
    print(f"2/4 Building container image {image} via Cloud Build...")
    run(["builds", "submit", str(ROOT), "--tag", image, "--project", PROJECT, "--quiet"])

    def _deploy_svc(svc_name: str):
        print(f"3/4 Deploying Cloud Run service {svc_name} in {REGION}...")
        run([
            "run", "deploy", svc_name,
            "--image", image,
            "--region", REGION,
            "--project", PROJECT,
            "--platform", "managed",
            "--allow-unauthenticated",
            "--cpu-boost",
            "--service-account", SA_EMAIL,
            "--memory", "512Mi",
            "--cpu", "1",
            "--max-instances", "4",
            "--set-env-vars", f"GOOGLE_CLOUD_PROJECT={PROJECT},GCP_REGION={REGION},GCS_BUCKET={BUCKET},BOARD_USER=dokimo,INVESTORS_BOARD_URL=https://vc-aigeqnv5nq-uc.a.run.app,INVESTOR_DECK_URL=https://vc-aigeqnv5nq-uc.a.run.app/deck",
            "--set-secrets", f"BOARD_PASSWORD={PW_SECRET}:latest,REFRESH_TOKEN={TOK_SECRET}:latest,GMAIL_OAUTH_CLIENT=gmail-oauth-client:latest,GMAIL_TOKEN_WARREN=gmail-token-warren:latest",
            "--quiet",
        ])

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_deploy_svc, (SERVICE, LEGACY_SERVICE)))

    ok, url = run(["services", "describe", SERVICE, "--region", REGION, "--project", PROJECT, "--format=value(status.url)"], check=False)
    if not ok:
        _, url = run(["run", "services", "describe", SERVICE, "--region", REGION, "--project", PROJECT, "--format=value(status.url)"])
    print(f"4/4 Short Dokimo Investor Watch URL live at: {url}")
    return url


if __name__ == "__main__":
    deploy()
