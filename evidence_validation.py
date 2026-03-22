"""Validate that model-cited quotes appear in retrieved chunk text (auditability)."""

import re
from typing import Any, Dict, List, Optional, Tuple

from retrieval_chunk import RetrievalChunk


def normalize_for_match(text: str) -> str:
    """Collapse whitespace for robust substring checks."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip()).casefold()


def quote_matches_chunk(quote: str, chunk_text: str) -> bool:
    """Return True if quote appears in chunk (normalized comparison)."""
    if not quote or not chunk_text:
        return False
    nq = normalize_for_match(quote)
    nt = normalize_for_match(chunk_text)
    return len(nq) > 0 and nq in nt


def validate_rule_evidence(
    rule: Dict[str, Any],
    chunks_by_index: Dict[int, RetrievalChunk],
) -> Tuple[bool, Optional[str]]:
    """
    Validate evidence_quotes on a single rule.
    Returns (ok, failure_reason).
    """
    quotes = rule.get("evidence_quotes")
    if not quotes or not isinstance(quotes, list):
        return False, "missing_evidence_quotes"

    for q in quotes:
        if not isinstance(q, dict):
            return False, "invalid_evidence_quote_shape"
        try:
            idx = int(q.get("chunk_index"))
        except (TypeError, ValueError):
            return False, "bad_chunk_index"
        verbatim = q.get("verbatim_quote") or q.get("quote") or ""
        if not isinstance(verbatim, str) or not verbatim.strip():
            return False, "empty_verbatim_quote"

        chunk = chunks_by_index.get(idx)
        if chunk is None:
            return False, "chunk_index_out_of_range"

        if not quote_matches_chunk(verbatim, chunk.text):
            return False, "quote_not_found_in_chunk"

    return True, None


def partition_rules_by_evidence(
    rules: List[Dict[str, Any]],
    chunks: List[RetrievalChunk],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Split rules into validated vs rejected with reasons.
    """
    chunks_by_index = {c.chunk_index: c for c in chunks}
    validated: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for rule in rules:
        if not isinstance(rule, dict):
            rejected.append({"rule": rule, "reason": "not_a_dict"})
            continue
        ok, reason = validate_rule_evidence(rule, chunks_by_index)
        if ok:
            validated.append(rule)
        else:
            rejected.append({"rule": rule, "reason": reason or "unknown"})

    return validated, rejected
