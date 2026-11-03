"""Dokimo Investor Research, Multi-Table Parser, Enrichment & Fit Scoring Engine.

Parses all 4 tables from Leo & Warren's raw list (data/raw_leo_investors.txt),
enriches partner names, emails, phones, LinkedIn URLs, check sizes, and portfolio history,
and scores every investor (0-100) across 4 tiers (Tier S, Tier A, Tier B, Tier C)
specifically for Dokimo.ai (Explainable AI Regulatory Compliance, Full-Population
Control Validation & Bob Autonomous Remediation for Regulated Financial Institutions).
"""
import csv
import datetime
import hashlib
import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = ROOT / "data" / "raw_leo_investors.txt"
CSV_FILE = ROOT / "data" / "investors.csv"
STATE_FILE = ROOT / "output" / "investor_state.json"

# Curated institutional knowledge base for funds in Leo & Warren's list
FUND_KB = {
    "ludwig advisors": {
        "category": "RegTech & Bank Regulatory Specialist",
        "tier": "S",
        "base_score": 99,
        "stage": "Seed / Series A / Strategic",
        "check_size": "$1M – $10M",
        "partner_default": "Eugene Ludwig",
        "title_default": "Managing Partner (Former US Comptroller of the Currency / OCC)",
        "website": "https://ludwigadvisors.com",
        "portfolio": "Promontory Financial Group (Founder), Canapi Ventures (Co-Founder), Sovereign Bank Regulatory Advisory",
        "bank_lp_value": "Direct C-Suite & Board access to 100+ US national & regional banks; former head of the OCC.",
        "why_fit": "Eugene Ludwig is the former US Comptroller of the Currency (OCC), founder of Promontory Financial Group, and co-founder of Canapi Ventures. No investor in the world understands OCC/FDIC/FRB consent orders, MRA remediation, and full-population control validation better.",
        "pitch_angle": "Lead with Dokimo's deterministic full-population policy-to-record control validation + Bob's explainable remediation engine replacing manual sample-based Promontory-style lookbacks.",
    },
    "canapi ventures": {
        "category": "Bank-LP Alliance FinTech & RegTech VC",
        "tier": "S",
        "base_score": 99,
        "stage": "Seed / Series A / Series B",
        "check_size": "$3M – $15M",
        "partner_default": "Walker Forehand",
        "title_default": "President, Co-Founder & General Partner",
        "website": "https://canapi.com",
        "portfolio": "Alloy, Blend, Middesk, Notarize, Island, Greenlight ($1.3B+ AUM across 70+ Bank LPs)",
        "bank_lp_value": "Backed by the Canapi Alliance of 70+ US banks (Live Oak, Huntington, Fifth Third, Comerica, USAA, etc.) — every LP is an immediate Dokimo buyer.",
        "why_fit": "Co-founded by Gene Ludwig and Chip Mahan with 70+ financial institutions as LPs. Actively invests in compliance, risk, and bank infrastructure where its bank LPs serve as design partners and commercial customers.",
        "pitch_angle": "Position Dokimo as the missing continuous control validation layer for Canapi's 70+ regional/super-regional bank LPs facing heightened OCC/FDIC/BSA exam scrutiny.",
    },
    "ribbit capital": {
        "category": "Tier-1 FinTech & Compliance Infrastructure VC",
        "tier": "S",
        "base_score": 98,
        "stage": "Seed / Series A / Series B",
        "check_size": "$5M – $25M",
        "partner_default": "Micky Malka",
        "title_default": "Founder & Managing Partner",
        "email_default": "micky@ribbitcap.com",
        "person_linkedin": "https://www.linkedin.com/in/mickymalka/",
        "website": "https://www.ribbitcap.com",
        "portfolio": "Chainalysis, Alloy, Coinbase, Nubank, Robinhood, Brex, Plaid",
        "bank_lp_value": "Global #1 pure-play FinTech/RegTech investor; portfolio compliance teams (Alloy, Chainalysis, Coinbase) are immediate ecosystem partners.",
        "why_fit": "Ribbit backed category-defining compliance infrastructure (Chainalysis, Alloy). Dokimo's shift from 1% sampling and document-only AI to 100% operational record validation is squarely in Micky Malka's wheelhouse.",
        "pitch_angle": "Show how Dokimo validates 100% of underlying ledger, wire, and trade records against written policies inside the institution's perimeter—complementing identity/KYC tools like Alloy.",
    },
    "illuminate financial": {
        "category": "Bank-Backed Capital Markets & RegTech VC",
        "tier": "S",
        "base_score": 98,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Alexander Ross",
        "title_default": "General Partner | Head of NYC",
        "website": "https://illuminatefinancial.com",
        "portfolio": "SteelEye, Baton Systems, CloudMargin, Privitar, Blockdaemon ($470M AUM)",
        "bank_lp_value": "Strategic LPs include J.P. Morgan, Citi, Barclays, BNY Mellon, Deutsche Börse, S&P Global, and Jefferies.",
        "why_fit": "Illuminate is purpose-built for enterprise capital markets, banking compliance, and regulatory technology, with Tier-1 global banks as strategic LPs who actively co-pilot portfolio solutions.",
        "pitch_angle": "Highlight SEC 15c3-3, CAT reporting, FINRA 3310, and cross-silo trade/wire control validation deployed 100% inside bank perimeters.",
    },
    "qed investors": {
        "category": "Tier-1 FinTech & Banking Operations VC",
        "tier": "S",
        "base_score": 97,
        "stage": "Seed / Series A / Series B",
        "check_size": "$3M – $20M",
        "partner_default": "Frank Rotman",
        "title_default": "Founding Partner",
        "website": "https://qedinvestors.com",
        "portfolio": "Credit Karma, Nubank, Remitly, SoFi, Hawk AI (AML/Compliance), Taktile ($3.3B+ AUM)",
        "bank_lp_value": "Founded by Capital One co-founders (Nigel Morris & Frank Rotman); deep operating network across US/UK/LatAm bank CROs and CCOs.",
        "why_fit": "QED founders built Capital One's data-driven risk and compliance engine from scratch and backed Hawk AI & Taktile. Both Frank Rotman and Nigel Morris are on Warren's contact list.",
        "pitch_angle": "Frame Dokimo as 'Information-Based Strategy (IBS) for Compliance & Internal Audit' — deterministic full-population testing paired with Bob's explainable remediation.",
    },
    "citigroup ventures": {
        "category": "Tier-1 Bank Strategic CVC",
        "tier": "S",
        "base_score": 97,
        "stage": "Seed / Series A / Series B Strategic",
        "check_size": "$3M – $15M",
        "partner_default": "Arvind Purushotham",
        "title_default": "Global Head of Citi Ventures",
        "email_default": "arvind.purushotham@citi.com",
        "website": "https://citi.com/ventures",
        "portfolio": "Feedzai, Socure, Chainalysis, Plaid, Trulioo, Snyk, Databricks",
        "bank_lp_value": "Citi has spent billions on consent-order data governance and internal control remediation — Citi is both a marquee investor and a massive commercial buyer.",
        "why_fit": "Citi's #1 board priority is automated data governance, regulatory reporting lineage, and consent-order control validation. Arvind Purushotham (via Leo) and Jelena Zec are directly on this list.",
        "pitch_angle": "Demonstrate how Dokimo automates full-population policy-to-record validation and audit evidence generation across fragmented banking data silos with zero data egress.",
    },
    "capital one ventures": {
        "category": "Tier-1 Bank Strategic CVC",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A / Series B Strategic",
        "check_size": "$2M – $15M",
        "partner_default": "Jaidev Shergill",
        "title_default": "Managing Partner & President, Capital One Ventures",
        "website": "https://capitalone.com/ventures",
        "portfolio": "Snowflake, Databricks, Sardinai, Persona, Secoda, Monte Carlo",
        "bank_lp_value": "Direct commercial channel into Capital One's cloud-native risk, data governance, and compliance engineering teams.",
        "why_fit": "Jaidev Shergill leads Capital One Ventures and heavily backs data observability, security, and automated risk/compliance infrastructure.",
        "pitch_angle": "Show how Dokimo sits on top of cloud data warehouses to validate 100% of operational records against regulatory rules nightly.",
    },
    "thomson reuters ventures": {
        "category": "RegTech, Legal, Risk & Compliance Strategic CVC",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Tamara Steffens",
        "title_default": "Managing Director",
        "email_default": "tamara.steffens@thomsonreuters.com",
        "person_linkedin": "https://www.linkedin.com/in/tamarasteffens/",
        "website": "https://www.trventures.com",
        "portfolio": "$250M Fund focused explicitly on Risk, Fraud, Compliance, Tax & Legal AI",
        "bank_lp_value": "Distribution & co-sell access to Thomson Reuters' global Regulatory Intelligence and Risk & Compliance customer base.",
        "why_fit": "Thomson Reuters Ventures' explicit mandate is AI for risk, fraud, and regulatory compliance. Dokimo bridges regulatory intelligence directly to operational record validation.",
        "pitch_angle": "Highlight how Dokimo turns regulatory obligations into executable full-population control checks and Bob-authored remediations.",
    },
    "bain capital ventures": {
        "category": "Tier-1 FinTech & Enterprise AI VC",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A / Series B",
        "check_size": "$3M – $25M",
        "partner_default": "Matt Harris",
        "title_default": "Partner (Head of FinTech)",
        "website": "https://baincapitalventures.com",
        "portfolio": "Socure, Alloy, Sardine, Finix, AvidXchange, Moveworks ($5.7B+ AUM)",
        "bank_lp_value": "Matt Harris is one of the most influential FinTech/RegTech investors in the US (backed Socure, Alloy, Sardine).",
        "why_fit": "Matt Harris has a 20+ year track record backing the foundational compliance and fraud stack (Socure, Alloy, Sardine). Dokimo is the natural next layer: autonomous internal control validation & remediation.",
        "pitch_angle": "Pitch Dokimo as the system of record for continuous post-onboarding & enterprise-wide regulatory control validation.",
    },
    "oak hc/ft": {
        "category": "Tier-1 FinTech & RegTech Specialist VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A / Growth",
        "check_size": "$5M – $30M",
        "partner_default": "Matt Streisfeld",
        "title_default": "General Partner",
        "website": "https://oakhcft.com",
        "portfolio": "Feedzai, Prove, Persona, Ethic, Paxos, Next Insurance ($4.7B AUM)",
        "bank_lp_value": "Deep executive advisory board of former bank CEOs, CROs, and CCOs.",
        "why_fit": "Oak HC/FT focuses exclusively on FinTech and Healthcare IT, with deep conviction in financial crime, risk, and regulatory compliance platforms.",
        "pitch_angle": "Emphasize how regulated institutions use Dokimo + Bob to eliminate exam surprises and cut MRA remediation timelines by 70%.",
    },
    "motive partners": {
        "category": "Financial Technology & Core Banking Specialist VC/PE",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A / Growth (Motive Ventures)",
        "check_size": "$2M – $20M",
        "partner_default": "Rob Heyvaert",
        "title_default": "Founder & Managing Partner",
        "website": "https://motivepartners.com",
        "portfolio": "InvestCloud, Wilshire, Backbase, Splitit, ComplyAdvantage ecosystem ($3B+ AUM)",
        "bank_lp_value": "Motive Create & Motive Labs partner directly with FIS, Fiserv, and global banks on core banking & compliance transformation.",
        "why_fit": "Rob Heyvaert built Capco and Motive Partners around bank technology transformation and regulatory infrastructure.",
        "pitch_angle": "Show how Dokimo plugs into legacy core banking & wealth platforms to provide continuous regulatory control assurance.",
    },
    "fin capital": {
        "category": "B2B FinTech & Enterprise RegTech Specialist VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A / Series B",
        "check_size": "$2M – $15M",
        "partner_default": "Logan Allin",
        "title_default": "Managing Partner & Founder",
        "website": "https://fin.capital",
        "portfolio": "Hummingbird (AML/SAR), Sumsub, Matera, Kopperfield, Array, Unqork",
        "bank_lp_value": "100% focused on B2B enterprise FinTech/RegTech with corporate bank LPs and Lighthouse enterprise bank program.",
        "why_fit": "Fin Capital invests exclusively in B2B FinTech/RegTech software (backed Hummingbird and Sumsub) and runs corporate bank pilot programs.",
        "pitch_angle": "Position Dokimo as enterprise-grade explainable AI that validates 100% of operational records before examiners arrive.",
    },
    "fintech collective": {
        "category": "Pure-Play FinTech & Capital Markets VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed / Series A",
        "check_size": "$1.5M – $8M",
        "partner_default": "Brooks Gibbins",
        "title_default": "Co-Founder and Managing Partner",
        "website": "https://fintech.io",
        "portfolio": "NYDIG, Ocrolus, Vestwell, Axoni, Quovo ($343M AUM)",
        "bank_lp_value": "NYC-based FinTech specialist with deep ties to Wall Street compliance, wealth, and banking leaders.",
        "why_fit": "Brooks Gibbins backs foundational data and workflow infrastructure for regulated capital markets and banking institutions.",
        "pitch_angle": "Show how Dokimo goes beyond document automation (like Ocrolus) to validate 100% of ledger and transaction records against written policies.",
    },
    "restive ventures": {
        "category": "Pure-Play AI FinTech & RegTech Seed/A VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed / Series A",
        "check_size": "$1M – $4M",
        "partner_default": "Ryan Falvey",
        "title_default": "Co-Founder & Managing Partner",
        "email_default": "ryan@restive.com",
        "website": "https://www.restive.com",
        "portfolio": "Plaid (early), Cable (automated financial crime assurance), FinTech AI Fund III ($45M)",
        "bank_lp_value": "Ryan Falvey previously backed Cable (automated compliance assurance) and runs a dedicated FinTech regulatory network.",
        "why_fit": "Restive's new $45M Fund III is explicitly dedicated to AI-powered financial services and regulatory infrastructure.",
        "pitch_angle": "Highlight Dokimo's live regulatory signal traction + full-population control testing + Bob's explainable remediation.",
    },
    "nyca": {
        "category": "Wall Street & Bank Executive FinTech VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Hans Morris",
        "title_default": "Managing Partner (Former President of Visa, COO of Citigroup CIB)",
        "website": "https://nyca.com",
        "portfolio": "Affirm, Plaid, SentiLink, TrueAccord, Provenance ($339M+ AUM)",
        "bank_lp_value": "NYCA's Limited Partner Advisor Network (LPAN) comprises 70+ former C-level bank, regulatory, and payments executives.",
        "why_fit": "Hans Morris (former President of Visa & Citi exec) and Thomas Brown (former Partner at Paul Hastings Financial Services) bring unmatched regulatory and C-suite bank doors.",
        "pitch_angle": "Focus on how Dokimo gives bank CCOs, CROs, and General Counsel tamper-evident proof that 100% of operational records comply with supervisory rules.",
    },
    "f-prime capital": {
        "category": "Fidelity-Backed FinTech & Enterprise AI VC",
        "tier": "S",
        "base_score": 93,
        "stage": "Seed / Series A / Series B",
        "check_size": "$3M – $15M",
        "partner_default": "David Jegen",
        "title_default": "Managing Partner (Head of FinTech)",
        "website": "https://fprimecapital.com",
        "portfolio": "Flywire, Plaid, Toast, Argyle, PerformLine (compliance monitoring)",
        "bank_lp_value": "Backed by Fidelity Investments; direct access to Fidelity's broker-dealer, asset management, and clearing ecosystem.",
        "why_fit": "David Jegen leads F-Prime's FinTech practice and publishes the F-Prime State of FinTech report; deep conviction in RegTech & wealth/broker-dealer compliance.",
        "pitch_angle": "Emphasize FINRA 3310, SEC 15c3-3, and CAT full-population control validation for broker-dealers, RIAs, and banks.",
    },
    "the legaltech fund": {
        "category": "Legal, Governance, Risk & Compliance Specialist VC",
        "tier": "S",
        "base_score": 93,
        "stage": "Seed / Series A",
        "check_size": "$1M – $5M",
        "partner_default": "Zach Posner",
        "title_default": "Co-Founder & Managing Partner",
        "website": "https://legaltech.com",
        "portfolio": "Carta, Ironclad, Harvey ecosystem, RegTech & GRC automation ($138M AUM)",
        "bank_lp_value": "Direct access to General Counsel, Chief Legal Officers, and CCOs across Fortune 500 and financial institutions.",
        "why_fit": "Specifically invests at the intersection of regulatory law, compliance policies, and enterprise enforcement defense.",
        "pitch_angle": "Show why document-only legal AI is not enough for regulated finance: Dokimo tests written legal/compliance policies against 100% of operational records.",
    },
    "conviction": {
        "category": "AI-Native ('Software 3.0') Enterprise & Compliance VC",
        "tier": "S",
        "base_score": 93,
        "stage": "Seed / Series A",
        "check_size": "$2M – $15M",
        "partner_default": "Sarah Guo",
        "title_default": "Founder & General Partner (ex-Greylock)",
        "email_default": "sarah@conviction.com",
        "website": "https://www.conviction.com",
        "portfolio": "Harvey (AI legal/compliance at $11B), Sierra, Baseten, Contextual AI, Vanta (at Greylock)",
        "bank_lp_value": "Sarah Guo backed Vanta (automated security compliance) and Harvey (AI legal); deep conviction in autonomous compliance agents.",
        "why_fit": "Sarah Guo backed both Vanta (continuous compliance) and Harvey. Dokimo is the exact fusion for regulated finance: continuous full-population data control validation + Bob (autonomous remediation agent).",
        "pitch_angle": "Pitch Dokimo as 'Vanta + Harvey for Regulated Financial Operations' — testing 100% of production records inside the bank's perimeter.",
    },
    "work-bench": {
        "category": "NYC Enterprise Software, Cyber & Bank GTM VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$2M – $8M",
        "partner_default": "Jessica Lin",
        "title_default": "Co-Founder & General Partner",
        "website": "https://work-bench.com",
        "portfolio": "CockroachDB, Socure, Arthur AI (explainable AI), Venn, Authzed ($307M AUM)",
        "bank_lp_value": "Runs NYC's premier Fortune 500 CISO/CIO/CCO enterprise buyer community with Wall Street banks.",
        "why_fit": "Work-Bench backed Socure and Arthur AI (Explainable AI) and specializes in selling enterprise infrastructure into Wall Street banks. Warm paths via both Warren and Justin.",
        "pitch_angle": "Leverage Work-Bench's Wall Street enterprise customer network and deep thesis on Explainable AI governance.",
    },
    "ejf ventures": {
        "category": "Community & Regional Bank Specialist FinTech VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Jonathan Bresler",
        "title_default": "Managing Partner",
        "website": "https://ejfcap.com",
        "portfolio": "EJF Silvergate/Bank FinTech Fund ($1.2B+ platform AUM across US regional & community banks)",
        "bank_lp_value": "EJF Capital is one of the largest debt/equity investors in US regional and community banks — direct introductions to 200+ bank CEOs.",
        "why_fit": "EJF Ventures specifically backs technology that solves regulatory, compliance, and operational bottlenecks for US regional and community banks.",
        "pitch_angle": "Show how regional banks under $50B assets use Dokimo to pass OCC/FDIC/BSA exams without hiring 30 manual compliance analysts.",
    },
    "sixthirty ventures": {
        "category": "Financial Services & InsurTech Go-To-Market VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$1M – $5M",
        "partner_default": "Atul Kamra",
        "title_default": "Managing Partner",
        "website": "https://sixthirty.co",
        "portfolio": "ComplyAdvantage, Untangled, Covercy, FinLocker ($84M AUM)",
        "bank_lp_value": "Early investor in ComplyAdvantage; runs hands-on business development programs with bank & wealth LPs.",
        "why_fit": "Atul Kamra backed ComplyAdvantage and focuses exclusively on enterprise FinTech, RegTech, and Cyber for financial institutions.",
        "pitch_angle": "Position Dokimo as the continuous internal control validation and automated remediation engine for SixThirty's bank & wealth LPs.",
    },
    "mouro capital": {
        "category": "Banco Santander-Backed Global FinTech & RegTech VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A / Series B",
        "check_size": "$3M – $15M",
        "partner_default": "Manuel Silva Martinez",
        "title_default": "General Partner",
        "website": "https://mourocapital.com",
        "portfolio": "Trulioo, Elliptic (crypto AML), Upgrade, Curve, Roostify ($400M AUM)",
        "bank_lp_value": "Spun out of Santander InnoVentures; strong US/UK/EU bank compliance & AML footprint (backed Trulioo & Elliptic).",
        "why_fit": "Mouro backed Trulioo and Elliptic and actively invests in cross-border banking compliance and regulatory automation.",
        "pitch_angle": "Highlight multi-jurisdiction coverage (US OCC/FDIC/FinCEN + UK FCA/PRA + EU DORA/BaFin/ECB) inside a single perimeter-isolated engine.",
    },
    "anthemis": {
        "category": "Global FinTech & Risk Infrastructure VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$1.5M – $10M",
        "partner_default": "Amy Nauiokas",
        "title_default": "Founder and CEO",
        "website": "https://anthemis.com",
        "portfolio": "Carta, Betterment, Alloy, Hokodo, Maxwell ($956M AUM)",
        "bank_lp_value": "Backed Alloy; extensive NY and London institutional financial services network.",
        "why_fit": "Anthemis is an early backer of Alloy and invests heavily in embedded risk, compliance, and financial services infrastructure.",
        "pitch_angle": "Pitch Dokimo as continuous post-transaction and enterprise policy-to-record control assurance.",
    },
    "valuestream ventures": {
        "category": "NYC B2B FinTech, Capital Markets & RegTech Seed VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$1M – $4M",
        "partner_default": "Greg Neufeld",
        "title_default": "General Partner",
        "website": "https://valuestreamventures.com",
        "portfolio": "B2B Capital Markets, RegTech, and Enterprise Financial Infrastructure",
        "bank_lp_value": "Runs FinTechNY and connects portfolio companies directly with Wall Street compliance & operations buyers.",
        "why_fit": "Pure-play NYC B2B FinTech & RegTech fund focused on mission-critical workflow and data validation for financial institutions.",
        "pitch_angle": "Emphasize immediate ROI on SEC, FINRA, and bank regulatory exam readiness.",
    },
    "commerce ventures": {
        "category": "FinTech, Banking & Risk Infrastructure VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$1.5M – $6M",
        "partner_default": "Vivek Krishnamurthy",
        "title_default": "Partner",
        "website": "https://commerce.vc",
        "portfolio": "Socure, Alloy, Marqeta, Bill.com, Plastiq ($385M AUM)",
        "bank_lp_value": "Early investor in both Socure and Alloy; deep strategic bank & payment network LPs.",
        "why_fit": "Commerce Ventures backed both Socure and Alloy and understands compliance buyer personas at US banks intimately.",
        "pitch_angle": "Show how Dokimo extends compliance automation from customer onboarding (Socure/Alloy) to 100% of ongoing internal controls.",
    },
    "ttv capital": {
        "category": "Pure-Play B2B FinTech & Banking Infrastructure VC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$2M – $8M",
        "partner_default": "Sean Banks",
        "title_default": "Partner",
        "website": "https://ttvcapital.com",
        "portfolio": "Greenlight, Bill.com, Featurespace (AML/Fraud), DefenseStorm (Bank Cyber/Compliance) ($758M AUM)",
        "bank_lp_value": "Backed Featurespace and DefenseStorm; deep Southeast/US regional bank CCO & CRO relationships.",
        "why_fit": "TTV backed DefenseStorm (community bank cyber/compliance) and Featurespace (AML); strong fit for Dokimo's bank compliance engine.",
        "pitch_angle": "Demonstrate Dokimo's automated BSA/AML, wire, and supervisory control validation across regional and community banks.",
    },
    "amex ventures": {
        "category": "Financial Services & Fraud/Compliance Strategic CVC",
        "tier": "S",
        "base_score": 92,
        "stage": "Seed / Series A / Series B Strategic",
        "check_size": "$2M – $12M",
        "partner_default": "Kevin Weber",
        "title_default": "Managing Director, Amex Ventures",
        "website": "https://americanexpress.com/us/aml/amex-ventures.html",
        "portfolio": "Plaid, Stripe, FalconX, BioCatch, Sardine, Menlo Security",
        "bank_lp_value": "Direct commercial partnership pathway into American Express's global risk, compliance, and merchant monitoring teams.",
        "why_fit": "Amex Ventures actively backs fraud, compliance, and enterprise AI infrastructure that can be deployed inside Amex.",
        "pitch_angle": "Show how Dokimo validates 100% of operational records against internal policies with explainable remediation.",
    },
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(s)).strip("-")


