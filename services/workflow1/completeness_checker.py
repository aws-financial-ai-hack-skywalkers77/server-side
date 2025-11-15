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
        # Use model from config, fallback to gemini-1.5-pro
        from config import Config
        model_name = Config.GEMINI_GENERATION_MODEL or 'gemini-2.5-flash'
        # Remove 'models/' prefix if present (generation models don't use it)
        if model_name.startswith('models/'):
            model_name = model_name.replace('models/', '')
        try:
            self.model = genai.GenerativeModel(model_name)
        except Exception as e:
            print(f"⚠️  Failed to initialize {model_name}, trying gemini-2.5-flash as fallback: {e}")
            try:
                # Fallback to gemini-2.5-flash (stable, available)
                self.model = genai.GenerativeModel('gemini-2.5-flash')
                print(f"✅ Using fallback model: gemini-2.5-flash")
            except Exception as e2:
                print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                try:
                    self.model = genai.GenerativeModel('gemini-2.0-flash-001')
                    print(f"✅ Using fallback model: gemini-2.0-flash-001")
                except Exception as e3:
                    try:
                        self.model = genai.GenerativeModel('gemini-flash-latest')
                        print(f"✅ Using fallback model: gemini-flash-latest")
                    except Exception as e4:
                        print(f"❌ All model initialization failed!")
                        raise e
        
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
        
        try:
            # Default to all check types
            if check_types is None:
                check_types = ['required_fields', 'calculations', 'cross_reference', 'jurisdiction_specific']
            
            print(f"🔍 Starting completeness check for document: {document_id}")
            
            # 1. Load document data
            document = await self._load_document(document_id)
            if not document:
                return {'error': 'Document not found'}
            
            # 2. Load form template for this jurisdiction/form
            try:
                form_template = await self._load_form_template(
                    document.get('jurisdiction'),
                    document.get('form_code'),
                    document.get('tax_year')
                )
            except Exception as template_error:
                print(f"❌ Error loading form template: {template_error}")
                import traceback
                traceback.print_exc()
                return {'error': f'Error loading form template: {str(template_error)}'}
            
            if not form_template:
                return {'error': 'Form template not found for this jurisdiction/year'}
            
            # 3. Run all requested checks
            all_issues = []
            check_results = {}
        
            if 'required_fields' in check_types or 'completeness' in check_types:
                try:
                    print("📋 Checking required fields...")
                    required_field_issues = await self._check_required_fields(
                        document, form_template
                    )
                    all_issues.extend(required_field_issues)
                    check_results['required_fields'] = {
                        'checked': True,
                        'issues_found': len(required_field_issues)
                    }
                except Exception as e:
                    print(f"❌ Error in required_fields check: {e}")
                    import traceback
                    traceback.print_exc()
            
            if 'calculations' in check_types:
                try:
                    print("🧮 Validating calculations...")
                    calculation_issues = await self._check_calculations(
                        document, form_template
                    )
                    all_issues.extend(calculation_issues)
                    check_results['calculations'] = {
                        'checked': True,
                        'issues_found': len(calculation_issues)
                    }
                except Exception as e:
                    print(f"❌ Error in calculations check: {e}")
                    import traceback
                    traceback.print_exc()
            
            if 'cross_reference' in check_types:
                try:
                    print("🔗 Checking cross-references...")
                    cross_ref_issues = await self._check_cross_references(
                        document, form_template
                    )
                    all_issues.extend(cross_ref_issues)
                    check_results['cross_reference'] = {
                        'checked': True,
                        'issues_found': len(cross_ref_issues)
                    }
                except Exception as e:
                    print(f"❌ Error in cross_reference check: {e}")
                    import traceback
                    traceback.print_exc()
            
            if 'jurisdiction_specific' in check_types:
                try:
                    print("⚖️ Checking jurisdiction-specific requirements...")
                    jurisdiction_issues = await self._check_jurisdiction_requirements(
                        document, form_template
                    )
                    all_issues.extend(jurisdiction_issues)
                    check_results['jurisdiction_specific'] = {
                        'checked': True,
                        'issues_found': len(jurisdiction_issues)
                    }
                except Exception as e:
                    print(f"❌ Error in jurisdiction_specific check: {e}")
                    import traceback
                    traceback.print_exc()
            
            # 4. Store all issues in database
            try:
                await self._store_issues(document_id, all_issues)
            except Exception as e:
                print(f"⚠️ Error storing issues (continuing anyway): {e}")
                import traceback
                traceback.print_exc()
            
            # 5. Update document status
            try:
                await self._update_document_status(document_id, 'checked')
            except Exception as e:
                print(f"⚠️ Error updating document status (continuing anyway): {e}")
            
            # 6. Generate summary
            critical_count = len([i for i in all_issues if isinstance(i, dict) and i.get('severity') == 'critical'])
            high_count = len([i for i in all_issues if isinstance(i, dict) and i.get('severity') == 'high'])
            medium_count = len([i for i in all_issues if isinstance(i, dict) and i.get('severity') == 'medium'])
            
            summary = {
                'document_id': document_id,
                'jurisdiction': document.get('jurisdiction', ''),
                'form_code': document.get('form_code', ''),
                'tax_year': document.get('tax_year'),
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
        except IndexError as e:
            print(f"❌ IndexError in check_document: {e}")
            import traceback
            traceback.print_exc()
            return {
                'error': f'IndexError: {str(e)}',
                'document_id': document_id,
                'message': 'An error occurred while checking the document. Check server logs for details.'
            }
        except Exception as e:
            print(f"❌ Error in check_document: {e}")
            import traceback
            traceback.print_exc()
            return {
                'error': f'{type(e).__name__}: {str(e)}',
                'document_id': document_id,
                'message': 'An error occurred while checking the document.'
            }
    
    async def _load_document(self, document_id: str) -> Optional[Dict]:
        """Load document data from database"""
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM tax_documents
            WHERE document_id = %s
        """, (document_id,))
        
        doc = cursor.fetchone()
        cursor.close()
        
        if not doc:
            return None
        
        # Convert to dict, handling both RealDictRow and tuple
        try:
            if hasattr(doc, 'keys'):
                doc_dict = dict(doc)
            else:
                # Fallback for tuple - get column names
                try:
                    cursor = self.db.cursor()
                    cursor.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'tax_documents'
                        ORDER BY ordinal_position
                    """)
                    column_rows = cursor.fetchall()
                    cursor.close()
                    
                    # Safely extract column names
                    columns = []
                    for row in column_rows:
                        if row and len(row) > 0:
                            try:
                                col_name = row[0] if isinstance(row, (tuple, list)) else row
                                if col_name:
                                    columns.append(col_name)
                            except (IndexError, TypeError):
                                continue
                    
                    if len(columns) == len(doc):
                        doc_dict = dict(zip(columns, doc))
                    else:
                        print(f"⚠️ Column count mismatch: {len(columns)} columns, {len(doc)} doc fields")
                        return None
                except Exception as e:
                    print(f"❌ Error getting column names: {e}")
                    return None
            
            # Parse extracted_data if it's a JSONB string
            if 'extracted_data' in doc_dict:
                extracted_data = doc_dict['extracted_data']
                if isinstance(extracted_data, str):
                    try:
                        import json
                        doc_dict['extracted_data'] = json.loads(extracted_data)
                    except:
                        doc_dict['extracted_data'] = {}
                elif not isinstance(extracted_data, dict):
                    doc_dict['extracted_data'] = {}
            
            return doc_dict
        except Exception as e:
            print(f"❌ Error converting document to dict: {e}")
            return None
    
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
        
        if not template:
            return None
        
        # Convert to dict, handling both RealDictRow and tuple
        if hasattr(template, 'keys'):
            return dict(template)
        else:
            # Fallback for tuple - get column names
            try:
                cursor = self.db.cursor()
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'form_templates'
                    ORDER BY ordinal_position
                """)
                column_rows = cursor.fetchall()
                cursor.close()
                
                # Safely extract column names
                columns = []
                for row in column_rows:
                    if row and len(row) > 0:
                        try:
                            col_name = row[0] if isinstance(row, (tuple, list)) else row
                            if col_name:
                                columns.append(col_name)
                        except (IndexError, TypeError):
                            continue
                
                if len(columns) == len(template):
                    return dict(zip(columns, template))
                else:
                    print(f"⚠️ Column count mismatch: {len(columns)} columns, {len(template)} template fields")
                    return None
            except Exception as e:
                print(f"❌ Error getting column names: {e}")
                return None
    
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
        if not isinstance(extracted_data, dict):
            extracted_data = {}
        
        # Debug: Log what we're checking
        print(f"📋 Checking required fields. Extracted data keys: {list(extracted_data.keys())}")
        print(f"   taxpayer_name: '{extracted_data.get('taxpayer_name', 'NOT FOUND')}'")
        print(f"   taxpayer_ssn: '{extracted_data.get('taxpayer_ssn', 'NOT FOUND')}'")
        print(f"   filing_status: '{extracted_data.get('filing_status', 'NOT FOUND')}'")
        
        # Handle required_fields - could be JSONB string or already parsed
        required_fields_raw = template.get('required_fields', [])
        if isinstance(required_fields_raw, str):
            try:
                import json
                required_fields = json.loads(required_fields_raw)
            except:
                required_fields = []
        else:
            required_fields = required_fields_raw if isinstance(required_fields_raw, list) else []
        
        for field in required_fields:
            if not isinstance(field, dict):
                continue
            field_name = field.get('name')
            if not field_name:
                continue
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
                    'form_reference': template.get('form_code', 'Unknown'),
                    'resolution_suggestion': f"Add the required field '{field_label}' to the form"
                })
                continue
            
            # Check if field is empty or contains invalid values
            field_value = extracted_data[field_name]
            field_value_str = str(field_value).strip() if field_value is not None else ''
            
            # Check for invalid values that indicate extraction failed
            invalid_values = ['on line', 'on line below', 'line below', 'see instructions', 
                            'enter name', 'your name', 'above', 'below', 'n/a', 'na', '']
            
            is_empty = field_value is None or field_value_str == ''
            is_invalid = field_value_str.lower() in [v.lower() for v in invalid_values] or len(field_value_str) < 2
            
            if is_empty or is_invalid:
                issue_desc = f"Required field '{field_label}' is empty" if is_empty else f"Required field '{field_label}' contains invalid value: '{field_value_str}'"
                issues.append({
                    'check_type': 'required_fields',
                    'status': 'fail',
                    'severity': 'high',
                    'field_name': field_name,
                    'issue_description': issue_desc,
                    'expected_value': 'Valid non-empty value',
                    'actual_value': field_value_str if field_value_str else 'Empty',
                    'form_reference': template.get('form_code', 'Unknown'),
                    'resolution_suggestion': f"Provide a valid value for '{field_label}'"
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
        if not isinstance(extracted_data, dict):
            extracted_data = {}
        
        # Parse form_fields_json if it exists and merge into extracted_data
        # This is where income fields (wages, interest, dividends, total_income) are stored
        form_fields_json = extracted_data.get('form_fields_json', '{}')
        if isinstance(form_fields_json, str):
            try:
                form_fields = json.loads(form_fields_json)
                if isinstance(form_fields, dict):
                    # Merge form fields into extracted_data for formula evaluation
                    extracted_data.update(form_fields)
                    print(f"🔍 Calculation Check: Merged form_fields into extracted_data: {form_fields}")
            except Exception as parse_error:
                print(f"⚠️ Calculation Check: Failed to parse form_fields_json: {parse_error}")
                # Try to parse as nested JSON (sometimes it's double-encoded)
                try:
                    if form_fields_json.startswith('"') and form_fields_json.endswith('"'):
                        form_fields_json_cleaned = form_fields_json[1:-1]  # Remove outer quotes
                        form_fields = json.loads(form_fields_json_cleaned)
                        if isinstance(form_fields, dict):
                            extracted_data.update(form_fields)
                            print(f"🔍 Calculation Check: Merged form_fields (double-encoded) into extracted_data: {form_fields}")
                except:
                    pass
        elif isinstance(form_fields_json, dict):
            extracted_data.update(form_fields_json)
            print(f"🔍 Calculation Check: Merged form_fields (dict) into extracted_data: {form_fields_json}")
        
        # Also check if income fields are in the root of extracted_data (from LLM extraction)
        # Sometimes they're stored directly, not in form_fields_json
        if not extracted_data.get('wages') and not extracted_data.get('interest') and not extracted_data.get('dividends'):
            print("⚠️ Calculation Check: No income fields found in form_fields_json, checking other locations...")
            # Check if they're in form_data or calculations
            form_data = extracted_data.get('form_data', {})
            if isinstance(form_data, dict):
                if 'wages' in form_data or 'interest' in form_data or 'dividends' in form_data:
                    extracted_data.update({k: v for k, v in form_data.items() if k in ['wages', 'interest', 'dividends', 'total_income']})
                    print(f"🔍 Calculation Check: Found income fields in form_data: {form_data}")
        
        # Debug: Show what fields are available for calculation
        print(f"🔍 Calculation Check: Available fields in extracted_data: {list(extracted_data.keys())}")
        print(f"🔍 Calculation Check: wages={extracted_data.get('wages')}, interest={extracted_data.get('interest')}, dividends={extracted_data.get('dividends')}, total_income={extracted_data.get('total_income')}")
        
        # Handle calculation_rules - could be JSONB string or already parsed
        calculation_rules_raw = template.get('calculation_rules', [])
        if isinstance(calculation_rules_raw, str):
            try:
                # json is already imported at the top of the file
                calculation_rules = json.loads(calculation_rules_raw)
            except Exception as e:
                print(f"⚠️ Calculation Check: Failed to parse calculation_rules JSON: {e}")
                calculation_rules = []
        else:
            calculation_rules = calculation_rules_raw if isinstance(calculation_rules_raw, list) else []
        
        print(f"🔍 Calculation Check: Found {len(calculation_rules)} calculation rules")
        
        # If no calculation rules, return early
        if not calculation_rules:
            print("⚠️ Calculation Check: No calculation rules found in template!")
            return issues
        
        for rule in calculation_rules:
            if not isinstance(rule, dict):
                continue
            rule_name = rule.get('name', 'Unknown')
            formula = rule.get('formula')
            result_field = rule.get('result_field')
            if not formula or not result_field:
                continue
            
            try:
                # Evaluate formula with extracted data
                # Example: "line_1 + line_2 = line_3"
                print(f"🔍 Calculation Check: Evaluating rule '{rule_name}'")
                print(f"   Formula: {formula}")
                print(f"   Result field: {result_field}")
                print(f"   Available data: wages={extracted_data.get('wages')}, interest={extracted_data.get('interest')}, dividends={extracted_data.get('dividends')}, total_income={extracted_data.get('total_income')}")
                
                calculated_value = self._evaluate_formula(formula, extracted_data)
                actual_value = extracted_data.get(result_field)
                
                print(f"   Calculated value: {calculated_value}")
                print(f"   Actual value: {actual_value}")
                
                if actual_value is None:
                    issues.append({
                        'check_type': 'calculations',
                        'status': 'fail',
                        'severity': 'high',
                        'field_name': result_field,
                        'issue_description': f"Calculation result field '{result_field}' is missing",
                        'expected_value': str(calculated_value),
                        'actual_value': 'Not found',
                        'form_reference': template.get('form_code', 'Unknown'),
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
                        'form_reference': f"{template.get('form_code', 'Unknown')} - {rule_name}",
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
                    'form_reference': template.get('form_code', 'Unknown'),
                    'resolution_suggestion': f"Manually verify calculation for {rule_name}"
                })
        
        return issues
    
    def _evaluate_formula(self, formula: str, data: Dict) -> float:
        """
        Safely evaluate a calculation formula
        Example: "wages + interest + dividends"
        """
        try:
            # Replace field names with actual values
            # Use sorted keys by length (longest first) to avoid partial replacements
            # e.g., "wages" shouldn't replace part of "wages_salary"
            expression = formula
            sorted_keys = sorted(data.keys(), key=len, reverse=True)
            
            for field_name in sorted_keys:
                value = data.get(field_name)
                if value is not None and field_name:
                    # Replace whole word only (with word boundaries)
                    import re
                    pattern = r'\b' + re.escape(str(field_name)) + r'\b'
                    expression = re.sub(pattern, str(value), expression)
            
            print(f"   Expression after replacement: {expression}")
            
            # Safely evaluate (only allow basic math operations)
            allowed_chars = set('0123456789+-*/(). ')
            if not all(c in allowed_chars for c in expression):
                raise ValueError("Formula contains invalid characters")
            
            result = eval(expression)
            return float(result) if result is not None else 0.0
        except (ValueError, TypeError, ZeroDivisionError) as e:
            raise ValueError(f"Error evaluating formula '{formula}': {str(e)}")
        except Exception as e:
            raise ValueError(f"Unexpected error evaluating formula: {str(e)}")
    
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
        if not isinstance(extracted_data, dict):
            extracted_data = {}
        
        # Handle dependencies - could be JSONB string or already parsed
        dependencies_raw = template.get('dependencies', [])
        if isinstance(dependencies_raw, str):
            try:
                import json
                dependencies = json.loads(dependencies_raw)
            except:
                dependencies = []
        else:
            dependencies = dependencies_raw if isinstance(dependencies_raw, list) else []
        
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
            
            # Extract JSON - safely handle split operations
            if '```json' in result_text:
                parts = result_text.split('```json')
                if len(parts) > 1:
                    json_part = parts[1].split('```')[0] if '```' in parts[1] else parts[1]
                    result_text = json_part
            elif '```' in result_text:
                parts = result_text.split('```')
                if len(parts) > 1:
                    result_text = parts[1]
            
            llm_issues = json.loads(result_text.strip())
            
            # Format issues
            for issue in llm_issues:
                issues.append({
                    'check_type': 'cross_reference',
                    'status': 'fail',
                    'severity': issue.get('severity', 'high'),
                    'field_name': issue.get('field_name', 'unknown'),
                    'issue_description': issue.get('issue_description', ''),
                    'expected_value': issue.get('expected_value', 'See description'),
                    'actual_value': issue.get('actual_value', 'See description'),
                    'form_reference': template.get('form_code', 'Unknown'),
                    'resolution_suggestion': f"Verify cross-reference: {issue.get('issue_description', 'Unknown issue')}"
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
        jurisdiction = document.get('jurisdiction', '')
        form_code = document.get('form_code', '')
        
        # Create search query for jurisdiction requirements
        query = f"Filing requirements for {form_code} in {jurisdiction}"
        query_embedding = await self.vectorizer.embed(query)
        
        # Validate embedding
        if not query_embedding or not isinstance(query_embedding, list) or len(query_embedding) == 0:
            print(f"⚠️ Warning: Invalid embedding for jurisdiction check, skipping")
            return issues
        
        # Convert embedding list to string format for pgvector
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Search for relevant laws
        try:
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Use embedding_str directly in SQL to avoid parameter binding issues with pgvector
            cursor.execute(f"""
                SELECT 
                    id,
                    chunk_text,
                    section_reference,
                    document_title
                FROM tax_laws
                WHERE jurisdiction = %s
                AND law_category LIKE '%%filing%%'
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT 5
            """, (jurisdiction,))
            
            relevant_laws = cursor.fetchall()
            cursor.close()
        except Exception as sql_error:
            print(f"❌ SQL error in jurisdiction check: {sql_error}")
            print(f"   Embedding length: {len(query_embedding) if query_embedding else 0}")
            print(f"   Embedding str length: {len(embedding_str) if 'embedding_str' in locals() else 0}")
            import traceback
            traceback.print_exc()
            return issues
        
        if not relevant_laws:
            return issues
        
        # Convert RealDictRow to dict if needed
        laws_list = []
        for law in relevant_laws:
            if hasattr(law, 'keys'):
                laws_list.append(dict(law))
            elif isinstance(law, (list, tuple)):
                # Handle tuple - this shouldn't happen with RealDictCursor, but just in case
                continue
            else:
                laws_list.append(law)
        
        relevant_laws = laws_list
        
        # Use LLM to check against laws
        laws_context = "\n\n---\n\n".join([
            f"Law {law.get('id', 'unknown')}: {law.get('section_reference', 'N/A')}\n{law.get('chunk_text', '')}"
            for law in relevant_laws
            if isinstance(law, dict) or hasattr(law, 'keys')
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
                    'issue_description': issue.get('issue_description', ''),
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
        if not issues:
            return
        
        cursor = self.db.cursor()
        
        for issue in issues:
            try:
                if not isinstance(issue, dict):
                    print(f"⚠️ Skipping invalid issue (not a dict): {type(issue)}")
                    continue
                
                cursor.execute("""
                    INSERT INTO completeness_checks (
                        document_id, check_type, status, severity,
                        field_name, issue_description, expected_value,
                        actual_value, form_reference, resolution_suggestion
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    document_id,
                    issue.get('check_type', 'unknown'),
                    issue.get('status', 'fail'),
                    issue.get('severity', 'medium'),
                    issue.get('field_name'),
                    issue.get('issue_description', ''),
                    issue.get('expected_value'),
                    issue.get('actual_value'),
                    issue.get('form_reference'),
                    issue.get('resolution_suggestion')
                ))
            except Exception as e:
                print(f"❌ Error storing issue: {e}, issue: {issue}")
                import traceback
                traceback.print_exc()
        
        try:
            self.db.commit()
        except Exception as e:
            print(f"❌ Error committing issues: {e}")
            self.db.rollback()
        finally:
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