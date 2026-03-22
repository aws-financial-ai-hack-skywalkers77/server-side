from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from compliance_engine import ComplianceEngine
from config import Config
from database import Database
from langgraph_compliance.internet_tools import internet_search
from langgraph_compliance.llm_helpers import (
    translate_pricing_rules_to_actions,
    workflow_decision_narrative,
)
from langgraph_compliance.state import ComplianceGraphState
from langgraph_compliance.trace import trace_step
from vectorizer import Vectorizer

logger = logging.getLogger(__name__)

ALLOWED_ACTION_TYPES = frozenset(
    {"cap_unit_price", "cap_line_total", "flat_fee", "blended_cap"}
)


@dataclass
class GraphDeps:
    db: Database
    vectorizer: Vectorizer
    engine: ComplianceEngine


def create_nodes(deps: GraphDeps) -> dict[str, Callable[[ComplianceGraphState], dict[str, Any]]]:
    db = deps.db
    vectorizer = deps.vectorizer
    engine = deps.engine

    def ingest_invoice(state: ComplianceGraphState) -> dict[str, Any]:
        iid = state["invoice_db_id"]
        invoice = db.get_invoice_with_line_items(iid, identifier_is_db_id=True)
        if not invoice:
            return {
                "safety_blocked": True,
                "errors": [f"invoice_not_found:{iid}"],
                "trace": [
                    trace_step(
                        "ingest_invoice",
                        "blocked_missing_invoice",
                        inputs={"invoice_db_id": iid},
                    )
                ],
            }
        line_items = invoice.get("line_items") or []
        source = "stored"
        if not line_items:
            line_items = engine._build_fallback_line_items(invoice)
            source = "inferred"
        inv = dict(invoice)
        inv["line_items"] = line_items
        return {
            "invoice": inv,
            "line_items": line_items,
            "line_item_source": source,
            "contract_contexts": [],
            "web_context_blocks": [],
            "clause_references": [],
            "external_evidence": [],
            "safety_blocked": False,
            "trace": [
                trace_step(
                    "ingest_invoice",
                    "loaded_invoice_and_line_items",
                    inputs={"invoice_db_id": iid},
                    outputs={
                        "invoice_id": inv.get("invoice_id"),
                        "line_items": len(line_items),
                        "line_item_source": source,
                    },
                )
            ],
        }

    def safety_gate(state: ComplianceGraphState) -> dict[str, Any]:
        flags: list[str] = []
        enable_web = bool(state.get("enable_web"))
        if enable_web and not Config.LANGGRAPH_WEB_ENABLED:
            enable_web = False
            flags.append("web_disabled_by_server_policy")
        if enable_web and not Config.LANGGRAPH_WEB_ALLOWLIST.strip():
            flags.append("web_allowlist_empty_public_fetch_still_https_only")
        inv = state.get("invoice") or {}
        if not inv.get("seller_name"):
            flags.append("missing_seller_name_retrieval_may_be_broad")
        trace = [
            trace_step(
                "safety_gate",
                "policy_check_complete",
                outputs={"enable_web": enable_web, "flags": flags},
            )
        ]
        out: dict[str, Any] = {"safety_flags": flags, "trace": trace}
        if enable_web != state.get("enable_web"):
            out["enable_web"] = enable_web
        return out

    def retrieve_contracts(state: ComplianceGraphState) -> dict[str, Any]:
        invoice = state["invoice"]
        try:
            contexts, refs = engine._retrieve_contract_context(invoice)
        except Exception as exc:
            logger.exception("retrieve_contracts failed")
            return {
                "contract_contexts": [],
                "clause_references": [],
                "errors": [f"retrieve_failed:{exc}"],
                "trace": [
                    trace_step(
                        "retrieve_contracts",
                        "vector_retrieval_failed",
                        inputs={"invoice_id": invoice.get("invoice_id")},
                        outputs={"error": str(exc)},
                    )
                ],
            }
        return {
            "contract_contexts": list(contexts),
            "clause_references": list(refs),
            "trace": [
                trace_step(
                    "retrieve_contracts",
                    "pgvector_contract_context",
                    inputs={"invoice_id": invoice.get("invoice_id")},
                    outputs={
                        "context_blocks": len(contexts),
                        "references": len(refs),
                    },
                    evidence_refs=[r.get("contract_id") for r in refs if r.get("contract_id")],
                )
            ],
        }

    def web_enrichment(state: ComplianceGraphState) -> dict[str, Any]:
        if not state.get("enable_web"):
            return {
                "trace": [
                    trace_step("web_enrichment", "skipped_disabled", outputs={})
                ]
            }
        invoice = state["invoice"]
        seller = (invoice.get("seller_name") or "").strip()
        summary = (invoice.get("summary") or "").strip()[:200]
        q = f"{seller} {summary} commercial pricing services rate".strip()
        payload = internet_search(q)
        blocks: list[str] = []
        evidence: list[dict[str, Any]] = []
        if not payload.get("ok"):
            return {
                "web_context_blocks": [],
                "trace": [
                    trace_step(
                        "web_enrichment",
                        "search_failed",
                        outputs={"error": payload.get("error")},
                    )
                ],
                "errors": [f"web_search:{payload.get('error')}"],
            }
        for i, r in enumerate(payload.get("results") or [], 1):
            title = r.get("title") or ""
            url = r.get("url") or ""
            snip = r.get("snippet") or ""
            blocks.append(
                f"=== WEB.SOURCE {i} (third_party_snippet, not_a_contract) ===\n"
                f"Title: {title}\nURL: {url}\nSnippet: {snip}\n"
            )
            evidence.append(
                {
                    "kind": "web_search_hit",
                    "title": title,
                    "url": url,
                    "snippet": snip[:500],
                }
            )
        return {
            "web_context_blocks": blocks,
            "external_evidence": list(state.get("external_evidence") or []) + evidence,
            "trace": [
                trace_step(
                    "web_enrichment",
                    "duckduckgo_hits_appended",
                    outputs={"hits": len(blocks), "query": payload.get("query")},
                    evidence_refs=[e.get("url") for e in evidence],
                )
            ],
        }

    def extract_pricing_rules(state: ComplianceGraphState) -> dict[str, Any]:
        invoice = dict(state["invoice"])
        invoice["line_items"] = state["line_items"]
        base_ctx = list(state.get("contract_contexts") or [])
        web = list(state.get("web_context_blocks") or [])
        merged = base_ctx + web
        if web:
            merged = (
                [
                    "NOTE: Following blocks include WEB SNIPPETS. "
                    "They are NOT contractual rates unless a contract clause says so. "
                    "Prefer signed contract text for enforceable caps.\n"
                ]
                + merged
            )
        try:
            pricing_rules = vectorizer.extract_pricing_rules(invoice, merged)
        except Exception as exc:
            logger.exception("extract_pricing_rules failed")
            return {
                "pricing_rules": {"rules": [], "notes": str(exc)},
                "errors": [f"extract_rules:{exc}"],
                "trace": [
                    trace_step(
                        "extract_pricing_rules",
                        "llm_extraction_failed",
                        outputs={"error": str(exc)},
                    )
                ],
            }
        rules = pricing_rules.get("rules") if isinstance(pricing_rules, dict) else []
        nrules = len(rules or [])
        return {
            "pricing_rules": pricing_rules,
            "trace": [
                trace_step(
                    "extract_pricing_rules",
                    "gemini_structured_rules",
                    inputs={"context_blocks": len(merged)},
                    outputs={"rules_extracted": nrules},
                )
            ],
        }

    def translate_rules(state: ComplianceGraphState) -> dict[str, Any]:
        invoice = state["invoice"]
        pricing_rules = state.get("pricing_rules") or {}
        parsed = translate_pricing_rules_to_actions(vectorizer, invoice, pricing_rules)
        actions = parsed.get("actions") or []
        if not isinstance(actions, list):
            actions = []
        return {
            "rule_actions": actions,
            "trace": [
                trace_step(
                    "translate_rules",
                    "rule_to_action_translation",
                    outputs={"actions": len(actions)},
                )
            ],
        }

    def validate_actions(state: ComplianceGraphState) -> dict[str, Any]:
        rules = (state.get("pricing_rules") or {}).get("rules") or []
        actions = state.get("rule_actions") or []
        issues: list[dict[str, Any]] = []
        for a in actions:
            if not isinstance(a, dict):
                issues.append({"issue": "action_not_object"})
                continue
            aid = a.get("id")
            if a.get("type") not in ALLOWED_ACTION_TYPES:
                issues.append({"action_id": aid, "issue": "invalid_type"})
            ri = a.get("rule_index")
            if not isinstance(ri, int) or ri < 0 or ri >= len(rules):
                issues.append({"action_id": aid, "issue": "rule_index_out_of_range"})
            try:
                c = float(a.get("confidence", 0))
                if c < 0 or c > 1:
                    issues.append({"action_id": aid, "issue": "confidence_range"})
            except (TypeError, ValueError):
                issues.append({"action_id": aid, "issue": "confidence_not_numeric"})
        summary = {
            "ok": len(issues) == 0,
            "issues": issues,
            "actions_count": len(actions),
            "rules_count": len(rules),
        }
        return {
            "action_validation": summary,
            "trace": [
                trace_step(
                    "validate_actions",
                    "schema_and_index_checks",
                    outputs=summary,
                )
            ],
        }

    def deterministic_evaluate(state: ComplianceGraphState) -> dict[str, Any]:
        invoice = dict(state["invoice"])
        invoice["line_items"] = state["line_items"]
        pricing_rules = state.get("pricing_rules") or {"rules": []}
        violations, evaluation_summary = engine._evaluate_invoice(
            invoice, state["line_items"], pricing_rules
        )
        return {
            "violations": violations,
            "evaluation_summary": evaluation_summary,
            "trace": [
                trace_step(
                    "deterministic_evaluate",
                    "numeric_engine_compliance_engine",
                    outputs={
                        "violations": len(violations),
                        **evaluation_summary,
                    },
                )
            ],
        }

    def risk_score(state: ComplianceGraphState) -> dict[str, Any]:
        invoice = dict(state["invoice"])
        invoice["line_items"] = state["line_items"]
        score = engine._calculate_risk_assessment_score(
            invoice, state["line_items"], state.get("violations") or []
        )
        return {
            "risk_assessment_score": score,
            "trace": [
                trace_step(
                    "risk_score",
                    "financial_exposure_index",
                    outputs={"risk_assessment_score": score},
                )
            ],
        }

    def halt_blocked(state: ComplianceGraphState) -> dict[str, Any]:
        return {
            "decision_narrative": "Analysis did not run because the invoice could not be loaded.",
            "evidence_pack": {"halt_reason": "missing_invoice_or_blocked_ingest"},
            "workflow_metadata": {"halted": True},
            "trace": [
                trace_step(
                    "halt_blocked",
                    "workflow_terminated",
                    outputs={"errors": state.get("errors")},
                )
            ],
        }

    def assemble_evidence(state: ComplianceGraphState) -> dict[str, Any]:
        digest_steps = [t.get("step") for t in state.get("trace") or []]
        trace_summary = " -> ".join(digest_steps)
        narrative = workflow_decision_narrative(
            vectorizer,
            state["invoice"],
            state.get("violations") or [],
            trace_summary,
        )
        low_conf = [
            a
            for a in (state.get("rule_actions") or [])
            if isinstance(a, dict)
            and float(a.get("confidence") or 0) < 0.55
        ]
        pack = {
            "contract_clause_references": state.get("clause_references") or [],
            "external_evidence": state.get("external_evidence") or [],
            "pricing_rules": state.get("pricing_rules"),
            "rule_actions": state.get("rule_actions"),
            "action_validation": state.get("action_validation"),
            "correctness_notes": {
                "deterministic_evaluation": True,
                "llm_rules_used_for_extraction_only": True,
                "low_confidence_actions": low_conf,
            },
        }
        return {
            "evidence_pack": pack,
            "decision_narrative": narrative,
            "workflow_metadata": {
                "pipeline": "langgraph_compliance_v1",
                "safety": {
                    "https_only_web": True,
                    "allowlist_configured": bool(Config.LANGGRAPH_WEB_ALLOWLIST.strip()),
                    "server_web_toggle": Config.LANGGRAPH_WEB_ENABLED,
                },
                "trace_steps": digest_steps,
            },
            "trace": [
                trace_step(
                    "assemble_evidence",
                    "narrative_and_evidence_bundle",
                    outputs={"low_confidence_actions": len(low_conf)},
                )
            ],
        }

    return {
        "ingest_invoice": ingest_invoice,
        "halt_blocked": halt_blocked,
        "safety_gate": safety_gate,
        "retrieve_contracts": retrieve_contracts,
        "web_enrichment": web_enrichment,
        "extract_pricing_rules": extract_pricing_rules,
        "translate_rules": translate_rules,
        "validate_actions": validate_actions,
        "deterministic_evaluate": deterministic_evaluate,
        "risk_score": risk_score,
        "assemble_evidence": assemble_evidence,
    }
