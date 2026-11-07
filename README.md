# Dokimo.ai — Investor Watch & Stage-Gated VC Fit Board (`vc`)

Live Short Cloud Run URL: **`https://vc-aigeqnv5nq-uc.a.run.app`** *(legacy alias: `https://dokimo-investors-aigeqnv5nq-uc.a.run.app`)*

---

## 1. Access & 1-Click Google Gmail Authentication (Zero Token Hassle)

- **Strictly Restricted to Two Users**:
  1. **Warren Zafrin** (`warren@dokimo.ai`)
  2. **Leo Spiegel** (`leo@dokimo.ai` / `leo@s22t.vc` / `leo@spiegelcapital.com`)
- **1-Click Google Gmail Workspace Sign-In (`/login` → `POST /auth/google`)**:
  - Click **`Continue with Google Gmail — warren@dokimo.ai`** or **`Continue with Google Gmail — leo@dokimo.ai`** on `/login`.
  - Sets a **365-day (`SESSION_TTL = 86400 * 365`) persistent `HttpOnly; Secure` session cookie** so you never have to re-enter or manage tokens.
- **Leo's Personal Laptop / Email Direct Access**:
  - One-click bookmark link: `https://vc-aigeqnv5nq-uc.a.run.app/?t=leo` *(or `?t=leo2026`)*
  - Or enter short code `leo2026` (or `l9kpqr7stuvwxyz0123456789abcdefg`) on `/login`.

---

## 2. Outbound Email Senders & Tracked 18-Slide Pitch Deck + Video

- **Authorized Outbound Senders**: Investor emails are sent **exclusively** from **Warren Zafrin (`warren@dokimo.ai`)** or **Leo Spiegel (`leo@dokimo.ai`)**.
- **Two-Mode Email Composer (in Every VC Modal)**:
  1. **Teaser Email Only (Default — No Deck)**: Crisp institutional thesis hook tailored to the VC's portfolio + Bank-LP network value + 15-minute calendar link.
  2. **Include 18-Slide Pitch Deck Link + Video (`include_pitch_deck = true`)**: Appends the tracked `/deck?inv=<id>` link (hosting the 3-minute executive pitch video + embedded 18-slide `$4M` Seed Deck) and optionally attaches `Dokimo_Pitch.pdf` (`8.2 MB`) directly to the email or `.eml` draft.
- **Live Pixel & Deck Telemetry**:
  - `/t/o/<inv_id>.gif` records email opens, unique openers (by IP + User-Agent fingerprint), and partner forwards (multiple distinct openers or `3+` opens).
  - `/deck?inv=<inv_id>` and `/deck/pdf?inv=<inv_id>` record live 18-slide deck views and PDF downloads.

---

## 3. Interactive Bar-Chart Telemetry (`/` Tab 2 & `/telemetry`) — Click Any Bar to Pull Up the VCs

The Investor Board telemetry view mirrors the Prospecting Board's visual bar-chart architecture with **6 interactive bar-chart panels**:

1. **Daily Activity by Region (Last 7 Days)**: `🇺🇸 US`, `🇬🇧 UK`, `🇪🇺 EU`, `🇮🇱/🇺🇸 Israel-US` across `📨 Sent`, `👁️ Opens`, `👤 Distinct Opener VCs`, and `📊 Deck Views / Forwards`.
2. **Daily Activity by Stage & Tier (Last 7 Days)**: `🌱 Pre-Seed / Day-0`, `Tier S (Bullseye)`, `Tier A (Enterprise AI)`, `Tier B` across all 4 metrics.
3. **Weekly Activity by Region (4-Week Cohort Window)**: `Sep/Oct Wave 1`, `Oct W3`, `Oct W4`, `Nov W1 (Current)`.
4. **Weekly Activity by Stage & Tier (4-Week Cohort Window)**: Weekly progression by VC stage and fit tier.
5. **Sender Comparison — Warren (`warren@dokimo.ai`) vs. Leo (`leo@dokimo.ai`)**: Daily & weekly sends, opens, distinct openers, and deck/forward events by sender.
6. **Every-AM Follow-Up & Rotation Schedule**: Live breakdown of `🔥 Hot Engaged`, `🔁 Day +4 Follow-Up Due`, `🔄 Day +7 Partner Rotation`, and `⏸️ Agent Paused`.

### Interactive Bar Drilldown (`#inv-chart-drilldown-panel`)
- **Click any vertical bar or legend pill** in any of the 5 charts to open the **Drilldown Table** directly above the charts showing the exact VCs in that bar (Rank, Tier, Pre-Seed flag, Fund, Partner, Email, Phone, Region, Sent By, Opens, Deck Views, Forwards, Status).
- Inside the drilldown table:
  - Click **`✉️ Open VC & Email/Deck Modal`** to open the full 5-Section IC Deep Research & Email Composer modal for that VC.
  - Click **`🔍 Jump to Row`** to switch to Tab 1 and highlight that VC on the main board.

---

## 4. Every-AM `5-Each` 2-Way Round-Robin Follow-Up & Rotation Engine (`/` Tab 3)

Matches the exact rationale, timing, and round-robin logic of the Prospecting Board:

- **Every Morning (`06:30 AM ET`) `5-Each` Assignment (`10 VCs/Day Total`)**:
  - Ranks all active VCs by live engagement (`Partner Forwards -> Deck Views -> Email Opens -> Pre-Seed / Tier-S Priority`) and assigns **10 VCs every morning**:
    - **Warren Zafrin (`warren@dokimo.ai`)**: **5 VCs**
    - **Leo Spiegel (`leo@dokimo.ai`)**: **5 VCs**
- **3-Stage Automated Follow-Up & Rotation Lifecycle**:
  - **`Day 0` (Step 1 Sent)**: Initial founder teaser or warm intro sent by Warren or Leo.
  - **`Day +4` (`🔁 Step-2 Follow-Up Due`)**: If no reply after 4 days (or immediately upon multi-open / forward signal), surfaces in the morning 5-each queue with the tracked 18-slide `$4M` Seed Deck + 3-minute walkthrough video.
  - **`Day +7` (`🔄 1-Week Partner / Warm-Intro Rotation`)**: If `0` opens after 7 days, rotates to a secondary GP/Partner at the same fund or switches the intro path between Warren and Leo.
  - **`Day +42` (`🛑 6-Week Inactive Flag`)**: If `0` opens/replies after 42 days (6 weeks), flags the fund as inactive (`Inactive 6w — Hold`) and rotates in a fresh Tier-S / Pre-Seed VC.
- **1-Click `⏸️ Pause Agent`**:
  - Clicking **`⏸️ Pause Agent`** on any VC immediately stops automated follow-up and rotation reminders while Warren or Leo handles the partner thread manually.
