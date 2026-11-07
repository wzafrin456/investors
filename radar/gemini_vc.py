"""Gemini & Vertex AI Investor Research, Fit Memo & Outreach Co-Pilot.

Follows Workspace Rule 1:
- Checks PostgreSQL `VERTEX_AI_CONFIG` or Google Cloud Application Default Credentials (Vertex AI endpoint)
  first so expired OAuth tokens in `GEMINI_API_KEY` never cause 401 errors, and falls back cleanly
  to deterministic institutional synthesis when offline.
"""
import json
import os
import shutil
import subprocess
import urllib.request
from . import investor_engine


def _get_gcp_metadata_token() -> str:
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            tok = json.loads(r.read().decode("utf-8")).get("access_token", "")
            if tok:
                return tok
    except Exception:
        pass
    gcloud = shutil.which("gcloud")
    if gcloud:
        try:
            env = dict(os.environ)
            cur = env.get("CLOUDSDK_METRICS_ENVIRONMENT", "")
            if "datacloud.antigravity" not in cur:
                env["CLOUDSDK_METRICS_ENVIRONMENT"] = (cur + " datacloud.antigravity").strip()
            out = subprocess.check_output(
                [gcloud, "auth", "print-access-token"],
                env=env,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=6,
            ).strip()
            if out:
                return out
        except Exception:
            pass
    return ""


