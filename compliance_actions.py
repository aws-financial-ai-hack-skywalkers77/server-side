"""Template-based recommended actions for violations (operational, not legal advice)."""

from typing import List, Optional


def recommended_actions_for_violation(
    violation_type: str,
    difference: float,
    clause_reference: Optional[str],
) -> List[str]:
    """
    Deterministic suggestions for AP / procurement follow-up.
    """
    vt = (violation_type or "").lower()
    actions: List[str] = [
        "Hold or queue this invoice for human review before payment release.",
        "Compare the billed line to the cited contract section in the source agreement.",
    ]
    if clause_reference:
        actions.append(
            f"Reference the contract position '{clause_reference}' when contacting the vendor."
        )
    if difference and difference > 500:
        actions.append(
            "Given the material overage, consider escalating to procurement or legal per your internal policy."
        )
    if "cap" in vt or "exceed" in vt:
        actions.append(
            "Request a revised invoice or credit memo if the charge exceeds the agreed cap."
        )
    if "mobilization" in vt or "surcharge" in vt:
        actions.append(
            "Verify whether surcharges were pre-approved and documented on the purchase order."
        )
    actions.append(
        "This list is operational guidance only; it is not legal advice."
    )
    return actions
