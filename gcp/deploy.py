"""Deploy the Dokimo Investor Watch & Gemini VC Fit Board to Google Cloud Run (dokimo-investors).

Creates/syncs gs://dokimo-aiops-investors/inputs/, builds container image via Cloud Build,
and deploys Cloud Run service `dokimo-investors` in `us-central1`.
"""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "dokimo-aiops")
REGION = os.environ.get("GCP_REGION", "us-central1")
SERVICE = "dokimo-investors"
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


def deploy():
    print(f"1/4 Ensuring GCS bucket gs://{BUCKET} exists and syncing investor data...")
    run(["storage", "buckets", "create", f"gs://{BUCKET}", "--project", PROJECT, "--location", REGION], check=False)
    for rel in [
        "config/access.json",
        "data/raw_leo_investors.txt",
        "data/investors.csv",
        "output/investor_state.json",
    ]:
        p = ROOT / rel
        if p.exists():
            run(["storage", "cp", str(p), f"gs://{BUCKET}/inputs/{rel}", "--project", PROJECT, "--quiet"])

    image = f"{REGION}-docker.pkg.dev/{PROJECT}/{REPO}/{SERVICE}:latest"
    print(f"2/4 Building container image {image} via Cloud Build...")
    run(["builds", "submit", str(ROOT), "--tag", image, "--project", PROJECT, "--quiet"])

    print(f"3/4 Deploying Cloud Run service {SERVICE} in {REGION}...")
    run([
        "run", "deploy", SERVICE,
        "--image", image,
        "--region", REGION,
        "--project", PROJECT,
        "--platform", "managed",
        "--allow-unauthenticated",
        "--service-account", SA_EMAIL,
        "--memory", "512Mi",
        "--cpu", "1",
        "--max-instances", "4",
        "--set-env-vars", f"GOOGLE_CLOUD_PROJECT={PROJECT},GCP_REGION={REGION},GCS_BUCKET={BUCKET},BOARD_USER=dokimo",
        "--set-secrets", f"BOARD_PASSWORD={PW_SECRET}:latest,REFRESH_TOKEN={TOK_SECRET}:latest",
        "--quiet",
    ])

    ok, url = run(["run", "services", "describe", SERVICE, "--region", REGION, "--project", PROJECT, "--format=value(status.url)"])
    print(f"4/4 Dokimo Investor Watch live at: {url}")
    return url


if __name__ == "__main__":
    deploy()
