import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from compliance_actions import recommended_actions_for_violation
from pdf_highlighter import PDFHighlighter
from retrieval_chunk import RetrievalChunk


def _to_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce DB Decimals, strings, etc. for safe arithmetic (avoid float * Decimal)."""
    if val is None:
        return default
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


class ComplianceEngine:
    """
    Orchestrates invoice compliance analysis by combining vector search (pgvector),
    Gemini-powered RAG interpretation, and deterministic rule enforcement.
    """

    def __init__(
        self,
        db,
        vectorizer,
        clause_limit: int = 5,
        next_run_interval_hours: int = 4,
    ):
        self.db = db
        self.vectorizer = vectorizer
        self.clause_limit = clause_limit
        self.next_run_interval_hours = next_run_interval_hours
        self.logger = logging.getLogger(__name__)
        self.pdf_highlighter = PDFHighlighter()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    def analyze_invoice(self, invoice_db_id: int) -> Dict[str, Any]:
        """
        Run the full compliance workflow for a single invoice.
        """
        invoice = self.db.get_invoice_with_line_items(
            invoice_db_id, identifier_is_db_id=True
        )
        if not invoice:
            raise ValueError(f"Invoice with database ID '{invoice_db_id}' not found")

        line_items = invoice.get("line_items", [])
        line_item_source = "stored"
        if not line_items:
            line_items = self._build_fallback_line_items(invoice)
            line_item_source = "inferred"
        invoice["line_items"] = line_items

        retrieval_chunks, retrieval_meta = self._retrieve_contract_context(invoice)
        no_contracts_found = len(retrieval_chunks) == 0
        clause_references = [c.to_reference_dict() for c in retrieval_chunks]

        if no_contracts_found:
            self.logger.warning(
                "No contract clauses retrieved for invoice '%s'", invoice.get("invoice_id")
            )

        pricing_rules = self._extract_pricing_rules(invoice, retrieval_chunks)
        violations, evaluation_summary, line_evaluations = self._evaluate_invoice(
            invoice, line_items, pricing_rules
        )

        review_status = self._compute_review_status(
            no_contracts_found=no_contracts_found,
            pricing_rules=pricing_rules,
            violations=violations,
            line_item_source=line_item_source,
            line_evaluations=line_evaluations,
        )
        escalations = self._build_escalations(
            no_contracts_found=no_contracts_found,
            line_item_source=line_item_source,
            pricing_rules=pricing_rules,
        )
        audit_trace = self._build_audit_trace(
            retrieval_meta=retrieval_meta,
            retrieval_chunks=retrieval_chunks,
            clause_references=clause_references,
            pricing_rules=pricing_rules,
            line_evaluations=line_evaluations,
        )

        # Calculate risk assessment score
        risk_assessment_score = self._calculate_risk_assessment_score(
            invoice, line_items, violations
        )
        risk_tier = self._risk_tier(risk_assessment_score, violations)

        status = "processed"
        processed_at = datetime.utcnow().isoformat() + "Z"
        next_run_at = datetime.utcnow() + timedelta(hours=self.next_run_interval_hours)

        report = {
            "invoice_id": invoice.get("invoice_id"),
            "invoice_db_id": invoice.get("id"),
            "status": status,
            "review_status": review_status,
            "escalations": escalations,
            "audit_trace": audit_trace,
            "processed_at": processed_at,
            "violations": violations,
            "evaluation_summary": evaluation_summary,
            "line_evaluations": line_evaluations,
            "line_item_source": line_item_source,
            "contract_clauses": clause_references,
            "pricing_rules": pricing_rules,
            "risk_assessment_score": risk_assessment_score,
            "risk_tier": risk_tier,
            "next_run_scheduled_in_hours": self.next_run_interval_hours,
        }

        # Always return an S3 URL - highlighted if contracts found and violations exist, original otherwise
        s3_url = None
        try:
            # Get S3 key for the invoice
            s3_key = self.db.get_invoice_s3_key(invoice.get("id"))
            if s3_key:
                # If no contracts found, return original PDF
                if no_contracts_found:
                    s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
                    self.logger.info(f"No contracts found, returning original PDF S3 URL: {s3_url}")
                else:
                    # Contracts found - highlight PDF if violations exist, otherwise return original
                    s3_url = self.pdf_highlighter.process_invoice_pdf(
                        s3_key=s3_key,
                        violations=violations
                    )
                    if s3_url:
                        if violations:
                            self.logger.info(f"Generated highlighted PDF S3 URL: {s3_url}")
                        else:
                            self.logger.info(f"No violations found, returning original PDF S3 URL: {s3_url}")
                    else:
                        self.logger.warning("PDF processing returned None, falling back to original")
                        s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
            else:
                self.logger.warning(f"No S3 key found for invoice {invoice.get('id')}, skipping S3 URL generation")
        except Exception as e:
            # Don't fail the entire compliance process if PDF processing fails
            self.logger.error(f"Error generating S3 URL: {e}", exc_info=True)
            # Try to return original PDF as fallback
            try:
                s3_key = self.db.get_invoice_s3_key(invoice.get("id"))
                if s3_key:
                    s3_url = self.pdf_highlighter.get_original_pdf_url(s3_key)
                    self.logger.info(f"Using original PDF S3 URL as fallback: {s3_url}")
            except Exception as fallback_error:
                self.logger.error(f"Failed to get original PDF S3 URL as fallback: {fallback_error}")
        
        # Add S3 URL to report (always include if available)
        if s3_url:
            report["s3_url"] = s3_url

        llm_meta_save = {
            "contract_clauses": clause_references,
            "audit_trace": audit_trace,
            "review_status": review_status,
            "escalations": escalations,
            "risk_tier": risk_tier,
        }
        if s3_url:
            llm_meta_save["s3_url"] = s3_url

        self.db.save_compliance_report(
            invoice_db_id=invoice.get("id"),
            invoice_number=invoice.get("invoice_id"),
            status=status,
            violations=violations,
            pricing_rules=pricing_rules,
            llm_metadata=llm_meta_save,
            next_run_at=next_run_at,
            risk_assessment_score=risk_assessment_score,
        )
        self.db.update_invoice_compliance_metadata(
            invoice_db_id=invoice.get("id"),
            status=review_status,
            risk_assessment_score=risk_assessment_score,
        )

        return report

    def analyze_invoices_bulk(self, limit: int = 200) -> Dict[str, Any]:
        """
        Execute compliance analysis across outstanding invoices.
        Returns array of individual reports (same format as single job) plus summary metadata.
        """
        pending_invoices = self.db.get_invoices_pending_compliance(limit=limit)
        processed_reports: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        for pending in pending_invoices:
            invoice_db_id = pending.get("id")
            invoice_number = pending.get("invoice_id")
            try:
                report = self.analyze_invoice(invoice_db_id)
                processed_reports.append(report)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error(
                    "Compliance analysis failed for invoice '%s': %s",
                    invoice_number or invoice_db_id,
                    exc,
                    exc_info=True,
                )
                failures.append(
                    {
                        "invoice_db_id": invoice_db_id,
                        "invoice_id": invoice_number,
                        "error": str(exc),
                    }
                )

        # Return format matching analyze_invoices_explicit (array of individual reports)
        return {
            "status": "processed",
            "processed": len(processed_reports),
            "failed": len(failures),
            "reports": processed_reports,  # Array of individual reports (same format as single job)
            "errors": failures if failures else [],
            # Additional metadata for bulk operations
            "invoices_in_queue": len(pending_invoices),
            "violations_detected": sum(
                len(report.get("violations", [])) for report in processed_reports
            ),
            "next_run_scheduled_in_hours": self.next_run_interval_hours,
        }

    def analyze_invoices_explicit(self, invoice_db_ids: List[int]) -> Dict[str, Any]:
        """
        Analyze a caller-supplied list of invoice database IDs.
        Returns per-invoice reports and any failures encountered.
        """
        reports: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        for invoice_db_id in invoice_db_ids:
            try:
                report = self.analyze_invoice(invoice_db_id)
                reports.append(report)
            except Exception as exc:  # pylint: disable=broad-except
                invoice_label = f"invoice_db_id={invoice_db_id}"
                self.logger.error(
                    "Compliance analysis failed for %s: %s",
                    invoice_label,
                    exc,
                    exc_info=True,
                )
                failures.append(
                    {
                        "invoice_db_id": invoice_db_id,
                        "error": str(exc),
                    }
                )

        return {
            "status": "processed",
            "processed": len(reports),
            "failed": len(failures),
            "reports": reports,
            "errors": failures if failures else [],
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _build_fallback_line_items(self, invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Create synthetic line items when none are stored.
        Uses invoice summary and subtotal/tax to approximate a single charge.
        """
        subtotal_amount = invoice.get("subtotal_amount")
        tax_amount = invoice.get("tax_amount")

        subtotal_value = (
            _to_float(subtotal_amount) if subtotal_amount is not None else None
        )
        tax_value = _to_float(tax_amount, 0.0) or 0.0

        if subtotal_value is None:
            self.logger.warning(
                "Invoice '%s' missing subtotal_amount; unable to infer line items.",
                invoice.get("invoice_id"),
            )
            return []

        description = invoice.get("summary") or "Invoice total"
        synthetic_line = {
            "line_id": f"{invoice.get('invoice_id')}_total",
            "description": description,
            "service_code": None,
            "quantity": 1,
            "unit_price": subtotal_value,
            "total_price": subtotal_value + tax_value,
            "metadata": {
                "source": "synthetic",
                "subtotal_amount": subtotal_value,
                "tax_amount": tax_value,
            },
        }

        self.logger.info(
            "Generated synthetic line item for invoice '%s' using subtotal=%s tax=%s",
            invoice.get("invoice_id"),
            subtotal_value,
            tax_value,
        )

        return [synthetic_line]

    def _retrieve_contract_context(
        self, invoice: Dict[str, Any]
    ) -> Tuple[List[RetrievalChunk], Dict[str, Any]]:
        query_text = self._build_contract_query(invoice)
        if not query_text:
            query_text = f"Pricing terms for vendor {invoice.get('seller_name', '')}"
        self.logger.info(
            "Vector search query for invoice '%s': %s",
            invoice.get("invoice_id"),
            query_text,
        )

        try:
            query_vector = self.vectorizer.vectorize_query(query_text)
        except Exception as exc:
            self.logger.error(
                "Failed to vectorize contract query for invoice '%s': %s",
                invoice.get("invoice_id"),
                exc,
            )
            raise

        vendor_name = invoice.get("seller_name")
        similarity_threshold = 0.0 if vendor_name else 0.3

        contract_matches = self.db.search_contracts_by_similarity(
            query_vector=query_vector,
            limit=self.clause_limit,
            similarity_threshold=similarity_threshold,
            vendor_name=vendor_name,
        )

        if vendor_name and len(contract_matches) == 0:
            self.logger.warning(
                "No contracts found for vendor '%s' matching invoice '%s'. "
                "Compliance analysis will proceed with no contract context.",
                vendor_name,
                invoice.get("invoice_id"),
            )

        chunks: List[RetrievalChunk] = []
        chunk_index = 0

        vendor_normalized = None
        if vendor_name:
            vendor_normalized = vendor_name.strip().lower()
            for suffix in [
                ", inc.",
                ", llc",
                ", ltd.",
                ", corporation",
                ", corp.",
                " inc.",
                " inc",
                ". inc",
                " llc",
                " ltd.",
                " ltd",
                " corporation",
                " corp.",
                " corp",
            ]:
                if vendor_normalized.endswith(suffix):
                    vendor_normalized = vendor_normalized[: -len(suffix)].strip()
                    break

        for match in contract_matches:
            if vendor_normalized:
                vendor_name_field = (match.get("vendor_name") or "").lower()
                context_text = (match.get("text") or "").lower()
                contract_id_lower = (match.get("contract_id") or "").lower()

                if (
                    vendor_normalized not in vendor_name_field
                    and vendor_normalized not in context_text
                    and vendor_normalized not in contract_id_lower
                ):
                    self.logger.warning(
                        "Skipping contract '%s' - vendor name '%s' not found. "
                        "This contract will not be used for compliance analysis.",
                        match.get("contract_id"),
                        vendor_name,
                    )
                    continue

            clauses = match.get("clauses")
            pricing_clauses = []
            if clauses:
                if isinstance(clauses, str):
                    try:
                        clauses = json.loads(clauses)
                    except (json.JSONDecodeError, TypeError):
                        clauses = None

                if clauses and isinstance(clauses, list):
                    for clause in clauses:
                        if isinstance(clause, dict):
                            clause_type = clause.get("clause_type", "").lower()
                            clause_text = clause.get("clause_text", "")
                            if clause_type == "pricing" and clause_text:
                                pricing_clauses.append(
                                    {
                                        "clause_id": clause.get("clause_id", ""),
                                        "section_title": clause.get("section_title", ""),
                                        "clause_text": clause_text,
                                    }
                                )

            pricing_sections = match.get("pricing_sections", "")
            full_text = match.get("text", "")
            summary = match.get("summary", "")

            similarity = match.get("similarity")
            try:
                similarity_value = float(similarity) if similarity is not None else None
            except (TypeError, ValueError):
                similarity_value = None

            service_types = match.get("service_types", [])
            if isinstance(service_types, str):
                try:
                    service_types = json.loads(service_types)
                except (json.JSONDecodeError, TypeError):
                    service_types = []
            if not isinstance(service_types, list):
                service_types = []

            contract_db_id = int(match.get("id") or 0)
            cid = match.get("contract_id")
            vname = match.get("vendor_name")

            if pricing_clauses:
                for clause in pricing_clauses[:3]:
                    clause_context = f"=== {clause.get('clause_id', 'Pricing Clause')} ===\n"
                    if clause.get("section_title"):
                        clause_context += f"Section: {clause['section_title']}\n"
                    clause_context += f"{clause['clause_text']}\n"
                    chunks.append(
                        RetrievalChunk(
                            chunk_index=chunk_index,
                            contract_db_id=contract_db_id,
                            contract_id=cid,
                            text=clause_context,
                            context_source="clauses",
                            similarity=similarity_value,
                            vendor_name=vname,
                            service_types=service_types,
                        )
                    )
                    chunk_index += 1
                    self.logger.debug(
                        "Using structured pricing clause: %s", clause.get("clause_id")
                    )
            elif pricing_sections:
                text = f"=== PRICING SECTIONS ===\n{pricing_sections}\n"
                chunks.append(
                    RetrievalChunk(
                        chunk_index=chunk_index,
                        contract_db_id=contract_db_id,
                        contract_id=cid,
                        text=text,
                        context_source="pricing_sections",
                        similarity=similarity_value,
                        vendor_name=vname,
                        service_types=service_types,
                    )
                )
                chunk_index += 1
                self.logger.debug("Using pricing_sections field")
            elif full_text:
                max_length = 3000
                if len(full_text) > max_length:
                    ft = full_text[:max_length] + "... [truncated]"
                else:
                    ft = full_text
                chunks.append(
                    RetrievalChunk(
                        chunk_index=chunk_index,
                        contract_db_id=contract_db_id,
                        contract_id=cid,
                        text=ft,
                        context_source="full_text",
                        similarity=similarity_value,
                        vendor_name=vname,
                        service_types=service_types,
                    )
                )
                chunk_index += 1
                self.logger.debug(
                    "Using full contract text (no structured clauses available)"
                )
            elif summary:
                chunks.append(
                    RetrievalChunk(
                        chunk_index=chunk_index,
                        contract_db_id=contract_db_id,
                        contract_id=cid,
                        text=summary,
                        context_source="summary",
                        similarity=similarity_value,
                        vendor_name=vname,
                        service_types=service_types,
                    )
                )
                chunk_index += 1
                self.logger.debug(
                    "Using contract summary (no other content available)"
                )
            else:
                continue

        if vendor_name and len(chunks) == 0:
            self.logger.error(
                "CRITICAL: No contracts passed vendor name filter for vendor '%s'. "
                "Compliance analysis cannot proceed without matching contracts.",
                vendor_name,
            )

        meta = {
            "query_text": query_text,
            "vendor_name": vendor_name,
        }
        return chunks, meta

    def _build_contract_query(self, invoice: Dict[str, Any]) -> str:
        """
        Build a semantic search query to find relevant contract clauses.
        Includes pricing-related terms, service types, and invoice details for better retrieval.
        """
        parts: List[str] = []
        
        # Add pricing-related terms to help find pricing clauses
        parts.append("pricing rates fees charges costs per unit maximum cap limit not to exceed")
        
        if invoice.get("seller_name"):
            parts.append(f"Vendor: {invoice['seller_name']}")
        if invoice.get("summary"):
            parts.append(f"Invoice Summary: {invoice['summary']}")
        
        # Include line item details for better matching
        service_keywords = set()
        for item in invoice.get("line_items", [])[:5]:
            description = item.get("description", "")
            service_code = item.get("service_code", "")
            unit_price = item.get("unit_price")
            
            if description:
                parts.append(f"Service: {description}")
                # Extract key service terms for matching
                service_keywords.update(description.lower().split()[:3])
            if service_code:
                parts.append(f"Service Code: {service_code}")
            if unit_price:
                # Include price context to find clauses with similar pricing
                parts.append(f"Price: ${unit_price}")
        
        # Add service keywords for better semantic matching
        if service_keywords:
            parts.append(" ".join(list(service_keywords)[:5]))
        
        return " | ".join(parts)

    def _extract_pricing_rules(
        self, invoice: Dict[str, Any], retrieval_chunks: List[RetrievalChunk]
    ) -> Dict[str, Any]:
        if not retrieval_chunks:
            return {
                "rules": [],
                "rejected_rules": [],
                "notes": "No contract context provided",
                "parse_failed": False,
                "extraction_model": None,
                "rules_raw_count": 0,
                "validated_rules_count": 0,
            }
        try:
            pricing_rules = self.vectorizer.extract_pricing_rules(
                invoice_metadata=invoice,
                retrieval_chunks=retrieval_chunks,
            )
            if not isinstance(pricing_rules, dict):
                raise ValueError("Pricing rules response must be a dictionary")
            return pricing_rules
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Failed to extract pricing rules for invoice '%s': %s",
                invoice.get("invoice_id"),
                exc,
                exc_info=True,
            )
            return {
                "rules": [],
                "rejected_rules": [],
                "notes": str(exc),
                "parse_failed": True,
                "extraction_model": None,
                "rules_raw_count": 0,
                "validated_rules_count": 0,
            }

    def _line_description_preview(self, item: Dict[str, Any]) -> Optional[str]:
        d = (item.get("description") or "").strip()
        if not d:
            return None
        return d[:120] + ("…" if len(d) > 120 else "")

    def _line_match_key(self, item: Dict[str, Any], idx: int) -> str:
        """
        Stable key for correlating violations with line items when line_id is missing.
        Prefer document line number; else DB row id; else position index.
        """
        raw = (item.get("line_id") or "").strip()
        if raw:
            return f"lid:{raw}"
        if item.get("id") is not None:
            return f"db:{int(item['id'])}"
        return f"idx:{idx}"

    def _evaluate_invoice(
        self,
        invoice: Dict[str, Any],
        line_items: List[Dict[str, Any]],
        pricing_rules: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
        rules = pricing_rules.get("rules") or []
        if not isinstance(rules, list):
            rules = []
        violations: List[Dict[str, Any]] = []
        line_evaluations: List[Dict[str, Any]] = []

        for idx, item in enumerate(line_items):
            line_id = item.get("line_id")
            match_key = self._line_match_key(item, idx)
            desc_preview = self._line_description_preview(item)
            actual_price = _to_float(self._calculate_actual_price(item))
            matched_rule = self._match_rule(item, rules)
            if not matched_rule:
                line_evaluations.append(
                    {
                        "line_index": idx,
                        "line_id": line_id,
                        "invoice_line_item_db_id": item.get("id"),
                        "line_match_key": match_key,
                        "description": desc_preview,
                        "outcome": "no_applicable_rule",
                        "detail": "No service_code or keyword match to a grounded rule",
                    }
                )
                continue

            expected_price = _to_float(
                self._calculate_expected_price(item, matched_rule)
            )
            tolerance = matched_rule.get("tolerance_amount")
            if tolerance is None:
                tolerance = 0
            else:
                try:
                    tolerance = float(tolerance)
                except (TypeError, ValueError):
                    tolerance = 0

            tolerance_percent = matched_rule.get("tolerance_percent")
            if tolerance_percent is None:
                tolerance_percent = 0
            else:
                try:
                    tolerance_percent = float(tolerance_percent)
                except (TypeError, ValueError):
                    tolerance_percent = 0

            if expected_price is None or actual_price is None:
                line_evaluations.append(
                    {
                        "line_index": idx,
                        "line_id": line_id,
                        "invoice_line_item_db_id": item.get("id"),
                        "line_match_key": match_key,
                        "description": desc_preview,
                        "outcome": "needs_review",
                        "detail": "Could not compute expected or actual price for comparison",
                    }
                )
                continue

            difference = actual_price - expected_price
            exceeds_amount = tolerance is not None and difference > tolerance
            exceeds_percent = False
            if tolerance_percent and tolerance_percent > 0:
                exceeds_percent = (
                    expected_price
                    and (difference / expected_price) * 100 > tolerance_percent
                )

            if difference > 0 and (exceeds_amount or exceeds_percent or tolerance == 0):
                violation_type = matched_rule.get(
                    "violation_type", "Price Cap Exceeded"
                )
                clause_reference = matched_rule.get("clause_reference") or None

                reasoning = self._generate_violation_reasoning(
                    item, matched_rule, expected_price, actual_price, difference
                )

                pdf_location = None
                item_metadata = item.get("metadata", {})
                if isinstance(item_metadata, dict):
                    pdf_location = item_metadata.get("pdf_location")
                elif isinstance(item_metadata, str):
                    try:
                        parsed_metadata = json.loads(item_metadata)
                        pdf_location = (
                            parsed_metadata.get("pdf_location")
                            if isinstance(parsed_metadata, dict)
                            else None
                        )
                    except (json.JSONDecodeError, TypeError):
                        pass

                violation = {
                    "line_id": line_id,
                    "line_match_key": match_key,
                    "invoice_line_item_id": item.get("id"),
                    "violation_type": violation_type,
                    "expected_price": round(expected_price, 2),
                    "actual_price": round(actual_price, 2),
                    "difference": round(difference, 2),
                    "clause_reference": clause_reference,
                    "reasoning": reasoning,
                    "recommended_actions": recommended_actions_for_violation(
                        violation_type,
                        float(difference),
                        clause_reference,
                    ),
                }

                if pdf_location:
                    violation["pdf_location"] = pdf_location

                violations.append(violation)
                line_evaluations.append(
                    {
                        "line_index": idx,
                        "line_id": line_id,
                        "invoice_line_item_db_id": item.get("id"),
                        "line_match_key": match_key,
                        "description": desc_preview,
                        "outcome": "violation",
                        "violation_type": violation_type,
                    }
                )
            else:
                line_evaluations.append(
                    {
                        "line_index": idx,
                        "line_id": line_id,
                        "invoice_line_item_db_id": item.get("id"),
                        "line_match_key": match_key,
                        "description": desc_preview,
                        "outcome": "checked_ok",
                        "detail": "Within tolerance or at/below contract expectation",
                    }
                )

        summary = {
            "line_items_evaluated": len(line_items),
            "rules_evaluated": len(rules),
            "violations_detected": len(violations),
        }
        return violations, summary, line_evaluations

    def _compute_review_status(
        self,
        *,
        no_contracts_found: bool,
        pricing_rules: Dict[str, Any],
        violations: List[Dict[str, Any]],
        line_item_source: str,
        line_evaluations: List[Dict[str, Any]],
    ) -> str:
        if no_contracts_found:
            return "no_contract_context"
        if pricing_rules.get("parse_failed"):
            return "rule_extraction_failed"
        raw_count = int(pricing_rules.get("rules_raw_count") or 0)
        rules = pricing_rules.get("rules") or []
        if raw_count > 0 and len(rules) == 0:
            return "insufficient_grounded_rules"
        if (
            not no_contracts_found
            and not pricing_rules.get("parse_failed")
            and len(rules) == 0
            and raw_count == 0
        ):
            return "needs_review"
        if violations:
            return "violation"
        if line_item_source == "inferred":
            return "needs_review"
        for le in line_evaluations:
            if (
                le.get("outcome") == "no_applicable_rule"
                and rules
            ):
                return "needs_review"
        for le in line_evaluations:
            if le.get("outcome") == "needs_review":
                return "needs_review"
        return "cleared"

    def _build_escalations(
        self,
        *,
        no_contracts_found: bool,
        line_item_source: str,
        pricing_rules: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if no_contracts_found:
            out.append(
                {
                    "code": "NO_CONTRACT",
                    "message": "No matching contract text was retrieved for this vendor; pricing rules were not grounded.",
                    "severity": "high",
                }
            )
        if line_item_source == "inferred":
            out.append(
                {
                    "code": "LINE_ITEMS_INFERRED",
                    "message": "Line items were synthesized from invoice totals; OCR line detail is preferred for audit.",
                    "severity": "medium",
                }
            )
        if pricing_rules.get("parse_failed"):
            out.append(
                {
                    "code": "PARSE_FAILED",
                    "message": "Could not parse structured pricing rules from the model output.",
                    "severity": "high",
                }
            )
        if pricing_rules.get("rules_raw_count", 0) > 0 and not (
            pricing_rules.get("rules") or []
        ):
            out.append(
                {
                    "code": "RULES_UNGROUNDED",
                    "message": "All extracted rules failed evidence validation (quotes must match chunk text).",
                    "severity": "high",
                }
            )
        if (
            not no_contracts_found
            and not pricing_rules.get("parse_failed")
            and not (pricing_rules.get("rules") or [])
            and int(pricing_rules.get("rules_raw_count") or 0) == 0
        ):
            out.append(
                {
                    "code": "NO_RULES_EXTRACTED",
                    "message": "No pricing rules were returned for the retrieved contract text.",
                    "severity": "medium",
                }
            )
        return out

    def _build_audit_trace(
        self,
        *,
        retrieval_meta: Dict[str, Any],
        retrieval_chunks: List[RetrievalChunk],
        clause_references: List[Dict[str, Any]],
        pricing_rules: Dict[str, Any],
        line_evaluations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rejected = pricing_rules.get("rejected_rules") or []
        rej_summary = []
        for r in rejected[:20]:
            if isinstance(r, dict):
                rej_summary.append(
                    {"reason": r.get("reason"), "has_rule": r.get("rule") is not None}
                )
        return {
            "version": "1",
            "retrieval": {
                "query_text": retrieval_meta.get("query_text"),
                "vendor_name": retrieval_meta.get("vendor_name"),
                "chunks": [c.to_audit_dict() for c in retrieval_chunks],
                "clause_references": clause_references,
            },
            "extraction": {
                "model": pricing_rules.get("extraction_model"),
                "rules_raw_count": pricing_rules.get("rules_raw_count"),
                "validated_rules_count": pricing_rules.get("validated_rules_count"),
                "rejected_rules_summary": rej_summary,
            },
            "evaluation": {"line_evaluations": line_evaluations},
        }

    def _risk_tier(
        self,
        risk_assessment_score: Optional[float],
        violations: List[Dict[str, Any]],
    ) -> str:
        """
        Coarse UI-facing tier: any contract violation is at least medium; large gaps = high.
        """
        if violations:
            total_diff = 0.0
            for v in violations:
                d = v.get("difference")
                if d is not None:
                    try:
                        total_diff += float(d)
                    except (TypeError, ValueError):
                        pass
            if total_diff >= 500.0 or (
                risk_assessment_score is not None and risk_assessment_score >= 0.05
            ):
                return "high"
            return "medium"
        if risk_assessment_score is None:
            return "unknown"
        if risk_assessment_score >= 0.05:
            return "high"
        if risk_assessment_score >= 0.01:
            return "medium"
        return "low"

    def _calculate_risk_assessment_score(
        self,
        invoice: Dict[str, Any],
        line_items: List[Dict[str, Any]],
        violations: List[Dict[str, Any]],
    ) -> Optional[float]:
        """
        Calculate risk assessment score for an invoice.
        
        Formula: (total_invoice_amount - max_invoice_amount_legal) / max_invoice_amount_legal
        
        Where:
        - total_invoice_amount: The total amount of the invoice (subtotal + tax)
        - max_invoice_amount_legal: The maximum amount that would have been payable
          if no contract rules were broken (cannot exceed total_invoice_amount)
        
        Returns:
        - Risk assessment score rounded to 4 decimal places (non-negative)
        - None if calculation cannot be performed
        """
        try:
            # Calculate total_invoice_amount from invoice subtotal + tax
            subtotal_amount = invoice.get("subtotal_amount")
            tax_amount = invoice.get("tax_amount", 0)
            
            if subtotal_amount is None:
                # Fallback: calculate from line items
                total_invoice_amount = sum(
                    _to_float(item.get("total_price"), 0.0) or 0.0
                    for item in line_items
                )
            else:
                subtotal = _to_float(subtotal_amount)
                tax = _to_float(tax_amount, 0.0) or 0.0
                if subtotal is not None:
                    total_invoice_amount = subtotal + tax
                else:
                    total_invoice_amount = sum(
                        _to_float(item.get("total_price"), 0.0) or 0.0
                        for item in line_items
                    )
            
            if total_invoice_amount <= 0:
                self.logger.warning(
                    "Cannot calculate risk score: total_invoice_amount is %s",
                    total_invoice_amount
                )
                return None
            
            # Map violations by stable line_match_key (handles missing line_id)
            violations_by_key: Dict[str, Any] = {}
            for violation in violations:
                mk = violation.get("line_match_key")
                if mk:
                    violations_by_key[mk] = violation

            # Calculate max_invoice_amount_legal
            # For each line item:
            # - If there's a violation, use expected_price
            # - If no violation, use actual total_price
            max_invoice_amount_legal = 0.0

            for idx, item in enumerate(line_items):
                match_key = self._line_match_key(item, idx)
                actual_total_price = self._calculate_actual_price(item)

                if match_key in violations_by_key:
                    violation = violations_by_key[match_key]
                    expected_price = violation.get("expected_price")
                    if expected_price is not None:
                        ep = _to_float(expected_price)
                        if ep is not None:
                            max_invoice_amount_legal += ep
                        elif actual_total_price is not None:
                            max_invoice_amount_legal += actual_total_price
                    elif actual_total_price is not None:
                        max_invoice_amount_legal += actual_total_price
                else:
                    # No violation, use actual price
                    if actual_total_price is not None:
                        at = _to_float(actual_total_price)
                        if at is not None:
                            max_invoice_amount_legal += at
            
            # Ensure max_invoice_amount_legal doesn't exceed total_invoice_amount
            if max_invoice_amount_legal > total_invoice_amount:
                max_invoice_amount_legal = total_invoice_amount
            
            if max_invoice_amount_legal <= 0:
                self.logger.warning(
                    "Cannot calculate risk score: max_invoice_amount_legal is %s",
                    max_invoice_amount_legal
                )
                return None
            
            # Calculate risk assessment score
            # Formula: (total_invoice_amount - max_invoice_amount_legal) / max_invoice_amount_legal
            score = (total_invoice_amount - max_invoice_amount_legal) / max_invoice_amount_legal
            
            # Ensure score is non-negative (round negative values to 0)
            if score < 0:
                score = 0.0
            
            # Round to 4 decimal places
            return round(score, 4)
            
        except Exception as exc:
            self.logger.error(
                "Error calculating risk assessment score: %s",
                exc,
                exc_info=True,
            )
            return None

    def _generate_violation_reasoning(
        self,
        line_item: Dict[str, Any],
        rule: Dict[str, Any],
        expected_price: float,
        actual_price: float,
        difference: float,
    ) -> Dict[str, Any]:
        """
        Generate human-readable reasoning for why a violation occurred.
        Returns a dictionary with explanation, expected_value, and actual_value.
        """
        description = line_item.get("description", "N/A")
        service_code = line_item.get("service_code", "")
        quantity = _to_float(line_item.get("quantity"), 1.0) or 1.0
        unit_price = line_item.get("unit_price")
        total_price = line_item.get("total_price")
        
        rule_notes = rule.get("notes", "")
        clause_ref = rule.get("clause_reference", "")
        violation_type = rule.get("violation_type", "Price Cap Exceeded")
        
        # Build expected value description
        expected_desc = ""
        if rule.get("flat_fee") is not None:
            ff = _to_float(rule.get("flat_fee"), 0.0) or 0.0
            expected_desc = f"${ff:.2f} (flat fee)"
        elif rule.get("unit_price") is not None:
            expected_unit = _to_float(rule.get("unit_price"), 0.0) or 0.0
            expected_total = expected_unit * quantity
            expected_desc = f"${expected_unit:.2f} per unit × {quantity} = ${expected_total:.2f}"
        elif rule.get("price_cap") is not None:
            cap = _to_float(rule.get("price_cap"), 0.0) or 0.0
            expected_desc = f"Maximum ${cap:.2f}"
        else:
            expected_desc = f"${expected_price:.2f}"
        
        # Build actual value description
        actual_desc = ""
        if total_price is not None:
            tp = _to_float(total_price, 0.0) or 0.0
            actual_desc = f"${tp:.2f}"
        elif unit_price is not None:
            up = _to_float(unit_price, 0.0) or 0.0
            actual_total = up * quantity
            actual_desc = f"${up:.2f} per unit × {quantity} = ${actual_total:.2f}"
        else:
            actual_desc = f"${actual_price:.2f}"
        
        # Generate explanation
        explanation_parts = [
            f"Violation detected for line item: {description}",
        ]
        
        if service_code:
            explanation_parts.append(f"Service Code: {service_code}")
        
        explanation_parts.append(
            f"The contract {clause_ref} specifies: {rule_notes}"
        )
        explanation_parts.append(
            f"Expected: {expected_desc}"
        )
        explanation_parts.append(
            f"Invoice shows: {actual_desc}"
        )
        explanation_parts.append(
            f"Difference: ${difference:.2f} over the contract limit"
        )
        
        explanation = " ".join(explanation_parts)
        
        return {
            "explanation": explanation,
            "expected_value": {
                "description": expected_desc,
                "amount": round(expected_price, 2),
                "unit_price": _to_float(rule.get("unit_price")),
                "flat_fee": _to_float(rule.get("flat_fee")),
                "price_cap": _to_float(rule.get("price_cap")),
            },
            "actual_value": {
                "description": actual_desc,
                "amount": round(actual_price, 2),
                "unit_price": _to_float(unit_price),
                "quantity": _to_float(quantity),
                "line_item_description": description,
            },
            "contract_requirement": {
                "clause_reference": clause_ref or None,
                "notes": rule_notes or None,
                "violation_type": violation_type or None,
            },
        }

    def _calculate_actual_price(self, line_item: Dict[str, Any]) -> Optional[float]:
        total_price = line_item.get("total_price")
        if total_price is not None:
            return _to_float(total_price)
        quantity = line_item.get("quantity", 1)
        unit_price = line_item.get("unit_price")
        if unit_price is None:
            return None
        q = _to_float(quantity, 1.0) or 1.0
        u = _to_float(unit_price)
        if u is None:
            return None
        return u * q

    def _calculate_expected_price(
        self, line_item: Dict[str, Any], rule: Dict[str, Any]
    ) -> Optional[float]:
        quantity = _to_float(line_item.get("quantity"), 1.0) or 1.0

        if rule.get("flat_fee") is not None:
            return _to_float(rule.get("flat_fee"))

        if rule.get("unit_price") is not None:
            u = _to_float(rule.get("unit_price"))
            if u is None:
                return None
            return u * quantity

        if rule.get("price_cap") is not None:
            c = _to_float(rule.get("price_cap"))
            if c is None:
                return None
            return c * quantity

        return None

    def _match_rule(
        self, line_item: Dict[str, Any], rules: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Match a line item to the most relevant pricing rule.
        Uses service code exact match first, then keyword matching with scoring.
        """
        description = (line_item.get("description") or "").lower()
        service_code = (line_item.get("service_code") or "").lower()
        
        # First pass: exact service code match
        for rule in rules:
            rule_service_code = (rule.get("service_code") or "").lower()
            if rule_service_code and rule_service_code == service_code:
                self.logger.debug(f"Matched rule by service_code: {service_code}")
                return rule

        # Second pass: keyword matching with scoring
        best_match = None
        best_score = 0
        
        for rule in rules:
            keywords = rule.get("keywords") or []
            if not keywords:
                continue
                
            normalized_keywords = [
                kw.lower().strip() for kw in keywords if isinstance(kw, str) and kw.strip()
            ]
            if not normalized_keywords:
                continue
            
            # Count how many keywords match
            matches = sum(1 for kw in normalized_keywords if kw in description)
            if matches > 0:
                # Score based on number of matches and keyword length (longer = more specific)
                score = matches * 10 + sum(len(kw) for kw in normalized_keywords if kw in description)
                if score > best_score:
                    best_score = score
                    best_match = rule
        
        if best_match:
            self.logger.debug(
                "Matched rule by keywords (score=%s): %s",
                best_score,
                best_match.get("keywords"),
            )
            return best_match

        return None

