from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class LangGraphAnalyzeRequest(BaseModel):
    enable_web: bool = Field(
        default=False,
        description="If true, runs DuckDuckGo search hits (requires LANGGRAPH_WEB_ENABLED=true on server).",
    )
    persist: bool = Field(
        default=True,
        description="Persist compliance report and update invoice metadata (same tables as classic engine).",
    )
    thread_id: Optional[str] = Field(
        default=None,
        description="Optional LangGraph checkpoint thread id for audit replay.",
    )


@router.get("/health")
async def langgraph_health():
    return {"status": "ok", "engine": "langgraph"}


@router.get("/capabilities")
async def langgraph_capabilities():
    return {
        "traceability": {
            "append_only_trace": True,
            "per_step_digests": True,
            "thread_checkpointing": "in_memory",
        },
        "correctness": {
            "deterministic_price_engine": "compliance_engine._evaluate_invoice",
            "risk_score": "compliance_engine._calculate_risk_assessment_score",
            "action_schema_validation": True,
        },
        "rule_to_action": {
            "translation_model": "gemini_via_vectorizer",
            "action_types": [
                "cap_unit_price",
                "cap_line_total",
                "flat_fee",
                "blended_cap",
            ],
        },
        "safety": {
            "https_only_urls": True,
            "optional_domain_allowlist": "LANGGRAPH_WEB_ALLOWLIST",
            "server_master_switch": "LANGGRAPH_WEB_ENABLED",
        },
        "internet_tools": [
            {
                "name": "search_public_web",
                "description": "DuckDuckGo text search; HTTPS results only.",
            },
            {
                "name": "fetch_public_url",
                "description": "GET with byte cap; allowlist enforced when configured.",
            },
        ],
        "extras": [
            "evidence_pack",
            "decision_narrative",
            "GET /langgraph/audit/{thread_id} for checkpoint inspection",
        ],
    }


@router.post("/analyze_invoice/{invoice_db_id}")
async def langgraph_analyze_invoice(
    invoice_db_id: int,
    body: LangGraphAnalyzeRequest,
    request: Request,
):
    runner = getattr(request.app.state, "langgraph_runner", None)
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="LangGraph runner not initialized",
        )
    try:
        result = runner.analyze_invoice(
            invoice_db_id,
            enable_web=body.enable_web,
            persist=body.persist,
            thread_id=body.thread_id,
        )
    except ValueError as ve:
        msg = str(ve)
        code = 404 if "not found" in msg.lower() else 422
        raise HTTPException(status_code=code, detail=msg)
    except Exception as exc:
        logger.exception("LangGraph analyze failed")
        raise HTTPException(status_code=500, detail=str(exc))

    if result.get("status") == "halted":
        errs = [str(e) for e in (result.get("errors") or [])]
        if any(e.startswith("invoice_not_found:") for e in errs):
            raise HTTPException(
                status_code=404,
                detail=f"Invoice with database ID '{invoice_db_id}' not found",
            )
    return result


@router.get("/audit/{thread_id}")
async def langgraph_audit_thread(thread_id: str, request: Request):
    runner = getattr(request.app.state, "langgraph_runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="LangGraph runner not initialized")
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snap = runner.graph.get_state(config)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"No checkpoint: {exc}")
    values = dict(snap.values) if snap.values else {}
    return {
        "thread_id": thread_id,
        "next_nodes": list(snap.next or []),
        "checkpoint_id": getattr(snap, "config", None),
        "state_keys": list(values.keys()),
        "trace_len": len(values.get("trace") or []),
        "invoice_id": (values.get("invoice") or {}).get("invoice_id"),
    }


