from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from compliance_engine import ComplianceEngine
from config import Config
from database import Database
from langgraph.checkpoint.memory import MemorySaver
from langgraph_compliance.graph import build_compliance_graph
from langgraph_compliance.nodes import GraphDeps
from pdf_highlighter import PDFHighlighter
from vectorizer import Vectorizer

logger = logging.getLogger(__name__)


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LangGraphComplianceRunner:
    """
    LangGraph orchestration for invoice compliance.
    Reuses ComplianceEngine retrieval/evaluation math and PDF/S3 flow.
    """

    def __init__(self, db: Database, vectorizer: Vectorizer):
        self.db = db
        self.vectorizer = vectorizer
        self.engine = ComplianceEngine(db=db, vectorizer=vectorizer)
        self.pdf_highlighter = PDFHighlighter()
        self.checkpointer = MemorySaver()
        self.graph = build_compliance_graph(
            GraphDeps(db=db, vectorizer=vectorizer, engine=self.engine),
            checkpointer=self.checkpointer,
        )

    def analyze_invoice(
        self,
        invoice_db_id: int,
        *,
        enable_web: bool = False,
        persist: bool = True,
        thread_id: Optional[str] = None,
    ) -> dict[str, Any]:
        tid = thread_id or str(uuid.uuid4())
        initial: dict[str, Any] = {
            "invoice_db_id": invoice_db_id,
            "enable_web": enable_web,
            "trace": [],
            "errors": [],
        }
        config: dict[str, Any] = {"configurable": {"thread_id": tid}}
        final = self.graph.invoke(initial, config)

        if final.get("safety_blocked"):
            return {
                "engine": "langgraph",
                "thread_id": tid,
                "status": "halted",
                "errors": final.get("errors") or [],
                "decision_narrative": final.get("decision_narrative"),
                "evidence_pack": final.get("evidence_pack"),
                "trace": final.get("trace") or [],
                "workflow_metadata": final.get("workflow_metadata"),
            }

        invoice = final["invoice"]
        violations = final.get("violations") or []
        pricing_rules = final.get("pricing_rules") or {}
        clause_references = final.get("clause_references") or []
        no_contracts_found = len(final.get("contract_contexts") or []) == 0

        processed_at = _utc_iso_z()
        next_run_at = datetime.now(timezone.utc) + timedelta(
            hours=self.engine.next_run_interval_hours
        )
        risk = final.get("risk_assessment_score")

        report: dict[str, Any] = {
            "engine": "langgraph",
            "thread_id": tid,
            "invoice_id": invoice.get("invoice_id"),
            "status": "processed",
            "processed_at": processed_at,
            "violations": violations,
            "evaluation_summary": final.get("evaluation_summary") or {},
            "line_item_source": final.get("line_item_source"),
            "contract_clauses": clause_references,
            "pricing_rules": pricing_rules,
            "risk_assessment_score": risk,
            "next_run_scheduled_in_hours": self.engine.next_run_interval_hours,
            "trace": final.get("trace") or [],
            "evidence_pack": final.get("evidence_pack"),
            "decision_narrative": final.get("decision_narrative"),
            "workflow_metadata": final.get("workflow_metadata") or {},
            "safety_flags": final.get("safety_flags") or [],
            "rule_actions": final.get("rule_actions") or [],
            "action_validation": final.get("action_validation") or {},
            "langchain_tools": {
                "names": ["search_public_web", "fetch_public_url"],
                "note": "Exposed for operator/LLM use; this pipeline calls search programmatically when enable_web=true.",
            },
        }

        llm_metadata = {
            "contract_clauses": clause_references,
            "langgraph_trace_steps": [
                t.get("step") for t in (final.get("trace") or []) if isinstance(t, dict)
            ],
            "external_evidence": (final.get("evidence_pack") or {}).get(
                "external_evidence"
            ),
            "rule_actions": final.get("rule_actions"),
        }

        if persist:
            self.db.save_compliance_report(
                invoice_db_id=invoice.get("id"),
                invoice_number=invoice.get("invoice_id"),
                status="processed",
                violations=violations,
                pricing_rules=pricing_rules,
                llm_metadata=llm_metadata,
                next_run_at=next_run_at,
                risk_assessment_score=risk,
            )
            self.db.update_invoice_compliance_metadata(
                invoice_db_id=invoice.get("id"),
                status="processed",
                risk_assessment_score=risk,
            )

        s3_url = None
        try:
            s3_key = self.db.get_invoice_s3_key(invoice.get("id"))
            if s3_key:
                if no_contracts_found:
                    s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
                else:
                    s3_url = self.pdf_highlighter.process_invoice_pdf(
                        s3_key=s3_key,
                        violations=violations,
                    )
                    if not s3_url:
                        s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
        except Exception as exc:
            logger.error("LangGraph PDF/S3 step failed: %s", exc, exc_info=True)
            try:
                s3_key = self.db.get_invoice_s3_key(invoice.get("id"))
                if s3_key:
                    s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
            except Exception:
                pass

        if s3_url:
            report["s3_url"] = s3_url

        return report