def _classify_and_score_investor(row: dict) -> dict:
    """Compute Dokimo Fit Score (0-100), Tier (S/A/B/C), Category, Thesis Rationale, and Pitch Angle."""
    fund = (row.get("fund") or "").strip()
    fnorm = _norm(fund)
    person = (row.get("person") or "").strip()
    bg = (row.get("background") or "").strip()
    rel_inv = (row.get("relevant_investments") or "").strip()
    contact = (row.get("our_contact") or "").strip()
    email = (row.get("email") or "").strip()
    mobile = (row.get("mobile_phone") or "").strip()
    corp_ph = (row.get("corporate_phone") or "").strip()
    source_table = row.get("source_table") or "Table 1"

    # Check exact or substring match in FUND_KB
    kb = None
    for k, v in FUND_KB.items():
        if k == fnorm or (len(k) >= 5 and k in fnorm):
            kb = v
            break

    combined_txt = f"{fund} {person} {bg} {rel_inv}".lower()

    # Detect Hardware / Semiconductor / Non-Fit funds from Leo's AINekko/Veevx tables
    semi_keywords = [
        "semi", "tsmc", "silicon", "hardware", "chip", "wafer", "fab", "manufacturing",
        "tenstorrent", "nervana", "habana", "graphcore", "hailo", "mythic", "celestial ai",
        "untether", "movellus", "flex logix", "lightmatter", "kalray", "syntiant", "nuvia",
        "analog device", "qualcomm", "samsung", "western digital", "tdk", "tel ventures",
        "metaprop", "fifth wall", "gigascale",
    ]
    fintech_keywords = [
        "fintech", "regtech", "compliance", "aml", "citi", "capital one", "amex",
        "socure", "alloy", "chainalysis", "fenergo", "quantexa", "harvey", "bank",
        "financial", "legal", "fraud", "risk", "15c3", "occ", "fdic", "luge", "vestigo",
    ]
    enterprise_ai_keywords = [
        "sequoia", "benchmark", "a16z", "accel", "general catalyst", "menlo", "lightspeed",
        "kleiner", "greylock", "insight", "deviation", "two sigma", "point72", "openai",
        "conviction", "team8", "cyberstarts", "costanoa", "signalfire", "firstmark",
        "foundation", "cota", "susa", "bain", "bessemer", "wing", "amplify", "zetta",
        "madrona", "battery", "dawn", "notion", "balderton", "index", "tlv", "acrew",
        "glilot", "f2", "aleph", "inovia", "golden", "information venture", "boldstart",
        "hummer winblad", "nea", "mayfield", "matrix", "spark", "crv", "sutter hill",
        "glasswing", "mosaic", "daybreak", "hoxton", "round13", "gv", "google ventures",
    ]

    if kb:
        tier = kb["tier"]
        score = kb["base_score"]
        category = kb["category"]
        stage = kb["stage"]
        check_size = kb["check_size"]
        portfolio = kb["portfolio"]
        bank_lp_value = kb["bank_lp_value"]
        why_fit = kb["why_fit"]
        pitch_angle = kb["pitch_angle"]
        if not person and kb.get("partner_default"):
            person = kb["partner_default"]
        if not row.get("title") and kb.get("title_default"):
            row["title"] = kb["title_default"]
        if not email and kb.get("email_default"):
            email = kb["email_default"]
        if not row.get("person_linkedin") and kb.get("person_linkedin"):
            row["person_linkedin"] = kb["person_linkedin"]
        if not row.get("website") and kb.get("website"):
            row["website"] = kb["website"]
    elif any(k in combined_txt for k in ["luge", "vestigo", "information venture", "TruStage", "pruven"]):
        tier = "S"
        score = 92
        category = "FinTech, InsurTech & Enterprise Risk VC"
        stage = "Seed / Series A"
        check_size = "$1.5M – $8M"
        portfolio = rel_inv or "B2B FinTech, RegTech, Enterprise Compliance & Risk Infrastructure"
        bank_lp_value = "Backed by financial institution LPs across North America; active pilot intros to bank & insurance CCOs/CROs."
        why_fit = f"{fund} invests specifically in B2B financial services, risk, and compliance infrastructure with direct financial institution LP backing."
        pitch_angle = "Emphasize Dokimo's full-population operational record validation and Bob's explainable remediation for regulated institutions."
    elif any(k in combined_txt for k in semi_keywords) and not any(k in combined_txt for k in ["databricks", "snowflake", "pinecone", "snyk", "abnormal", "cohere"]):
        tier = "C"
        score = 54
        category = "Semiconductor / Hardware / Sector-Specific (Low Fit)"
        stage = "Seed / Series A / DeepTech"
        check_size = "$2M – $15M"
        portfolio = rel_inv or bg or "Semiconductors, Silicon, Edge Hardware, or Non-Financial Verticals"
        bank_lp_value = "Minimal banking/compliance LP overlap (sourced from Leo's AINekko/Veevx hardware list)."
        why_fit = f"{fund} focuses primarily on semiconductor/hardware/non-RegTech verticals ({bg or rel_inv or 'DeepTech/Hardware'}). Lower priority for Dokimo's software-first regulatory compliance platform."
        pitch_angle = "Deprioritize for core SaaS round—only engage if pitching sovereign on-prem AI appliance deployments inside air-gapped defense/financial data centers."
    elif any(k in combined_txt for k in fintech_keywords):
        tier = "S"
        score = 93
        category = "FinTech, RegTech & Compliance Infrastructure VC"
        stage = "Seed / Series A / Growth"
        check_size = "$2M – $15M"
        portfolio = rel_inv or bg or "FinTech, RegTech & Financial Infrastructure"
        bank_lp_value = "Strong executive network across regulated financial institutions and compliance buyers."
        why_fit = f"{fund} has explicit FinTech/compliance investment thesis ({bg or rel_inv or 'Regulated Financial Services'})."
        pitch_angle = "Lead with full-population policy-to-record control validation + Bob's explainable remediation replacing 1% sampling."
    elif any(k in combined_txt for k in enterprise_ai_keywords):
        tier = "A"
        score = 88
        category = "Tier-1 Enterprise AI, Cyber & B2B Software VC"
        stage = "Seed / Series A / Series B"
        check_size = "$3M – $20M"
        portfolio = rel_inv or bg or "Enterprise AI, Data Infrastructure, Cybersecurity & Governance"
        bank_lp_value = "Tier-1 enterprise GTM network with Fortune 500 CISOs, CIOs, and Chief Risk Officers."
        why_fit = f"{fund} is a premier Enterprise AI & B2B software investor ({bg or rel_inv or 'Enterprise Software & AI Infrastructure'}) actively backing vertical AI agents with verifiable ROI."
        pitch_angle = "Frame Dokimo as the sovereign, deterministic + Explainable AI (Bob) system of record for regulated enterprise compliance and internal audit."
    else:
        tier = "B"
        score = 76
        category = "Frontier AI, Deep-Tech & Multi-Stage VC"
        stage = "Seed / Series A"
        check_size = "$1M – $10M"
        portfolio = rel_inv or bg or "Frontier AI, Systems & Enterprise Infrastructure"
        bank_lp_value = "Selective enterprise and technical co-investor network."
        why_fit = f"{fund} backs technical AI and infrastructure founders ({bg or rel_inv or 'AI & Systems'})."
        pitch_angle = "Emphasize Dokimo's hybrid neuro-symbolic architecture (deterministic full-population rule engine + Bob's explainable LLM remediation inside customer perimeter)."

    # Adjust score slightly for warm contact, direct email, and mobile phone availability
    if "warren" in contact.lower() and score >= 75:
        score = min(99, score + 1)
    if (email or mobile) and score >= 75:
        score = min(99, score + 1)

    return {
        "tier": tier,
        "dokimo_fit_score": score,
        "category": category,
        "stage": stage,
        "check_size": check_size,
        "person": person,
        "email": email,
        "portfolio": portfolio,
        "bank_lp_value": bank_lp_value,
        "why_fit": why_fit,
        "pitch_angle": pitch_angle,
    }


