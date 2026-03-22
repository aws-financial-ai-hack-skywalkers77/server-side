"""Unit tests for evidence validation and rule matching behavior."""
import unittest
from typing import Any, Dict, List, Optional

from evidence_validation import (
    normalize_for_match,
    quote_matches_chunk,
    validate_rule_evidence,
)
from retrieval_chunk import RetrievalChunk


class TestEvidenceValidation(unittest.TestCase):
    def test_normalize_for_match_collapse_whitespace(self):
        self.assertEqual(normalize_for_match("  a   b  "), "a b")

    def test_quote_matches_chunk_substring(self):
        chunk = "The rate shall not exceed $120 per unit for routine work."
        self.assertTrue(quote_matches_chunk("not exceed $120", chunk))
        self.assertFalse(quote_matches_chunk("not in text", chunk))

    def test_validate_rule_evidence_ok(self):
        chunks = {
            0: RetrievalChunk(
                chunk_index=0,
                contract_db_id=1,
                contract_id="C-1",
                text="Cap is $50 per hour.",
                context_source="full_text",
            )
        }
        rule = {
            "keywords": ["hour"],
            "unit_price": 50,
            "evidence_quotes": [{"chunk_index": 0, "verbatim_quote": "Cap is $50 per hour"}],
        }
        ok, reason = validate_rule_evidence(rule, chunks)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_validate_bad_chunk_index(self):
        chunks = {
            0: RetrievalChunk(
                chunk_index=0,
                contract_db_id=1,
                contract_id="C-1",
                text="x",
                context_source="full_text",
            )
        }
        rule = {
            "evidence_quotes": [{"chunk_index": 99, "verbatim_quote": "x"}],
        }
        ok, reason = validate_rule_evidence(rule, chunks)
        self.assertFalse(ok)
        self.assertEqual(reason, "chunk_index_out_of_range")


def _match_rule_no_fallback(
    line_item: Dict[str, Any], rules: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Mirrors ComplianceEngine._match_rule (no unsafe third-pass fallback)."""
    description = (line_item.get("description") or "").lower()
    service_code = (line_item.get("service_code") or "").lower()

    for rule in rules:
        rule_service_code = (rule.get("service_code") or "").lower()
        if rule_service_code and rule_service_code == service_code:
            return rule

    best_match = None
    best_score = 0
    for rule in rules:
        keywords = rule.get("keywords") or []
        if not keywords:
            continue
        normalized_keywords = [
            kw.lower().strip() for kw in keywords if isinstance(kw, str) and kw.strip()
        ]
        if not normalized_keywords:
            continue
        matches = sum(1 for kw in normalized_keywords if kw in description)
        if matches > 0:
            score = matches * 10 + sum(
                len(kw) for kw in normalized_keywords if kw in description
            )
            if score > best_score:
                best_score = score
                best_match = rule

    if best_match:
        return best_match
    return None


class TestMatchRuleNoFallback(unittest.TestCase):
    def test_no_keyword_match_returns_none_even_if_rules_have_prices(self):
        rules = [
            {
                "keywords": [],
                "unit_price": 100,
                "price_cap": None,
                "service_code": "",
            }
        ]
        item = {
            "description": "Completely unrelated line item text",
            "service_code": "",
        }
        self.assertIsNone(_match_rule_no_fallback(item, rules))


if __name__ == "__main__":
    unittest.main()
