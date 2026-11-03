"""2-Page PDF Investor Pitch Memo ('Dokimo VC Tear-Sheet') Generator.

Generates a standards-compliant 2-page PDF 1.4 document tailored specifically to any
of the 213 investors on the Dokimo Investor Radar board, highlighting:
  - Page 1: Fund-Specific Thesis Alignment, Portfolio Synergy, Problem & Dokimo Architecture
  - Page 2: Live Regulatory Signal Traction, Portfolio/Bank-LP Co-Sell Blueprint & Deal Highlights
"""
import datetime
import re


def _pdf_escape(txt: str) -> str:
    clean = (
        (txt or "")
        .replace("—", "-")
        .replace("–", "-")
        .replace("·", "|")
        .replace("•", "*")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
        .replace("→", "->")
        .replace("≤", "<=")
        .replace("≥", ">=")
    )
    clean = clean.encode("ascii", errors="ignore").decode("ascii")
    return clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_pdf_lines(text: str, width: int = 94) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def generate_investor_tearsheet_pdf(investor: dict) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for a customized 2-page Dokimo VC Tear-Sheet PDF."""
    inv_id = investor.get("id") or "INV-001"
    fund = investor.get("fund") or "Venture Partner"
    person = investor.get("person") or "General Partner"
    title = investor.get("title") or "Partner"
    tier = investor.get("tier") or "S"
    score = investor.get("dokimo_fit_score") or 95
    category = investor.get("category") or "FinTech & Enterprise AI VC"
    stage = investor.get("stage") or "Seed / Series A"
    check_size = investor.get("check_size") or "$2M - $15M"
    our_contact = investor.get("our_contact") or "Warren / Leo"
    email = investor.get("email") or "warren@dokimo.ai"
    portfolio = investor.get("portfolio") or "Enterprise AI, FinTech & Regulated Infrastructure"
    bank_lp_value = investor.get("bank_lp_value") or "Strategic enterprise and financial services buyer network."
    why_fit = investor.get("why_fit") or f"{fund} backs category-defining enterprise software and financial infrastructure."
    pitch_angle = investor.get("pitch_angle") or "Full-population policy-to-record control validation + Bob autonomous remediation."
    date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y")

    # ---------------- PAGE 1 ----------------
    ops_p1 = [
        # Top Header Banner (Dark Navy #111827)
        "0.067 0.094 0.153 rg",
        "36 704 540 60 re f",
        "1 1 1 rg",
        "BT /F2 8.5 Tf 48 748 Td (DOKIMO.AI  |  CONFIDENTIAL 2-PAGE VC TEAR-SHEET & CUSTOM INVESTMENT MEMO  [PAGE 1 OF 2]) Tj ET",
        f"BT /F2 13.5 Tf 48 730 Td (DOKIMO.AI x {_pdf_escape(fund.upper()[:46])}) Tj ET",
        f"BT /F1 8.5 Tf 48 714 Td (Prepared for: {_pdf_escape(person)} ({_pdf_escape(title[:42])})  |  Contact: {_pdf_escape(email)}  |  Date: {_pdf_escape(date_str)}) Tj ET",
        # Sub-banner KPI bar
        "0.937 0.957 0.980 rg",
        "36 676 540 24 re f",
        "0.118 0.251 0.686 rg",
        f"BT /F2 8.2 Tf 48 685 Td (DOKIMO FIT: {score}/100 (TIER {_pdf_escape(tier)})  |  CATEGORY: {_pdf_escape(category[:36])}  |  CHECK: {_pdf_escape(check_size)}  |  LEAD: {_pdf_escape(our_contact)}) Tj ET",
    ]

    y1 = 652

    def _p1_header(heading: str):
        nonlocal y1
        ops_p1.append("0.698 0.133 0.204 rg")
        ops_p1.append(f"36 {y1 - 3} 4 14 re f")
        ops_p1.append("0.067 0.094 0.153 rg")
        ops_p1.append(f"BT /F2 10.2 Tf 46 {y1} Td ({_pdf_escape(heading)}) Tj ET")
        y1 -= 15

    def _p1_para(text: str, bold_prefix: str = "", indent: int = 46):
        nonlocal y1
        full_txt = (bold_prefix + " " + text).strip() if bold_prefix else text
        lines = _wrap_pdf_lines(full_txt, width=94)
        ops_p1.append("0.16 0.19 0.24 rg")
        for idx_l, ln in enumerate(lines):
            font_tag = "/F2" if (idx_l == 0 and bold_prefix) else "/F1"
            ops_p1.append(f"BT {font_tag} 8.7 Tf {indent} {y1} Td ({_pdf_escape(ln)}) Tj ET")
            y1 -= 11.5
        y1 -= 3.5

    _p1_header(f"1. EXECUTIVE THESIS: WHY DOKIMO.AI FITS {fund.upper()}")
    _p1_para(why_fit, bold_prefix="Thesis Alignment:")
    _p1_para(portfolio, bold_prefix=f"{fund} Portfolio Context:")
    _p1_para(pitch_angle, bold_prefix="Core Investment Hook:")

    _p1_header("2. THE STRUCTURAL FAILURE IN REGULATED FINANCIAL COMPLIANCE")
    _p1_para(
        "Regulated banks, broker-dealers, credit unions, and fintechs spend $180B+ annually on compliance, internal audit, and supervisory remediation (OCC, FDIC, FRB, CFPB, SEC 15c3-3, FINRA 3310, FinCEN BSA/AML, EU DORA). Yet repeat consent orders and Matters Requiring Attention (MRAs) are at an all-time high."
    )
    _p1_para(
        "1. Legacy GRC & Manual Lookbacks Only Test 1% Samples: Compliance and internal audit teams pull 25-to-50 row spreadsheet samples once a quarter. Examiners now reject sample-based assurance when underlying transaction feeds contain millions of rows."
    )
    _p1_para(
        "2. First-Wave 'Document AI' Stops at Reading PDFs: Generic LLM tools summarize policy documents or draft memos in isolation, but cannot verify whether production wire corridors, customer reserve ledgers, or AML alert engines actually obeyed the written rule."
    )

    _p1_header("3. THE DOKIMO.AI SOLUTION: FULL-POPULATION VALIDATION + BOB REMEDIATION")
    _p1_para(
        "Pillar 1 - Policy-to-Control Compilation: Dokimo ingests written internal policies, consent orders, and statutory rules (e.g., FINRA 3310, SEC 15c3-3, OCC Heightened Standards) and compiles version-controlled validation specifications."
    )
    _p1_para(
        "Pillar 2 - Nightly 100% Full-Population Record Testing (Zero Data Egress): Dokimo executes inside the institution's own VPC or on-prem perimeter, validating 100% of operational records across core banking, wire, trade, and surveillance silos every night."
    )
    _p1_para(
        "Pillar 3 - Bob (Explainable AI Compliance & Remediation Agent): Whenever a control exception occurs, Bob cites the exact failing record IDs and denominator, maps the statutory breach, and drafts the concrete remediation & control patch for a named officer's sign-off."
    )

    # Page 1 Footer
    ops_p1.extend([
        "0.067 0.094 0.153 rg",
        "36 38 540 28 re f",
        "1 1 1 rg",
        f"BT /F2 8.3 Tf 48 50 Td (DOKIMO.AI  |  Custom Tear-Sheet for {_pdf_escape(fund)} ({_pdf_escape(inv_id)})  |  Continued on Page 2 ->) Tj ET",
    ])

    # ---------------- PAGE 2 ----------------
    ops_p2 = [
        # Top Header Banner
        "0.067 0.094 0.153 rg",
        "36 704 540 60 re f",
        "1 1 1 rg",
        "BT /F2 8.5 Tf 48 748 Td (DOKIMO.AI  |  CONFIDENTIAL 2-PAGE VC TEAR-SHEET & CUSTOM INVESTMENT MEMO  [PAGE 2 OF 2]) Tj ET",
        f"BT /F2 13.5 Tf 48 730 Td (TRACTION, PORTFOLIO SYNERGY & DEAL HIGHLIGHTS FOR {_pdf_escape(fund.upper()[:34])}) Tj ET",
        f"BT /F1 8.5 Tf 48 714 Td (Partner: {_pdf_escape(person)}  |  Stage: {_pdf_escape(stage)}  |  Target Check: {_pdf_escape(check_size)}  |  Ref: {_pdf_escape(inv_id)}) Tj ET",
        # Sub-banner bar
        "0.937 0.957 0.980 rg",
        "36 676 540 24 re f",
        "0.118 0.251 0.686 rg",
        "BT /F2 8.2 Tf 48 685 Td (LIVE COVERAGE: 20,065 Regulated Institutions  |  16 Global Regulators  |  288+ Active Enforcement Orders Tracked) Tj ET",
    ]

    y2 = 652

    def _p2_header(heading: str):
        nonlocal y2
        ops_p2.append("0.698 0.133 0.204 rg")
        ops_p2.append(f"36 {y2 - 3} 4 14 re f")
        ops_p2.append("0.067 0.094 0.153 rg")
        ops_p2.append(f"BT /F2 10.2 Tf 46 {y2} Td ({_pdf_escape(heading)}) Tj ET")
        y2 -= 15

    def _p2_para(text: str, bold_prefix: str = "", indent: int = 46):
        nonlocal y2
        full_txt = (bold_prefix + " " + text).strip() if bold_prefix else text
        lines = _wrap_pdf_lines(full_txt, width=94)
        ops_p2.append("0.16 0.19 0.24 rg")
        for idx_l, ln in enumerate(lines):
            font_tag = "/F2" if (idx_l == 0 and bold_prefix) else "/F1"
            ops_p2.append(f"BT {font_tag} 8.7 Tf {indent} {y2} Td ({_pdf_escape(ln)}) Tj ET")
            y2 -= 11.5
        y2 -= 3.5

    _p2_header(f"4. STRATEGIC LP & PORTFOLIO SYNERGY WITH {fund.upper()}")
    _p2_para(bank_lp_value, bold_prefix="Institutional Network & LP Leverage:")
    _p2_para(
        f"Co-Sell & Design Partner Flywheel: Every regulated bank, fintech, or enterprise in {fund}'s ecosystem faces annual supervisory examinations. Dokimo's '15-Minute Bring One Control' onboarding lets {fund}'s LPs and portfolio companies validate one high-priority regulatory control inside their own environment in under 30 days."
    )

    _p2_header("5. LIVE AUTONOMOUS GTM ENGINE & REGULATORY SIGNAL GRAPH")
    _p2_para(
        "Unlike traditional enterprise startups with cold outbound GTM, Dokimo built an autonomous Regulatory Signal & Enforcement Intelligence Engine monitoring 20,065 US & global financial institutions across 16 regulators (OCC, FRB, FDIC, CFPB, FinCEN, SEC, FINRA, NYDFS, FCA, PRA, BaFin, ECB, EBA, MAS, ASIC, OSFI)."
    )
    _p2_para(
        "When a bank or peer institution receives a Consent Order, Cease & Desist, or Formal Agreement, Dokimo automatically maps the exact control failure, generates a custom 1-Page Examiner Control Tear-Down, and initiates personalized executive outreach to the CCO, CRO, and General Counsel."
    )

    _p2_header("6. DEFENSIBLE ARCHITECTURAL MOAT & ENTERPRISE SECURITY")
    _p2_para(
        "1. Neuro-Symbolic Accuracy (Zero Hallucinated Numbers): Deterministic SQL/Python control execution guarantees 100% mathematical precision with explicit denominators on every rate, while Bob (LLM) synthesizes the regulatory mapping and remediation code."
    )
    _p2_para(
        "2. 100% Customer-Perimeter Isolation: Deploys via Docker/Kubernetes inside the bank's VPC or air-gapped on-prem environment. Raw customer PII and transaction ledgers never leave the institution."
    )
    _p2_para(
        "3. Tamper-Evident Examiner Evidence Packs: Generates cryptographically verifiable control execution logs ready to hand directly to OCC, FDIC, SEC, FINRA, or Big-4 independent auditors."
    )

    _p2_header("7. FOUNDING TEAM & IMMEDIATE NEXT STEP")
    _p2_para(
        f"Founding Leadership: Warren Zafrin (CEO, warren@dokimo.ai) & Leo (Co-Founder) — deep institutional track record across regulated financial infrastructure, enterprise AIops, and autonomous compliance engineering."
    )
    _p2_para(
        f"Proposed Next Step for {person} ({fund}): 20-minute live platform walkthrough demonstrating (a) Dokimo's Full-Population Control Engine, (b) Bob's interactive policy & MRA remediation workflow, and (c) the live 20,065-institution Regulatory Signal Graph."
    )

    # Page 2 Footer Box
    ops_p2.extend([
        "0.067 0.094 0.153 rg",
        "36 38 540 36 re f",
        "1 1 1 rg",
        f"BT /F2 9 Tf 48 58 Td (SCHEDULE PARTNER WALKTHROUGH: Warren Zafrin, CEO - warren@dokimo.ai  |  https://dokimo.ai) Tj ET",
        f"BT /F1 8.2 Tf 48 45 Td (Prepared Exclusively for {_pdf_escape(person)} at {_pdf_escape(fund)}  |  Dokimo Investor Radar Ref: {_pdf_escape(inv_id)}) Tj ET",
    ])

    b_p1 = "\n".join(ops_p1).encode("ascii")
    b_p2 = "\n".join(ops_p2).encode("ascii")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 7 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 8 0 R >>\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n",
        f"7 0 obj\n<< /Length {len(b_p1)} >>\nstream\n".encode("ascii") + b_p1 + b"\nendstream\nendobj\n",
        f"8 0 obj\n<< /Length {len(b_p2)} >>\nstream\n".encode("ascii") + b_p2 + b"\nendstream\nendobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", fund).strip("_")[:40]
    filename = f"Dokimo_2Page_VC_TearSheet_{slug}_{inv_id}.pdf"
    return bytes(pdf), filename