def _build_outreach_copy(row: dict) -> tuple[str, str, str]:
    """Generate (warm_intro_blurb, direct_email_subject, direct_email_body) for each investor."""
    fund = row.get("fund") or "your firm"
    person = row.get("person") or "Partner"
    first_name = person.split()[0] if person and person not in ("(various)", "(partners)", "(team)", "—") else "there"
    contact = row.get("our_contact") or "Leo"
    portfolio = row.get("portfolio") or "enterprise AI and financial infrastructure"
    pitch_angle = row.get("pitch_angle") or "validating 100% of operational records against written policies overnight."

    warm_blurb = (
        f"Hi {first_name} — hope you're doing well. Wanted to connect you with Warren Zafrin, CEO of Dokimo.ai (https://dokimo.ai). "
        f"Given {fund}'s work around {portfolio[:90]}, Dokimo is right up your alley: regulated banks, broker-dealers, and fintechs use Dokimo to test written compliance policies against 100% of underlying operational records (wires, trades, accounts) inside their own perimeter every night—and when a control breaks, Bob (their Explainable AI compliance agent) drafts the remediation for human sign-off. "
        f"They already have live autonomous regulatory intelligence tracking 20,065 institutions across 16 regulators. Worth a quick 15-minute intro with Warren?"
    )

    subj = f"Dokimo.ai x {fund} — Autonomous Full-Population Control Validation & Bob Remediation"
    body = (
        f"Hi {first_name},\n\n"
        f"{'Following up on our connection through ' + contact + ' — ' if contact else ''}I'm Warren Zafrin, CEO of Dokimo.ai.\n\n"
        f"We built Dokimo because regulated financial institutions (banks, broker-dealers, credit unions, and fintechs) are failing OCC, FDIC, SEC, FINRA, and BSA examinations for the same structural reason: legacy GRC relies on 1% manual spreadsheet samples, while first-wave 'document AI' stops at reading policies and memos in isolation without checking whether production databases, wire corridors, and trade feeds actually followed the rule.\n\n"
        f"What Dokimo.ai does differently:\n"
        f"1. Full-Population Policy-to-Record Validation: Runs 100% inside the institution's perimeter every night, testing written policies against every underlying operational record.\n"
        f"2. Bob (Explainable AI Remediation Agent): Links every exception to the exact rule and record, and automatically drafts the remediation and control specification for a named officer's sign-off.\n"
        f"3. Live Regulatory Signal Graph: Continuously monitors 16 global regulators and 20,065 institutions.\n\n"
        f"Why {fund}: {pitch_angle}\n\n"
        f"Would you have 15 minutes this week or next to walk through the live platform?\n\n"
        f"Best regards,\n"
        f"Warren Zafrin\n"
        f"CEO, Dokimo.ai\n"
        f"warren@dokimo.ai | https://dokimo.ai"
    )
    return warm_blurb, subj, body


