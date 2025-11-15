# services/workflow2/comparison_engine.py

import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import psycopg2.extras
from datetime import datetime
import uuid

class JurisdictionComparisonEngine:
    """
    Workflow 2: Jurisdiction Comparison Engine
    
    Helps CAs understand differences between jurisdictions:
    - Side-by-side rule comparisons
    - Highlight what's different/missing
    - Identify unique requirements
    - Generate learning checklists
    """
    
    def __init__(
        self,
        db_connection,
        vectorizer,
        gemini_api_key: str
    ):
        self.db = db_connection
        self.vectorizer = vectorizer
        if not gemini_api_key:
            print("⚠️ WARNING: GEMINI_API_KEY is not set! LLM calls will fail.")
        else:
            genai.configure(api_key=gemini_api_key)
            # Use model from config, fallback to gemini-2.5-flash (stable, available)
            from config import Config
            model_name = Config.GEMINI_GENERATION_MODEL or 'gemini-2.5-flash'
            # Remove 'models/' prefix if present (generation models don't use it)
            if model_name.startswith('models/'):
                model_name = model_name.replace('models/', '')
            # Try gemini-pro if gemini-1.5-pro fails (for compatibility)
            # The SDK will automatically add 'models/' prefix
            print(f"🤖 Initializing Gemini model: {model_name} with API key: {'*' * 10 + gemini_api_key[-4:] if gemini_api_key else 'NOT SET'}")
            try:
                self.model = genai.GenerativeModel(model_name)
            except Exception as e:
                print(f"⚠️  Failed to initialize {model_name}, trying gemini-2.5-flash as fallback...")
                try:
                    # Fallback to gemini-2.5-flash (stable, widely available)
                    self.model = genai.GenerativeModel('gemini-2.5-flash')
                    print(f"✅ Using fallback model: gemini-2.5-flash")
                except Exception as e2:
                    print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                    try:
                        self.model = genai.GenerativeModel('gemini-2.0-flash-001')
                        print(f"✅ Using fallback model: gemini-2.0-flash-001")
                    except Exception as e3:
                        print(f"⚠️  gemini-2.0-flash-001 also failed, trying gemini-flash-latest...")
                        try:
                            self.model = genai.GenerativeModel('gemini-flash-latest')
                            print(f"✅ Using fallback model: gemini-flash-latest")
                        except Exception as e4:
                            print(f"❌ All model initialization failed!")
                            print(f"   Please check your GEMINI_API_KEY")
                            raise e
    
    async def create_comparison(
        self,
        base_jurisdiction: str,
        target_jurisdiction: str,
        scope: str = 'individual_income',
        tax_year: int = None,
        requested_by: str = None
    ) -> Dict[str, Any]:
        """
        Create a comprehensive jurisdiction comparison
        
        Args:
            base_jurisdiction: What CA knows (e.g., 'US-NY')
            target_jurisdiction: What CA wants to learn (e.g., 'EU-DE')
            scope: Type of tax ('individual_income', 'corporate', 'vat')
            tax_year: Specific year (defaults to current)
            requested_by: User identifier
        
        Returns:
            Complete comparison with all differences highlighted
        """
        
        if tax_year is None:
            tax_year = datetime.now().year
        
        comparison_id = f"COMP-{uuid.uuid4().hex[:8].upper()}"
        
        print(f"🔍 Creating comparison: {base_jurisdiction} vs {target_jurisdiction}")
        print(f"   Scope: {scope}, Year: {tax_year}")
        
        # 1. Extract rules from both jurisdictions
        # Ensure database connection is fresh
        if self.db.closed:
            print("⚠️ Database connection closed, attempting to reconnect...")
            raise ConnectionError("Database connection is closed - please retry the request")
        
        print(f"🔍 Database connection status: {'OPEN' if not self.db.closed else 'CLOSED'}")
        
        base_rules = await self._extract_jurisdiction_rules(
            base_jurisdiction, scope, tax_year
        )
        
        target_rules = await self._extract_jurisdiction_rules(
            target_jurisdiction, scope, tax_year
        )
        
        print(f"📋 Base rules: {len(base_rules)} sections")
        print(f"📋 Target rules: {len(target_rules)} sections")
        
        if not base_rules and not target_rules:
            print("⚠️ No rules found for either jurisdiction - cannot compare")
            return {
                'comparison_id': comparison_id,
                'base_jurisdiction': base_jurisdiction,
                'target_jurisdiction': target_jurisdiction,
                'scope': scope,
                'tax_year': tax_year,
                'created_at': datetime.now().isoformat(),
                'total_differences': 0,
                'critical_differences': 0,
                'important_differences': 0,
                'differences': [],
                'learning_checklist': [],
                'note': 'No rules found in knowledge base for these jurisdictions'
            }
        
        # 2. Perform intelligent comparison using LLM
        differences = await self._compare_rules_with_llm(
            base_jurisdiction,
            target_jurisdiction,
            base_rules,
            target_rules,
            scope
        )
        
        print(f"✅ Found {len(differences)} key differences")
        
        # 3. Store comparison results
        await self._store_comparison(
            comparison_id,
            base_jurisdiction,
            target_jurisdiction,
            scope,
            tax_year,
            requested_by,
            differences
        )
        
        # 4. Generate learning checklist
        checklist = await self._generate_learning_checklist(
            base_jurisdiction,
            target_jurisdiction,
            differences
        )
        
        # 5. Create summary
        summary = {
            'comparison_id': comparison_id,
            'base_jurisdiction': base_jurisdiction,
            'target_jurisdiction': target_jurisdiction,
            'scope': scope,
            'tax_year': tax_year,
            'created_at': datetime.now().isoformat(),
            'total_differences': len(differences),
            'critical_differences': len([d for d in differences if d['impact_level'] == 'critical']),
            'important_differences': len([d for d in differences if d['impact_level'] == 'important']),
            'differences': differences,
            'learning_checklist': checklist
        }
        
        return summary
    
    async def _extract_jurisdiction_rules(
        self,
        jurisdiction: str,
        scope: str,
        tax_year: int
    ) -> List[Dict]:
        """
        Extract key rules for a jurisdiction using vector search
        """
        
        # Create search queries for different aspects
        search_queries = [
            f"{scope} tax filing requirements in {jurisdiction}",
            f"{scope} tax rates and brackets in {jurisdiction}",
            f"{scope} tax deductions and credits in {jurisdiction}",
            f"{scope} tax payment deadlines in {jurisdiction}",
            f"{scope} required forms and schedules in {jurisdiction}"
        ]
        
        all_rules = []
        
        for query in search_queries:
            query_embedding = await self.vectorizer.embed(query)
            
            # Convert embedding list to string format for pgvector
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            print(f"   Searching for: {query[:60]}...")
            # Query with date filtering - but allow NULL dates (for documents without dates)
            # Use f-string for embedding to avoid parameter binding issues with pgvector
            cursor.execute(f"""
                SELECT 
                    id,
                    jurisdiction,
                    law_category,
                    document_title,
                    chunk_text,
                    section_reference,
                    metadata,
                    1 - (embedding <=> '{embedding_str}'::vector) as similarity
                FROM tax_laws
                WHERE jurisdiction = %s
                AND (
                    effective_date IS NULL 
                    OR effective_date <= %s::date
                )
                AND (
                    expiry_date IS NULL 
                    OR expiry_date > %s::date
                )
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT 10
            """, (
                jurisdiction,
                f"{tax_year}-12-31",
                f"{tax_year}-01-01"
            ))
            
            results = cursor.fetchall()
            cursor.close()
            
            print(f"   Found {len(results)} results for query")
            
            for row in results:
                all_rules.append({
                    'id': row['id'],
                    'category': row['law_category'],
                    'title': row['document_title'],
                    'text': row['chunk_text'],
                    'section': row['section_reference'],
                    'similarity': row['similarity'],
                    'query_context': query
                })
        
        # Deduplicate based on ID
        seen_ids = set()
        unique_rules = []
        for rule in all_rules:
            if rule['id'] not in seen_ids:
                seen_ids.add(rule['id'])
                unique_rules.append(rule)
        
        print(f"📋 Extracted {len(unique_rules)} unique rules for {jurisdiction}")
        return unique_rules
    
    async def _compare_rules_with_llm(
        self,
        base_jurisdiction: str,
        target_jurisdiction: str,
        base_rules: List[Dict],
        target_rules: List[Dict],
        scope: str
    ) -> List[Dict]:
        """
        Use LLM to intelligently compare rules and identify differences
        """
        
        # Check if we have rules to compare
        if not base_rules:
            print(f"⚠️ No rules found for base jurisdiction {base_jurisdiction}")
            return []
        if not target_rules:
            print(f"⚠️ No rules found for target jurisdiction {target_jurisdiction}")
            return []
        
        # Prepare context
        base_context = "\n\n".join([
            f"[{rule['category']}] {rule['section']}\n{rule['text'][:500]}"
            for rule in base_rules[:15]  # Limit to avoid token overflow
        ])
        
        target_context = "\n\n".join([
            f"[{rule['category']}] {rule['section']}\n{rule['text'][:500]}"
            for rule in target_rules[:15]
        ])
        
        print(f"📝 Comparing {len(base_rules)} base rules vs {len(target_rules)} target rules")
        
        prompt = f"""You are a tax expert helping a CA who knows {base_jurisdiction} tax law learn about {target_jurisdiction} tax law.

SCOPE: {scope}

{base_jurisdiction.upper()} TAX RULES:
{base_context}

{target_jurisdiction.upper()} TAX RULES:
{target_context}

TASK:
Compare these two jurisdictions and identify KEY DIFFERENCES that a tax professional must know. Focus on:
1. CRITICAL differences that could lead to errors (different filing requirements, calculation methods)
2. IMPORTANT differences that affect most taxpayers (rate structures, common deductions)
3. INFORMATIONAL differences (terminology, form names)

IMPORTANT: You MUST identify at least 3-5 key differences. Even if the jurisdictions are similar, find meaningful differences in:
- Tax rates or brackets
- Deduction amounts or eligibility
- Filing deadlines
- Required forms
- Calculation methods
- Exemptions or thresholds

For EACH difference, provide:
- difference_type: 'filing_deadline', 'tax_rate', 'deduction', 'credit', 'form_requirement', 'calculation_method', 'threshold', 'exemption'
- category: High-level category (e.g., 'rates', 'deductions', 'filing')
- base_rule: How it works in {base_jurisdiction} (be specific with numbers/percentages if applicable)
- target_rule: How it works in {target_jurisdiction} (be specific with numbers/percentages if applicable)
- impact_level: 'critical', 'important', or 'informational'
- explanation: Clear explanation of the difference and why it matters
- examples: Array of practical examples showing the difference

Focus on PRACTICAL, ACTIONABLE differences. Skip theoretical or rarely-applicable rules.

CRITICAL: Return ONLY a valid JSON array. Do not include any explanatory text before or after the JSON.
The response must start with [ and end with ].

Example format:
[
  {{
    "difference_type": "tax_rate",
    "category": "rates",
    "base_rule": "NY has progressive rates from 4% to 10.9%",
    "target_rule": "CA has progressive rates from 1% to 13.3%",
    "impact_level": "critical",
    "explanation": "CA has higher top marginal rate, affecting high-income taxpayers",
    "examples": ["A taxpayer earning $200,000 would pay 10.9% in NY vs 13.3% in CA on income above $1M"]
  }},
  {{
    "difference_type": "deduction",
    "category": "deductions",
    "base_rule": "NY standard deduction is $8,000 for single filers",
    "target_rule": "CA standard deduction is $5,202 for single filers",
    "impact_level": "important",
    "explanation": "NY offers higher standard deduction, reducing taxable income more",
    "examples": ["Single filer in NY can deduct $2,798 more than in CA"]
  }}
]
"""
        
        try:
            print(f"🤖 Calling LLM for comparison...")
            print(f"   Base rules: {len(base_rules)} sections")
            print(f"   Target rules: {len(target_rules)} sections")
            print(f"   Base context length: {len(base_context)} chars")
            print(f"   Target context length: {len(target_context)} chars")
            
            # Check if context is too short (might indicate no relevant rules)
            if len(base_context) < 100:
                print(f"⚠️  WARNING: Base context is very short ({len(base_context)} chars) - may not have relevant rules")
            if len(target_context) < 100:
                print(f"⚠️  WARNING: Target context is very short ({len(target_context)} chars) - may not have relevant rules")
            
            # Try to generate content, with fallback if model not available
            try:
                response = self.model.generate_content(prompt)
                result_text = response.text
            except Exception as model_error:
                error_str = str(model_error)
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                    # Try gemini-2.5-flash first (stable, widely available)
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                        response = fallback_model.generate_content(prompt)
                        result_text = response.text
                        print(f"✅ Successfully used fallback model: gemini-2.5-flash")
                    except Exception as e2:
                        print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                        # Try gemini-2.0-flash-001 as second fallback
                        try:
                            fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                            print(f"✅ Successfully used fallback model: gemini-2.0-flash-001")
                        except Exception as e3:
                            print(f"⚠️  gemini-2.0-flash-001 also failed, trying gemini-flash-latest...")
                            # Try gemini-flash-latest as third fallback
                            try:
                                fallback_model = genai.GenerativeModel('gemini-flash-latest')
                                response = fallback_model.generate_content(prompt)
                                result_text = response.text
                                print(f"✅ Successfully used fallback model: gemini-flash-latest")
                            except Exception as e4:
                                print(f"❌ All model fallbacks failed!")
                                print(f"   Original error: {error_str}")
                                print(f"   gemini-2.5-flash error: {str(e2)}")
                                print(f"   gemini-2.0-flash-001 error: {str(e3)}")
                                print(f"   gemini-flash-latest error: {str(e4)}")
                                print(f"   Please check your GEMINI_API_KEY and available models")
                                raise model_error  # Re-raise original error
                else:
                    # Re-raise if it's a different error
                    raise
            print(f"✅ LLM response received ({len(result_text)} chars)")
            print(f"   First 300 chars: {result_text[:300]}")
            
            # Save original for debugging
            original_text = result_text
            
            # Extract JSON - improved parsing
            if '```json' in result_text:
                parts = result_text.split('```json')
                if len(parts) > 1:
                    json_part = parts[1].split('```')[0] if '```' in parts[1] else parts[1]
                    result_text = json_part
                    print(f"   Found ```json block, extracted {len(result_text)} chars")
            elif '```' in result_text:
                parts = result_text.split('```')
                if len(parts) > 1:
                    result_text = parts[1]
                    print(f"   Found ``` block, extracted {len(result_text)} chars")
            
            # Clean up the JSON string
            result_text = result_text.strip()
            result_text = result_text.strip(' \n\r\t')
            
            # Try to find JSON array in the text if it's not at the start
            if not result_text.startswith('['):
                print(f"   ⚠️  Response doesn't start with '[', searching for array pattern...")
                import re
                array_match = re.search(r'\[.*\]', result_text, re.DOTALL)
                if array_match:
                    result_text = array_match.group(0)
                    print(f"   ✅ Found array pattern, length: {len(result_text)}")
                else:
                    print(f"   ❌ No array pattern found in response")
                    print(f"   Full response (first 1000 chars): {original_text[:1000]}")
            
            print(f"🔍 Attempting to parse JSON (length: {len(result_text)})")
            print(f"   First 500 chars: {result_text[:500]}")
            
            # Try to parse JSON
            try:
                differences = json.loads(result_text)
            except json.JSONDecodeError as parse_error:
                print(f"❌ JSON parsing failed: {parse_error}")
                print(f"   Error at position: {parse_error.pos if hasattr(parse_error, 'pos') else 'unknown'}")
                print(f"   Text around error: {result_text[max(0, parse_error.pos-50):parse_error.pos+50] if hasattr(parse_error, 'pos') else 'N/A'}")
                print(f"   Full response (first 1500 chars): {original_text[:1500]}")
                raise  # Re-raise to be caught by outer except
            
            # Validate differences structure
            if not isinstance(differences, list):
                print(f"⚠️  WARNING: LLM returned non-list type: {type(differences)}")
                if isinstance(differences, dict):
                    print(f"   Converting dict to list...")
                    differences = [differences]
                else:
                    print(f"   Cannot convert {type(differences)} to list, returning empty")
                    differences = []
            
            print(f"✅ Parsed {len(differences)} differences from LLM")
            
            if len(differences) == 0:
                print(f"⚠️  ⚠️  ⚠️  CRITICAL: LLM returned empty differences array!")
                print(f"   Original response length: {len(original_text)}")
                print(f"   Parsed text length: {len(result_text)}")
                print(f"   Full original response:")
                print(f"   {'='*80}")
                print(f"   {original_text}")
                print(f"   {'='*80}")
                print(f"   This could mean:")
                print(f"   1. LLM couldn't find differences (jurisdictions too similar?)")
                print(f"   2. LLM response format issue")
                print(f"   3. Prompt needs adjustment")
            else:
                # Validate each difference has required fields
                valid_differences = []
                for i, diff in enumerate(differences):
                    if not isinstance(diff, dict):
                        print(f"   ⚠️  Difference {i} is not a dict: {type(diff)}")
                        continue
                    required_fields = ['difference_type', 'category', 'base_rule', 'target_rule', 'impact_level']
                    missing = [f for f in required_fields if f not in diff]
                    if missing:
                        print(f"   ⚠️  Difference {i} missing fields: {missing}")
                        continue
                    valid_differences.append(diff)
                
                if len(valid_differences) < len(differences):
                    print(f"   ⚠️  Filtered {len(differences) - len(valid_differences)} invalid differences")
                differences = valid_differences
            
            # Enrich with law IDs
            for diff in differences:
                # Find matching base and target law IDs
                diff['base_law_ids'] = [r['id'] for r in base_rules[:5]]
                diff['target_law_ids'] = [r['id'] for r in target_rules[:5]]
            
            return differences
            
        except json.JSONDecodeError as json_error:
            print(f"❌ JSON parsing error: {json_error}")
            print(f"   Error details: {str(json_error)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000]}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500]}")
            import traceback
            traceback.print_exc()
            return []
        except Exception as e:
            print(f"❌ Error comparing with LLM: {type(e).__name__}: {e}")
            print(f"   Error details: {str(e)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000] if 'result_text' in locals() else 'N/A'}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500] if 'original_text' in locals() else 'N/A'}")
            import traceback
            traceback.print_exc()
            return []
    
    async def research_specific_topic(
        self,
        base_jurisdiction: str,
        target_jurisdiction: str,
        topic: str,
        tax_year: int = None
    ) -> Dict[str, Any]:
        """
        Deep dive into a specific topic comparison
        
        Example: "What are the home office deduction rules?"
        """
        
        if tax_year is None:
            tax_year = datetime.now().year
        
        print(f"🔬 Researching: {topic}")
        print(f"   {base_jurisdiction} vs {target_jurisdiction}")
        
        # Search both jurisdictions for this specific topic
        query_embedding = await self.vectorizer.embed(topic)
        
        base_results = await self._search_jurisdiction_topic(
            base_jurisdiction, query_embedding, tax_year
        )
        
        target_results = await self._search_jurisdiction_topic(
            target_jurisdiction, query_embedding, tax_year
        )
        
        # Generate detailed comparison
        comparison = await self._generate_topic_comparison(
            base_jurisdiction,
            target_jurisdiction,
            topic,
            base_results,
            target_results
        )
        
        return {
            'topic': topic,
            'base_jurisdiction': base_jurisdiction,
            'target_jurisdiction': target_jurisdiction,
            'tax_year': tax_year,
            'comparison': comparison,
            'base_sources': [{'id': r['id'], 'section': r['section_reference']} for r in base_results],
            'target_sources': [{'id': r['id'], 'section': r['section_reference']} for r in target_results]
        }
    
    async def _search_jurisdiction_topic(
        self,
        jurisdiction: str,
        query_embedding,
        tax_year: int,
        limit: int = 10
    ) -> List[Dict]:
        """Search for topic in specific jurisdiction"""
        
        # Convert embedding list to string format for pgvector
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Use f-string for embedding to avoid parameter binding issues with pgvector
        cursor.execute(f"""
            SELECT 
                id,
                jurisdiction,
                law_category,
                document_title,
                chunk_text,
                section_reference,
                1 - (embedding <=> '{embedding_str}'::vector) as similarity
            FROM tax_laws
            WHERE jurisdiction = %s
            AND (
                effective_date IS NULL 
                OR effective_date <= %s::date
            )
            AND (
                expiry_date IS NULL 
                OR expiry_date > %s::date
            )
            ORDER BY embedding <=> '{embedding_str}'::vector
            LIMIT %s
        """, (
            jurisdiction,
            f"{tax_year}-12-31",
            f"{tax_year}-01-01",
            limit
        ))
        
        results = cursor.fetchall()
        cursor.close()
        
        return [dict(row) for row in results]
    
    async def _generate_topic_comparison(
        self,
        base_jurisdiction: str,
        target_jurisdiction: str,
        topic: str,
        base_results: List[Dict],
        target_results: List[Dict]
    ) -> str:
        """Generate detailed topic comparison"""
        
        base_context = "\n\n".join([
            f"{r['section_reference']}\n{r['chunk_text']}"
            for r in base_results[:5]
        ])
        
        target_context = "\n\n".join([
            f"{r['section_reference']}\n{r['chunk_text']}"
            for r in target_results[:5]
        ])
        
        prompt = f"""You are a tax expert. Provide a detailed comparison of how "{topic}" is handled in two different jurisdictions.

{base_jurisdiction.upper()} RULES:
{base_context}

{target_jurisdiction.upper()} RULES:
{target_context}

TASK:
Write a clear, practical comparison that helps a CA who knows {base_jurisdiction} understand {target_jurisdiction}.

Format your response as:

## {base_jurisdiction.upper()} Approach
[Explain how it works here]

## {target_jurisdiction.upper()} Approach
[Explain how it works here]

## Key Differences
1. [Difference 1]
2. [Difference 2]
...

## Practical Implications
[What the CA needs to know when preparing returns]

## Example Scenario
[Real-world example showing the difference]

Keep it practical and action-oriented. Focus on what matters for preparing accurate tax returns.
"""
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            error_str = str(e)
            if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                try:
                    # Try gemini-2.5-flash first
                    fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                    response = fallback_model.generate_content(prompt)
                    return response.text
                except Exception as e2:
                    print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                        response = fallback_model.generate_content(prompt)
                        return response.text
                    except Exception as e3:
                        print(f"⚠️  gemini-2.0-flash-001 also failed, trying gemini-flash-latest...")
                        try:
                            fallback_model = genai.GenerativeModel('gemini-flash-latest')
                            response = fallback_model.generate_content(prompt)
                            return response.text
                        except Exception as e4:
                            return f"Error generating comparison: All models failed. Original: {str(e)}, 2.5-flash: {str(e2)}, 2.0-flash: {str(e3)}, latest: {str(e4)}"
            return f"Error generating comparison: {str(e)}"
    
    async def _generate_learning_checklist(
        self,
        base_jurisdiction: str,
        target_jurisdiction: str,
        differences: List[Dict]
    ) -> List[Dict]:
        """
        Generate a checklist for CA to learn target jurisdiction
        """
        
        checklist = []
        
        # Group by category
        categories = {}
        for diff in differences:
            cat = diff.get('category', 'general')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(diff)
        
        # Create checklist items
        for category, items in categories.items():
            critical_items = [i for i in items if i['impact_level'] == 'critical']
            important_items = [i for i in items if i['impact_level'] == 'important']
            
            if critical_items:
                checklist.append({
                    'category': category,
                    'priority': 'high',
                    'title': f"Master {category} differences (CRITICAL)",
                    'item_count': len(critical_items),
                    'action': f"Review and understand all {len(critical_items)} critical differences in {category}",
                    'items': [item['explanation'] for item in critical_items]
                })
            
            if important_items:
                checklist.append({
                    'category': category,
                    'priority': 'medium',
                    'title': f"Learn {category} variations",
                    'item_count': len(important_items),
                    'action': f"Familiarize yourself with {len(important_items)} important differences in {category}",
                    'items': [item['explanation'] for item in important_items]
                })
        
        # Sort by priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        checklist.sort(key=lambda x: priority_order.get(x['priority'], 3))
        
        return checklist
    
    async def _store_comparison(
        self,
        comparison_id: str,
        base_jurisdiction: str,
        target_jurisdiction: str,
        scope: str,
        tax_year: int,
        requested_by: Optional[str],
        differences: List[Dict]
    ):
        """Store comparison results in database"""
        
        # Check if connection is closed
        if self.db.closed:
            print("⚠️ Database connection closed, cannot store comparison")
            raise ConnectionError("Database connection is closed - cannot store comparison")
        
        try:
            cursor = self.db.cursor()
            
            # Store main comparison
            print(f"💾 Storing comparison {comparison_id} with {len(differences)} differences...")
            cursor.execute("""
            INSERT INTO jurisdiction_comparisons (
                comparison_id, base_jurisdiction, target_jurisdiction,
                comparison_scope, tax_year, requested_by, comparison_results
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            comparison_id,
            base_jurisdiction,
            target_jurisdiction,
            scope,
            tax_year,
            requested_by,
            psycopg2.extras.Json({'differences': differences})
            ))
            
            # Store individual differences
            stored_count = 0
            for diff in differences:
                if not isinstance(diff, dict):
                    print(f"⚠️ Skipping invalid difference (not a dict): {type(diff)}")
                    continue
                
                try:
                    cursor.execute("""
                        INSERT INTO jurisdiction_differences (
                            comparison_id, difference_type, category,
                            base_rule, target_rule, impact_level, explanation, examples
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        comparison_id,
                        diff.get('difference_type', 'unknown'),
                        diff.get('category', 'general'),
                        diff.get('base_rule', ''),
                        diff.get('target_rule', ''),
                        diff.get('impact_level', 'informational'),
                        diff.get('explanation', ''),
                        psycopg2.extras.Json(diff.get('examples', []))
                    ))
                    stored_count += 1
                except Exception as diff_error:
                    print(f"⚠️ Error storing individual difference: {diff_error}")
                    print(f"   Difference: {diff}")
                    continue
            
            self.db.commit()
            cursor.close()
            
            print(f"✅ Stored comparison {comparison_id} with {stored_count}/{len(differences)} differences")
        except Exception as store_error:
            print(f"❌ Error storing comparison: {store_error}")
            import traceback
            traceback.print_exc()
            self.db.rollback()
            raise