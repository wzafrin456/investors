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

from . import enrichment_kb

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
    "vestigo ventures": {
        "category": "Pure-Play Early-Stage FinTech & Wealth/Bank RegTech VC",
        "tier": "S",
        "base_score": 97,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $4M",
        "partner_default": "Ian Sheridan",
        "title_default": "Managing Director & Co-Founder",
        "website": "https://vestigoventures.com",
        "portfolio": "Early-stage AI FinTech, WealthTech, Broker-Dealer & Bank Compliance Infrastructure ($179M AUM)",
        "bank_lp_value": "Founded by former LPL Financial CEO Mark Casady; direct C-suite access to US broker-dealers, RIAs, and regional banks.",
        "why_fit": "Vestigo writes $1M–$4M Pre-Seed/Seed checks specifically into AI-native FinTech & compliance infrastructure for banks and broker-dealers. Zero 'too early' risk.",
        "pitch_angle": "Pitch Dokimo as the automated FINRA 3310, SEC 15c3-3, and OCC/FDIC full-population control validation & Bob remediation engine.",
    },
    "luge capital": {
        "category": "Financial-Institution-Backed Seed FinTech & AI VC",
        "tier": "S",
        "base_score": 97,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$500K – $3.5M",
        "partner_default": "David Nault",
        "title_default": "Co-Founder & General Partner",
        "website": "https://luge.vc",
        "portfolio": "Flinks,Owl.co (financial crime/claims AI), OneVest, Plooto ($156M AUM across Seed Funds)",
        "bank_lp_value": "Backed directly by major North American financial institutions and insurance/banking LPs that pilot portfolio companies.",
        "why_fit": "Luge invests exclusively at Pre-Seed/Seed in B2B FinTech and AI compliance solutions where its financial institution LPs need operational automation.",
        "pitch_angle": "Show how Luge's bank and financial institution LPs can deploy Dokimo inside their VPC to test 100% of records against written policies nightly.",
    },
    "information venture partners": {
        "category": "B2B FinTech, RegTech & Banking Risk Seed/A VC",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A",
        "check_size": "$1.5M – $5M",
        "partner_default": "David Unsworth",
        "title_default": "Co-Founder & General Partner",
        "website": "https://informationvp.com",
        "portfolio": "Verafin (AML/Fraud — acquired by Nasdaq for $2.75B), Adaptive Shield, Coconut Software, Sensibill",
        "bank_lp_value": "Spun out of RBC Venture Partners; early backers of Verafin ($2.75B AML exit to Nasdaq) with deep US/North American bank CRO/CCO ties.",
        "why_fit": "David Unsworth's team backed Verafin (the gold-standard bank AML/fraud exit) and focuses 100% on B2B enterprise FinTech, risk, and regulatory compliance.",
        "pitch_angle": "Frame Dokimo as the 'Verafin for Enterprise-Wide Regulatory Control Validation & Consent-Order Defense'—powered by deterministic rules + Bob.",
    },
    "pruven capital": {
        "category": "Financial Services & Enterprise AI Strategic VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Sudip Chakrabarti",
        "title_default": "Partner",
        "website": "https://pruvencapital.com",
        "portfolio": " Enterprise AI, Cyber, FinTech & Regulated Financial Operations ($350M+ AUM)",
        "bank_lp_value": "Backed by Prudential Financial; active warm conversation already initiated (Talked Feb 28 + follow-up).",
        "why_fit": "Sudip Chakrabarti already engaged on Feb 28 and invests at the intersection of enterprise AI infrastructure and regulated financial services.",
        "pitch_angle": "Follow up on the Feb 28 discussion with Dokimo's live 20,065-institution Regulatory Signal Graph and Bob's autonomous control remediation.",
    },
    "boldstart": {
        "category": "Day-0 / Inception Enterprise Security, Governance & AI VC",
        "tier": "S",
        "base_score": 96,
        "stage": "Day-0 / Pre-Seed / Seed Lead",
        "check_size": "$1M – $5M",
        "partner_default": "Ed Sim",
        "title_default": "Founder & Managing Partner",
        "website": "https://boldstart.vc",
        "portfolio": "Snyk, BigID (data privacy/compliance), Protect AI, SecurityScorecard, Jit",
        "bank_lp_value": "NYC's #1 Day-0 enterprise infrastructure fund; deep Fortune 500 & Wall Street CISO/CDO customer network (backed BigID & Snyk from inception).",
        "why_fit": "Ed Sim writes Day-0 first checks BEFORE revenue into technical enterprise governance, security, and compliance infrastructure (like BigID). Never says 'too early'.",
        "pitch_angle": "Pitch Dokimo as 'BigID + Snyk for Regulated Financial Controls' — compiling written policies into automated nightly checks across 100% of operational records.",
    },
    "team8": {
        "category": "Company-Builder & Seed VC in FinTech, Cyber & Enterprise AI",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed Lead",
        "check_size": "$2M – $8M",
        "partner_default": "Liran Grinberg",
        "title_default": "Co-Founder & Managing Partner",
        "website": "https://team8.vc",
        "portfolio": "Claroty, Talon, Dig Security, VisibleRisk, Dedicated US FinTech & Enterprise AI Fund ($1B+ AUM)",
        "bank_lp_value": "Team8's CISO/CRO/CCO Village includes 100+ Fortune 500 and global bank executives (Walmart, Citi, Barclays, Moody's LPs).",
        "why_fit": "Team8 has dedicated FinTech and Cyber/AI Seed funds backed by global banks and Moody's, and actively co-designs solutions with bank CROs/CISOs at Seed.",
        "pitch_angle": "Show how Dokimo unifies data governance, regulatory control testing, and Bob's explainable remediation inside the bank's perimeter.",
    },
    "cyberstarts": {
        "category": "Day-0 Inception Enterprise Governance, Risk & Cyber VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Day-0 / Pre-Seed / Seed Lead",
        "check_size": "$1.5M – $6M",
        "partner_default": "Gili Raanan",
        "title_default": "Founder & General Partner",
        "website": "https://cyberstarts.com",
        "portfolio": "Wiz ($12B+), Island (Enterprise Browser in 50+ banks), Cyera (Data Governance), Fireblocks (FinTech infrastructure)",
        "bank_lp_value": "Gili Raanan co-founded/seeded Fireblocks, Island, Wiz, and Cyera—with unmatched CISO/CRO validation access at US banks.",
        "why_fit": "Cyberstarts invests at Day-0 based on CISO/CCO pain validation before a single dollar of ARR, and already backed Fireblocks and Island (heavily adopted by US banks).",
        "pitch_angle": "Position Dokimo as 'Cyera/Wiz for Regulatory & Financial Compliance Controls' — agentless, 100% full-population record validation inside the bank VPC.",
    },
    "costanoa ventures": {
        "category": "Early-Stage B2B Data, FinTech & Compliance Infrastructure VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Pre-Seed / Seed / Series A",
        "check_size": "$1.5M – $6M",
        "partner_default": "Tony Liu",
        "title_default": "Partner (Enterprise AI, Data & FinTech)",
        "website": "https://costanoa.vc",
        "portfolio": "Alation (Data Governance), Persona, Highnote, Matera, Distributional (AI Testing/Compliance)",
        "bank_lp_value": "Backed Alation (enterprise data governance in major banks) and Distributional (enterprise AI testing).",
        "why_fit": "Tony Liu focuses specifically on early-stage B2B FinTech, data governance, and AI reliability/compliance infrastructure.",
        "pitch_angle": "Show how Dokimo sits on top of the data catalog (like Alation) to execute deterministic regulatory policy checks across 100% of production records.",
    },
    "glasswing ventures": {
        "category": "Pure-Play Pre-Seed & Seed Enterprise AI & Security VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $4M",
        "partner_default": "Rudina Seseri",
        "title_default": "Founder & Managing Partner",
        "website": "https://glasswing.vc",
        "portfolio": "Black Kite (third-party cyber/risk compliance), FeatureByte, ChaosSearch, Pliant ($277M AUM)",
        "bank_lp_value": "Boston/NYC Pre-Seed & Seed AI specialist with an Executive Advisory Council of bank & Fortune 500 CIOs/CISOs.",
        "why_fit": "Rudina Seseri leads Pre-Seed and Seed rounds in neuro-symbolic/explainable Enterprise AI for risk, security, and compliance. Never says 'too early' at Seed.",
        "pitch_angle": "Highlight Dokimo's hybrid neuro-symbolic compliance engine (deterministic SQL/Python full-population rules + Bob's explainable remediation).",
    },
    "susa ventures": {
        "category": "Data-Moat & Compounding Workflow Seed Specialist VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $4M",
        "partner_default": "Chad Byers",
        "title_default": "Co-Founder & General Partner",
        "website": "https://susaventures.com",
        "portfolio": "Robinhood, Plaid (early), Flexport, Middesk (business KYB/compliance), Stord",
        "bank_lp_value": "Early Seed backer of Robinhood, Plaid, and Middesk (compliance/KYB).",
        "why_fit": "Susa leads Seed rounds in B2B companies building proprietary data moats in financial services and compliance (backed Middesk & Robinhood at Seed).",
        "pitch_angle": "Lead with Dokimo's proprietary 20,065-institution Regulatory Signal Graph + compounding library of executable OCC/FDIC/SEC/FINRA control rules.",
    },
    "acrew capital": {
        "category": "FinTech, Data & Security Seed/Series A VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed / Series A",
        "check_size": "$1.5M – $8M",
        "partner_default": "Theresia Gouw",
        "title_default": "Founding Partner",
        "website": "https://acrewcapital.com",
        "portfolio": "Chime, Plaid, Cato Networks, At-Bay, Laika/Thoropass (automated compliance audit)",
        "bank_lp_value": "Backed Thoropass (compliance/audit automation), Plaid, and Chime; strong FinTech & CISO/CCO network.",
        "why_fit": "Theresia Gouw backed Thoropass (compliance audit automation) and top FinTechs; immediately understands why regulated banks need automated full-population control testing.",
        "pitch_angle": "Pitch Dokimo as 'Thoropass for Bank & Broker-Dealer Regulatory Examinations (OCC, FDIC, SEC, FINRA, BSA)'—testing 100% of operational records.",
    },
    "firstmark": {
        "category": "NYC Enterprise AI, Data & FinTech Seed/Series A VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed / Series A",
        "check_size": "$2M – $8M",
        "partner_default": "Matt Turck",
        "title_default": "Partner (Author of MAD Data & AI Landscape)",
        "website": "https://firstmark.com",
        "portfolio": "Dataiku (used by Tier-1 banks), Carta, CockroachDB, Traceable, Ada ($3.5B AUM)",
        "bank_lp_value": "Runs NYC's largest Data Driven NYC community and backed Dataiku & Carta; warm suggestion from Justin on your tracker.",
        "why_fit": "Matt Turck and Adam Nelson lead NYC Seed/A rounds in enterprise data & AI governance (backed Dataiku, heavily deployed across global banks).",
        "pitch_angle": "Show how Dokimo turns enterprise data pipelines into continuous, audit-ready regulatory control verification with Bob's autonomous remediation.",
    },
    "signalfire": {
        "category": "AI-Native Enterprise & FinTech Seed/Series A VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed / Series A",
        "check_size": "$1.5M – $8M",
        "partner_default": "Chris Farmer",
        "title_default": "Founder & CEO",
        "website": "https://signalfire.com",
        "portfolio": "Grammarly, Stampli, EvenUp (AI legal/claims), Horizon3, Descript ($2.2B AUM)",
        "bank_lp_value": "Beacon AI talent & GTM engine + in-house former financial services & security C-suite advisors.",
        "why_fit": "SignalFire heavily backs vertical AI agents replacing manual legal/compliance review (like EvenUp) and writes dedicated Pre-Seed/Seed checks.",
        "pitch_angle": "Position Dokimo + Bob as the vertical AI compliance & internal audit agent for the $180B regulated financial services compliance market.",
    },
    "daybreak ventures": {
        "category": "Pre-Seed & Seed AI Workflow & FinTech VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$750K – $2.5M",
        "partner_default": "Rex Woodbury",
        "title_default": "Founder & Managing Partner (ex-Index Ventures)",
        "website": "https://daybreakventures.com",
        "portfolio": "Pre-Seed & Seed AI-native B2B workflow and financial software",
        "bank_lp_value": "Pure-play Pre-Seed/Seed fund ($36M Fund I) that writes fast first checks without requiring Series-A ARR.",
        "why_fit": "Rex Woodbury launched Daybreak specifically to lead/co-lead Pre-Seed and Seed rounds in AI-native enterprise workflows before multistage funds enter.",
        "pitch_angle": "Show how Bob + Dokimo's full-population validation replaces armies of manual bank compliance & lookback consultants.",
    },
    "glilot capital": {
        "category": "Early-Stage Enterprise Cyber, Governance & AI Seed VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed Lead",
        "check_size": "$2M – $6M",
        "partner_default": "Kobi Samboursky",
        "title_default": "Founder & Managing Partner",
        "website": "https://glilotcapital.com",
        "portfolio": "AtBay, Lightspin, Concentric AI (data governance), IntSights ($750M AUM)",
        "bank_lp_value": "Runs a 200+ US CISO/CIO/CCO advisory board that validates and buys from portfolio companies at Seed.",
        "why_fit": "Glilot Seed leads early-stage B2B data governance, compliance, and AI security startups selling into US banks and Fortune 500 enterprises.",
        "pitch_angle": "Pitch Dokimo as autonomous regulatory data governance & control assurance with zero data egress.",
    },
    "f2 venture capital": {
        "category": "Pre-Seed & Seed Enterprise AI & Data Infrastructure VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $4M",
        "partner_default": "Jonathan Saacks",
        "title_default": "Managing Partner",
        "website": "https://f2vc.com",
        "portfolio": " Seed-stage B2B AI, FinTech, and Data Governance startups",
        "bank_lp_value": "Dedicated Pre-Seed/Seed specialist connecting technical AI founders with NYC/US financial services buyers.",
        "why_fit": "F2 invests exclusively at Pre-Seed and Seed in technical enterprise AI & data platforms—zero 'too early' friction.",
        "pitch_angle": "Lead with Dokimo's deterministic full-population policy validation engine + Bob's explainable remediation.",
    },
    "tlv partners": {
        "category": "Seed-Stage Enterprise AI, FinTech & Governance VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Seed Lead",
        "check_size": "$2M – $6M",
        "partner_default": "Rona Segev",
        "title_default": "Co-Founder & Managing Partner",
        "website": "https://tlv.partners",
        "portfolio": "Unit (Banking-as-a-Service compliance), Aqua Security, Next Insurance, Run:ai ($1B+ AUM)",
        "bank_lp_value": "Seed backer of Unit (embedded banking & sponsor-bank compliance across US regional banks).",
        "why_fit": "Rona Segev backed Unit at Seed and knows firsthand the massive OCC/FDIC third-party & BaaS compliance pain that US banks face.",
        "pitch_angle": "Show how Dokimo solves the exact OCC/FDIC partner-bank and core compliance validation crisis that BaaS and regional banks face.",
    },
    "amplify": {
        "category": "Technical Seed Enterprise AI, Data & Infrastructure VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1.5M – $6M",
        "partner_default": "Mike Dauber",
        "title_default": "General Partner",
        "website": "https://amplifypartners.com",
        "portfolio": "Datadog, DBT Labs, Hightouch, Great Expectations (Data Validation), Hex, Runway",
        "bank_lp_value": "Early Seed backer of DBT Labs and Great Expectations (data quality/validation)—warm path via Roman/Leo.",
        "why_fit": "Amplify backed Great Expectations (data testing) and DBT at Seed. Dokimo is 'Great Expectations for Regulated Financial Compliance + Bob Remediation'.",
        "pitch_angle": "Frame Dokimo as turning written regulatory policies into automated data assertions across 100% of bank records, paired with Bob's remediation agent.",
    },
    "zetta": {
        "category": "Pure-Play Pre-Seed & Seed AI-First Enterprise VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1.5M – $5M",
        "partner_default": "Jocelyn Goldfein",
        "title_default": "Managing Director",
        "website": "https://zettavp.com",
        "portfolio": "Domo, Tractable (AI financial/insurance claims), Clearbit, Kaggle, Forever-Seed AI B2B",
        "bank_lp_value": "100% focused on Pre-Seed/Seed B2B AI applications with proprietary data loops.",
        "why_fit": "Zetta only invests at Pre-Seed/Seed in AI-native B2B software with a compounding system-of-record data moat.",
        "pitch_angle": "Highlight Dokimo's closed-loop compliance graph: Regulatory Signal -> Full-Population Record Test -> Bob Remediation -> Examiner Evidence.",
    },
    "quiet capital": {
        "category": "Early-Stage FinTech & Enterprise Software VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $5M",
        "partner_default": "Michael Bloch",
        "title_default": "Partner",
        "website": "https://quiet.com",
        "portfolio": "Modern Treasury, Lithic, Middesk, Ramp, OneChronos (SEC regulated ATS)",
        "bank_lp_value": "Backed Modern Treasury, Lithic, Middesk, and OneChronos—deep US FinTech & bank compliance network.",
        "why_fit": "Quiet Capital seeded Modern Treasury, Middesk, and OneChronos; they love mission-critical financial plumbing and compliance automation at Seed.",
        "pitch_angle": "Pitch Dokimo as the automated compliance & ledger control verification engine for banks, broker-dealers, and payment platforms.",
    },
    "quite capital": {
        "category": "Early-Stage FinTech & Enterprise Software VC",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$1M – $5M",
        "partner_default": "Michael Bloch",
        "title_default": "Partner",
        "website": "https://quiet.com",
        "portfolio": "Modern Treasury, Lithic, Middesk, Ramp, OneChronos (SEC regulated ATS)",
        "bank_lp_value": "Backed Modern Treasury, Lithic, Middesk, and OneChronos—deep US FinTech & bank compliance network.",
        "why_fit": "Quiet Capital seeded Modern Treasury, Middesk, and OneChronos; they love mission-critical financial plumbing and compliance automation at Seed.",
        "pitch_angle": "Pitch Dokimo as the automated compliance & ledger control verification engine for banks, broker-dealers, and payment platforms.",
    },
    "elad gil": {
        "category": "Solo GP & Super-Angel in Enterprise AI & FinTech",
        "tier": "S",
        "base_score": 95,
        "stage": "Pre-Seed / Seed / Series A",
        "check_size": "$500K – $5M",
        "partner_default": "Elad Gil",
        "title_default": "Solo GP, Gil Capital",
        "website": "https://eladgil.com",
        "portfolio": "Harvey (AI Legal/Compliance), Stripe, Brex, Deel, Checkr, Figma, Perplexity",
        "bank_lp_value": "Single fastest high-signal AI & FinTech decision-maker in Silicon Valley (backed Harvey, Stripe, Brex, Checkr).",
        "why_fit": "Elad Gil backed Harvey (AI legal), Checkr (compliance), Stripe, and Brex, and makes solo investment decisions in days without committee delays.",
        "pitch_angle": "Pitch Dokimo as 'Harvey for Operational Bank & Broker-Dealer Compliance' — validating 100% of production records against written rules.",
    },
    "nat friedman": {
        "category": "AI Operator Investor (Former GitHub CEO / NFDG)",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed",
        "check_size": "$500K – $5M",
        "partner_default": "Nat Friedman",
        "title_default": "Investor & Former CEO of GitHub",
        "website": "https://nat.org",
        "portfolio": "Scale AI, Perplexity, ElevenLabs, Safe Superintelligence, B2B AI Agents",
        "bank_lp_value": "Fast solo/operator check writer with deep conviction in code-generating & deterministic verification agents.",
        "why_fit": "Nat Friedman backs high-velocity AI agent founders where LLMs write executable verification rules and remediations (like Bob).",
        "pitch_angle": "Show how Bob compiles natural-language regulatory policies into executable SQL/Python validation rules and code patches.",
    },
    "daniel gross": {
        "category": "AI Operator Investor (Pioneer / NFDG)",
        "tier": "S",
        "base_score": 94,
        "stage": "Pre-Seed / Seed",
        "check_size": "$500K – $5M",
        "partner_default": "Daniel Gross",
        "title_default": "Investor (Former Y Combinator AI Partner)",
        "website": "https://dcgross.com",
        "portfolio": "Stripe, Rippling, GitHub, Figma, Perplexity, Applied Enterprise AI",
        "bank_lp_value": "Fast solo decision-maker who backs applied enterprise AI at Seed without bureaucracy.",
        "why_fit": "Daniel Gross writes fast Seed checks into technical founders applying AI to massive regulated industries.",
        "pitch_angle": "Emphasize Dokimo's autonomous regulatory signal-to-control loop across 20,065 financial institutions.",
    },
    "paul moritz": {
        "category": "Enterprise Infrastructure & Governance Legend (Ex-VMware/Pivotal CEO)",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Chairman-Level Angel",
        "check_size": "$250K – $2M",
        "partner_default": "Paul Maritz",
        "title_default": "Investor & Former CEO of VMware & Pivotal",
        "website": "https://www.linkedin.com/in/paul-maritz/",
        "portfolio": "VMware, Pivotal, Cloudera, Mojio, Enterprise Data & Cloud Governance",
        "bank_lp_value": "Already in active follow-up on Leo's sheet; former CEO of VMware & Pivotal (trusted by every global bank CIO).",
        "why_fit": "Paul Maritz built the enterprise virtualization and cloud platform stack used by every bank on Wall Street and is already in Leo's active follow-up pipeline.",
        "pitch_angle": "Show how Dokimo deploys inside bank VMware/Kubernetes perimeters to provide continuous regulatory control assurance.",
    },
    "deviation capital": {
        "category": "Quant-Backed FinTech, Data & Enterprise AI VC (fka Two Sigma Ventures)",
        "tier": "A",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Colin Beirne",
        "title_default": "Founder & Managing Partner",
        "website": "https://deviation.com",
        "portfolio": "Crux Informatics (financial data validation),Truera (AI explainability), Plaidecosystem, GitLab",
        "bank_lp_value": "Spun out of Two Sigma ($60B+ quant hedge fund); deep Wall Street quant, broker-dealer, and SEC/FINRA compliance DNA.",
        "why_fit": "Colin Beirne backed Truera (AI Explainability, acquired by Snowflake) and Crux (financial data validation); understands SEC/FINRA & bank data controls deeply.",
        "pitch_angle": "Highlight Dokimo's mathematical full-population verification + Bob's explainable AI remediation for SEC 15c3-3, CAT, FINRA 3310, and OCC controls.",
    },
    "point72 ventures": {
        "category": "Wall Street FinTech, Capital Markets & Compliance AI VC",
        "tier": "A",
        "base_score": 92,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Pete Casella",
        "title_default": "Senior Partner & Co-Head of FinTech",
        "website": "https://p72.vc",
        "portfolio": "Quantexa (AML/Financial Crime), SteelEye (Trade/Comms Compliance), Droit (Regulatory Decision Engine), DriveWealth",
        "bank_lp_value": "Backed Droit (computational regulatory rules for banks), Quantexa, and SteelEye—direct Wall Street & global bank compliance network.",
        "why_fit": "Pete Casella backed Droit (regulatory rules engine), Quantexa, and SteelEye. Dokimo is the AI-native next generation of Droit + full-population record validation.",
        "pitch_angle": "Pitch Dokimo as 'AI-Native Droit + Full-Population Record Testing' — validating 100% of operational records against regulatory policies with Bob remediation.",
    },
    # --- QUALIFIED TRANSATLANTIC UK & EU FINTECH / REGTECH / BANK-CVC INVESTORS ---
    "13books capital": {
        "category": "🇬🇧 UK/US Pure-Play B2B FinTech & RegTech Seed VC (fka Element Ventures)",
        "tier": "S",
        "base_score": 97,
        "stage": "Seed / Series A Lead",
        "check_size": "$1.5M – $5M",
        "partner_default": "Michael McFadgen",
        "title_default": "Founding Partner",
        "email_default": "michael@13books.com",
        "person_linkedin": "https://www.linkedin.com/in/michaelmcfadgen/",
        "website": "https://www.13books.com",
        "portfolio": "Fenergo (Bank KYC/CLM), Duco (Bank Data Reconciliation), Hepster, Billhop",
        "bank_lp_value": "Founding partners backed Fenergo and Duco (deployed at 100+ global US, UK & EU banks); invests transatlantically in US + UK RegTech.",
        "why_fit": "Michael McFadgen and Steve Gibson backed Fenergo (CLM/KYC) and Duco (bank reconciliation). Unlike Europe-only generalist funds, 13books invests specifically in transatlantic B2B RegTech selling to NYC & London banks.",
        "pitch_angle": "Pitch Dokimo as 'Fenergo + Duco for the Agentic AI Era' — uniting written compliance policies with 100% full-population operational record reconciliation and Bob's explainable remediation across OCC/SEC/FINRA and FCA/PRA/DORA.",
    },
    "outward vc": {
        "category": "🇬🇧 UK/Transatlantic Early-Stage FinTech & RegTech Seed Specialist",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed Lead",
        "check_size": "$1.5M – $5M",
        "partner_default": "Devin Kohli",
        "title_default": "Co-Founder & Co-Head",
        "email_default": "devin@outward.vc",
        "person_linkedin": "https://www.linkedin.com/in/devinkohli/",
        "website": "https://outward.vc",
        "portfolio": "Bud Financial, PrimaryBid, Vauban, Comma, B2B RegTech & Banking Infrastructure",
        "bank_lp_value": "Backed by Investec Bank and NIBC Bank plus institutional LPs; direct commercial bridge into London and transatlantic banks.",
        "why_fit": "Devin Kohli leads Seed rounds in B2B RegTech and banking infrastructure solving regulatory compliance bottlenecks (FCA Consumer Duty, PRA SS1/23, DORA, and US OCC/SEC exams).",
        "pitch_angle": "Show how Dokimo's full-population control validation and Bob agent allow banks in New York and London to validate 100% of records without adding compliance headcount.",
    },
    "albionvc": {
        "category": "🇬🇧 UK/Transatlantic B2B RegTech, FinCrime & Enterprise AI VC",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A Lead",
        "check_size": "$1.5M – $6M",
        "partner_default": "Jay Wilson",
        "title_default": "Partner (FinTech, RegTech & Risk AI)",
        "email_default": "jwilson@albion.vc",
        "person_linkedin": "https://www.linkedin.com/in/jay-wilson-vc/",
        "website": "https://www.albion.vc",
        "portfolio": "Quantexa (Bank Decision Intelligence/AML Unicorn), Elliptic (Crypto AML), Ophelos, Diffblue",
        "bank_lp_value": "Early investor in Quantexa and Elliptic—two of the most successful US/UK bank compliance platforms in the world.",
        "why_fit": "AlbionVC backed Quantexa and Elliptic from early stages and has a dedicated thesis on AI-driven regulatory compliance and financial crime prevention across US and UK banks.",
        "pitch_angle": "Position Dokimo as the policy-to-record control assurance counterpart to Quantexa—testing 100% of bank records against written OCC, SEC, FINRA, FCA, and DORA rules.",
    },
    "augmentum fintech": {
        "category": "🇬🇧 UK/EU Publicly Listed FinTech & RegTech Specialist VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Series A",
        "check_size": "$2M – $6M",
        "partner_default": "Tim Levene",
        "title_default": "CEO & Managing Partner",
        "email_default": "tim@augmentum.vc",
        "person_linkedin": "https://www.linkedin.com/in/timlevene/",
        "website": "https://augmentum.vc",
        "portfolio": "Onfido (Identity/KYC, acquired by Entrust), Tide, Grover, iwoca, BullionVault, Volt",
        "bank_lp_value": "Permanent-capital FinTech & RegTech fund in London with deep UK/EU bank & FCA regulatory advisory relationships.",
        "why_fit": "Tim Levene backed Onfido (global US/UK identity compliance) and focuses 100% on regulated FinTech & RegTech infrastructure with transatlantic scale.",
        "pitch_angle": "Show how Dokimo is the next-generation institutional compliance verification layer after KYC/identity—validating 100% of ongoing operational transactions and controls.",
    },
    "abn amro ventures": {
        "category": "🇪🇺 European Bank CVC Investing in US & EU RegTech / FinCrime",
        "tier": "A",
        "base_score": 95,
        "stage": "Seed / Series A Strategic Bank CVC",
        "check_size": "$2M – $8M",
        "partner_default": "Hugo Bongers",
        "title_default": "Managing Director, ABN AMRO Ventures",
        "email_default": "hugo.bongers@nl.abnamro.com",
        "person_linkedin": "https://www.linkedin.com/in/hugobongers/",
        "website": "https://www.abnamro.com/ventures",
        "portfolio": "Hummingbird (US AML/SAR CRM), Socure (US KYC), Chainalysis (US AML), ThetaRay (Cross-Border AML), Hadrian",
        "bank_lp_value": "Strategic Venture Arm of ABN AMRO Bank (€400B+ assets); actively invests in US-headquartered RegTechs (Hummingbird, Socure, Chainalysis) and deploys them across European banking.",
        "why_fit": "QUALIFIED TRANSATLANTIC BANK CVC: Unlike Europe-only VCs, ABN AMRO Ventures backed US-headquartered Hummingbird, Socure, and Chainalysis because ABN AMRO needs best-in-class AML & compliance automation.",
        "pitch_angle": "Pitch Dokimo as the natural companion to their Hummingbird & Socure investments: validating 100% of underlying bank records against ECB, BaFin, DNB, DORA, and US rules.",
    },
    "commerzventures": {
        "category": "🇪🇺 Transatlantic US + EU FinTech & RegTech VC (Backed by Commerzbank)",
        "tier": "A",
        "base_score": 94,
        "stage": "Seed / Series A",
        "check_size": "$2M – $8M",
        "partner_default": "Paul Morgenthaler",
        "title_default": "Partner, CommerzVentures",
        "email_default": "paul@commerzventures.com",
        "person_linkedin": "https://www.linkedin.com/in/paulmorgenthaler/",
        "website": "https://commerzventures.com",
        "portfolio": "Socure (US KYC), Marqeta (US), Mambu, Doconomy, ByMiles (€550M AUM)",
        "bank_lp_value": "Backed by Commerzbank (Frankfurt); explicit mandate to invest in the USA, UK, Europe, and Israel (backed US-based Socure & Marqeta).",
        "why_fit": "QUALIFIED US + EU MANDATE: CommerzVentures explicitly invests in US FinTech/RegTech companies (like Socure) and opens immediate commercial doors to Commerzbank and DACH institutions under BaFin MaRisk, GwG, and EU DORA.",
        "pitch_angle": "Lead with Dokimo's in-perimeter deployment (satisfying German Bankgeheimnis, GDPR Art. 28, BaFin MaRisk, and OCC/FDIC) + Bob's explainable remediation.",
    },
    "deutsche bank corporate venture capital": {
        "category": "🇪🇺/🇺🇸 Transatlantic Tier-1 Bank CVC (Frankfurt, London & NYC)",
        "tier": "A",
        "base_score": 94,
        "stage": "Seed / Series A Strategic Bank CVC",
        "check_size": "$2M – $10M",
        "partner_default": "Gil Perez",
        "title_default": "Chief Innovation Officer & Head of DB Corporate Venture Capital",
        "email_default": "gil.perez@db.com",
        "person_linkedin": "https://www.linkedin.com/in/gilperez/",
        "website": "https://www.db.com",
        "portfolio": "Kodex AI (AI Financial Compliance), SkyHive, Symphony, Dwolla, Modefin",
        "bank_lp_value": "Direct strategic investment & enterprise deployment bridge into Deutsche Bank across NYC (Wall Street), London, and Frankfurt.",
        "why_fit": "Deutsche Bank operates under simultaneous US (FRB/OCC/SEC/FINRA/FinCEN) and EU/UK (BaFin/ECB/FCA/DORA) supervision and already invested in Kodex AI for compliance document intelligence.",
        "pitch_angle": "Show how Dokimo goes beyond document Q&A to test 100% of Deutsche Bank's production trade, wire, and account records against written US & EU policies overnight.",
    },
    "blackfin tech": {
        "category": "🇪🇺 Europe & UK's Largest Dedicated FinTech & RegTech Seed/A Fund",
        "tier": "S",
        "base_score": 96,
        "stage": "Seed / Series A Lead",
        "check_size": "$1.5M – $6M",
        "partner_default": "Julien Creuzé",
        "title_default": "Managing Director, BlackFin Tech",
        "email_default": "julien.creuze@blackfin.com",
        "person_linkedin": "https://www.linkedin.com/in/juliencreuze/",
        "website": "https://www.blackfintech.com",
        "portfolio": "ClauseMatch (Policy Management — acquired by Corlytics), Hawk AI (AML Transaction Monitoring), Friss, Akur8 (€4B+ AUM)",
        "bank_lp_value": "100% dedicated to financial services & RegTech; backed ClauseMatch (regulatory policy management) and Hawk AI (AML monitoring, expanded to US).",
        "why_fit": "BlackFin backed ClauseMatch (written policy management) and Hawk AI (AML)—they know better than anyone that written policies sit disconnected from operational databases, which is the exact gap Dokimo solves.",
        "pitch_angle": "Pitch Dokimo as the 'ClauseMatch-to-Database Execution Bridge': taking written compliance policies and deterministically testing 100% of operational records with Bob remediation.",
    },
    "finch capital": {
        "category": "🇪🇺/🇬🇧 EU & UK RegTech, Compliance AI & FinTech Specialist VC",
        "tier": "S",
        "base_score": 95,
        "stage": "Seed / Early Growth",
        "check_size": "$1.5M – $5M",
        "partner_default": "Radboud Vlaar",
        "title_default": "Managing Partner",
        "email_default": "vlaar@finchcapital.com",
        "person_linkedin": "https://www.linkedin.com/in/radboudvlaar/",
        "website": "https://finchcapital.com",
        "portfolio": "Fourthline (European Bank KYC/AML), Symmetrical, Goodlord, Laventi",
        "bank_lp_value": "Deep commercial network across UK, Dutch, German, and pan-European banks facing EU AI Act, DORA, and AMLA mandates.",
        "why_fit": "Radboud Vlaar backed Fourthline (bank KYC/compliance) and explicitly targets capital-efficient B2B RegTech automating bank compliance across UK, EU, and US markets.",
        "pitch_angle": "Highlight Dokimo's live coverage of 16 regulators (OCC, FDIC, SEC, FINRA, FCA, PRA, BaFin, ECB) and full-population policy-to-record control assurance.",
    },
    "speedinvest": {
        "category": "🇪🇺/🇬🇧 Pre-Seed & Seed FinTech & RegTech Lead VC (Vienna, Berlin, London)",
        "tier": "S",
        "base_score": 95,
        "stage": "Pre-Seed / Seed Lead",
        "check_size": "$500K – $3M",
        "partner_default": "Stefan Klestil",
        "title_default": "General Partner, FinTech",
        "email_default": "stefan@speedinvest.com",
        "person_linkedin": "https://www.linkedin.com/in/stefanklestil/",
        "website": "https://www.speedinvest.com",
        "portfolio": "Curve, Wayflyer, Bitpanda, Complytron, Billie, FinTech & RegTech Seed",
        "bank_lp_value": "Backed by European institutional & bank LPs (including NEA co-investments in US/EU FinTech); fast Day-0 Pre-Seed/Seed check writer.",
        "why_fit": "Stefan Klestil and Speedinvest's FinTech team write fast Pre-Seed and Seed checks ($500K–$3M) into transatlantic FinTech and RegTech founders without requiring Series-A ARR.",
        "pitch_angle": "Pitch Dokimo as the transatlantic US + EU/UK autonomous compliance validation platform capturing both OCC/SEC/FINRA and EU DORA / AMLA demand.",
    },
    "portage ventures": {
        "category": "🇬🇧/🇪🇺/🇺🇸 Transatlantic FinTech & RegTech Platform VC (London, Paris, NYC)",
        "tier": "A",
        "base_score": 93,
        "stage": "Seed / Series A",
        "check_size": "$2M – $10M",
        "partner_default": "Hélène Falchier",
        "title_default": "Partner (Former CEO of Natixis / BPCE Ventures)",
        "email_default": "hf@portagevc.com",
        "person_linkedin": "https://www.linkedin.com/in/helenefalchier/",
        "website": "https://portagevc.com",
        "portfolio": "Socure (US), Alloy (US), Clark, Penta, Alpaca, Wealthsimple ($4B+ FinTech platform)",
        "bank_lp_value": "Backed by global financial institutions across North America, UK, and Europe; Hélène Falchier formerly ran Natixis/BPCE's bank venture arm.",
        "why_fit": "QUALIFIED TRANSATLANTIC FINTECH VC: Portage operates in NYC, London, and Paris and already co-invested in US compliance leaders Alloy and Socure.",
        "pitch_angle": "Show how Dokimo completes the Alloy/Socure compliance stack with continuous full-population post-onboarding control validation across US and European banks.",
    },
    "mayfield": {
        "category": "Tier-1 Enterprise AI & Compliance Infrastructure VC (Active Warm Thread)",
        "tier": "A",
        "base_score": 92,
        "stage": "Seed / Series A (AI & Enterprise)",
        "check_size": "$2M – $15M",
        "partner_default": "Patrick Salyer / Navin Chaddha",
        "title_default": "Partner (Enterprise AI & Governance) / Managing Partner",
        "email_default": "psalyer@mayfield.com",
        "person_linkedin": "https://www.linkedin.com/in/patricksalyer/",
        "website": "https://www.mayfield.com",
        "portfolio": "HashiCorp, Marketo, Poshmark, BigID, Rancher, AI Teammates ($250M AI Seed/A Fund)",
        "bank_lp_value": "Mayfield launched a dedicated $250M AI Teammates seed/early-stage initiative; Patrick Salyer specifically evaluates AI compliance and identity governance.",
        "why_fit": "ACTIVE WARM THREAD: On Oct 2, Managing Partner Navin Chaddha looped in Partner Patrick Salyer ('adding my partner Patrick who has looked at this space'), who requested & received the Dokimo overview deck on Oct 5.",
        "pitch_angle": "Follow up directly with Patrick Salyer (psalyer@mayfield.com) & Navin Chaddha (nchaddha@mayfield.com) positioning Bob as the 'AI Teammate for Bank Compliance & Internal Audit' backed by deterministic 100% population validation.",
    },
    "battery ventures": {
        "category": "Enterprise AI, Data Observability & Risk Software VC",
        "tier": "B",
        "base_score": 88,
        "stage": "Seed / Series A / Growth",
        "check_size": "$3M – $25M",
        "partner_default": "Dharmesh Thakker",
        "title_default": "General Partner (Enterprise AI, Data & Cyber)",
        "email_default": "dharmesh@battery.com",
        "person_linkedin": "https://www.linkedin.com/in/dthakker/",
        "website": "https://www.battery.com",
        "portfolio": "Databricks, Monte Carlo (data observability), Gong, Postman, Coupa, MarketAxess",
        "bank_lp_value": "Deep financial services software DNA (early investor in MarketAxess & Coupa) and data observability (Monte Carlo).",
        "why_fit": "Dharmesh Thakker backed Databricks and Monte Carlo (data observability). Dokimo is 'Compliance & Control Observability' on top of bank data warehouses.",
        "pitch_angle": "Frame Dokimo as 'Monte Carlo for Regulatory Control Validation' — validating 100% of production records against written OCC/FDIC/SEC policies inside the bank's cloud perimeter.",
    },
    "bluerun ventures": {
        "category": "Early-Stage FinTech & Enterprise AI Seed/A VC",
        "tier": "A",
        "base_score": 89,
        "stage": "Seed / Series A",
        "check_size": "$1M – $8M",
        "partner_default": "Jeff Chu",
        "title_default": "Managing Partner",
        "email_default": "jchu@brv.com",
        "person_linkedin": "https://www.linkedin.com/in/jeff-chu-brv/",
        "website": "https://www.brv.com",
        "portfolio": "PayPal (first institutional investor), Kabbage, Chime, Banjo, FreedomPay",
        "bank_lp_value": "Strong FinTech heritage (first institutional check into PayPal and Kabbage); active early-stage US FinTech & AI check-writer.",
        "why_fit": "Leo emailed Managing Partner Jeff Chu (jchu@brv.com) on Sep 30 for Dokimo's seed round; BRV has deep conviction in foundational financial services infrastructure.",
        "pitch_angle": "Highlight how Dokimo replaces manual sample-based bank audits with 100% full-population policy-to-record validation and Bob autonomous remediation.",
    },
    "sunstone partners": {
        "category": "Tech-Enabled Compliance, Cyber & Enterprise Software Growth/Strategic",
        "tier": "A",
        "base_score": 89,
        "stage": "Strategic / Growth / Co-Investor",
        "check_size": "$5M – $25M",
        "partner_default": "Michael Biggee",
        "title_default": "Co-Founder & Managing Director",
        "email_default": "mbiggee@sunstonepartners.com",
        "person_linkedin": "https://www.linkedin.com/in/michael-biggee-00248b6/",
        "website": "https://www.sunstonepartners.com",
        "portfolio": "Avertium, CyberSheath,owsky, Schellman (compliance/audit), NetSPI",
        "bank_lp_value": "Invests heavily in cybersecurity, IT compliance, and audit/assessment firms — direct strategic channel for audit/compliance firm partnerships.",
        "why_fit": "ACTIVE WARM THREAD: Warren sent the Dokimo pitch deck directly to Co-Founder Michael Biggee (mbiggee@sunstonepartners.com) on Oct 9.",
        "pitch_angle": "Leverage Sunstone's portfolio of cybersecurity and compliance assessment firms as a channel multiplier for Dokimo's automated full-population validation.",
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

    # Canonicalize fund names & deduplicate strictly 1 row per Fund (combining multiple partners cleanly)
    fund_aliases = {
        "gv": "GV (Google Ventures)",
        "google ventures": "GV (Google Ventures)",
        "gv (google ventures)": "GV (Google Ventures)",
        "menlo": "Menlo Ventures",
        "menlo ventures": "Menlo Ventures",
        "battery": "Battery Ventures",
        "battery ventures": "Battery Ventures",
        "triatomic": "Triatomic Capital",
        "triatomic capital": "Triatomic Capital",
        "two sigma": "Deviation Capital (fka Two Sigma Ventures)",
        "deviation capital (fka two sigma ventures)": "Deviation Capital (fka Two Sigma Ventures)",
        "vvus": "Vertex Ventures US",
        "quite capital": "Quiet Capital",
        "quiet capital": "Quiet Capital",
        "raptor/rosen": "Raptor Group",
        "raptor group": "Raptor Group",
        "miramar": "Miramar VP",
        "miramar vp": "Miramar VP",
        "playground (network)": "Playground Global",
        "playground global": "Playground Global",
        "analog device ventures": "Analog Devices Ventures",
        "matter vc (tsmc fund)": "Matter Venture Partners",
        "Paul Moritz": "Paul Maritz",
    }

    # Inject Qualified Transatlantic UK & EU FinTech/RegTech/Bank-CVC Funds (Invest in US + UK/EU, Zero Europe-HQ-Only Trap)
    qualified_uk_eu_funds = [
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "13books Capital",
            "person": "Michael McFadgen",
            "title": "Founding Partner (fka Element Ventures)",
            "background": "Pure-play B2B FinTech & RegTech Seed/A VC in London investing across UK & US (backed Fenergo, Duco)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified UK/US B2B RegTech Seed VC — backed Fenergo (KYC/CLM) and Duco (reconciliation)",
            "email": "michael@13books.com",
            "person_linkedin": "https://www.linkedin.com/in/michaelmcfadgen/",
            "website": "https://www.13books.com",
            "company_linkedin": "https://www.linkedin.com/company/13books-capital/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+44 20 3983 8000",
            "city": "London",
            "state": "",
            "country": "United Kingdom",
            "total_funding": "",
            "relevant_investments": "Fenergo, Duco, Hepster, Billhop",
            "next_action": "Pitch 'Fenergo + Duco for the Agentic AI Era' (US + UK/EU bank controls)",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Outward VC",
            "person": "Devin Kohli",
            "title": "Co-Founder & Co-Head",
            "background": "London & Transatlantic Early-Stage B2B FinTech & RegTech Seed VC backed by Investec & NIBC Bank",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified UK/US Seed Lead (£1M-£4M checks) focused on B2B RegTech & banking compliance",
            "email": "devin@outward.vc",
            "person_linkedin": "https://www.linkedin.com/in/devinkohli/",
            "website": "https://outward.vc",
            "company_linkedin": "https://www.linkedin.com/company/outwardvc/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+44 20 7566 0000",
            "city": "London",
            "state": "",
            "country": "United Kingdom",
            "total_funding": "",
            "relevant_investments": "Bud Financial, PrimaryBid, Vauban, Comma",
            "next_action": "Send Seed deck + FCA/PRA/OCC full-population validation memo",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "AlbionVC",
            "person": "Jay Wilson",
            "title": "Partner (FinTech, RegTech & Risk AI)",
            "background": "Early investor in Quantexa & Elliptic; backs UK & transatlantic RegTech/FinCrime software",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified UK/US RegTech VC — backed Quantexa (bank AML unicorn) & Elliptic",
            "email": "jwilson@albion.vc",
            "person_linkedin": "https://www.linkedin.com/in/jay-wilson-vc/",
            "website": "https://www.albion.vc",
            "company_linkedin": "https://www.linkedin.com/company/albionvc/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+44 20 7601 1850",
            "city": "London",
            "state": "",
            "country": "United Kingdom",
            "total_funding": "",
            "relevant_investments": "Quantexa, Elliptic, Ophelos, Diffblue",
            "next_action": "Pitch Dokimo as policy-to-record control assurance counterpart to Quantexa",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Augmentum Fintech",
            "person": "Tim Levene",
            "title": "CEO & Managing Partner",
            "background": "UK's publicly listed FinTech/RegTech specialist VC (backed Onfido, Tide, iwoca)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified UK/EU FinTech & RegTech specialist — backed Onfido (global US/UK compliance)",
            "email": "tim@augmentum.vc",
            "person_linkedin": "https://www.linkedin.com/in/timlevene/",
            "website": "https://augmentum.vc",
            "company_linkedin": "https://www.linkedin.com/company/augmentum-fintech/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+44 20 3961 5420",
            "city": "London",
            "state": "",
            "country": "United Kingdom",
            "total_funding": "",
            "relevant_investments": "Onfido, Tide, Grover, iwoca, Volt",
            "next_action": "Pitch post-onboarding 100% transaction & control validation",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "ABN AMRO Ventures",
            "person": "Hugo Bongers",
            "title": "Managing Director, ABN AMRO Ventures",
            "background": "European Bank CVC actively investing in US & EU RegTech (backed US-based Hummingbird, Socure, Chainalysis, ThetaRay)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Verified US + EU Mandate: backed US-headquartered Hummingbird, Socure & Chainalysis",
            "email": "hugo.bongers@nl.abnamro.com",
            "person_linkedin": "https://www.linkedin.com/in/hugobongers/",
            "website": "https://www.abnamro.com/ventures",
            "company_linkedin": "https://www.linkedin.com/company/abn-amro-ventures/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+31 20 628 9393",
            "city": "Amsterdam",
            "state": "",
            "country": "Netherlands (EU)",
            "total_funding": "",
            "relevant_investments": "Hummingbird (US), Socure (US), Chainalysis (US), ThetaRay, Hadrian",
            "next_action": "Pitch Dokimo as full-population control validation companion to Hummingbird & Socure",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "CommerzVentures",
            "person": "Paul Morgenthaler",
            "title": "Partner, CommerzVentures",
            "background": "Frankfurt FinTech/RegTech VC backed by Commerzbank; explicit mandate for USA, Europe & Israel (backed Socure, Marqeta)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Verified US + EU Mandate: explicitly invests in USA & Europe (backed Socure & Marqeta)",
            "email": "paul@commerzventures.com",
            "person_linkedin": "https://www.linkedin.com/in/paulmorgenthaler/",
            "website": "https://commerzventures.com",
            "company_linkedin": "https://www.linkedin.com/company/commerzventures/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+49 69 136 20",
            "city": "Frankfurt",
            "state": "",
            "country": "Germany (EU)",
            "total_funding": "",
            "relevant_investments": "Socure (US), Marqeta (US), Mambu, Doconomy",
            "next_action": "Pitch in-perimeter BaFin MaRisk / DORA + US OCC/FDIC full-population control testing",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Deutsche Bank Corporate Venture Capital",
            "person": "Gil Perez",
            "title": "Chief Innovation Officer & Head of DB CVC",
            "background": "Transatlantic NYC + Frankfurt + London Bank CVC (backed Kodex AI financial compliance LLM, Symphony)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Verified US + EU/UK Bank CVC — operates in NYC, London & Frankfurt (backed Kodex AI)",
            "email": "gil.perez@db.com",
            "person_linkedin": "https://www.linkedin.com/in/gilperez/",
            "website": "https://www.db.com",
            "company_linkedin": "https://www.linkedin.com/company/deutsche-bank/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+1 212-250-2500",
            "city": "New York / Frankfurt / London",
            "state": "NY",
            "country": "Germany (EU) / US / UK",
            "total_funding": "",
            "relevant_investments": "Kodex AI, SkyHive, Symphony, Dwolla",
            "next_action": "Pitch deterministic full-population record validation beyond document Q&A",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "BlackFin Tech",
            "person": "Julien Creuzé",
            "title": "Managing Director, BlackFin Capital Partners",
            "background": "Europe & UK's largest dedicated FinTech & RegTech fund (€4B+ AUM; backed ClauseMatch policy management & Hawk AI AML)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified EU/UK RegTech Leader — backed ClauseMatch (policy management) & Hawk AI (US/EU AML)",
            "email": "julien.creuze@blackfin.com",
            "person_linkedin": "https://www.linkedin.com/in/juliencreuze/",
            "website": "https://www.blackfintech.com",
            "company_linkedin": "https://www.linkedin.com/company/blackfin-capital-partners/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+33 1 56 43 29 00",
            "city": "Paris / Frankfurt / London",
            "state": "",
            "country": "France / Germany (EU) / UK",
            "total_funding": "",
            "relevant_investments": "ClauseMatch (acquired by Corlytics), Hawk AI, Friss, Akur8",
            "next_action": "Pitch Dokimo as the ClauseMatch-to-Database full-population execution bridge",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Finch Capital",
            "person": "Radboud Vlaar",
            "title": "Managing Partner",
            "background": "Amsterdam & London RegTech, Compliance AI & FinTech specialist VC (backed Fourthline KYC/AML)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified EU/UK RegTech Seed/A VC — backed Fourthline (bank KYC/AML)",
            "email": "vlaar@finchcapital.com",
            "person_linkedin": "https://www.linkedin.com/in/radboudvlaar/",
            "website": "https://finchcapital.com",
            "company_linkedin": "https://www.linkedin.com/company/finch-capital/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+31 20 240 2900",
            "city": "Amsterdam / London",
            "state": "",
            "country": "Netherlands (EU) / UK",
            "total_funding": "",
            "relevant_investments": "Fourthline, Symmetrical, Goodlord, Laventi",
            "next_action": "Send 2-Page Tear-Sheet highlighting 16-regulator US + UK/EU coverage",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Speedinvest",
            "person": "Stefan Klestil",
            "title": "General Partner, FinTech",
            "background": "Pan-European & UK Pre-Seed/Seed FinTech & RegTech Lead VC (Vienna, Berlin, London; co-invests transatlantically with US VCs)",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Qualified Pre-Seed/Seed Check-Writer ($500K-$3M) in FinTech & RegTech",
            "email": "stefan@speedinvest.com",
            "person_linkedin": "https://www.linkedin.com/in/stefanklestil/",
            "website": "https://www.speedinvest.com",
            "company_linkedin": "https://www.linkedin.com/company/speedinvest/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+43 1 909 4416",
            "city": "London / Berlin / Vienna",
            "state": "",
            "country": "Austria / Germany (EU) / UK",
            "total_funding": "",
            "relevant_investments": "Curve, Wayflyer, Bitpanda, Complytron, Billie",
            "next_action": "Pitch Pre-Seed/Seed round with US + EU DORA/AMLA bank compliance angle",
        },
        {
            "source_table": "Transatlantic UK/EU Qualified",
            "fund": "Portage Ventures",
            "person": "Hélène Falchier",
            "title": "Partner (Former CEO of Natixis / BPCE Ventures)",
            "background": "Transatlantic FinTech & RegTech VC (NYC, London, Paris) — backed US compliance leaders Alloy & Socure",
            "our_contact": "Warren / Leo",
            "latest_status": "Not Contacted",
            "comment": "Verified US + EU + UK Mandate: backed Alloy (US) & Socure (US); led by ex-Natixis bank CVC head",
            "email": "hf@portagevc.com",
            "person_linkedin": "https://www.linkedin.com/in/helenefalchier/",
            "website": "https://portagevc.com",
            "company_linkedin": "https://www.linkedin.com/company/portage-ventures/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+33 1 53 05 00 00",
            "city": "Paris / London / New York",
            "state": "",
            "country": "France (EU) / UK / US",
            "total_funding": "",
            "relevant_investments": "Alloy (US), Socure (US), Clark, Penta, Alpaca",
            "next_action": "Pitch Dokimo as post-onboarding full-population control validation alongside Alloy/Socure",
        },
        {
            "source_table": "Gmail Sep/Oct Outreach Tracker",
            "fund": "Sunstone Partners",
            "person": "Michael Biggee",
            "title": "Co-Founder & Managing Director",
            "background": "Tech-enabled compliance, cybersecurity & audit services growth equity (Schellman, NetSPI, Avertium)",
            "our_contact": "Warren",
            "latest_status": "Deck / Data Room Sent",
            "comment": "Oct 9: Warren emailed pitch deck directly to Michael Biggee (mbiggee@sunstonepartners.com)",
            "email": "mbiggee@sunstonepartners.com",
            "person_linkedin": "https://www.linkedin.com/in/michael-biggee-00248b6/",
            "website": "https://www.sunstonepartners.com",
            "company_linkedin": "https://www.linkedin.com/company/sunstone-partners/",
            "twitter": "",
            "mobile_phone": "",
            "corporate_phone": "+1 650-289-4400",
            "city": "San Mateo",
            "state": "CA",
            "country": "United States",
            "total_funding": "",
            "relevant_investments": "Schellman, NetSPI, Avertium, CyberSheath",
            "next_action": "Follow up with Michael Biggee (mbiggee@sunstonepartners.com) on Oct 9 pitch deck review",
        },
    ]
    parsed_items.extend(qualified_uk_eu_funds)

    merged_map = {}
    for item in parsed_items:
        raw_fn = _norm(item["fund"])
        canon_fund = fund_aliases.get(raw_fn, item["fund"].strip())
        item["fund"] = canon_fund
        fn = _norm(canon_fund)
        key = fn  # Strictly 1 row per canonical fund — zero duplicates on the board!
        if key not in merged_map:
            merged_map[key] = dict(item)
        else:
            cur = merged_map[key]
            # Combine partner names if a second partner at the same fund is listed
            p_new = (item.get("person") or "").strip()
            p_cur = (cur.get("person") or "").strip()
            if p_new and not p_new.startswith("(") and p_new.lower() not in ("individual", "ai infra team", "systems partners", "infra partners", "ai infra partners"):
                if not p_cur or p_cur.startswith("("):
                    cur["person"] = p_new
                elif p_new.lower() not in p_cur.lower():
                    cur["person"] = f"{p_cur} / {p_new}"
            for field in [
                "title", "background", "our_contact", "latest_status", "comment", "email",
                "person_linkedin", "website", "company_linkedin", "twitter", "mobile_phone",
                "corporate_phone", "city", "state", "country", "total_funding",
                "relevant_investments", "next_action",
            ]:
                if not cur.get(field) and item.get(field):
                    cur[field] = item[field]
                elif field in ("background", "relevant_investments", "our_contact", "comment") and item.get(field) and item[field] not in cur.get(field, ""):
                    cur[field] = f"{cur[field]} | {item[field]}".strip(" |")

    # Enrich & score all items — keeping ONLY the RIGHT VCs for Dokimo (filtering out Wrong/Hardware VCs & Hard Declines)
    state = load_state()

    # Stage-Gated Deep Dive Lists:
    # 0. NON-US REGIONAL MANDATE TRAPS & CHANGED/INACTIVE/HARDWARE FUNDS
    non_us_or_changed_funds = [
        "balderton", "dawn capital", "notion capital", "hoxton", "iq capital",
        "mosaic ventures", "round13", "golden ventures", "pitango", "viola elevate",
        "meron", "aleph", "air street", "crane.vc", "inovia", "hummer winblad",
        "khosla", "eclipse ventures", "matter venture", "aal.vc", "anfavc", "anzu partners",
        "castle-fund", "daemonventures", "embedded ventures", "energize capital",
        "up.partners", "riot ventures", "root vc", "rountree", "harpoon",
        "pax ventures", "red glass", "fathom capital", "miramar", "pegasus",
        "jci ventures", "hp ventures", "intel capital", "cisco", "cloud infra operators",
        "nvidia alumni", "playground", "cleremont", "fj", "wild west",
    ]
    # 1. TRUE US + UK + EU DAY-0 / PRE-SEED & SEED CHECK-WRITERS (Write $500K-$4M checks BEFORE $1M ARR — Zero "Too Early" Risk)
    day0_seed_funds = [
        "ludwig advisors", "valuestream", "vestigo", "restive", "legaltech fund", "sixthirty",
        "work-bench", "luge capital", "commerce ventures", "fintech collective", "anthemis",
        "ejf ventures", "information venture", "ttv capital", "boldstart", "conviction",
        "cyberstarts", "team8", "glilot", "f2 venture", "tlv partners", "costanoa",
        "susa ventures", "daybreak", "glasswing", "amplify", "zetta", "elad gil", "nat friedman",
        "daniel gross", "paul maritz", "paul moritz", "acrew", "firstmark", "signalfire",
        "quiet capital", "sierra ventures", "counterpart", "raptor", "triatomic",
        "radical ventures", "vertex ventures", "rally ventures",
        "13books", "outward vc", "albionvc", "augmentum", "blackfin", "finch capital", "speedinvest",
    ]
    # 2. SERIES A / GROWTH / $400M+ MULTISTAGE FUNDS THAT SAY "TOO EARLY" WITHOUT $1M+ ARR OR 3+ BANK LOGOS
    too_early_series_a_traps = [
        "nyca", "motive partners", "thomson reuters", "qed investors", "ribbit capital",
        "bain capital", "oak hc/ft", "fin capital", "f-prime", "mouro capital",
        "general atlantic", "insight partners", "sequoia", "a16z", "benchmark",
        "general catalyst", "bessemer", "accel", "kleiner perkins", "greylock",
        "menlo", "nea", "index ventures", "battery", "foundation capital", "crv",
        "spark capital", "sutter hill", "coatue", "founders fund", "altimeter",
        "alpha wave", "prosperity7", "dcvc", "madrona", "mayfield", "wing capital",
        "innovation endeavors", "bluerun",
    ]

    uk_funds = ["illuminate financial", "anthemis", "mouro capital", "13books", "outward vc", "albionvc", "augmentum", "index ventures"]
    eu_funds = ["abn amro", "commerzventures", "deutsche bank", "blackfin", "finch capital", "speedinvest", "portage", "constructor", "motive partners"]
    il_us_funds = ["team8", "cyberstarts", "glilot", "f2 venture", "tlv partners"]

    enriched = []
    for idx, (k, row) in enumerate(merged_map.items(), start=1):
        inv_id = "INV-" + hashlib.sha1(k.encode("utf-8")).hexdigest()[:8].upper()
        enrichment_kb.enrich_investor_contact_fields(inv_id, row)
        fit = _classify_and_score_investor(row)
        row.update(fit)
        enrichment_kb.enrich_investor_contact_fields(inv_id, row)
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
        if st.get("person"):
            row["person"] = st["person"]
        if st.get("email"):
            row["email"] = st["email"]
        row["updated_at"] = st.get("updated_at", "")
        row["updated_by"] = st.get("updated_by", "")
        row["deck_opens"] = int(st.get("deck_opens") or (1 if "deck sent" in (row.get("latest_status") or "").lower() or "looking at deck" in (row.get("latest_status") or "").lower() else 0))
        row["pdf_downloads"] = int(st.get("pdf_downloads") or 0)
        row["last_opened_at"] = st.get("last_opened_at", "")
        row["follow_up_date"] = st.get("follow_up_date", "")
        row["followup_note"] = st.get("followup_note", "")
        row["followup_updated_at"] = st.get("followup_updated_at", "")
        row["leo_sep_oct_outreach"] = bool(st.get("leo_sep_oct_outreach", False))

        # EXCLUDE "Wrong" VCs (Tier C Hardware/Semiconductor funds, Europe-HQ-Only traps like Balderton, Changed funds like Hummer Winblad, & explicit hard "No/Declined" funds)
        fn_lc = row["fund"].lower()
        if row["tier"] == "C":
            continue
        if any(reg_trap in fn_lc for reg_trap in non_us_or_changed_funds):
            continue
        st_lc = (row.get("latest_status") or "").lower()
        cm_lc = (row.get("comment") or "").lower()
        if any(x in st_lc for x in ("declined", "not a lead", "not a fit", "turned down")) or "said no" in cm_lc or "not in our region" in cm_lc:
            continue
        if "passed" in st_lc and "too early" not in cm_lc:
            continue

        # Assign Region (US, UK, EU, IL / US)
        if any(u in fn_lc for u in uk_funds):
            row["region"] = "UK"
        elif any(e in fn_lc for e in eu_funds):
            row["region"] = "EU"
        elif any(il in fn_lc for il in il_us_funds):
            row["region"] = "IL / US"
        else:
            row["region"] = "US"

        # Apply Stage-Gated Deep Dive Re-Classification & Qualification Gate so Warren never wastes time
        if "too early" in cm_lc or any(t in fn_lc for t in too_early_series_a_traps):
            # Unless we already have an active scheduling thread (e.g. Barry Eggers at Lightspeed)
            if any(w in st_lc for w in ("scheduling", "talked", "deck / data room sent", "meeting")):
                row["tier"] = "A"
                row["stage"] = "Warm Active Thread (Multi-Stage)"
                row["dokimo_fit_score"] = min(92, max(88, int(row["dokimo_fit_score"])))
                row["qualification_gate"] = f"✅ QUALIFIED ({row['region']}) · Active Warm Partner Thread · Transatlantic/US Eligible"
            else:
                row["tier"] = "B"
                row["stage"] = "⏳ Hold for $1M ARR / 3+ Bank Logos (Series A)"
                row["dokimo_fit_score"] = min(79, int(row["dokimo_fit_score"]) - 15)
                row["why_fit"] = f"[STAGE WARNING — HOLD UNTIL $1M ARR / 3 BANK LOGOS] {row['why_fit']} (Large multistage/Series-A fund — will say 'too early' if pitched before initial paying bank logos)."
                row["qualification_gate"] = f"⏳ STAGE-GATED ({row['region']}) · Hold Until $1M ARR / 3+ Bank Logos (Do Not Waste Time Pitching Pre-ARR)"
                if not row.get("next_action"):
                    row["next_action"] = "Hold until 3+ paying bank pilots / $1M ARR (avoid 'too early' trap)"
        elif any(d in fn_lc for d in day0_seed_funds):
            row["tier"] = "S"
            row["stage"] = "🟢 PITCH NOW: Day-0 / Pre-Seed & Seed Lead"
            row["dokimo_fit_score"] = max(94, min(99, int(row["dokimo_fit_score"]) + 3))
            if "[PITCH NOW" not in row["why_fit"]:
                row["why_fit"] = f"[🟢 PITCH NOW — TRUE PRE-SEED / EARLY-SEED CHECK WRITER] {row['why_fit']}"
            row["qualification_gate"] = f"✅ QUALIFIED ({row['region']}) · Writes $500K–$4M Pre-Seed/Seed Checks Before $1M ARR · Transatlantic/US Eligible"
            if not row.get("next_action"):
                row["next_action"] = f"Pitch Now — Send 2-Page Tear-Sheet & book 15-min intro with {row.get('person') or row['fund']}"
        else:
            # Strategic Bank CVCs & Warm-Intro Seed/A Funds (Citi, CapOne, Amex, Canapi, Illuminate, PruVen, Deviation, Point72, ABN AMRO, CommerzVentures, DB CVC, Portage)
            row["tier"] = "A"
            row["stage"] = "🔵 Warm-Intro / Strategic Bank CVC"
            row["dokimo_fit_score"] = min(93, max(86, int(row["dokimo_fit_score"])))
            row["qualification_gate"] = f"✅ QUALIFIED ({row['region']}) · Strategic Bank CVC / Warm Thread · Direct Bank Commercial + Investment Mandate"
            if not row.get("next_action"):
                row["next_action"] = f"Trigger warm intro / Strategic CVC + Bank Pilot dual track with {row.get('person') or row['fund']}"

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


