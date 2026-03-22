"""Tagged contract retrieval chunks for audit-grade traceability."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalChunk:
    """One unit of contract text passed to the pricing-rule extractor."""

    chunk_index: int
    contract_db_id: int
    contract_id: Optional[str]
    text: str
    context_source: str  # clauses | pricing_sections | full_text | summary
    similarity: Optional[float] = None
    vendor_name: Optional[str] = None
    service_types: Optional[List[Any]] = None

    def to_reference_dict(self) -> Dict[str, Any]:
        """API-facing clause reference row (backward compatible + new fields)."""
        ref: Dict[str, Any] = {
            "contract_id": self.contract_id,
            "contract_db_id": self.contract_db_id,
            "chunk_index": self.chunk_index,
            "vendor_name": self.vendor_name,
            "similarity": self.similarity,
            "context_source": self.context_source,
            "service_types": self.service_types if self.service_types is not None else [],
        }
        return ref

    def to_audit_dict(self) -> Dict[str, Any]:
        d = self.to_reference_dict()
        d["text_preview"] = (self.text[:240] + "...") if len(self.text) > 240 else self.text
        return d


def chunks_as_context_strings(chunks: List[RetrievalChunk]) -> List[str]:
    return [c.text for c in chunks]
