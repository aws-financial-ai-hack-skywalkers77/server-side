# DocuFlow — Contract–invoice compliance API

This service **cross-references invoices against stored contracts** to surface **pricing and policy mismatches**: it retrieves contract text that matches the vendor and invoice semantics, **extracts grounded pricing rules** with explicit evidence, then runs a **deterministic checker** over invoice line items so discrepancies are explainable and actionable—not a black-box score.

Pipeline at a glance: **upload & extract** (Landing AI ADE) → **embed & index** (Gemini + PostgreSQL/pgvector) → **retrieve contract context** → **propose rules** (Gemini, evidence-constrained) → **validate evidence** (code) → **evaluate lines** (code) → **persist report** + optional **highlighted PDF**.

---

## 1. Traceability & evidence

Auditors and product teams need to see *why* a line was flagged and *which contract text* supports it.

- **Tagged retrieval chunks** (`RetrievalChunk`): Every excerpt passed to the rule extractor carries `chunk_index`, `contract_db_id`, `contract_id`, `context_source` (e.g. structured `clauses`, `pricing_sections`, `full_text`, `summary`), similarity, and when available **`clause_id`** (from structured pricing clauses). These fields surface in **`contract_clauses`** on the analyze response and in **`audit_trace.retrieval`**.

- **Evidence-bound rules**: The pricing-rule prompt (`vectorizer.extract_pricing_rules`) requires each rule to include **`evidence_quotes`**: `{ "chunk_index", "verbatim_quote" }` copied from the chunk text. **`evidence_validation`** (`evidence_validation.py`) normalizes whitespace/case and verifies each quote is a **substring of the corresponding chunk**. Rules that fail validation land in **`rejected_rules`** with a reason (e.g. `quote_not_found_in_chunk`, `chunk_index_out_of_range`); only validated rules participate in evaluation.

- **Audit trace**: `audit_trace` bundles retrieval metadata (query text, vendor), per-chunk audit rows (including text previews), clause reference rows, extraction stats (`rules_raw_count`, `validated_rules_count`, rejected-rule summaries), and **line-level evaluation outcomes** so a single response reconstructs the decision path.

- **Clause drill-down**: **`GET /contracts/{contract_db_id}/clause?clause_id=...`** returns the full structured clause object (e.g. `clause_type`, `section_title`, `clause_text`, `page_number`) from the contract’s stored `clauses` JSON—useful when UI shows a `clause_id` from `contract_clauses`.

- **Violations**: Each violation carries **`clause_reference`** (from the matched rule), structured **`reasoning`**, and optional **`pdf_location`** when line metadata includes coordinates—supporting document-level review and highlighting workflows.

---

## 2. Correctness & risk handling

The system separates **interpretation** (LLM, constrained) from **arithmetic and policy checks** (code), and communicates **confidence and failure modes** explicitly.

- **Deterministic evaluation** (`ComplianceEngine._evaluate_invoice`): After rules are validated, matching uses **service code** first, then **keyword scoring** against line descriptions. **Expected vs actual** amounts respect **flat fee**, **unit price**, and **price cap** semantics; **tolerance_amount** and **tolerance_percent** gate whether a positive delta counts as a violation.

- **Review status** (`review_status`): Coarse states include `no_contract_context`, `rule_extraction_failed`, `insufficient_grounded_rules`, `needs_review`, `violation`, and `cleared`—driven by retrieval success, parse/evidence outcomes, rule count, violations, and whether line items were **inferred** from totals.

- **Escalations** (`escalations`): Structured codes such as `NO_CONTRACT`, `LINE_ITEMS_INFERRED`, `PARSE_FAILED`, `RULES_UNGROUNDED`, and `NO_RULES_EXTRACTED` give operators and automations a stable signal without parsing prose.

- **Risk** (`risk_assessment_score`, `risk_tier`): A dedicated score compares payable totals to a “legal max” implied by violations; **`risk_tier`** (`high` / `medium` / `low` / `unknown`) summarizes exposure for dashboards.

- **Retrieval safety**: When a **vendor name** is present, contract hits are filtered so the vendor appears in contract metadata or text—reducing cross-vendor false matches. If **no line items** exist in the database, the engine builds a **single synthetic line** from subtotal/tax (`line_item_source: "inferred"`), completes the workflow, and surfaces that assumption in review/escalations.

- **Outputs**: Analyze responses can include an **`s3_url`** for the invoice PDF (original or violation-aware processing via `PDFHighlighter`), so reviewers open the same artifact the system used.

---

## 3. Rule-to-action translation

Findings are only useful if finance and AP know **what to do next**.

- **`recommended_actions`** (`compliance_actions.recommended_actions_for_violation`): Each violation includes a **deterministic list** of suggested steps—e.g. hold payment pending review, reconcile against the cited contract section, reference **`clause_reference`** in vendor outreach, escalate material overages (e.g. large **`difference`**), and cap/surcharge-specific checks. The module ends with an explicit **non-legal-advice** disclaimer.

