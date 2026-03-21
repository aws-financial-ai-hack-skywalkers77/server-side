import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


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

        contract_contexts, clause_references = self._retrieve_contract_context(invoice)
        if not contract_contexts:
            self.logger.warning(
                "No contract clauses retrieved for invoice '%s'", invoice.get("invoice_id")
            )

        pricing_rules = self._extract_pricing_rules(invoice, contract_contexts)
        violations, evaluation_summary = self._evaluate_invoice(
            invoice, line_items, pricing_rules
        )

        status = "processed"
        processed_at = datetime.utcnow().isoformat() + "Z"
        next_run_at = datetime.utcnow() + timedelta(hours=self.next_run_interval_hours)

        report = {
            "invoice_id": invoice.get("invoice_id"),
            "status": status,
            "processed_at": processed_at,
            "violations": violations,
            "evaluation_summary": evaluation_summary,
            "line_item_source": line_item_source,
            "contract_clauses": clause_references,
            "next_run_scheduled_in_hours": self.next_run_interval_hours,
        }

        self.db.save_compliance_report(
            invoice_db_id=invoice.get("id"),
            invoice_number=invoice.get("invoice_id"),
            status=status,
            violations=violations,
            pricing_rules=pricing_rules,
            llm_metadata={"contract_clauses": clause_references},
            next_run_at=next_run_at,
        )
        self.db.update_invoice_compliance_metadata(
            invoice_db_id=invoice.get("id"),
            status=status,
        )

        return report

    def analyze_invoices_bulk(self, limit: int = 200) -> Dict[str, Any]:
        """
        Execute compliance analysis across outstanding invoices.
        Returns summary metrics suitable for schedulers.
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

        summary = {
            "status": "bulk_run_started",
            "invoices_in_queue": len(pending_invoices),
            "processed": len(processed_reports),
            "failed": len(failures),
            "violations_detected": sum(
                len(report.get("violations", [])) for report in processed_reports
            ),
            "next_run_scheduled_in_hours": self.next_run_interval_hours,
        }

        if failures:
            summary["errors"] = failures

        return summary

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

        try:
            subtotal_value = float(subtotal_amount) if subtotal_amount is not None else None
        except (TypeError, ValueError):
            subtotal_value = None

        try:
            tax_value = float(tax_amount) if tax_amount is not None else 0.0
        except (TypeError, ValueError):
            tax_value = 0.0

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
    ) -> (List[str], List[Dict[str, Any]]):
        query_text = self._build_contract_query(invoice)
        if not query_text:
            query_text = f"Pricing terms for vendor {invoice.get('seller_name', '')}"
        self.logger.info("Vector search query for invoice '%s': %s", invoice.get("invoice_id"), query_text)

        try:
            query_vector = self.vectorizer.vectorize_query(query_text)
        except Exception as exc:
            self.logger.error(
                "Failed to vectorize contract query for invoice '%s': %s",
                invoice.get("invoice_id"),
                exc,
            )
            raise

        contract_matches = self.db.search_contracts_by_similarity(
            query_vector=query_vector,
            limit=self.clause_limit,
            similarity_threshold=0.1,
        )
        contexts: List[str] = []
        clause_references: List[Dict[str, Any]] = []

        for match in contract_matches:
            context = match.get("text") or match.get("summary")
            if not context:
                continue
            contexts.append(context)
            similarity = match.get("similarity")
            try:
                similarity_value = float(similarity) if similarity is not None else None
            except (TypeError, ValueError):
                similarity_value = None
            clause_references.append(
                {
                    "contract_id": match.get("contract_id"),
                    "similarity": similarity_value,
                }
            )

        return contexts, clause_references

    def _build_contract_query(self, invoice: Dict[str, Any]) -> str:
        parts: List[str] = []
        if invoice.get("seller_name"):
            parts.append(f"Vendor: {invoice['seller_name']}")
        if invoice.get("summary"):
            parts.append(f"Invoice Summary: {invoice['summary']}")
        for item in invoice.get("line_items", [])[:5]:
            description = item.get("description")
            service_code = item.get("service_code")
            if description:
                parts.append(f"Service Description: {description}")
            if service_code:
                parts.append(f"Service Code: {service_code}")
        return " | ".join(parts)

    def _extract_pricing_rules(
        self, invoice: Dict[str, Any], contract_contexts: List[str]
    ) -> Dict[str, Any]:
        try:
            pricing_rules = self.vectorizer.extract_pricing_rules(
                invoice_metadata=invoice,
                contract_contexts=contract_contexts,
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
            return {"rules": [], "notes": str(exc)}

    def _evaluate_invoice(
        self,
        invoice: Dict[str, Any],
        line_items: List[Dict[str, Any]],
        pricing_rules: Dict[str, Any],
    ) -> (List[Dict[str, Any]], Dict[str, Any]):
        rules = pricing_rules.get("rules", [])
        violations: List[Dict[str, Any]] = []

        for item in line_items:
            actual_price = self._calculate_actual_price(item)
            matched_rule = self._match_rule(item, rules)
            if not matched_rule:
                continue

            expected_price = self._calculate_expected_price(item, matched_rule)
            tolerance = matched_rule.get("tolerance_amount", 0)
            tolerance_percent = matched_rule.get("tolerance_percent", 0)

            if expected_price is None or actual_price is None:
                continue

            difference = actual_price - expected_price
            exceeds_amount = tolerance is not None and difference > tolerance
            exceeds_percent = False
            if tolerance_percent:
                exceeds_percent = (
                    expected_price
                    and (difference / expected_price) * 100 > tolerance_percent
                )

            if difference > 0 and (exceeds_amount or exceeds_percent or tolerance == 0):
                violation_type = matched_rule.get(
                    "violation_type", "Price Cap Exceeded"
                )
                violations.append(
                    {
                        "line_id": item.get("line_id"),
                        "violation_type": violation_type,
                        "expected_price": round(expected_price, 2),
                        "actual_price": round(actual_price, 2),
                        "difference": round(difference, 2),
                        "contract_clause_reference": matched_rule.get(
                            "clause_reference"
                        ),
                        "applied_rule": matched_rule,
                    }
                )

        summary = {
            "line_items_evaluated": len(line_items),
            "rules_evaluated": len(rules),
            "violations_detected": len(violations),
        }
        return violations, summary

    def _calculate_actual_price(self, line_item: Dict[str, Any]) -> Optional[float]:
        total_price = line_item.get("total_price")
        if total_price is not None:
            return float(total_price)
        quantity = line_item.get("quantity", 1)
        unit_price = line_item.get("unit_price")
        if unit_price is None:
            return None
        try:
            return float(unit_price) * float(quantity or 1)
        except (TypeError, ValueError):
            return None

    def _calculate_expected_price(
        self, line_item: Dict[str, Any], rule: Dict[str, Any]
    ) -> Optional[float]:
        quantity = line_item.get("quantity", 1)
        try:
            quantity = float(quantity or 1)
        except (TypeError, ValueError):
            quantity = 1.0

        if rule.get("flat_fee") is not None:
            try:
                return float(rule["flat_fee"])
            except (TypeError, ValueError):
                return None

        if rule.get("unit_price") is not None:
            try:
                return float(rule["unit_price"]) * quantity
            except (TypeError, ValueError):
                return None

        if rule.get("price_cap") is not None:
            try:
                return float(rule["price_cap"]) * quantity
            except (TypeError, ValueError):
                return None

        return None

    def _match_rule(
        self, line_item: Dict[str, Any], rules: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        description = (line_item.get("description") or "").lower()
        service_code = (line_item.get("service_code") or "").lower()

        for rule in rules:
            rule_service_code = (rule.get("service_code") or "").lower()
            if rule_service_code and rule_service_code == service_code:
                return rule

            keywords = rule.get("keywords") or []
            normalized_keywords = [
                kw.lower() for kw in keywords if isinstance(kw, str)
            ]
            if description and normalized_keywords:
                if any(keyword in description for keyword in normalized_keywords):
                    return rule
        return None

