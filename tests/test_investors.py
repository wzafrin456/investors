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
        self.assertEqual(total, 213)
        self.assertEqual(
            total,
            metrics["tier_s_count"] + metrics["tier_a_count"] + metrics["tier_b_count"] + metrics["tier_c_count"],
        )

        # Verify 100% enrichment of partner emails and LinkedIn URLs across all 213 rows
        self.assertEqual(metrics["with_email_count"], 213)
        self.assertEqual(metrics["with_email_rate"], "213 of 213 (100.0%)")
        self.assertEqual(metrics["with_linkedin_count"], 213)
        self.assertEqual(metrics["with_linkedin_rate"], "213 of 213 (100.0%)")

        # Verify every rate includes its denominator
        for k in ["tier_s_rate", "tier_a_rate", "tier_b_rate", "tier_c_rate", "with_email_rate", "with_linkedin_rate", "with_phone_rate"]:
            self.assertIn(f"of {total}", metrics[k])

        # Verify 2-page PDF VC Tear-Sheet generation
        pdf_bytes, fname = pdf_memo.generate_investor_tearsheet_pdf(rows[0])
        self.assertTrue(pdf_bytes.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Count 2", pdf_bytes)
        self.assertTrue(fname.endswith(".pdf"))

        # Verify Daily & Weekly Investor Pipeline Digest payload
        dig_daily = investor_digest.build_digest_payload(mode="daily")
        self.assertTrue(dig_daily["ok"])
        self.assertIn("213 of 213 (100.0%)", dig_daily["html_body"])
        self.assertGreater(len(dig_daily["warren_queue"]), 5)
        self.assertGreater(len(dig_daily["leo_queue"]), 5)

        # Verify top bullseye investors are ranked in Tier S
        by_fund = {r["fund"].lower(): r for r in rows}
        self.assertEqual(by_fund["ludwig advisors"]["tier"], "S")
        self.assertEqual(by_fund["canapi ventures"]["tier"], "S")
        self.assertEqual(by_fund["ribbit capital"]["tier"], "S")
        self.assertEqual(by_fund["illuminate financial"]["tier"], "S")
        self.assertEqual(by_fund["citigroup ventures"]["tier"], "S")

        # Verify semiconductor/hardware funds from AINekko/Veevx are separated into Tier C
        self.assertEqual(by_fund["tenstorrent"]["tier"], "C")
        self.assertEqual(by_fund["tdk ventures"]["tier"], "C")

        # Verify status update & persistence
        top_id = rows[0]["id"]
        upd = investor_engine.update_investor_status(top_id, latest_status="Warm Intro Requested", comment="Priority #1", updated_by="Warren")
        self.assertTrue(upd["ok"])
        self.assertEqual(upd["investor"]["latest_status"], "Warm Intro Requested")
        # Reset
        investor_engine.update_investor_status(top_id, latest_status="Not Contacted", comment="", updated_by="Warren")

        # Verify Gemini memo & strategist fallback/synthesis
        memo_res = gemini_vc.research_investor_with_gemini(top_id)
        self.assertTrue(memo_res["ok"])
        self.assertGreater(len(memo_res["memo"]), 100)

        chat_res = gemini_vc.ask_gemini_vc_strategist("Who are the top bank-LP VCs?")
        self.assertTrue(chat_res["ok"])
        self.assertGreater(len(chat_res["answer"]), 100)

        # Verify token authentication for Warren and Leo
        self.assertIsNotNone(access.verify_token("Ot6KUqBPu8WPOB9f7bjIWsNh03kiblX5"))
        self.assertIsNotNone(access.verify_token("L9kPqR7sTuVwXyZ0123456789AbCdEfG"))


if __name__ == "__main__":
    unittest.main()
