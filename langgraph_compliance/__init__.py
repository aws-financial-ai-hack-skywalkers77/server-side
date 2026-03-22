"""LangGraph-based invoice compliance workflow (traceability, web tools, safety gates)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph_compliance.runner import LangGraphComplianceRunner

__all__ = ["LangGraphComplianceRunner"]


def __getattr__(name: str):
    if name == "LangGraphComplianceRunner":
        from langgraph_compliance.runner import LangGraphComplianceRunner

        return LangGraphComplianceRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