- **Violation payload**: Besides amounts, violations expose **`violation_type`**, **`reasoning`** (human-readable explanation plus structured expected/actual/contract requirement), and **`recommended_actions`** so UIs and ticket systems can render workflows without extra heuristics.

- **Escalations → workflows**: Machine-readable **`code`** / **`severity`** / **`message`** objects align with internal playbooks (procurement, legal, vendor master data fixes).

---

## Features (capabilities)

- **Document upload**: PDF invoices and contracts via Landing AI ADE extraction and PostgreSQL persistence (vectors + metadata).
- **Semantic contract search**: pgvector similarity, optional RAG Q&A (`POST /query_contracts`).
- **Compliance automation**: `POST /analyze_invoice/{invoice_db_id}`, batch and bulk variants, latest report retrieval, bulk queue processing for schedulers.
- **REST CRUD-style reads**: Paginated invoices/contracts, PDF URLs, compliance report by invoice.

---

## Setup

### Prerequisites

- Python 3.8+ (or Docker — see [DOCKER.md](DOCKER.md))
- PostgreSQL with **pgvector**
- Landing AI API key
- Google Gemini API key (embeddings + generation)

### Installation

```bash
cd server-side   # or your clone path
pip install -r requirements.txt
cp .env.example .env
```

Configure `.env` (see `.env.example` for full list): database (`DB_*`), `LANDING_AI_API_KEY` / `VISION_AGENT_API_KEY`, `GEMINI_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `GEMINI_GENERATION_MODEL`, upload limits, optional S3/CORS settings.

Tables are created on startup when the app connects to the database.

### Docker quick start

```bash
cp .env.example .env
# edit .env
docker-compose up -d
docker-compose logs -f api
```

Default API base: `http://localhost:8001` (see your `main.py` / compose port mapping).

---

## Running the API

```bash
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8001
```

Interactive docs: **`/docs`** (Swagger).

---

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/upload_document` | Upload PDF; `document_type` = `invoice` or `contract` |
| GET | `/invoices`, `/invoices/{db_id}`, `/invoices/by_invoice_id/{invoice_id}` | List / fetch invoices |
| GET | `/invoices/.../pdf_url`, `/invoices/.../pdf` | Presigned or streamed PDF |
| GET | `/invoices/{invoice_db_id}/compliance_report/latest` | Last stored compliance payload |
| GET | `/contracts`, `/contracts/{db_id}` | List / fetch contract by DB id |
| GET | `/contracts/{contract_db_id}/clause` | Query `clause_id` — full clause JSON |
| POST | `/analyze_invoice/{invoice_db_id}` | Full compliance run (violations, audit trace, risk, clauses, S3 URL) |
| POST | `/analyze_invoices` | Body: `invoice_ids` and/or `invoice_numbers` |
| POST | `/analyze_invoices_bulk` | Optional `limit`; processes pending/outdated queue |
| POST | `/query_contracts` | RAG question over contracts |
| GET | `/health` | Liveness |

### Compliance analyze (example)

```bash
curl -X POST "http://localhost:8001/analyze_invoice/123" -H "Accept: application/json"
```

`123` is `invoices.id`. Response highlights include: `violations`, `evaluation_summary`, `line_evaluations`, `contract_clauses`, `pricing_rules`, `audit_trace`, `review_status`, `escalations`, `risk_assessment_score`, `risk_tier`, `line_item_source`, optional `s3_url`.

---

## Project structure (core modules)

| Module | Role |
|--------|------|
| `main.py` | FastAPI routes |
| `database.py` | PostgreSQL + pgvector, contracts/clauses, compliance persistence |
| `document_processor.py` | Landing AI ADE extraction (invoices & contracts, structured `clauses`) |
| `vectorizer.py` | Embeddings, RAG, pricing-rule JSON + evidence partitioning |
| `evidence_validation.py` | Quote-in-chunk validation, rule accept/reject |
| `compliance_engine.py` | Retrieval, rule extraction orchestration, evaluation, audit trace, risk |
| `compliance_actions.py` | `recommended_actions` templates |
| `retrieval_chunk.py` | Chunk tagging and API reference dicts |
| `pdf_highlighter.py` | Invoice PDF URL / highlighting |

---

## Testing & tooling

```bash
python test_api.py invoice path/to/invoice.pdf
python test_api.py contract path/to/contract.pdf
```

Additional unit tests (e.g. evidence validation): `python -m unittest discover -s tests -p 'test_*.py'` if `pytest` is not installed.

---

## Error handling

Failures are logged and returned with appropriate HTTP status codes (validation, missing resources, upstream extraction/LLM/DB errors). Compliance analysis avoids failing the entire run when optional steps (e.g. PDF URL generation) error; check logs and `escalations` / `review_status` on the report.

---

## Client integration

For upload and analyze flows, use `multipart/form-data` for `/upload_document` and JSON where specified. Long-form React/Axios patterns are easy to derive from the examples above and from **`/docs`**. Keep the API base URL configurable for each environment.