def save_followup_note(inv_id: str, note: str, updated_by: str = "Warren") -> dict:
    """Persist an auto-saved 4-line follow-up & action note (max 4 lines / 400 chars) for an investor row."""
    iid = (inv_id or "").strip()
    if not iid:
        return {"ok": False, "error": "Missing investor id"}
    lines = str(note or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) > 4:
        lines = lines[:3] + [" ".join(lines[3:])]
    clean_note = "\n".join(lines)[:400]
    state = load_state()
    cur = state.get(iid) or {}
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d %H:%M UTC")
    cur["followup_note"] = clean_note
    cur["followup_updated_at"] = ts if clean_note.strip() else ""
    cur["updated_by"] = updated_by
    cur["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state[iid] = cur
    save_state(state)
    return {"ok": True, "id": iid, "note": clean_note, "updated_at": cur["followup_updated_at"]}


def update_investor_status(
    inv_id: str,
    latest_status: str = None,
    comment: str = None,
    next_action: str = None,
    assigned_owner: str = None,
    follow_up_date: str = None,
    followup_note: str = None,
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
    if follow_up_date is not None:
        cur["follow_up_date"] = str(follow_up_date).strip()[:40]
    if followup_note is not None:
        lines = str(followup_note).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if len(lines) > 4:
            lines = lines[:3] + [" ".join(lines[3:])]
        cur["followup_note"] = "\n".join(lines)[:400]
        cur["followup_updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d %H:%M UTC")
    cur["updated_by"] = updated_by
    cur["updated_at"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    state[iid] = cur
    save_state(state)
    # Re-persist CSV
    rows = get_all_investors(persist_csv=True)
    updated_row = next((r for r in rows if r["id"] == iid), None)
    return {"ok": True, "id": iid, "investor": updated_row}


def record_investor_engagement(inv_id: str, event_type: str = "open") -> dict:
    """Record when an investor opens a pitch link or downloads a 2-page PDF VC Tear-Sheet."""
    iid = (inv_id or "").strip()
    if not iid:
        return {"ok": False}
    state = load_state()
    cur = state.get(iid) or {}
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if event_type == "pdf":
        cur["pdf_downloads"] = int(cur.get("pdf_downloads") or 0) + 1
    else:
        cur["deck_opens"] = int(cur.get("deck_opens") or 0) + 1
        cur["last_opened_at"] = now_str
    state[iid] = cur
    save_state(state)
    return {"ok": True, "id": iid, "state": cur}


CSV_COLUMNS = [
    "rank", "id", "tier", "dokimo_fit_score", "region", "qualification_gate", "fund", "person", "title", "category",
    "stage", "check_size", "our_contact", "latest_status", "next_action", "follow_up_date", "followup_note", "comment",
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
    us_rows = [r for r in rows if r.get("region") == "US"]
    uk_rows = [r for r in rows if r.get("region") == "UK"]
    eu_rows = [r for r in rows if r.get("region") == "EU"]
    il_us_rows = [r for r in rows if r.get("region") == "IL / US"]
    with_email = [r for r in rows if r.get("email")]
    with_linkedin = [r for r in rows if r.get("person_linkedin")]
    with_phone = [r for r in rows if r.get("display_phone")]
    warren_contacts = [r for r in rows if "warren" in (r.get("our_contact") or "").lower()]
    leo_contacts = [r for r in rows if "leo" in (r.get("our_contact") or "").lower()]
    active_convos = [
        r for r in rows
        if (r.get("latest_status") or "").lower() not in ("", "not contacted", "declined", "not a lead")
        and "passed" not in (r.get("latest_status") or "").lower()
    ]
    leo_sep_oct = [
        r for r in rows
        if r.get("leo_sep_oct_outreach")
    ]
    followup_queue = [
        r for r in rows
        if (r.get("followup_note") or "").strip()
        or (r.get("follow_up_date") or "").strip()
        or any(k in (r.get("latest_status") or "").lower() for k in ("follow", "scheduling", "deck", "intro", "call", "talked", "waiting"))
    ]
    decks_sent = [
        r for r in rows
        if any(k in (r.get("latest_status") or "").lower() for k in ("deck", "call", "meeting", "intro", "sent", "committed", "pitch"))
        or int(r.get("deck_opens") or 0) > 0
    ]
    decks_opened = [
        r for r in rows
        if int(r.get("deck_opens") or 0) > 0 or int(r.get("pdf_downloads") or 0) > 0
        or "looking at deck" in (r.get("latest_status") or "").lower()
    ]
    tier_sa_followup = [
        r for r in rows
        if r["tier"] in ("S", "A")
        and (r.get("latest_status") or "").lower() not in ("declined", "not a lead", "committed", "deprioritize / skip")
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
        "us_count": len(us_rows),
        "us_rate": f"{len(us_rows)} of {total} ({round(len(us_rows) / denom * 100, 1)}%)",
        "uk_count": len(uk_rows),
        "uk_rate": f"{len(uk_rows)} of {total} ({round(len(uk_rows) / denom * 100, 1)}%)",
        "eu_count": len(eu_rows),
        "eu_rate": f"{len(eu_rows)} of {total} ({round(len(eu_rows) / denom * 100, 1)}%)",
        "il_us_count": len(il_us_rows),
        "il_us_rate": f"{len(il_us_rows)} of {total} ({round(len(il_us_rows) / denom * 100, 1)}%)",
        "with_email_count": len(with_email),
        "with_email_rate": f"{len(with_email)} of {total} ({round(len(with_email) / denom * 100, 1)}%)",
        "with_linkedin_count": len(with_linkedin),
        "with_linkedin_rate": f"{len(with_linkedin)} of {total} ({round(len(with_linkedin) / denom * 100, 1)}%)",
        "with_phone_count": len(with_phone),
        "with_phone_rate": f"{len(with_phone)} of {total} ({round(len(with_phone) / denom * 100, 1)}%)",
        "warren_contact_count": len(warren_contacts),
        "leo_contact_count": len(leo_contacts),
        "active_convo_count": len(active_convos),
        "leo_sep_oct_count": len(leo_sep_oct),
        "leo_sep_oct_rate": f"{len(leo_sep_oct)} of {total} ({round(len(leo_sep_oct) / denom * 100, 1)}%)",
        "followup_queue_count": len(followup_queue),
        "decks_sent_count": len(decks_sent),
        "decks_sent_rate": f"{len(decks_sent)} of {total} ({round(len(decks_sent) / denom * 100, 1)}%)",
        "decks_opened_count": len(decks_opened),
        "decks_opened_rate": f"{len(decks_opened)} of {total} ({round(len(decks_opened) / denom * 100, 1)}%)",
        "tier_sa_followup_count": len(tier_sa_followup),
        "tier_sa_followup_rate": f"{len(tier_sa_followup)} of {len(tier_s) + len(tier_a)} ({round(len(tier_sa_followup) / max(1, len(tier_s) + len(tier_a)) * 100, 1)}%)",
    }


def build_executive_vc_report(rows: list[dict] = None) -> dict:
    """Build the comprehensive 'Who Is the Right VC for Dokimo?' Research Report (Right VCs Only, Deduplicated)."""
    rows = rows if rows is not None else get_all_investors(persist_csv=False)
    metrics = build_summary_metrics(rows)
    tier_s = [r for r in rows if r["tier"] == "S"]
    tier_a = [r for r in rows if r["tier"] == "A"]
    tier_b = [r for r in rows if r["tier"] == "B"]

    fintech_seed_leads = [
        r for r in tier_s
        if any(k in (r["fund"] + " " + r["category"]).lower() for k in ["ludwig", "valuestream", "vestigo", "restive", "legaltech", "sixthirty", "work-bench", "luge", "commerce", "fintech", "anthemis", "ejf", "information venture", "ttv"])
    ]
    ai_cyber_seed_leads = [
        r for r in tier_s
        if r not in fintech_seed_leads
    ]

    return {
        "ok": True,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%d %b %Y %H:%M UTC"),
        "metrics": metrics,
        "executive_thesis": (
            f"All Wrong/Hardware VCs, non-US regional mandate traps (Balderton, Dawn, Notion, Hoxton, Round13), changed/inactive firms (Hummer Winblad), "
            f"hard passes (Khosla), and duplicate partner entries have been eliminated. Across the {metrics['total_investors']} deduplicated RIGHT VCs for Dokimo, "
            f"{metrics['tier_s_rate']} are Tier-S True Pre-Seed & Early-Seed Check-Writers ($500K–$4M before $1M ARR — PITCH NOW), "
            f"{metrics['tier_a_rate']} are Tier-A Warm-Intro & Strategic Bank CVCs (Citigroup Ventures, PruVen, Canapi, Illuminate, Capital One, Amex), "
            f"and {metrics['tier_b_rate']} are Tier-B Series-A / Multistage funds (Motive Partners, NYCA, Thomson Reuters Ventures, QED, Ribbit, Bain) held until $1M ARR / 3+ paying bank logos."
        ),
        "wave1_bank_lp_and_strategics": fintech_seed_leads[:15],
        "wave2_fintech_regtech_leads": ai_cyber_seed_leads[:18],
        "wave3_enterprise_ai_leads": tier_a[:22],
        "deprioritize_hardware_funds": tier_b[:20],
    }

