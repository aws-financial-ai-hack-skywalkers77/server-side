from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict


class ComplianceGraphState(TypedDict, total=False):
    """Shared state for the compliance LangGraph."""

    invoice_db_id: int
    enable_web: bool

    invoice: dict[str, Any]
    line_items: list[dict[str, Any]]
    line_item_source: str

    contract_contexts: list[str]
    web_context_blocks: list[str]
    clause_references: list[dict[str, Any]]
    external_evidence: list[dict[str, Any]]

    pricing_rules: dict[str, Any]
    rule_actions: list[dict[str, Any]]
    action_validation: dict[str, Any]

    violations: list[dict[str, Any]]
    evaluation_summary: dict[str, Any]
    risk_assessment_score: Optional[float]

    safety_flags: list[str]
    safety_blocked: bool

    trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]

    evidence_pack: dict[str, Any]
    decision_narrative: str
    workflow_metadata: dict[str, Any]
