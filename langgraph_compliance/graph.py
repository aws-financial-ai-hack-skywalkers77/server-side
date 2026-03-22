from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from langgraph_compliance.nodes import GraphDeps, create_nodes
from langgraph_compliance.state import ComplianceGraphState


def _route_after_ingest(state: ComplianceGraphState) -> str:
    return "halt" if state.get("safety_blocked") else "continue"


def build_compliance_graph(
    deps: GraphDeps,
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    node_map = create_nodes(deps)
    g = StateGraph(ComplianceGraphState)

    for name, fn in node_map.items():
        g.add_node(name, fn)

    g.set_entry_point("ingest_invoice")
    g.add_conditional_edges(
        "ingest_invoice",
        _route_after_ingest,
        {"halt": "halt_blocked", "continue": "safety_gate"},
    )
    g.add_edge("halt_blocked", END)

    g.add_edge("safety_gate", "retrieve_contracts")
    g.add_edge("retrieve_contracts", "web_enrichment")
    g.add_edge("web_enrichment", "extract_pricing_rules")
    g.add_edge("extract_pricing_rules", "translate_rules")
    g.add_edge("translate_rules", "validate_actions")
    g.add_edge("validate_actions", "deterministic_evaluate")
    g.add_edge("deterministic_evaluate", "risk_score")
    g.add_edge("risk_score", "assemble_evidence")
    g.add_edge("assemble_evidence", END)

    return g.compile(checkpointer=checkpointer)
