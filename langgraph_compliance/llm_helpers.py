from __future__ import annotations

import json
import logging
from typing import Any

from vectorizer import Vectorizer

logger = logging.getLogger(__name__)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


def gemini_json_object(vectorizer: Vectorizer, prompt: str) -> dict[str, Any]:
    model, name = vectorizer._get_generative_model()
    logger.info("LangGraph LLM call model=%s", name)
    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.15, "top_p": 0.9},
        )
    except Exception:
        response = model.generate_content(prompt)
    raw = vectorizer._extract_text_from_response(response)
    return _parse_json_object(raw)


def translate_pricing_rules_to_actions(
    vectorizer: Vectorizer,
    invoice: dict[str, Any],
    pricing_rules: dict[str, Any],
) -> dict[str, Any]:
    """Rule → structured executable action specs (for audit / UI), not the numeric engine."""
    rules = pricing_rules.get("rules") or []
    if not rules:
        return {"actions": [], "notes": "no_rules"}

    inv_id = invoice.get("invoice_id", "")
    seller = invoice.get("seller_name", "")
    prompt = f"""You translate contract-derived pricing rules into explicit compliance actions.

Invoice: {inv_id} vendor={seller}

Rules JSON (array indices matter):
{json.dumps(rules, indent=2)[:12000]}

Return ONLY valid JSON:
{{
  "actions": [
    {{
      "id": "string unique id e.g. A1",
      "rule_index": 0,
      "type": "cap_unit_price | cap_line_total | flat_fee | blended_cap",
      "description": "one sentence what to check on an invoice line",
      "parameters": {{
         "unit_price_max": null,
         "line_total_max": null,
         "flat_fee": null,
         "tolerance_amount": null,
         "tolerance_percent": null,
         "match_keywords": ["optional", "strings"],
         "match_service_code": null
      }},
      "provenance": {{
        "clause_reference": "from rule if any",
        "source": "contract_extraction"
      }},
      "confidence": 0.0
    }}
  ],
  "notes": "short audit note"
}}

Rules:
- type must be one of: cap_unit_price, cap_line_total, flat_fee, blended_cap
- confidence in [0,1] — lower if rule is ambiguous
- parameters must mirror the rule's numbers when present; use null when unknown
"""
    try:
        return gemini_json_object(vectorizer, prompt)
    except Exception as exc:
        logger.exception("translate_pricing_rules_to_actions failed: %s", exc)
        return {"actions": [], "notes": f"translation_failed: {exc}"}


def workflow_decision_narrative(
    vectorizer: Vectorizer,
    invoice: dict[str, Any],
    violations: list[dict[str, Any]],
    trace_summary: str,
) -> str:
    prompt = f"""Write a concise 5-8 sentence compliance officer narrative in plain English.

Invoice: {invoice.get('invoice_id')} vendor={invoice.get('seller_name')}
Violations count: {len(violations)}
Key workflow steps (hashes/digests only, do not invent facts): {trace_summary[:2000]}

If violations list is non-empty, summarize the nature of mismatch (price/cap) without fabricating amounts not shown above.
If zero violations, state that no price-cap breaches were detected under extracted rules.

Do not mention internal system names. No bullet symbols — short paragraphs only.
"""
    try:
        model, _ = vectorizer._get_generative_model()
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.25},
        )
        return vectorizer._extract_text_from_response(response).strip()
    except Exception as exc:
        logger.warning("decision_narrative failed: %s", exc)
        return f"Narrative unavailable: {exc}"
