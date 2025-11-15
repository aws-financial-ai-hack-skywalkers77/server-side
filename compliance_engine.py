import json
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

        # Calculate risk assessment score
        risk_assessment_score = self._calculate_risk_assessment_score(
            invoice, line_items, violations
        )

        status = "processed"
        processed_at = datetime.utcnow().isoformat() + "Z"
        next_run_at = datetime.utcnow() + timedelta(hours=self.next_run_interval_hours)

        report = {
            "invoice_id": invoice.get("invoice_id"),
            "db_id": invoice.get("id"),  # Database ID of the invoice
            "status": status,
            "processed_at": processed_at,
            "violations": violations,
            "evaluation_summary": evaluation_summary,
            "line_item_source": line_item_source,
            "contract_clauses": clause_references,
            "pricing_rules": pricing_rules,  # Include extracted pricing rules
            "risk_assessment_score": risk_assessment_score,  # Add risk assessment score
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
            risk_assessment_score=risk_assessment_score,
        )
        self.db.update_invoice_compliance_metadata(
            invoice_db_id=invoice.get("id"),
            status=status,
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

        # Get vendor name from invoice for strict filtering
        vendor_name = invoice.get("seller_name")
        
        contract_matches = self.db.search_contracts_by_similarity(
            query_vector=query_vector,
            limit=self.clause_limit,
            similarity_threshold=0.3,  # Increased from 0.1 to get more relevant matches
            vendor_name=vendor_name,  # Hard filter: only contracts for this vendor
        )
        
        if vendor_name and len(contract_matches) == 0:
            self.logger.warning(
                "No contracts found for vendor '%s' matching invoice '%s'. "
                "Compliance analysis will proceed with no contract context.",
                vendor_name,
                invoice.get("invoice_id")
            )
        contexts: List[str] = []
        clause_references: List[Dict[str, Any]] = []
        
        # Normalize vendor name for post-filtering check
        vendor_normalized = None
        if vendor_name:
            vendor_normalized = vendor_name.strip().lower()
            # Remove common business suffixes for matching
            for suffix in [' inc.', ' inc', '. inc', ' llc', ' ltd.', ' ltd', ' corporation', ' corp.', ' corp']:
                if vendor_normalized.endswith(suffix):
                    vendor_normalized = vendor_normalized[:-len(suffix)].strip()
                    break

        for match in contract_matches:
            # Hard filter: Check vendor_name field first (most reliable), then text
            if vendor_normalized:
                vendor_name_field = (match.get("vendor_name") or "").lower()
                context_text = (match.get("text") or "").lower()
                contract_id_lower = (match.get("contract_id") or "").lower()
                
                # Check vendor_name field, text, or contract_id
                if (vendor_normalized not in vendor_name_field and 
                    vendor_normalized not in context_text and 
                    vendor_normalized not in contract_id_lower):
                    self.logger.warning(
                        "Skipping contract '%s' - vendor name '%s' not found. "
                        "This contract will not be used for compliance analysis.",
                        match.get("contract_id"),
                        vendor_name
                    )
                    continue
            
            # Priority 1: Use structured pricing clauses if available
            clauses = match.get("clauses")
            pricing_clauses = []
            if clauses:
                # Handle JSONB - might be string or already parsed
                if isinstance(clauses, str):
                    try:
                        clauses = json.loads(clauses)
                    except (json.JSONDecodeError, TypeError):
                        clauses = None
                
                if clauses and isinstance(clauses, list):
                    # Filter for pricing-type clauses first
                    for clause in clauses:
                        if isinstance(clause, dict):
                            clause_type = clause.get("clause_type", "").lower()
                            clause_text = clause.get("clause_text", "")
                            if clause_type == "pricing" and clause_text:
                                pricing_clauses.append({
                                    "clause_id": clause.get("clause_id", ""),
                                    "section_title": clause.get("section_title", ""),
                                    "clause_text": clause_text
                                })
            
            # Priority 2: Use pricing_sections field if available
            pricing_sections = match.get("pricing_sections", "")
            
            # Priority 3: Fallback to full text
            full_text = match.get("text", "")
            summary = match.get("summary", "")
            
            # Build context: prefer structured data, fallback to full text
            if pricing_clauses:
                # Use structured pricing clauses
                for clause in pricing_clauses[:3]:  # Limit to top 3 pricing clauses
                    clause_context = f"=== {clause.get('clause_id', 'Pricing Clause')} ===\n"
                    if clause.get("section_title"):
                        clause_context += f"Section: {clause['section_title']}\n"
                    clause_context += f"{clause['clause_text']}\n"
                    contexts.append(clause_context)
                    self.logger.debug(f"Using structured pricing clause: {clause.get('clause_id')}")
            elif pricing_sections:
                # Use pricing_sections field
                contexts.append(f"=== PRICING SECTIONS ===\n{pricing_sections}\n")
                self.logger.debug("Using pricing_sections field")
            elif full_text:
                # Fallback to full text (truncate if too long)
                max_length = 3000
                if len(full_text) > max_length:
                    contexts.append(full_text[:max_length] + "... [truncated]")
                else:
                    contexts.append(full_text)
                self.logger.debug("Using full contract text (no structured clauses available)")
            elif summary:
                # Last resort: use summary
                contexts.append(summary)
                self.logger.debug("Using contract summary (no other content available)")
            else:
                # Skip if no content available
                continue
            
            similarity = match.get("similarity")
            try:
                similarity_value = float(similarity) if similarity is not None else None
            except (TypeError, ValueError):
                similarity_value = None
            
            # Include service types in reference for better traceability
            service_types = match.get("service_types", [])
            # Handle JSONB - might be string or already parsed
            if isinstance(service_types, str):
                try:
                    service_types = json.loads(service_types)
                except (json.JSONDecodeError, TypeError):
                    service_types = []
            
            context_source = "clauses" if pricing_clauses else ("pricing_sections" if pricing_sections else "full_text")
            
            clause_references.append(
                {
                    "contract_id": match.get("contract_id"),
                    "vendor_name": match.get("vendor_name"),
                    "similarity": similarity_value,
                    "service_types": service_types if isinstance(service_types, list) else [],
                    "context_source": context_source,
                }
            )

        if vendor_name and len(contexts) == 0:
            self.logger.error(
                "CRITICAL: No contracts passed vendor name filter for vendor '%s'. "
                "Compliance analysis cannot proceed without matching contracts.",
                vendor_name
            )

        return contexts, clause_references

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
            # Handle None values from JSON - convert to 0 for proper comparison
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
                continue

            difference = actual_price - expected_price
            exceeds_amount = tolerance is not None and difference > tolerance
            exceeds_percent = False
            if tolerance_percent and tolerance_percent > 0:
                exceeds_percent = (
                    expected_price
                    and (difference / expected_price) * 100 > tolerance_percent
                )

            # Detect violation if difference > 0 and (tolerance exceeded OR no tolerance allowed)
            if difference > 0 and (exceeds_amount or exceeds_percent or tolerance == 0):
                violation_type = matched_rule.get(
                    "violation_type", "Price Cap Exceeded"
                )
                clause_reference = matched_rule.get("clause_reference") or None
                
                # Generate LLM reasoning for the violation
                reasoning = self._generate_violation_reasoning(
                    item, matched_rule, expected_price, actual_price, difference
                )
                
                # Extract bounding box from line item metadata if available
                pdf_location = None
                item_metadata = item.get("metadata", {})
                if isinstance(item_metadata, dict):
                    pdf_location = item_metadata.get("pdf_location")
                elif isinstance(item_metadata, str):
                    # Handle case where metadata might be stored as JSON string
                    try:
                        parsed_metadata = json.loads(item_metadata)
                        pdf_location = parsed_metadata.get("pdf_location") if isinstance(parsed_metadata, dict) else None
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                violation = {
                    "line_id": item.get("line_id"),
                    "violation_type": violation_type,
                    "expected_price": round(expected_price, 2),
                    "actual_price": round(actual_price, 2),
                    "difference": round(difference, 2),
                    "clause_reference": clause_reference,
                    "reasoning": reasoning,
                }
                
                # Add bounding box if available
                if pdf_location:
                    violation["pdf_location"] = pdf_location
                
                violations.append(violation)

        summary = {
            "line_items_evaluated": len(line_items),
            "rules_evaluated": len(rules),
            "violations_detected": len(violations),
        }
        return violations, summary

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
                    float(item.get("total_price", 0) or 0)
                    for item in line_items
                )
            else:
                try:
                    subtotal = float(subtotal_amount)
                    tax = float(tax_amount) if tax_amount else 0.0
                    total_invoice_amount = subtotal + tax
                except (TypeError, ValueError):
                    # Fallback: calculate from line items
                    total_invoice_amount = sum(
                        float(item.get("total_price", 0) or 0)
                        for item in line_items
                    )
            
            if total_invoice_amount <= 0:
                self.logger.warning(
                    "Cannot calculate risk score: total_invoice_amount is %s",
                    total_invoice_amount
                )
                return None
            
            # Build a map of violations by line_id for quick lookup
            violations_by_line_id = {}
            for violation in violations:
                line_id = violation.get("line_id")
                if line_id:
                    violations_by_line_id[line_id] = violation
            
            # Calculate max_invoice_amount_legal
            # For each line item:
            # - If there's a violation, use expected_price
            # - If no violation, use actual total_price
            max_invoice_amount_legal = 0.0
            
            for item in line_items:
                line_id = item.get("line_id")
                actual_total_price = self._calculate_actual_price(item)
                
                if line_id and line_id in violations_by_line_id:
                    # Use expected_price from violation
                    violation = violations_by_line_id[line_id]
                    expected_price = violation.get("expected_price")
                    if expected_price is not None:
                        try:
                            max_invoice_amount_legal += float(expected_price)
                        except (TypeError, ValueError):
                            # Fallback to actual price if expected_price is invalid
                            if actual_total_price is not None:
                                max_invoice_amount_legal += actual_total_price
                    elif actual_total_price is not None:
                        max_invoice_amount_legal += actual_total_price
                else:
                    # No violation, use actual price
                    if actual_total_price is not None:
                        max_invoice_amount_legal += actual_total_price
            
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
        quantity = line_item.get("quantity", 1)
        unit_price = line_item.get("unit_price")
        total_price = line_item.get("total_price")
        
        rule_notes = rule.get("notes", "")
        clause_ref = rule.get("clause_reference", "")
        violation_type = rule.get("violation_type", "Price Cap Exceeded")
        
        # Build expected value description
        expected_desc = ""
        if rule.get("flat_fee") is not None:
            expected_desc = f"${rule.get('flat_fee'):.2f} (flat fee)"
        elif rule.get("unit_price") is not None:
            expected_unit = rule.get("unit_price")
            expected_total = expected_unit * quantity
            expected_desc = f"${expected_unit:.2f} per unit × {quantity} = ${expected_total:.2f}"
        elif rule.get("price_cap") is not None:
            expected_desc = f"Maximum ${rule.get('price_cap'):.2f}"
        else:
            expected_desc = f"${expected_price:.2f}"
        
        # Build actual value description
        actual_desc = ""
        if total_price is not None:
            actual_desc = f"${total_price:.2f}"
        elif unit_price is not None:
            actual_total = unit_price * quantity
            actual_desc = f"${unit_price:.2f} per unit × {quantity} = ${actual_total:.2f}"
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
        
        # Convert Decimal to float for JSON serialization
        def to_float(val):
            if val is None:
                return None
            try:
                return float(val)
            except (TypeError, ValueError):
                return val
        
        return {
            "explanation": explanation,
            "expected_value": {
                "description": expected_desc,
                "amount": round(expected_price, 2),
                "unit_price": to_float(rule.get("unit_price")),
                "flat_fee": to_float(rule.get("flat_fee")),
                "price_cap": to_float(rule.get("price_cap")),
            },
            "actual_value": {
                "description": actual_desc,
                "amount": round(actual_price, 2),
                "unit_price": to_float(unit_price),
                "quantity": to_float(quantity),
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
            self.logger.debug(f"Matched rule by keywords (score={best_score}): {best_match.get('keywords')}")
            return best_match
        
        # Third pass: if no rules have keywords, use the first rule with pricing constraints
        # This is a fallback for cases where LLM extracted rules but didn't add keywords
        for rule in rules:
            if rule.get("unit_price") or rule.get("price_cap") or rule.get("flat_fee"):
                self.logger.debug("Using fallback rule (no keywords matched)")
                return rule
        
        return None