def parse_raw_leo_list(raw_text: str = None) -> list[dict]:
    """Parse all 4 sub-tables from Leo & Warren's raw CSV text into normalized, enriched investor dicts."""
    if raw_text is None:
        raw_text = RAW_FILE.read_text(encoding="utf-8") if RAW_FILE.exists() else ""

    # Use csv.reader across the full text (since multiline quoted fields exist in Table 1!)
    reader = csv.reader(io.StringIO(raw_text))
    all_rows = list(reader)

    table_mode = "table1"
    parsed_items = []
    last_firm_t3 = ""

    for r_idx, row in enumerate(all_rows):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        first_cell = cells[0].replace("\n", " ").strip()
        second_cell = cells[1].replace("\n", " ").strip() if len(cells) > 1 else ""

        # Detect table header transitions
        if first_cell == "Fund / Org" and len(cells) >= 15:
            table_mode = "table1"
            continue
        if first_cell == "Fund / Org" and len(cells) < 10:
            table_mode = "table2"
            continue
        if first_cell == "Firm" and second_cell == "Priority":
            table_mode = "table3" if table_mode != "table3" else "table4"
            continue

        if table_mode == "table1":
            # Pad to 25 columns
            c = cells + [""] * max(0, 25 - len(cells))
            fund = re.sub(r"\s+", " ", c[0]).strip()
            person = re.sub(r"\s+", " ", c[1]).strip()
            if not fund and not person:
                continue
            parsed_items.append({
                "source_table": "Table 1 (Core FinTech & Top VC List)",
                "fund": fund,
                "person": person,
                "title": c[2],
                "investor_type": c[3] or "VC",
                "raw_priority": c[4] or "medium",
                "background": c[5],
                "our_contact": c[6] or "Warren / Leo",
                "latest_status": c[7] or "Not Contacted",
                "comment": c[8],
                "email": c[9],
                "person_linkedin": c[10],
                "website": c[11],
                "company_linkedin": c[12],
                "twitter": c[13],
                "mobile_phone": c[14].lstrip("'"),
                "corporate_phone": c[15].lstrip("'"),
                "industry": c[16],
                "employees": c[17],
                "city": c[18],
                "state": c[19],
                "country": c[20],
                "total_funding": c[21],
                "latest_funding": c[22],
                "latest_funding_amount": c[23],
                "last_raised_at": c[24][:10] if c[24] else "",
                "relevant_investments": "",
                "next_action": "",
            })
        elif table_mode == "table2":
            c = cells + [""] * max(0, 5 - len(cells))
            fund = re.sub(r"\s+", " ", c[0]).strip()
            person = re.sub(r"\s+", " ", c[1]).strip()
            if not fund and not person:
                continue
            # Extract inline linkedin URL if embedded in person name
            li_url = ""
            m_li = re.search(r"\((https?://[^\)]+)\)", person)
            if m_li:
                li_url = m_li.group(1)
                person = person.replace(m_li.group(0), "").strip()
            parsed_items.append({
                "source_table": "Table 2 (Leo DeepTech & AI Infra Network)",
                "fund": fund,
                "person": person,
                "title": "Partner" if c[2] == "VC" else c[2],
                "investor_type": c[2] or "VC",
                "raw_priority": "medium",
                "background": c[3],
                "our_contact": c[4] or "Leo",
                "latest_status": "Not Contacted",
                "comment": "",
                "email": "",
                "person_linkedin": li_url,
                "website": "",
                "company_linkedin": "",
                "twitter": "",
                "mobile_phone": "",
                "corporate_phone": "",
                "industry": "venture capital & private equity",
                "employees": "",
                "city": "",
                "state": "",
                "country": "",
                "total_funding": "",
                "latest_funding": "",
                "latest_funding_amount": "",
                "last_raised_at": "",
                "relevant_investments": "",
                "next_action": "",
            })
        elif table_mode in ("table3", "table4"):
            c = cells + [""] * max(0, 8 - len(cells))
            fund = re.sub(r"\s+", " ", c[0]).strip()
            if fund:
                last_firm_t3 = fund
            elif c[2] or c[3]:
                fund = last_firm_t3
            if not fund:
                continue
            person = re.sub(r"\s+", " ", c[2]).strip()
            if person == "—":
                person = ""
            contact_raw = c[3].strip()
            email = ""
            li_url = ""
            # Handle <email> inside partner or contact column
            m_em = re.search(r"<([^>]+@[^>]+)>", person)
            if m_em:
                email = m_em.group(1).strip()
                person = person.replace(m_em.group(0), "").strip()
            if "@" in contact_raw:
                email = contact_raw
            if person.startswith("http"):
                li_url = person
                person = "Bill Reichert" if "billreichert" in li_url else ""
            website = fund if fund.startswith("http") else ""
            if website:
                fund = re.sub(r"^https?://(www\.)?", "", website).strip("/").title()
            prio_map = {"1": "high", "2": "medium", "3": "low"}
            parsed_items.append({
                "source_table": "Table 3 (Leo Partner & Portfolio Matrix)" if table_mode == "table3" else "Table 4 (Active Deck & Data Room Tracker)",
                "fund": fund,
                "person": person,
                "title": "Partner",
                "investor_type": "VC",
                "raw_priority": prio_map.get(c[1], "medium"),
                "background": c[6] if c[6] != "—" else "",
                "our_contact": c[5] if c[5] and c[5] != "—" else "Leo",
                "latest_status": c[6] if c[6] and c[6] != "—" else "Not Contacted",
                "comment": c[6] if c[6] and c[6] != "—" else "",
                "email": email,
                "person_linkedin": li_url,
                "website": website,
                "company_linkedin": "",
                "twitter": "",
                "mobile_phone": "",
                "corporate_phone": "",
                "industry": "venture capital & private equity",
                "employees": "",
                "city": "",
                "state": "",
                "country": "",
                "total_funding": "",
                "latest_funding": "",
                "latest_funding_amount": "",
                "last_raised_at": "",
                "relevant_investments": c[4] if c[4] != "—" else "",
                "next_action": c[7] if c[7] != "—" else "",
            })

    # Deduplicate / merge records sharing the same (fund_norm, person_norm) while keeping distinct partners at the same fund separate
    merged_map = {}
    for item in parsed_items:
        fn = _norm(item["fund"])
        pn = _norm(item["person"])
        # If person is empty or generic, see if there's already an entry for this fund with no person
        key = f"{fn}||{pn}"
        if key not in merged_map:
            merged_map[key] = dict(item)
        else:
            cur = merged_map[key]
            for field in [
                "title", "background", "our_contact", "latest_status", "comment", "email",
                "person_linkedin", "website", "company_linkedin", "twitter", "mobile_phone",
                "corporate_phone", "city", "state", "country", "total_funding",
                "relevant_investments", "next_action",
            ]:
                if not cur.get(field) and item.get(field):
                    cur[field] = item[field]
                elif field in ("background", "relevant_investments", "our_contact") and item.get(field) and item[field] not in cur.get(field, ""):
                    cur[field] = f"{cur[field]} | {item[field]}".strip(" |")

    # Enrich & score all items
    state = load_state()
    enriched = []
    for idx, (k, row) in enumerate(merged_map.items(), start=1):
        inv_id = "INV-" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:8].upper()
        fit = _classify_and_score_investor(row)
        row.update(fit)
        row["id"] = inv_id

        # Apply any persisted user edits from output/investor_state.json
        st = state.get(inv_id) or {}
        if st.get("latest_status"):
            row["latest_status"] = st["latest_status"]
        if st.get("next_action") is not None and st.get("next_action") != "":
            row["next_action"] = st["next_action"]
        if st.get("comment") is not None and st.get("comment") != "":
            row["comment"] = st["comment"]
        if st.get("assigned_owner"):
            row["our_contact"] = st["assigned_owner"]
        row["updated_at"] = st.get("updated_at", "")
        row["updated_by"] = st.get("updated_by", "")

        row["display_phone"] = row["mobile_phone"] or row["corporate_phone"] or ""
        row["phone_kind"] = "Mobile" if row["mobile_phone"] else ("Office" if row["corporate_phone"] else "")

        blurb, subj, body = _build_outreach_copy(row)
        row["warm_intro_blurb"] = blurb
        row["direct_email_subject"] = subj
        row["direct_email_body"] = body

        enriched.append(row)

    # Sort by Dokimo Fit Score descending, then Tier S -> A -> B -> C, then whether direct email/phone exists
    tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
    enriched.sort(
        key=lambda x: (
            tier_order.get(x["tier"], 9),
            -int(x["dokimo_fit_score"]),
            0 if (x.get("email") or x.get("mobile_phone")) else 1,
            x["fund"].lower(),
        )
    )
    for rank_idx, r in enumerate(enriched, start=1):
        r["rank"] = rank_idx

    return enriched


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_investor_status(
    inv_id: str,
    latest_status: str = None,
    comment: str = None,
    next_action: str = None,
    assigned_owner: str = None,
    updated_by: str = "Warren",
) -> dict:
    iid = (inv_id or "").strip()
    if not iid:
        return {"ok": False, "error": "Missing investor id"}
    state = load_state()
    cur = state.get(iid) or {}
    if latest_status is not None:
        cur["latest_status"] = str(latest_status).strip()[:120]
    if comment is not None:
        cur["comment"] = str(comment).strip()[:500]
    if next_action is not None:
        cur["next_action"] = str(next_action).strip()[:200]
    if assigned_owner is not None:
        cur["assigned_owner"] = str(assigned_owner).strip()[:80]
    cur["updated_by"] = updated_by
    cur["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state[iid] = cur
    save_state(state)
    # Re-persist CSV
    rows = get_all_investors(persist_csv=True)
    updated_row = next((r for r in rows if r["id"] == iid), None)
    return {"ok": True, "id": iid, "investor": updated_row}


CSV_COLUMNS = [
    "rank", "id", "tier", "dokimo_fit_score", "fund", "person", "title", "category",
    "stage", "check_size", "our_contact", "latest_status", "next_action", "comment",
    "email", "mobile_phone", "corporate_phone", "person_linkedin", "website",
    "city", "state", "country", "portfolio", "bank_lp_value", "why_fit", "pitch_angle",
    "source_table",
]


def get_all_investors(persist_csv: bool = True) -> list[dict]:
    rows = parse_raw_leo_list()
    if persist_csv:
        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    return rows


def build_summary_metrics(rows: list[dict] = None) -> dict:
    """Compute exact denominator-backed summary metrics across all parsed investors."""
    rows = rows if rows is not None else get_all_investors(persist_csv=False)
    total = len(rows)
    denom = max(1, total)
    tier_s = [r for r in rows if r["tier"] == "S"]
    tier_a = [r for r in rows if r["tier"] == "A"]
    tier_b = [r for r in rows if r["tier"] == "B"]
    tier_c = [r for r in rows if r["tier"] == "C"]
    with_email = [r for r in rows if r.get("email")]
    with_phone = [r for r in rows if r.get("display_phone")]
    warren_contacts = [r for r in rows if "warren" in (r.get("our_contact") or "").lower()]
    leo_contacts = [r for r in rows if "leo" in (r.get("our_contact") or "").lower()]
    active_convos = [
        r for r in rows
        if (r.get("latest_status") or "").lower() not in ("", "not contacted", "declined", "not a lead")
        and "passed" not in (r.get("latest_status") or "").lower()
    ]

    return {
        "total_investors": total,
        "tier_s_count": len(tier_s),
        "tier_s_rate": f"{len(tier_s)} of {total} ({round(len(tier_s) / denom * 100, 1)}%)",
        "tier_a_count": len(tier_a),
        "tier_a_rate": f"{len(tier_a)} of {total} ({round(len(tier_a) / denom * 100, 1)}%)",
        "tier_b_count": len(tier_b),
        "tier_b_rate": f"{len(tier_b)} of {total} ({round(len(tier_b) / denom * 100, 1)}%)",
        "tier_c_count": len(tier_c),
        "tier_c_rate": f"{len(tier_c)} of {total} ({round(len(tier_c) / denom * 100, 1)}%)",
        "with_email_count": len(with_email),
        "with_email_rate": f"{len(with_email)} of {total} ({round(len(with_email) / denom * 100, 1)}%)",
        "with_phone_count": len(with_phone),
        "with_phone_rate": f"{len(with_phone)} of {total} ({round(len(with_phone) / denom * 100, 1)}%)",
        "warren_contact_count": len(warren_contacts),
        "leo_contact_count": len(leo_contacts),
        "active_convo_count": len(active_convos),
    }


def build_executive_vc_report(rows: list[dict] = None) -> dict:
    """Build the comprehensive 'Who Is the Right VC for Dokimo?' Research Report."""
    rows = rows if rows is not None else get_all_investors(persist_csv=False)
    metrics = build_summary_metrics(rows)
    tier_s = [r for r in rows if r["tier"] == "S"]
    tier_a = [r for r in rows if r["tier"] == "A"]
    tier_c = [r for r in rows if r["tier"] == "C"]

    bank_strategics = [
        r for r in tier_s
        if any(k in (r["fund"] + " " + r["category"]).lower() for k in ["citi", "capital one", "amex", "canapi", "illuminate", "thomson reuters", "ludwig", "ejf", "mouro", "nyca", "f-prime"])
    ]
    pure_fintech_leads = [
        r for r in tier_s
        if r not in bank_strategics
    ]

    return {
        "ok": True,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        "metrics": metrics,
        "executive_thesis": (
            f"Across the {metrics['total_investors']} investor records consolidated from Leo and Warren's 4 lists, "
            f"there is a sharp bifurcation: {metrics['tier_s_rate']} are Tier-S Bullseye FinTech, RegTech, and Bank-LP Strategic investors, "
            f"and {metrics['tier_a_rate']} are Tier-A Enterprise AI & Cyber investors, whereas {metrics['tier_c_rate']} come from Leo's "
            f"AINekko/Veevx semiconductor & hardware lists (e.g., TSMC/Matter VC, Tenstorrent, TDK, TEL Ventures, Analog Devices) and should be deprioritized for Dokimo's software/AI round."
        ),
        "wave1_bank_lp_and_strategics": bank_strategics[:12],
        "wave2_fintech_regtech_leads": pure_fintech_leads[:14],
        "wave3_enterprise_ai_leads": tier_a[:15],
        "deprioritize_hardware_funds": tier_c[:15],
    }
