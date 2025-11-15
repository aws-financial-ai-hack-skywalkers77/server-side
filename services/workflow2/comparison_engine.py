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
            # Use model from config, fallback to gemini-1.5-pro
            from config import Config
            model_name = Config.GEMINI_GENERATION_MODEL or 'gemini-1.5-pro'
            # Remove 'models/' prefix if present (generation models don't use it)
            if model_name.startswith('models/'):
                model_name = model_name.replace('models/', '')
            print(f"🤖 Initializing Gemini model: {model_name} with API key: {'*' * 10 + gemini_api_key[-4:] if gemini_api_key else 'NOT SET'}")
            self.model = genai.GenerativeModel(model_name)
    
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
            # Try to get a fresh connection - this requires access to the connection getter
            # For now, raise an error and let the endpoint handle reconnection
            raise ConnectionError("Database connection is closed - please retry the request")
        
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
            cursor.execute("""
                SELECT 
                    id,
                    jurisdiction,
                    law_category,
                    document_title,
                    chunk_text,
                    section_reference,
                    metadata,
                    1 - (embedding <=> %s::vector) as similarity
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
                ORDER BY embedding <=> %s::vector
                LIMIT 10
            """, (
                embedding_str,
                jurisdiction,
                f"{tax_year}-12-31",
                f"{tax_year}-01-01",
                embedding_str
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

For EACH difference, provide:
- difference_type: 'filing_deadline', 'tax_rate', 'deduction', 'credit', 'form_requirement', 'calculation_method', 'threshold', 'exemption'
- category: High-level category (e.g., 'rates', 'deductions', 'filing')
- base_rule: How it works in {base_jurisdiction}
- target_rule: How it works in {target_jurisdiction}
- impact_level: 'critical', 'important', or 'informational'
- explanation: Clear explanation of the difference and why it matters
- examples: Practical example showing the difference

Focus on PRACTICAL, ACTIONABLE differences. Skip theoretical or rarely-applicable rules.

Return as JSON array:
[
  {{
    "difference_type": "...",
    "category": "...",
    "base_rule": "...",
    "target_rule": "...",
    "impact_level": "...",
    "explanation": "...",
    "examples": ["..."]
  }}
]
"""
        
        try:
            print(f"🤖 Calling LLM for comparison...")
            print(f"   Base rules: {len(base_rules)} sections")
            print(f"   Target rules: {len(target_rules)} sections")
            response = self.model.generate_content(prompt)
            result_text = response.text
            print(f"✅ LLM response received ({len(result_text)} chars)")
            print(f"   First 200 chars: {result_text[:200]}")
            
            # Extract JSON
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            differences = json.loads(result_text.strip())
            print(f"✅ Parsed {len(differences)} differences from LLM")
            if len(differences) == 0:
                print(f"⚠️  WARNING: LLM returned empty differences array")
                print(f"   Full response: {result_text[:500]}")
            
            # Enrich with law IDs
            for diff in differences:
                # Find matching base and target law IDs
                diff['base_law_ids'] = [r['id'] for r in base_rules[:5]]
                diff['target_law_ids'] = [r['id'] for r in target_rules[:5]]
            
            return differences
            
        except json.JSONDecodeError as json_error:
            print(f"❌ JSON parsing error: {json_error}")
            print(f"   Response text: {result_text[:500] if 'result_text' in locals() else 'N/A'}")
            import traceback
            traceback.print_exc()
            return []
        except Exception as e:
            print(f"❌ Error comparing with LLM: {e}")
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
        
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT 
                id,
                jurisdiction,
                law_category,
                document_title,
                chunk_text,
                section_reference,
                1 - (embedding <=> %s::vector) as similarity
            FROM tax_laws
            WHERE jurisdiction = %s
            AND effective_date <= %s::date
            AND (expiry_date IS NULL OR expiry_date > %s::date)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (
            query_embedding,
            jurisdiction,
            f"{tax_year}-12-31",
            f"{tax_year}-01-01",
            query_embedding,
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
            return  # Skip storage if connection is closed
        
        cursor = self.db.cursor()
        
        # Store main comparison
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
        for diff in differences:
            cursor.execute("""
                INSERT INTO jurisdiction_differences (
                    comparison_id, difference_type, category,
                    base_rule, target_rule, impact_level, explanation, examples
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                comparison_id,
                diff.get('difference_type'),
                diff.get('category'),
                diff.get('base_rule'),
                diff.get('target_rule'),
                diff.get('impact_level'),
                diff.get('explanation'),
                psycopg2.extras.Json(diff.get('examples', []))
            ))
        
        self.db.commit()
        cursor.close()
        
        print(f"✅ Stored comparison {comparison_id}")