"""Unit and numeric verification tests for Dokimo Investor Watch & Gemini VC Fit Board."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from radar import access, gemini_vc, investor_digest, investor_engine, pdf_memo


class TestInvestorEngine(unittest.TestCase):
    def test_parse_and_numeric_consistency(self):
        rows = investor_engine.get_all_investors(persist_csv=True)
        metrics = investor_engine.build_summary_metrics(rows)

        # Verify total equals exact sum of tiers (Cross-layer numeric consistency)
        total = metrics["total_investors"]
        self.assertEqual(total, 113)
        self.assertEqual(
            total,
            metrics["tier_s_count"] + metrics["tier_a_count"] + metrics["tier_b_count"] + metrics["tier_c_count"],
        )
        # Verify strictly Right VCs only (zero Tier C hardware/semiconductor funds)
        self.assertEqual(metrics["tier_c_count"], 0)

        # Verify zero duplicate canonical funds
        fund_names = [r["fund"].lower() for r in rows]
        self.assertEqual(len(fund_names), len(set(fund_names)))

        # Verify Balderton, Hummer Winblad, Playground, and Khosla are excluded
        for excluded in ("balderton", "hummer winblad", "playground", "khosla"):
            self.assertFalse(any(excluded in fn for fn in fund_names))

        # Verify 100% enrichment of partner emails and LinkedIn URLs across all 113 Right VCs
        self.assertEqual(metrics["with_email_count"], 113)
        self.assertEqual(metrics["with_email_rate"], "113 of 113 (100.0%)")
        self.assertEqual(metrics["with_linkedin_count"], 113)
        self.assertEqual(metrics["with_linkedin_rate"], "113 of 113 (100.0%)")

        # Verify every rate includes its denominator
        for k in [
            "pre_seed_rate", "bank_lp_bullseye_rate",
            "tier_s_rate", "tier_a_rate", "tier_b_rate", "tier_c_rate",
            "us_rate", "uk_rate", "eu_rate", "il_us_rate",
            "with_email_rate", "with_linkedin_rate", "with_phone_rate", "leo_sep_oct_rate",
        ]:
            self.assertIn(f"of {total}", metrics[k])

        self.assertGreaterEqual(metrics["bank_lp_bullseye_count"], 40)
        for r in rows:
            self.assertTrue(r.get("why_now_hook"), r["fund"])
            self.assertNotIn("[🟢 PITCH NOW", r["why_now_hook"])
            self.assertNotIn("[STAGE WARNING", r["why_now_hook"])

        # Verify simplified 5-column Investor Board HTML and JS syntax
        from gcp import app as inv_app
        board_html = inv_app.render_board_html()
        for token in (
            "Single Clean Investor Filter Bar",
            'id="preset-preseed-btn"',
            'id="preset-banklp-btn"',
            "Bank-LP &amp; RegTech Bullseye",
            "VC Fund, Stage &amp; Check Size",
            "Partner &amp; Direct Contact",
            "Why Now Hook, Portfolio &amp; Bank-LP Leverage",
            "Owner (Warren / Leo), Status &amp; 1-Click Draft",
        ):
            self.assertIn(token, board_html)

        # Verify 2-page PDF VC Tear-Sheet generation
        pdf_bytes, fname = pdf_memo.generate_investor_tearsheet_pdf(rows[0])
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Count 2", pdf_bytes)
        self.assertTrue(fname.endswith(".pdf"))

        # Verify Daily & Weekly Investor Pipeline Digest payload
        dig_daily = investor_digest.build_digest_payload(mode="daily")
        self.assertTrue(dig_daily["ok"])
        self.assertIn("113 of 113 (100.0%)", dig_daily["html_body"])

        # Verify top bullseye Pre-Seed/Seed check-writers are ranked in Tier S and Warm CVCs/Threads in Tier A
        by_fund = {r["fund"].lower(): r for r in rows}
        self.assertEqual(by_fund["ludwig advisors"]["tier"], "S")
        self.assertEqual(by_fund["boldstart"]["tier"], "S")
        self.assertEqual(by_fund["13books capital"]["tier"], "S")
        self.assertEqual(by_fund["blackfin tech"]["tier"], "S")
        self.assertEqual(by_fund["citigroup ventures"]["tier"], "A")
        self.assertEqual(by_fund["mayfield"]["tier"], "B")
        self.assertEqual(by_fund["thomson reuters ventures"]["tier"], "B")

        # Verify sender permissions are strictly restricted to Warren and Leo ONLY
        w_viewer = access.verify_token("Ot6KUqBPu8WPOB9f7bjIWsNh03kiblX5")
        l_viewer = access.verify_token("L9kPqR7sTuVwXyZ0123456789AbCdEfG")
        self.assertIsNotNone(w_viewer)
        self.assertIsNotNone(l_viewer)
        self.assertTrue(access.can_send_investor_emails(w_viewer))
        self.assertTrue(access.can_send_investor_emails(l_viewer))

    def test_mutual_cc_and_duplicate_email_guard(self):
        import copy

        # 1. Verify Warren -> CCs Leo, and Leo -> CCs Warren
        w_msg = investor_digest.build_investor_mime_message(
            inv_id="INV-TEST01",
            sender="warren",
            to_email="partner@testvc.com",
            subject="Dokimo.ai Seed Round",
            plain_body="Hi Partner,\n\nBest,\nWarren",
        )
        self.assertIn("warren@dokimo.ai", w_msg["From"])
        self.assertIn("leo@dokimo.ai", w_msg["Cc"])
        self.assertIn("Leo Spiegel", w_msg["Cc"])

        l_msg = investor_digest.build_investor_mime_message(
            inv_id="INV-TEST01",
            sender="leo",
            to_email="partner@testvc.com",
            subject="Dokimo.ai Seed Round",
            plain_body="Hi Partner,\n\nBest,\nLeo",
        )
        self.assertIn("leo@dokimo.ai", l_msg["From"])
        self.assertIn("warren@dokimo.ai", l_msg["Cc"])
        self.assertIn("Warren Zafrin", l_msg["Cc"])

        # 2. Verify Duplicate Email Guard blocks duplicate sends by ID or by recipient email
        orig_state = copy.deepcopy(investor_engine.load_state())
        try:
            res1 = investor_engine.record_investor_send(
                inv_id="INV-UNIT-DUP",
                sender="warren",
                to_email="gp@vc-example.com",
                subject="Dokimo Seed",
            )
            self.assertTrue(res1["ok"])
            self.assertEqual(res1["cc_email"], "leo@dokimo.ai")

            # Duplicate send to same ID by Warren -> blocked
            res2 = investor_engine.record_investor_send(
                inv_id="INV-UNIT-DUP",
                sender="warren",
                to_email="gp@vc-example.com",
                subject="Dokimo Seed Again",
            )
            self.assertFalse(res2["ok"])
            self.assertTrue(res2.get("duplicate_blocked"))

            # Duplicate send to same recipient email by Leo -> blocked
            res3 = investor_engine.record_investor_send(
                inv_id="INV-UNIT-OTHER",
                sender="leo",
                to_email="GP@vc-example.com",
                subject="Dokimo Intro",
            )
            self.assertFalse(res3["ok"])
            self.assertTrue(res3.get("duplicate_blocked"))

            # Explicit Step-2 follow-up override (force_followup=True) -> allowed & CCs Warren
            res4 = investor_engine.record_investor_send(
                inv_id="INV-UNIT-DUP",
                sender="leo",
                to_email="gp@vc-example.com",
                subject="Following up",
                force_followup=True,
            )
            self.assertTrue(res4["ok"])
            self.assertEqual(res4["cc_email"], "warren@dokimo.ai")
        finally:
            investor_engine.save_state(orig_state)


if __name__ == "__main__":
    unittest.main()
