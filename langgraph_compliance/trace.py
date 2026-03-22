from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json_digest(obj: Any, max_chars: int = 256) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, default=str)
    except TypeError:
        raw = str(obj)
    if len(raw) > max_chars:
        raw = raw[:max_chars]
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def trace_step(
    step: str,
    detail: str,
    *,
    inputs: Mapping[str, Any] | None = None,
    outputs: Mapping[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """One append-only audit record for traceability."""
    return {
        "ts": _utc_now_iso(),
        "step": step,
        "detail": detail,
        "inputs_digest": _stable_json_digest(inputs or {}),
        "outputs_digest": _stable_json_digest(outputs or {}),
        "evidence_refs": list(evidence_refs or []),
    }
