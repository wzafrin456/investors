# Dokimo Investor Watch & Gemini VC Fit Intelligence Board

Standalone repository (`/home/warre/investors`) and Google Cloud Run application (`dokimo-investors`) built in the Enforcement-Watch style to research, score, and manage investor outreach across Leo and Warren's 4 consolidated VC & Strategic Investor lists.

## Key Capabilities
1. **Multi-Table Parser & Deduplication (`radar/investor_engine.py`)**:
   - Parses all 4 tables from `data/raw_leo_investors.txt` into a unified, enriched dataset (`data/investors.csv`).
   - Scores every investor (`0–100`) and classifies them into 4 tiers:
     - **Tier S (`92–99`)**: Bullseye FinTech, RegTech, Bank-LP Alliances, Former Regulators, & Strategic Bank CVCs (e.g., Ludwig Advisors, Canapi Ventures, Ribbit Capital, Illuminate Financial, QED Investors, Citi Ventures, Capital One Ventures, Thomson Reuters Ventures, Bain Capital Ventures, Oak HC/FT, Motive Partners, Fin Capital, FinTech Collective, Restive Ventures, NYCA Partners, F-Prime, The LegalTech Fund, Conviction, Work-Bench).
     - **Tier A (`84–91`)**: Tier-1 Enterprise AI, Cyber & B2B Software Lead VCs (Sequoia, Benchmark, a16z, Accel, General Catalyst, Menlo, Lightspeed, Kleiner Perkins, Greylock, Insight, Deviation, Team8, Cyberstarts, Costanoa, SignalFire, FirstMark, Foundation, etc.).
     - **Tier B (`72–83`)**: Selective Frontier / Deep-Tech AI VCs.
     - **Tier C (`42–65`)**: Semiconductor / Silicon / Hardware VCs from Leo's `AINekko` / `Veevx` lists — flagged to deprioritize for Dokimo's software/AI round.
2. **Gemini 2.5 Flash Investor Co-Pilot (`radar/gemini_vc.py`)**:
   - Generates 5-part Investment Committee (IC) Fit Memos, Portfolio Conflict/Synergy Checks, Forwardable Warm-Intro Blurbs for Leo, and Direct Founder Emails for Warren Zafrin.
3. **Cloud Run Application (`gcp/app.py`)**:
   - `/` — Ranked VC Fit & Priority Board
   - `/report` — Executive Research Report: *Who Is the Right VC for Dokimo?*
   - `/outreach` — Leo & Warren Warm-Intro & Direct Outreach Studio
   - `/chat` — Ask Gemini VC Strategist