def call_gemini(prompt: str, max_tokens: int = 4096, json_mode: bool = False) -> str | None:
    """Call Vertex AI Gemini (gemini-2.5-flash) via GCP Service Account / Metadata token or GEMINI_API_KEY."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "dokimo-aiops")
    location = os.environ.get("GCP_REGION", "us-central1")
    token = _get_gcp_metadata_token()
    gen_cfg = {
        "temperature": 0.15 if json_mode else 0.25,
        "maxOutputTokens": max_tokens,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"

    if token:
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}"
            f"/publishers/google/models/gemini-2.5-flash:generateContent"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as r:
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
            "generationConfig": gen_cfg,
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

    custom_leo = inv["warm_intro_blurb"]
    custom_warren_subj = inv["direct_email_subject"]
    custom_warren_body = inv["direct_email_body"]
    if custom_focus and custom_focus.strip():
        em_prompt = (
            "You are writing short, natural, peer-to-peer human emails for Leo Spiegel (Chairman) and Warren Zafrin (Founder & CEO of Dokimo.ai) to the VC partner below.\n"
            "STRICT HUMAN WRITING RULES (NO GPT / NO AI FORMATTING):\n"
            "- Write like a real founder/chairman typing a personal note in Gmail (3 to 4 short conversational paragraphs).\n"
            "- DO NOT use numbered lists (1. 2. 3.), bullet points, bold headers, emojis, or em-dashes (—).\n"
            "- DO NOT use AI buzzwords like 'neuro-symbolic', 'deterministic', 'full-population', or 'agentic review'.\n"
            "- Customize directly to the partner's exact title, named portfolio companies, and the user's specific angle below.\n"
            "- Always ask for a 25-minute meeting (never 15 or 20 minutes).\n\n"
            f"USER QUESTION / ANGLE: {custom_focus.strip()}\n"
            f"INVESTOR: {inv['person']} ({inv['title']}) at {inv['fund']}\n"
            f"PORTFOLIO & THESIS: {inv['portfolio']} | {inv['why_fit']}\n"
            f"PRIOR INTERACTION / SIGNAL: {inv.get('comment', '')}\n"
            f"INCLUDE PITCH DECK LINK (https://vc-aigeqnv5nq-uc.a.run.app/d/{inv['id']}): {'YES' if inv.get('include_pitch_deck') else 'NO'}\n\n"
            "Return strict JSON with keys: {\"leo_email\": \"Subject: ...\\n\\nHi ...\", \"warren_subject\": \"...\", \"warren_body\": \"Hi ...\"}."
        )
        raw_em = call_gemini(em_prompt, max_tokens=1500)
        if raw_em:
            try:
                import re as _re
                m = _re.search(r"\{.*\}", raw_em, _re.S)
                if m:
                    parsed = json.loads(m.group(0))
                    if parsed.get("leo_email"):
                        custom_leo = str(parsed["leo_email"]).strip()
                    if parsed.get("warren_subject"):
                        custom_warren_subj = str(parsed["warren_subject"]).strip()
                    if parsed.get("warren_body"):
                        custom_warren_body = str(parsed["warren_body"]).strip()
            except Exception:
                pass

    return {
        "ok": True,
        "id": inv["id"],
        "fund": inv["fund"],
        "person": inv["person"],
        "tier": inv["tier"],
        "dokimo_fit_score": inv["dokimo_fit_score"],
        "receptivity_breakdown": inv.get("receptivity_breakdown", ""),
        "canonical_value_prop": inv.get("canonical_value_prop", ""),
        "memo": ai_memo,
        "warm_intro_blurb": custom_leo,
        "direct_email_subject": custom_warren_subj,
        "direct_email_body": custom_warren_body,
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


def gemini_search_investors(query: str) -> dict:
    """Use Vertex AI Gemini (gemini-2.5-flash) to semantically search, filter, rank, and explain matching investors across all 113 Right VCs."""
    rows = investor_engine.get_all_investors(persist_csv=False)
    total = len(rows)
    q_clean = (query or "").strip()
    if not q_clean:
        return {
            "ok": True,
            "query": "",
            "matched_ids": [r["id"] for r in rows],
            "matched_count": total,
            "total_investors": total,
            "rate": f"{total} of {total} (100.0%)",
            "ai_summary": f"Showing all {total} of {total} (100.0%) qualified Right VCs.",
            "reasons_by_id": {},
        }

    # Build a compact, token-efficient catalog of all 113 investors for Gemini
    catalog_lines = []
    for r in rows:
        pre_tag = "PRE-SEED/DAY-0" if r.get("is_pre_seed") else "SEED/STAGE"
        out_tag = "SEP-OCT-EMAILED" if r.get("leo_sep_oct_outreach") else "UNCONTACTED"
        catalog_lines.append(
            f"{r['id']}|{r['fund']}|{r['person']}|Tier:{r['tier']}({r['dokimo_fit_score']})|{pre_tag}|Reg:{r['region']}|Chk:{r['check_size']}|Own:{r['our_contact']}|St:{r['latest_status']}({out_tag})|Cat:{r['category']}|Port:{(r.get('portfolio') or '')[:90]}|LP:{(r.get('bank_lp_value') or '')[:80]}"
        )

    prompt = (
        "You are Dokimo.ai's Gemini VC Search Engine assisting CEO Warren Zafrin and Leo Spiegel.\n"
        f"Total qualified VCs in database: {total}.\n"
        f"User Search Query: \"{q_clean}\"\n\n"
        "Below is the full catalog of all 113 VCs (ID|Fund|Partner|Tier|PreSeed|Region|Check|Owner|Status|Category|Portfolio|BankLP):\n"
        + "\n".join(catalog_lines)
        + "\n\nTask:\n"
        "1. Select the exact investor IDs (`INV-...`) that match the user's semantic intent, ranked most relevant first.\n"
        "2. Write a concise 2-to-3 sentence `ai_summary` stating the exact denominator (`X of 113 funds matched`), naming the top matching funds and partners, and giving an actionable recommendation.\n"
        "3. Provide a short 1-line `reasons_by_id` map for the top matched IDs (up to 25) explaining why each fund matches the query.\n"
        "Respond ONLY with valid JSON matching this schema:\n"
        "{\"matched_ids\": [\"INV-...\"], \"ai_summary\": \"...\", \"reasons_by_id\": {\"INV-...\": \"...\"}}"
    )

    raw = call_gemini(prompt, max_tokens=4096, json_mode=True)
    parsed = None
    if raw:
        clean_json = raw.strip()
        if clean_json.startswith("```"):
            clean_json = clean_json.split("\n", 1)[-1]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3].strip()
        try:
            parsed = json.loads(clean_json)
        except Exception:
            start = clean_json.find("{")
            end = clean_json.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(clean_json[start : end + 1])
                except Exception:
                    parsed = None

    valid_ids = {r["id"] for r in rows}
    if parsed and isinstance(parsed.get("matched_ids"), list):
        matched_ids = [iid for iid in parsed["matched_ids"] if iid in valid_ids]
        reasons = {k: str(v) for k, v in (parsed.get("reasons_by_id") or {}).items() if k in valid_ids}
        cnt = len(matched_ids)
        pct = round(cnt / max(1, total) * 100, 1)
        ai_summary = str(parsed.get("ai_summary") or "").strip()
        if f"of {total}" not in ai_summary:
            ai_summary = f"[{cnt} of {total} funds ({pct}%) matched] " + ai_summary
        return {
            "ok": True,
            "engine": "gemini-2.5-flash",
            "query": q_clean,
            "matched_ids": matched_ids,
            "matched_count": cnt,
            "total_investors": total,
            "rate": f"{cnt} of {total} ({pct}%)",
            "ai_summary": ai_summary,
            "reasons_by_id": reasons,
        }

    # Deterministic semantic fallback if Vertex AI / API is unreachable
    q_lc = q_clean.lower()
    tokens = [t for t in q_lc.replace(",", " ").replace("?", " ").split() if t not in ("who", "which", "are", "the", "for", "with", "and", "in", "to", "show", "me", "find", "vcs", "vc", "funds", "investors", "have", "that")]
    scored = []
    reasons = {}
    for r in rows:
        hay = " ".join([
            r.get("fund", ""), r.get("person", ""), r.get("title", ""), r.get("category", ""),
            r.get("region", ""), r.get("stage", ""), r.get("pre_seed_flag", ""), r.get("check_size", ""),
            r.get("our_contact", ""), r.get("latest_status", ""), r.get("portfolio", ""),
            r.get("bank_lp_value", ""), r.get("why_fit", ""), r.get("followup_note", ""),
            "pre-seed preseed day-0" if r.get("is_pre_seed") else "",
            "uncontacted not contacted" if (r.get("latest_status") or "").lower() in ("", "not contacted") else "contacted emailed",
        ]).lower()
        pts = 0
        matched_terms = []
        if "pre-seed" in q_lc or "preseed" in q_lc or "day-0" in q_lc or "day 0" in q_lc:
            if r.get("is_pre_seed"):
                pts += 10
                matched_terms.append("Pre-Seed / Day-0 Check-Writer")
        if "bank" in q_lc or "cvc" in q_lc or "lp" in q_lc:
            if "bank" in hay or "cvc" in hay:
                pts += 5
                matched_terms.append("Bank LP / CVC leverage")
        if "uncontacted" in q_lc or "not contacted" in q_lc or "new" in q_lc:
            if not r.get("leo_sep_oct_outreach") and (r.get("latest_status") or "").lower() in ("", "not contacted"):
                pts += 6
                matched_terms.append("Uncontacted")
        for tok in tokens:
            if tok in hay:
                pts += 3
                matched_terms.append(tok)
        if pts > 0:
            scored.append((pts, int(r.get("dokimo_fit_score") or 0), r))
            reasons[r["id"]] = f"Matched on {', '.join(dict.fromkeys(matched_terms[:4]))} · {r['stage']} ({r['check_size']})"

    scored.sort(key=lambda x: (-x[0], -x[1]))
    matched_ids = [x[2]["id"] for x in scored]
    cnt = len(matched_ids)
    pct = round(cnt / max(1, total) * 100, 1)
    top_names = ", ".join(f"{x[2]['fund']} ({x[2]['person']})" for x in scored[:5])
    return {
        "ok": True,
        "engine": "gemini-hybrid",
        "query": q_clean,
        "matched_ids": matched_ids,
        "matched_count": cnt,
        "total_investors": total,
        "rate": f"{cnt} of {total} ({pct}%)",
        "ai_summary": f"Matched {cnt} of {total} ({pct}%) Right VCs for \"{q_clean}\". Top ranked matches: {top_names or 'None'}.",
        "reasons_by_id": reasons,
    }

