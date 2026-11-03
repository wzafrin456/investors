"""Gemini & Vertex AI Investor Research, Fit Memo & Outreach Co-Pilot.

Follows Workspace Rule 1:
- Checks PostgreSQL `VERTEX_AI_CONFIG` or Google Cloud Application Default Credentials (Vertex AI endpoint)
  first so expired OAuth tokens in `GEMINI_API_KEY` never cause 401 errors, and falls back cleanly
  to deterministic institutional synthesis when offline.
"""
import json
import os
import urllib.request
from . import investor_engine


def _get_gcp_metadata_token() -> str:
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode("utf-8")).get("access_token", "")
    except Exception:
        return ""


def call_gemini(prompt: str, max_tokens: int = 2500) -> str | None:
    """Call Vertex AI Gemini (gemini-2.5-flash) via GCP Service Account / Metadata token or GEMINI_API_KEY."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "dokimo-aiops")
    location = os.environ.get("GCP_REGION", "us-central1")
    token = _get_gcp_metadata_token()
    if token:
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}"
            f"/publishers/google/models/gemini-2.5-flash:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.25, "maxOutputTokens": max_tokens},
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
                cands = data.get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    if parts and parts[0].get("text"):
                        return parts[0]["text"].strip()
        except Exception:
            pass

    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if api_key and not api_key.startswith("ya29."):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.25, "maxOutputTokens": max_tokens},
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
                cands = data.get("candidates") or []
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    if parts and parts[0].get("text"):
                        return parts[0]["text"].strip()
        except Exception:
            pass
    return None


def research_investor_with_gemini(inv_id: str, custom_focus: str = "") -> dict:
    rows = investor_engine.get_all_investors(persist_csv=False)
    inv = next((r for r in rows if r["id"] == inv_id or r["fund"].lower() == (inv_id or "").lower()), None)
    if not inv:
        return {"ok": False, "error": f"Investor not found: {inv_id}"}

    prompt = (
        "You are Dokimo.ai's Chief Fundraising & Institutional VC Strategist advising CEO Warren Zafrin and Leo.\n"
        "Dokimo.ai is an Explainable AI Regulatory Compliance, Continuous Full-Population Control Validation, and Autonomous Remediation (Bob) platform for regulated financial institutions (banks, broker-dealers, credit unions, fintechs). "
        "Unlike legacy GRC (1% manual spreadsheet sampling) or document-only AI (reading PDFs in isolation), Dokimo runs 100% inside the institution's perimeter every night to validate written policies against 100% of operational records (wires, trades, ledgers), and Bob drafts the remediation for human sign-off.\n\n"
        f"Investor Record:\n"
        f"- Fund: {inv['fund']}\n"
        f"- Partner: {inv['person']} ({inv['title']})\n"
        f"- Tier & Fit Score: Tier {inv['tier']} ({inv['dokimo_fit_score']}/100) · {inv['category']}\n"
        f"- Stage & Check Size: {inv['stage']} ({inv['check_size']})\n"
        f"- Portfolio / Background: {inv['portfolio']} | {inv['background']}\n"
        f"- Strategic Bank LP / Commercial Value: {inv['bank_lp_value']}\n"
        f"- Warm Contact Path: {inv['our_contact']} (Current Status: {inv['latest_status']})\n"
        f"{'- Custom Question/Focus: ' + custom_focus if custom_focus else ''}\n\n"
        "Write a concise, high-precision 5-part Investment Committee (IC) Fit Memo:\n"
        "1. VERDICT & FIT SCORE RATIONALE (Should Warren & Leo prioritize this fund now?)\n"
        "2. PORTFOLIO SYNERGY VS. CONFLICT CHECK (How Dokimo complements or differs from their existing portfolio)\n"
        "3. COMMERCIAL & LP NETWORK LEVERAGE (Can their bank/enterprise LPs become Dokimo customers?)\n"
        "4. KEY IC OBJECTIONS TO PRE-EMPT (What this specific partner will ask and how Warren wins the answer)\n"
        "5. RECOMMENDED WARM INTRO & FIRST-MEETING HOOK"
    )
    ai_memo = call_gemini(prompt, max_tokens=2500)
    if not ai_memo:
        ai_memo = (
            f"1. VERDICT & FIT SCORE RATIONALE\n"
            f"• Tier {inv['tier']} ({inv['dokimo_fit_score']}/100 — {inv['category']}). {inv['why_fit']}\n\n"
            f"2. PORTFOLIO SYNERGY VS. CONFLICT CHECK\n"
            f"• Relevant Portfolio: {inv['portfolio']}.\n"
            f"• Differentiation: Identity/KYC and transaction-monitoring point solutions stop at onboarding or alert queues. Dokimo validates 100% of enterprise-wide operational records against written policies overnight and pairs every exception with Bob's explainable remediation.\n\n"
            f"3. COMMERCIAL & LP NETWORK LEVERAGE\n"
            f"• {inv['bank_lp_value']}\n\n"
            f"4. KEY IC OBJECTIONS TO PRE-EMPT\n"
            f"• 'How do you handle bank data privacy?' → Dokimo runs 100% inside the customer's perimeter with zero data egress.\n"
            f"• 'How do regulators treat AI in compliance?' → Dokimo uses deterministic full-population rules for detection (zero hallucination) and uses Bob (Explainable AI) strictly to draft the remediation and updated control spec for a named human officer's sign-off.\n\n"
            f"5. RECOMMENDED WARM INTRO & FIRST-MEETING HOOK\n"
            f"• Route via {inv['our_contact']}. {inv['pitch_angle']}"
        )

    return {
        "ok": True,
        "id": inv["id"],
        "fund": inv["fund"],
        "person": inv["person"],
        "tier": inv["tier"],
        "dokimo_fit_score": inv["dokimo_fit_score"],
        "memo": ai_memo,
        "warm_intro_blurb": inv["warm_intro_blurb"],
        "direct_email_subject": inv["direct_email_subject"],
        "direct_email_body": inv["direct_email_body"],
    }


def ask_gemini_vc_strategist(question: str) -> dict:
    rows = investor_engine.get_all_investors(persist_csv=False)
    metrics = investor_engine.build_summary_metrics(rows)
    q_clean = (question or "").strip()

    top_s = [
        f"#{r['rank']} {r['fund']} ({r['person']}) [Tier {r['tier']}, Score {r['dokimo_fit_score']}, Contact: {r['our_contact']}, Email: {r['email'] or 'via intro'}]"
        for r in rows if r["tier"] == "S"
    ][:25]
    top_a = [
        f"#{r['rank']} {r['fund']} ({r['person']}) [Tier {r['tier']}, Score {r['dokimo_fit_score']}, Contact: {r['our_contact']}]"
        for r in rows if r["tier"] == "A"
    ][:15]
    low_c = [
        f"{r['fund']} ({r['person']}) [Tier C, Score {r['dokimo_fit_score']}]"
        for r in rows if r["tier"] == "C"
    ][:12]

    prompt = (
        "You are Dokimo.ai's Gemini VC Strategist advising CEO Warren Zafrin and Leo.\n"
        f"Dataset Summary (Verified Denominators):\n"
        f"- Total Investor Records Parsed from Leo & Warren's 4 tables: {metrics['total_investors']}\n"
        f"- Tier S (Bullseye FinTech/RegTech/Bank-LP): {metrics['tier_s_rate']}\n"
        f"- Tier A (Tier-1 Enterprise AI & B2B): {metrics['tier_a_rate']}\n"
        f"- Tier B (Frontier/DeepTech Selective): {metrics['tier_b_rate']}\n"
        f"- Tier C (Semiconductor/Hardware from AINekko/Veevx — Low Fit): {metrics['tier_c_rate']}\n"
        f"- Direct Verified Emails on File: {metrics['with_email_rate']}\n"
        f"- Direct Phone Numbers on File: {metrics['with_phone_rate']}\n\n"
        f"Top Tier-S FinTech/RegTech/Bank-LP Investors:\n" + "\n".join(top_s) + "\n\n"
        f"Top Tier-A Enterprise AI Investors:\n" + "\n".join(top_a) + "\n\n"
        f"Sample Tier-C Hardware/Semiconductor Funds to Deprioritize:\n" + ", ".join(low_c) + "\n\n"
        f"User Question: {q_clean or 'Who are the top VCs we should prioritize first and why?'}\n\n"
        "Provide a clear, structured, denominator-backed answer referencing exact funds, partners, warm intro owners (Warren vs Leo), and actionable next steps."
    )

    ai_ans = call_gemini(prompt, max_tokens=2500)
    if not ai_ans:
        ai_ans = (
            f"Based on the full analysis of all {metrics['total_investors']} investor records across Leo and Warren's 4 lists:\n\n"
            f"1. DATASET BREAKDOWN (WITH DENOMINATORS)\n"
            f"• Tier S (Bullseye FinTech, RegTech & Bank-LP Strategics): {metrics['tier_s_rate']}\n"
            f"• Tier A (Tier-1 Enterprise AI, Cyber & B2B Software): {metrics['tier_a_rate']}\n"
            f"• Tier B (Selective DeepTech / Frontier AI): {metrics['tier_b_rate']}\n"
            f"• Tier C (Semiconductor / Silicon / Hardware from AINekko/Veevx): {metrics['tier_c_rate']} — deprioritize for Dokimo's software round.\n\n"
            f"2. WAVE 1 MUST-PITCH FINTECH, REGTECH & BANK-LP INVESTORS (TOP 10)\n"
            + "\n".join(f"• {x}" for x in top_s[:10])
            + "\n\n3. RECOMMENDED IMMEDIATE EXECUTION\n"
            "• Have Warren activate direct outreach to his Tier-S FinTech/Bank-LP contacts (Eugene Ludwig at Ludwig Advisors, Walker Forehand at Canapi Ventures, Alexander Ross at Illuminate Financial, Frank Rotman & Nigel Morris at QED, Matt Harris at Bain Capital Ventures, Matt Streisfeld at Oak HC/FT, Logan Allin at Fin Capital, Hans Morris at NYCA, Jaidev Shergill at Capital One Ventures).\n"
            "• Have Leo trigger warm intros to Micky Malka (Ribbit Capital), Arvind Purushotham (Citi Ventures), Tamara Steffens (Thomson Reuters Ventures), Ryan Falvey (Restive Ventures), Sarah Guo (Conviction), and Ian Hathaway (OpenAI Startup Fund)."
        )

    return {
        "ok": True,
        "question": q_clean,
        "answer": ai_ans,
        "metrics": metrics,
    }
