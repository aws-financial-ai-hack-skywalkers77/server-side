# services/workflow1/completeness_checker.py

import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import psycopg2.extras
from datetime import datetime

class FormCompletenessChecker:
    """
    Workflow 1: Tax Form Completeness Checker
    
    Validates uploaded tax documents for:
    - Required field completeness
    - Calculation accuracy
    - Cross-reference consistency
    - Jurisdiction-specific requirements
    """
    
    def __init__(
        self,
        db_connection,
        vectorizer,
        gemini_api_key: str
    ):
        self.db = db_connection
        self.vectorizer = vectorizer
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro')
        
    async def check_document(
        self,
        document_id: str,
        check_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Main entry point for completeness checking
        
        Args:
            document_id: ID of uploaded tax document
            check_types: List of checks to run ['required_fields', 'calculations', 'cross_reference']
                        If None, runs all checks
        
        Returns:
            Comprehensive check results with all issues found
        """
        
        # Default to all check types
        if check_types is None:
            check_types = ['required_fields', 'calculations', 'cross_reference', 'jurisdiction_specific']
        
        print(f"🔍 Starting completeness check for document: {document_id}")
        
        # 1. Load document data
        document = await self._load_document(document_id)
        if not document:
            return {'error': 'Document not found'}
        
        # 2. Load form template for this jurisdiction/form
        form_template = await self._load_form_template(
            document['jurisdiction'],
            document['form_code'],
            document['tax_year']
        )
        
        if not form_template:
            return {'error': 'Form template not found for this jurisdiction/year'}
        
        # 3. Run all requested checks
        all_issues = []
        check_results = {}
        
        if 'required_fields' in check_types:
            print("📋 Checking required fields...")
            required_field_issues = await self._check_required_fields(
                document, form_template
            )
            all_issues.extend(required_field_issues)
            check_results['required_fields'] = {
                'checked': True,
                'issues_found': len(required_field_issues)
            }
        
        if 'calculations' in check_types:
            print("🧮 Validating calculations...")
            calculation_issues = await self._check_calculations(
                document, form_template
            )
            all_issues.extend(calculation_issues)
            check_results['calculations'] = {
                'checked': True,
                'issues_found': len(calculation_issues)
            }
        
        if 'cross_reference' in check_types:
            print("🔗 Checking cross-references...")
            cross_ref_issues = await self._check_cross_references(
                document, form_template
            )
            all_issues.extend(cross_ref_issues)
            check_results['cross_reference'] = {
                'checked': True,
                'issues_found': len(cross_ref_issues)
            }
        
        if 'jurisdiction_specific' in check_types:
            print("⚖️ Checking jurisdiction-specific requirements...")
            jurisdiction_issues = await self._check_jurisdiction_requirements(
                document, form_template
            )
            all_issues.extend(jurisdiction_issues)
            check_results['jurisdiction_specific'] = {
                'checked': True,
                'issues_found': len(jurisdiction_issues)
            }
        
        # 4. Store all issues in database
        await self._store_issues(document_id, all_issues)
        
        # 5. Update document status
        await self._update_document_status(document_id, 'checked')
        
        # 6. Generate summary
        critical_count = len([i for i in all_issues if i['severity'] == 'critical'])
        high_count = len([i for i in all_issues if i['severity'] == 'high'])
        medium_count = len([i for i in all_issues if i['severity'] == 'medium'])
        
        summary = {
            'document_id': document_id,
            'jurisdiction': document['jurisdiction'],
            'form_code': document['form_code'],
            'tax_year': document['tax_year'],
            'checked_at': datetime.now().isoformat(),
            'checks_performed': check_results,
            'total_issues': len(all_issues),
            'critical_issues': critical_count,
            'high_priority_issues': high_count,
            'medium_priority_issues': medium_count,
            'status': 'needs_attention' if critical_count > 0 else 'ready_for_review',
            'issues': all_issues
        }
        
        print(f"✅ Check complete: {len(all_issues)} issues found")
        return summary
    
    async def _load_document(self, document_id: str) -> Optional[Dict]:
        """Load document data from database"""
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM tax_documents
            WHERE document_id = %s
        """, (document_id,))
        
        doc = cursor.fetchone()
        cursor.close()
        
        return dict(doc) if doc else None
    
    async def _load_form_template(
        self,
        jurisdiction: str,
        form_code: str,
        tax_year: int
    ) -> Optional[Dict]:
        """Load form template with requirements"""
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM form_templates
            WHERE jurisdiction = %s
            AND form_code = %s
            AND tax_year = %s
        """, (jurisdiction, form_code, tax_year))
        
        template = cursor.fetchone()
        cursor.close()
        
        return dict(template) if template else None
    
    async def _check_required_fields(
        self,
        document: Dict,
        template: Dict
    ) -> List[Dict]:
        """
        Check if all required fields are present and non-empty
        """
        issues = []
        extracted_data = document.get('extracted_data', {})
        required_fields = template.get('required_fields', [])
        
        for field in required_fields:
            field_name = field['name']
            field_label = field.get('label', field_name)
            is_conditional = field.get('conditional', False)
            
            # Check if field exists
            if field_name not in extracted_data:
                issues.append({
                    'check_type': 'required_fields',
                    'status': 'fail',
                    'severity': 'critical' if not is_conditional else 'high',
                    'field_name': field_name,
                    'issue_description': f"Required field '{field_label}' is missing",
                    'expected_value': 'Field must be present',
                    'actual_value': 'Not found',
                    'form_reference': template['form_code'],
                    'resolution_suggestion': f"Add the required field '{field_label}' to the form"
                })
                continue
            
            # Check if field is empty
            field_value = extracted_data[field_name]
            if field_value is None or str(field_value).strip() == '':
                issues.append({
                    'check_type': 'required_fields',
                    'status': 'fail',
                    'severity': 'high',
                    'field_name': field_name,
                    'issue_description': f"Required field '{field_label}' is empty",
                    'expected_value': 'Non-empty value',
                    'actual_value': 'Empty',
                    'form_reference': template['form_code'],
                    'resolution_suggestion': f"Provide a value for '{field_label}'"
                })
        
        return issues
    
    async def _check_calculations(
        self,
        document: Dict,
        template: Dict
    ) -> List[Dict]:
        """
        Validate calculations using form template rules
        """
        issues = []
        extracted_data = document.get('extracted_data', {})
        calculation_rules = template.get('calculation_rules', [])
        
        for rule in calculation_rules:
            rule_name = rule['name']
            formula = rule['formula']
            result_field = rule['result_field']
            
            try:
                # Evaluate formula with extracted data
                # Example: "line_1 + line_2 = line_3"
                calculated_value = self._evaluate_formula(formula, extracted_data)
                actual_value = extracted_data.get(result_field)
                
                if actual_value is None:
                    issues.append({
                        'check_type': 'calculations',
                        'status': 'fail',
                        'severity': 'high',
                        'field_name': result_field,
                        'issue_description': f"Calculation result field '{result_field}' is missing",
                        'expected_value': str(calculated_value),
                        'actual_value': 'Not found',
                        'form_reference': template['form_code'],
                        'resolution_suggestion': f"Add calculated value {calculated_value} to {result_field}"
                    })
                    continue
                
                # Convert to float for comparison
                actual_float = float(actual_value)
                calculated_float = float(calculated_value)
                
                # Allow small rounding differences (0.01)
                if abs(actual_float - calculated_float) > 0.01:
                    issues.append({
                        'check_type': 'calculations',
                        'status': 'fail',
                        'severity': 'critical',
                        'field_name': result_field,
                        'issue_description': f"Calculation error in '{rule_name}'",
                        'expected_value': f"{calculated_float:.2f}",
                        'actual_value': f"{actual_float:.2f}",
                        'form_reference': f"{template['form_code']} - {rule_name}",
                        'resolution_suggestion': f"Recalculate {result_field}. Expected: {calculated_float:.2f}, Found: {actual_float:.2f}"
                    })
            
            except Exception as e:
                issues.append({
                    'check_type': 'calculations',
                    'status': 'fail',
                    'severity': 'medium',
                    'field_name': result_field,
                    'issue_description': f"Could not validate calculation: {rule_name}",
                    'expected_value': 'Valid calculation',
                    'actual_value': f"Error: {str(e)}",
                    'form_reference': template['form_code'],
                    'resolution_suggestion': f"Manually verify calculation for {rule_name}"
                })
        
        return issues
    
    def _evaluate_formula(self, formula: str, data: Dict) -> float:
        """
        Safely evaluate a calculation formula
        Example: "field_a + field_b - field_c"
        """
        # Replace field names with actual values
        expression = formula
        for field_name, value in data.items():
            if value is not None:
                expression = expression.replace(field_name, str(value))
        
        # Safely evaluate (only allow basic math operations)
        allowed_chars = set('0123456789+-*/(). ')
        if not all(c in allowed_chars for c in expression):
            raise ValueError("Formula contains invalid characters")
        
        return eval(expression)
    
    async def _check_cross_references(
        self,
        document: Dict,
        template: Dict
    ) -> List[Dict]:
        """
        Check cross-references between related forms/schedules
        Example: Schedule C total should match Form 1040 line X
        """
        issues = []
        extracted_data = document.get('extracted_data', {})
        dependencies = template.get('dependencies', [])
        
        # Use LLM to intelligently check cross-references
        if not dependencies:
            return issues
        
        prompt = f"""You are a tax form validation expert. Check cross-references between forms.

