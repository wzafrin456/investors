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
            "tier_s_rate", "tier_a_rate", "tier_b_rate", "tier_c_rate",
            "us_rate", "uk_rate", "eu_rate", "il_us_rate",
            "with_email_rate", "with_linkedin_rate", "with_phone_rate", "leo_sep_oct_rate",
        ]:
            self.assertIn(f"of {total}", metrics[k])

        # Verify 18 Sep/Oct Leo & Warren Gmail outreach threads are tracked
        self.assertEqual(metrics["leo_sep_oct_count"], 18)
        self.assertEqual(metrics["leo_sep_oct_rate"], "18 of 113 (15.9%)")

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
        self.assertEqual(by_fund["mayfield"]["tier"], "A")
        self.assertEqual(by_fund["thomson reuters ventures"]["tier"], "B")

        # Verify token authentication is strictly restricted to Warren and Leo ONLY
        self.assertIsNotNone(access.verify_token("Ot6KUqBPu8WPOB9f7bjIWsNh03kiblX5"))
        self.assertIsNotNone(access.verify_token("L9kPqR7sTuVwXyZ0123456789AbCdEfG"))
        # Verify all other team tokens (Esther, Joe, Bernie, Steven, Pat) are rejected
        for revoked_tok in (
            "mIvN8EUUkzg2a_3XRPXV9Ylmwlb4LT-u",
            "-4U1JlMW3CtSpIc8nWXZAB4ezSVeU4yb",
            "bV9kLmN8pQrStUvWxYz0123456789AbC",
            "sG7hJkL2mNpQrStUvWxYz9876543210D",
            "pT4vWxYz1234567890aBcDeFgHiJkLmN",
        ):
            self.assertIsNone(access.verify_token(revoked_tok))
        allowed_ids = {g["id"] for g in access.load_grants()}
        self.assertEqual(allowed_ids, {"warren@dokimo.ai", "leo@dokimo.ai", "leo@s22t.vc"})


if __name__ == "__main__":
    unittest.main()
