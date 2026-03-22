# Trust, limits, and human review

## Purpose

Docuflow assists with document extraction, retrieval, and **rule-based checks** against contract text. It is designed to support human review, not to replace legal, compliance, or finance sign-off.

## What the system does

- Stores extracted invoice and contract metadata and embeddings in PostgreSQL.
- Optionally stores original PDFs in AWS S3 when configured.
- Runs a compliance pipeline that **retrieves** contract excerpts, asks a model to extract **structured pricing rules** with **verbatim quotes** validated against those excerpts, then applies **deterministic arithmetic** to compare invoice lines to those rules.
- Returns **audit metadata** (chunk references, model id, rejections, line outcomes) for reviewer verification.

## What the system does not do

- **Legal advice:** Outputs are operational hints only. Interpretation of law and contract language for your jurisdiction is out of scope.
- **Automatic payment decisions:** The service does not approve, reject, or release payments.
- **Guaranteed completeness:** Retrieval may miss the correct agreement; absence of a violation does not prove compliance without human confirmation of the right master contract and data quality.

## Data handling

- Configure database and S3 credentials via environment variables; restrict network access in production.
- Treat uploaded PDFs and extracted fields as sensitive business data.

## Escalation and review

- Reports include `review_status`, `escalations`, and `audit_trace`. Use `needs_review`, `no_contract_context`, `rule_extraction_failed`, or `insufficient_grounded_rules` as signals for manual follow-up.
- RAG answers (`/query_contracts`) are grounded only in **returned excerpts**; verify against full source documents for decisions.

## Operational use

- Prefer explicit human approval workflows before relying on automated flags in production.