DOCUMENT DATA:
{json.dumps(extracted_data, indent=2)}

DEPENDENCIES TO CHECK:
{json.dumps(dependencies, indent=2)}

TASK:
Verify that values in dependent forms/schedules match their references in the main form.
Identify any mismatches or missing cross-references.

Return a JSON array of issues found. Each issue should have:
- field_name: The field with the mismatch
- issue_description: What's wrong
- expected_value: What should be there
- actual_value: What's currently there
- severity: "critical" or "high"

If no issues found, return an empty array [].

FORMAT: [{{ "field_name": "...", "issue_description": "...", ... }}]
"""
        
        try:
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            # Extract JSON
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            llm_issues = json.loads(result_text.strip())
            
            # Format issues
            for issue in llm_issues:
                issues.append({
                    'check_type': 'cross_reference',
                    'status': 'fail',
                    'severity': issue.get('severity', 'high'),
                    'field_name': issue['field_name'],
                    'issue_description': issue['issue_description'],
                    'expected_value': issue.get('expected_value', 'See description'),
                    'actual_value': issue.get('actual_value', 'See description'),
                    'form_reference': template['form_code'],
                    'resolution_suggestion': f"Verify cross-reference: {issue['issue_description']}"
                })
        
        except Exception as e:
            print(f"❌ Error checking cross-references with LLM: {e}")
        
        return issues
    
    async def _check_jurisdiction_requirements(
        self,
        document: Dict,
        template: Dict
    ) -> List[Dict]:
        """
        Check jurisdiction-specific requirements using RAG
        """
        issues = []
        jurisdiction = document['jurisdiction']
        form_code = document['form_code']
        
        # Create search query for jurisdiction requirements
        query = f"Filing requirements for {form_code} in {jurisdiction}"
        query_embedding = await self.vectorizer.embed(query)
        
        # Search for relevant laws
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT 
                id,
                chunk_text,
                section_reference,
                document_title
            FROM tax_laws
            WHERE jurisdiction = %s
            AND law_category LIKE '%filing%'
            ORDER BY embedding <=> %s::vector
            LIMIT 5
        """, (jurisdiction, query_embedding))
        
        relevant_laws = cursor.fetchall()
        cursor.close()
        
        if not relevant_laws:
            return issues
        
        # Use LLM to check against laws
        laws_context = "\n\n---\n\n".join([
            f"Law {law['id']}: {law['section_reference']}\n{law['chunk_text']}"
            for law in relevant_laws
        ])
        
        prompt = f"""You are a tax compliance expert for {jurisdiction}.

DOCUMENT DATA:
{json.dumps(document.get('extracted_data', {}), indent=2)}

APPLICABLE LAWS:
{laws_context}

TASK:
Check if the document meets all jurisdiction-specific requirements mentioned in the laws.
Look for:
- Missing required schedules or attachments
- Incorrect filing status for jurisdiction
- Missing signatures or certifications
- Jurisdiction-specific deductions or credits not properly claimed

Return JSON array of issues. If compliant, return [].

FORMAT: [{{"field_name": "...", "issue_description": "...", "severity": "high", "law_reference_id": 123}}]
"""
        
        try:
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            
            llm_issues = json.loads(result_text.strip())
            
            for issue in llm_issues:
                issues.append({
                    'check_type': 'jurisdiction_specific',
                    'status': 'fail',
                    'severity': issue.get('severity', 'high'),
                    'field_name': issue.get('field_name', 'general'),
                    'issue_description': issue['issue_description'],
                    'expected_value': 'Compliance with jurisdiction requirements',
                    'actual_value': 'Non-compliant',
                    'form_reference': f"{form_code} - {jurisdiction}",
                    'resolution_suggestion': issue.get('resolution', 'Review jurisdiction requirements')
                })
        
        except Exception as e:
            print(f"❌ Error checking jurisdiction requirements: {e}")
        
        return issues
    
    async def _store_issues(self, document_id: str, issues: List[Dict]):
        """Store all issues in database"""
        cursor = self.db.cursor()
        
        for issue in issues:
            try:
                cursor.execute("""
                    INSERT INTO completeness_checks (
                        document_id, check_type, status, severity,
                        field_name, issue_description, expected_value,
                        actual_value, form_reference, resolution_suggestion
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    document_id,
                    issue.get('check_type'),
                    issue.get('status'),
                    issue.get('severity'),
                    issue.get('field_name'),
                    issue.get('issue_description'),
                    issue.get('expected_value'),
                    issue.get('actual_value'),
                    issue.get('form_reference'),
                    issue.get('resolution_suggestion')
                ))
            except Exception as e:
                print(f"❌ Error storing issue: {e}")
        
        self.db.commit()
        cursor.close()
    
    async def _update_document_status(self, document_id: str, status: str):
        """Update document processing status"""
        cursor = self.db.cursor()
        cursor.execute("""
            UPDATE tax_documents
            SET status = %s, processed_at = NOW()
            WHERE document_id = %s
        """, (status, document_id))
        self.db.commit()
        cursor.close()