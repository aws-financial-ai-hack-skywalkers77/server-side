# services/workflow3/planning_engine.py

import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import psycopg2.extras
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)

class MultiJurisdictionPlanningEngine:
    """
    Workflow 3: Multi-Jurisdiction Tax Planning
    
    Helps CAs with clients who have income/operations in multiple jurisdictions:
    - Identify tax treaty opportunities
    - Calculate potential double taxation
    - Suggest optimal structures
    - Flag reporting requirements
    - Generate compliance timeline
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
        
        # Use model from config, fallback to gemini-2.5-flash
        from config import Config
        model_name = Config.GEMINI_GENERATION_MODEL or 'gemini-2.5-flash'
        # Remove 'models/' prefix if present (generation models don't use it)
        if model_name.startswith('models/'):
            model_name = model_name.replace('models/', '')
        print(f"🤖 Initializing Gemini model: {model_name} with API key: {'*' * 10 + gemini_api_key[-4:] if gemini_api_key else 'NOT SET'}")
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
    
    async def create_planning_scenario(
        self,
        client_id: str,
        client_name: str,
        scenario_name: str,
        jurisdictions_involved: List[str],
        income_sources: List[Dict],
        objectives: List[str],
        tax_year: int = None
    ) -> Dict[str, Any]:
        """
        Create a comprehensive multi-jurisdiction tax planning scenario
        
        Args:
            client_id: Unique client identifier
            client_name: Client name
            scenario_name: Description of scenario
            jurisdictions_involved: List of jurisdictions ['US-NY', 'EU-DE', 'UK']
            income_sources: List of income sources with details:
                [
                    {
                        'type': 'employment',
                        'jurisdiction': 'US-NY',
                        'amount_range': '100000-150000',
                        'description': 'Software engineer salary'
                    },
                    {
                        'type': 'rental_income',
                        'jurisdiction': 'EU-DE',
                        'amount_range': '30000-50000',
                        'description': 'Apartment rental'
                    }
                ]
            objectives: What client wants to optimize ['minimize_tax', 'compliance', 'simplicity']
            tax_year: Year for planning
        
        Returns:
            Comprehensive planning analysis with recommendations
        """
        
        if tax_year is None:
            tax_year = datetime.now().year
        
        scenario_id = f"PLAN-{uuid.uuid4().hex[:8].upper()}"
        
        print(f"📊 Creating planning scenario: {scenario_name}")
        print(f"   Client: {client_name}")
        print(f"   Jurisdictions: {', '.join(jurisdictions_involved)}")
        print(f"   Income sources: {len(income_sources)}")
        
        # 1. Analyze applicable tax treaties
        try:
            print(f"🔍 Step 1: Analyzing tax treaties...")
            treaty_analysis = await self._analyze_tax_treaties(
                jurisdictions_involved
            )
            print(f"✅ Found {len(treaty_analysis)} treaty analyses")
        except Exception as e:
            print(f"❌ Error analyzing treaties: {e}")
            import traceback
            traceback.print_exc()
            treaty_analysis = []
        
        # 2. Calculate tax exposures in each jurisdiction
        try:
            print(f"💰 Step 2: Calculating tax exposures...")
            tax_exposures = await self._calculate_tax_exposures(
                jurisdictions_involved,
                income_sources,
                treaty_analysis,
                tax_year
            )
            print(f"✅ Calculated {len(tax_exposures)} tax exposures")
        except Exception as e:
            print(f"❌ Error calculating tax exposures: {e}")
            import traceback
            traceback.print_exc()
            tax_exposures = []
        
        # 3. Identify reporting requirements
        try:
            reporting_requirements = await self._identify_reporting_requirements(
                jurisdictions_involved,
                income_sources,
                tax_year
            )
        except Exception as e:
            print(f"❌ Error identifying reporting requirements: {e}")
            import traceback
            traceback.print_exc()
            reporting_requirements = []
        
        # 4. Generate optimization recommendations
        try:
            print(f"💡 Step 4: Generating recommendations...")
            recommendations = await self._generate_recommendations(
                client_name,
                jurisdictions_involved,
                income_sources,
                tax_exposures,
                treaty_analysis,
                objectives
            )
            print(f"✅ Generated {len(recommendations)} recommendations")
        except Exception as e:
            print(f"❌ Error generating recommendations: {e}")
            import traceback
            traceback.print_exc()
            recommendations = []
        
        # 5. Create compliance timeline
        try:
            print(f"📅 Step 5: Creating compliance timeline...")
            compliance_timeline = await self._create_compliance_timeline(
                jurisdictions_involved,
                tax_year
            )
            print(f"✅ Created {len(compliance_timeline)} timeline items")
        except Exception as e:
            print(f"❌ Error creating compliance timeline: {e}")
            import traceback
            traceback.print_exc()
            compliance_timeline = []
        
        # 6. Store scenario in database
        try:
            print(f"💾 Storing scenario {scenario_id} in database...")
            await self._store_planning_scenario(
                scenario_id,
                client_id,
                client_name,
                scenario_name,
                jurisdictions_involved,
                income_sources,
                objectives,
                tax_year,
                {
                    'treaty_analysis': treaty_analysis,
                    'tax_exposures': tax_exposures,
                    'reporting_requirements': reporting_requirements,
                    'recommendations': recommendations,
                    'compliance_timeline': compliance_timeline
                }
            )
            print(f"✅ Successfully stored scenario {scenario_id} in database")
        except Exception as e:
            print(f"❌ Error storing scenario in database: {e}")
            import traceback
            traceback.print_exc()
            # Continue even if storage fails - scenario is still returned to user
            print(f"⚠️ Warning: Scenario {scenario_id} created but not stored in database")
            # Log the full error for debugging
            logger.error(f"Failed to store scenario {scenario_id}: {e}", exc_info=True)
        
        # 7. Generate executive summary
        try:
            # Safely calculate high priority actions
            high_priority = 0
            if recommendations and isinstance(recommendations, list):
                high_priority = len([r for r in recommendations if isinstance(r, dict) and r.get('priority') == 'critical'])
            
            # Safely calculate exposure totals
            exposure_min = 0
            exposure_max = 0
            if tax_exposures and isinstance(tax_exposures, list):
                exposure_min = sum(e.get('estimated_impact_min', 0) for e in tax_exposures if isinstance(e, dict))
                exposure_max = sum(e.get('estimated_impact_max', 0) for e in tax_exposures if isinstance(e, dict))
            
            summary = {
                'scenario_id': scenario_id,
                'client_name': client_name,
                'scenario_name': scenario_name,
                'jurisdictions': jurisdictions_involved,
                'tax_year': tax_year,
                'created_at': datetime.now().isoformat(),
                'treaty_benefits_available': len(treaty_analysis) if treaty_analysis else 0,
                'total_jurisdictions_with_exposure': len(tax_exposures) if tax_exposures else 0,
                'high_priority_actions': high_priority,
                'estimated_total_exposure_min': exposure_min,
                'estimated_total_exposure_max': exposure_max,
                'analysis': {
                    'treaties': treaty_analysis if treaty_analysis else [],
                    'exposures': tax_exposures if tax_exposures else [],
                    'reporting': reporting_requirements if reporting_requirements else [],
                    'recommendations': recommendations if recommendations else [],
                    'timeline': compliance_timeline if compliance_timeline else []
                }
            }
        except Exception as summary_error:
            print(f"❌ Error creating summary: {summary_error}")
            # Return basic summary on error
            summary = {
                'scenario_id': scenario_id,
                'client_name': client_name,
                'scenario_name': scenario_name,
                'jurisdictions': jurisdictions_involved,
                'tax_year': tax_year,
                'created_at': datetime.now().isoformat(),
                'error': f"Error generating summary: {str(summary_error)}",
                'analysis': {
                    'treaties': treaty_analysis if 'treaty_analysis' in locals() else [],
                    'exposures': tax_exposures if 'tax_exposures' in locals() else [],
                    'reporting': reporting_requirements if 'reporting_requirements' in locals() else [],
                    'recommendations': recommendations if 'recommendations' in locals() else [],
                    'timeline': compliance_timeline if 'compliance_timeline' in locals() else []
                }
            }
        
        print(f"✅ Planning scenario created: {scenario_id}")
        return summary
    
    async def _analyze_tax_treaties(
        self,
        jurisdictions: List[str]
    ) -> List[Dict]:
        """
        Identify applicable tax treaties between jurisdictions
        """
        
        treaties = []
        
        # Check all jurisdiction pairs
        for i, country_a in enumerate(jurisdictions):
            for country_b in jurisdictions[i+1:]:
                # Normalize to country codes (remove state/province)
                country_a_code = country_a.split('-')[0] if '-' in country_a else country_a
                country_b_code = country_b.split('-')[0] if '-' in country_b else country_b
                
                # Search for treaty
                cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cursor.execute("""
                    SELECT * FROM tax_treaties
                    WHERE (country_a = %s AND country_b = %s)
                       OR (country_a = %s AND country_b = %s)
                    LIMIT 1
                """, (country_a_code, country_b_code, country_b_code, country_a_code))
                
                treaty = cursor.fetchone()
                cursor.close()
                
                if treaty:
                    treaties.append({
                        'id': treaty['id'],
                        'countries': [country_a, country_b],
                        'treaty_name': treaty['treaty_name'],
                        'effective_date': str(treaty['effective_date']),
                        'key_provisions': treaty['key_provisions'],
                        'benefits': self._extract_treaty_benefits(treaty)
                    })
                else:
                    treaties.append({
                        'countries': [country_a, country_b],
                        'treaty_exists': False,
                        'implication': 'No tax treaty - potential double taxation risk'
                    })
        
        return treaties
    
    def _extract_treaty_benefits(self, treaty: Dict) -> List[str]:
        """Extract practical benefits from treaty"""
        provisions = treaty.get('key_provisions', {})
        benefits = []
        
        if 'withholding_rates' in provisions:
            benefits.append(f"Reduced withholding rates: {provisions['withholding_rates']}")
        
        if 'permanent_establishment' in provisions:
            benefits.append("Permanent establishment provisions available")
        
        if 'tax_credits' in provisions:
            benefits.append("Foreign tax credit mechanism")
        
        return benefits
    
    async def _calculate_tax_exposures(
        self,
        jurisdictions: List[str],
        income_sources: List[Dict],
        treaty_analysis: List[Dict],
        tax_year: int
    ) -> List[Dict]:
        """
        Calculate potential tax exposure in each jurisdiction
        """
        
        exposures = []
        
        print(f"💰 Calculating tax exposures for {len(jurisdictions)} jurisdictions...")
        
        for jurisdiction in jurisdictions:
            # Get income sources in this jurisdiction
            local_income = [
                inc for inc in income_sources
                if inc.get('jurisdiction') == jurisdiction
            ]
            
            if not local_income:
                print(f"   ⚠️ No income sources found for {jurisdiction}, skipping exposure calculation")
                continue
            
            print(f"   📊 Analyzing exposure for {jurisdiction} ({len(local_income)} income sources)...")
            
            # Get tax rates for this jurisdiction
            tax_rates = await self._get_tax_rates(jurisdiction, tax_year)
            
            # Use LLM to analyze exposure
            exposure_analysis = await self._analyze_jurisdiction_exposure(
                jurisdiction,
                local_income,
                income_sources,  # All income for context
                tax_rates,
                treaty_analysis
            )
            
            if exposure_analysis:
                print(f"   ✅ Exposure calculated for {jurisdiction}")
                exposures.append(exposure_analysis)
            else:
                print(f"   ⚠️ No exposure analysis returned for {jurisdiction}")
        
        print(f"💰 Total exposures calculated: {len(exposures)}")
        return exposures
    
    async def _get_tax_rates(
        self,
        jurisdiction: str,
        tax_year: int
    ) -> Optional[Dict]:
        """Get tax rate structure for jurisdiction"""
        
        cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("""
            SELECT * FROM tax_rates
            WHERE jurisdiction = %s
            AND tax_year = %s
            LIMIT 1
        """, (jurisdiction, tax_year))
        
        result = cursor.fetchone()
        cursor.close()
        
        return dict(result) if result else None
    
    async def _analyze_jurisdiction_exposure(
        self,
        jurisdiction: str,
        local_income: List[Dict],
        all_income: List[Dict],
        tax_rates: Optional[Dict],
        treaties: List[Dict]
    ) -> Optional[Dict]:
        """Use LLM to analyze tax exposure in jurisdiction"""
        
        if not local_income:
            print(f"   ⚠️ No local income for {jurisdiction}, skipping exposure analysis")
            return None
        
        print(f"   🔍 Analyzing exposure for {jurisdiction} with {len(local_income)} income sources...")
        
        # Find relevant treaties
        relevant_treaties = [
            t for t in treaties
            if jurisdiction in t.get('countries', [])
        ]
        
        treaty_context = "\n".join([
            f"Treaty with {t['countries']}: {t.get('treaty_name', 'No treaty')}"
            for t in relevant_treaties
        ]) if relevant_treaties else "No applicable treaties"
        
        prompt = f"""You are a tax planning expert. Analyze potential tax exposure in {jurisdiction}.

LOCAL INCOME SOURCES IN {jurisdiction}:
{json.dumps(local_income, indent=2)}

ALL CLIENT INCOME (for context):
{json.dumps(all_income, indent=2)}

TAX RATE STRUCTURE:
{json.dumps(tax_rates, indent=2) if tax_rates else 'Not available'}

APPLICABLE TREATIES:
{treaty_context}

TASK:
1. Estimate the tax exposure range in {jurisdiction}
2. Identify if there's double taxation risk
3. Note any withholding tax requirements
4. Suggest mitigation strategies using treaties

Return JSON:
{{
  "jurisdiction": "{jurisdiction}",
  "exposure_type": "primary_income" or "foreign_income" or "double_taxation",
  "risk_level": "high" or "medium" or "low",
  "estimated_impact_min": <number>,
  "estimated_impact_max": <number>,
  "primary_concerns": ["concern1", "concern2"],
  "mitigation_strategies": ["strategy1", "strategy2"]
}}
"""
        
        try:
            print(f"🤖 Calling LLM to analyze exposure for {jurisdiction}...")
            print(f"   Income sources: {len(local_income)}")
            
            # Try to generate content, with fallback if model not available
            try:
                response = self.model.generate_content(prompt)
                result_text = response.text
            except Exception as model_error:
                error_str = str(model_error)
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                    # Fallback to gemini-2.5-flash
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                        response = fallback_model.generate_content(prompt)
                        result_text = response.text
                        print(f"✅ Successfully used fallback model: gemini-2.5-flash")
                    except Exception as e2:
                        print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                        try:
                            fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                            print(f"✅ Successfully used fallback model: gemini-2.0-flash-001")
                        except Exception as e3:
                            print(f"⚠️  gemini-2.0-flash-001 also failed, trying gemini-flash-latest...")
                            try:
                                fallback_model = genai.GenerativeModel('gemini-flash-latest')
                                response = fallback_model.generate_content(prompt)
                                result_text = response.text
                                print(f"✅ Successfully used fallback model: gemini-flash-latest")
                            except Exception as e4:
                                print(f"❌ All model fallbacks failed!")
                                print(f"   Original error: {error_str}")
                                raise model_error
                else:
                    raise
            
            print(f"✅ LLM response received for {jurisdiction} ({len(result_text)} chars)")
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
            
            # Try to find JSON object in the text if it's not at the start
            if not result_text.startswith('{'):
                print(f"   ⚠️  Response doesn't start with '{{', searching for JSON object...")
                import re
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    result_text = json_match.group(0)
                    print(f"   ✅ Found JSON object, length: {len(result_text)}")
                else:
                    print(f"   ❌ No JSON object found in response")
                    print(f"   Full response (first 1000 chars): {original_text[:1000]}")
            
            print(f"🔍 Attempting to parse JSON (length: {len(result_text)})")
            print(f"   First 500 chars: {result_text[:500]}")
            
            # Try to parse JSON
            try:
                exposure = json.loads(result_text)
            except json.JSONDecodeError as parse_error:
                print(f"❌ JSON parsing failed: {parse_error}")
                print(f"   Error at position: {parse_error.pos if hasattr(parse_error, 'pos') else 'unknown'}")
                print(f"   Text around error: {result_text[max(0, parse_error.pos-50):parse_error.pos+50] if hasattr(parse_error, 'pos') else 'N/A'}")
                print(f"   Full response (first 1500 chars): {original_text[:1500]}")
                return None
            
            # Validate exposure structure
            if not isinstance(exposure, dict):
                print(f"⚠️  WARNING: LLM returned non-dict type: {type(exposure)}")
                return None
            
            if not exposure.get('exposure_type'):
                print(f"⚠️  WARNING: LLM returned exposure without 'exposure_type'")
                print(f"   Full response: {original_text[:1000]}")
                return None
            
            print(f"✅ Parsed exposure analysis for {jurisdiction}")
            print(f"   Exposure type: {exposure.get('exposure_type')}")
            print(f"   Risk level: {exposure.get('risk_level')}")
            return exposure
        
        except json.JSONDecodeError as json_error:
            print(f"❌ JSON parsing error for {jurisdiction}: {json_error}")
            print(f"   Error details: {str(json_error)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000]}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500]}")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            print(f"❌ Error analyzing exposure for {jurisdiction}: {type(e).__name__}: {e}")
            print(f"   Error details: {str(e)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000] if 'result_text' in locals() else 'N/A'}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500] if 'original_text' in locals() else 'N/A'}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _identify_reporting_requirements(
        self,
        jurisdictions: List[str],
        income_sources: List[Dict],
        tax_year: int
    ) -> List[Dict]:
        """
        Identify all reporting requirements across jurisdictions
        """
        
        requirements = []
        
        for jurisdiction in jurisdictions:
            # Search for filing requirements
            query = f"tax filing requirements reporting obligations {jurisdiction}"
            query_embedding = await self.vectorizer.embed(query)
            
            # Convert embedding list to string format for pgvector
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Use f-string for embedding to avoid parameter binding issues with pgvector
            # Note: %% escapes % in f-strings for LIKE clauses
            cursor.execute(f"""
                SELECT 
                    chunk_text,
                    section_reference,
                    document_title
                FROM tax_laws
                WHERE jurisdiction = %s
                AND law_category LIKE '%%filing%%'
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT 5
            """, (jurisdiction,))
            
            law_results = cursor.fetchall()
            cursor.close()
            
            if law_results:
                # Use LLM to extract specific requirements
                req = await self._extract_filing_requirements(
                    jurisdiction,
                    income_sources,
                    law_results
                )
                if req:
                    requirements.extend(req)
        
        return requirements
    
    async def _extract_filing_requirements(
        self,
        jurisdiction: str,
        income_sources: List[Dict],
        law_results: List[Dict]
    ) -> List[Dict]:
        """Extract specific filing requirements using LLM"""
        
        laws_context = "\n\n".join([
            f"{law['section_reference']}\n{law['chunk_text']}"
            for law in law_results
        ])
        
        prompt = f"""Extract specific filing requirements for {jurisdiction}.

INCOME SOURCES:
{json.dumps(income_sources, indent=2)}

APPLICABLE LAWS:
{laws_context}

TASK:
List all forms, schedules, and reports required. Include:
- Form names/numbers
- Filing deadlines
- Who must file
- Penalties for non-compliance

Return JSON array:
[
  {{
    "jurisdiction": "{jurisdiction}",
    "requirement_type": "annual_return" or "quarterly" or "information_return",
    "form_name": "...",
    "deadline": "...",
    "applies_to": "...",
    "penalty_for_late_filing": "..."
  }}
]
"""
        
        try:
            # Try to generate content, with fallback if model not available
            try:
                response = self.model.generate_content(prompt)
                result_text = response.text
            except Exception as model_error:
                error_str = str(model_error)
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                        response = fallback_model.generate_content(prompt)
                        result_text = response.text
                    except Exception as e2:
                        try:
                            fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                        except Exception as e3:
                            fallback_model = genai.GenerativeModel('gemini-flash-latest')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                else:
                    raise
            
            # Save original for debugging
            original_text = result_text
            
            # Extract JSON - improved parsing
            if '```json' in result_text:
                parts = result_text.split('```json')
                if len(parts) > 1:
                    json_part = parts[1].split('```')[0] if '```' in parts[1] else parts[1]
                    result_text = json_part
            elif '```' in result_text:
                parts = result_text.split('```')
                if len(parts) > 1:
                    result_text = parts[1]
            
            # Clean up the JSON string
            result_text = result_text.strip()
            result_text = result_text.strip(' \n\r\t')
            
            # Try to find JSON array in the text if it's not at the start
            if not result_text.startswith('['):
                import re
                array_match = re.search(r'\[.*\]', result_text, re.DOTALL)
                if array_match:
                    result_text = array_match.group(0)
            
            try:
                requirements = json.loads(result_text)
            except json.JSONDecodeError as parse_error:
                print(f"❌ JSON parsing error for requirements: {parse_error}")
                print(f"   Full response (first 1500 chars): {original_text[:1500]}")
                return []
            
            # Validate structure
            if not isinstance(requirements, list):
                if isinstance(requirements, dict):
                    requirements = [requirements]
                else:
                    return []
            
            return requirements
        
        except Exception as e:
            print(f"❌ Error extracting requirements: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def _generate_recommendations(
        self,
        client_name: str,
        jurisdictions: List[str],
        income_sources: List[Dict],
        exposures: List[Dict],
        treaties: List[Dict],
        objectives: List[str]
    ) -> List[Dict]:
        """
        Generate actionable tax planning recommendations
        """
        
        prompt = f"""You are a senior tax advisor creating a planning strategy for {client_name}.

CLIENT OBJECTIVES:
{', '.join(objectives)}

JURISDICTIONS INVOLVED:
{', '.join(jurisdictions)}

INCOME PROFILE:
{json.dumps(income_sources, indent=2)}

TAX EXPOSURES:
{json.dumps(exposures, indent=2)}

AVAILABLE TREATIES:
{json.dumps([t for t in treaties if t.get('treaty_exists', True)], indent=2)}

TASK:
Generate 5-10 specific, actionable recommendations to optimize this client's tax situation.

Each recommendation should be:
- SPECIFIC (not general advice)
- ACTIONABLE (clear steps)
- PRIORITIZED (critical > high > medium)

Return JSON array:
[
  {{
    "priority": "critical" or "high" or "medium",
    "recommendation_type": "structure" or "timing" or "documentation" or "treaty_benefit" or "reporting",
    "title": "Short title",
    "description": "Detailed explanation",
    "expected_benefit": "What client gains",
    "implementation_steps": ["step1", "step2"],
    "risks_and_considerations": ["risk1", "risk2"],
    "timeline": "When to implement"
  }}
]

Focus on PRACTICAL actions that will make a real difference.
"""
        
        try:
            print(f"🤖 Calling LLM to generate recommendations...")
            print(f"   Client: {client_name}")
            print(f"   Jurisdictions: {len(jurisdictions)}")
            print(f"   Exposures: {len(exposures)}")
            print(f"   Treaties: {len(treaties)}")
            
            # Try to generate content, with fallback if model not available
            try:
                response = self.model.generate_content(prompt)
                result_text = response.text
            except Exception as model_error:
                error_str = str(model_error)
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                    # Fallback to gemini-2.5-flash
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                        response = fallback_model.generate_content(prompt)
                        result_text = response.text
                        print(f"✅ Successfully used fallback model: gemini-2.5-flash")
                    except Exception as e2:
                        print(f"⚠️  gemini-2.5-flash also failed, trying gemini-2.0-flash-001...")
                        try:
                            fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                            print(f"✅ Successfully used fallback model: gemini-2.0-flash-001")
                        except Exception as e3:
                            print(f"⚠️  gemini-2.0-flash-001 also failed, trying gemini-flash-latest...")
                            try:
                                fallback_model = genai.GenerativeModel('gemini-flash-latest')
                                response = fallback_model.generate_content(prompt)
                                result_text = response.text
                                print(f"✅ Successfully used fallback model: gemini-flash-latest")
                            except Exception as e4:
                                print(f"❌ All model fallbacks failed!")
                                print(f"   Original error: {error_str}")
                                raise model_error
                else:
                    raise
            
            print(f"✅ LLM response received for recommendations ({len(result_text)} chars)")
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
                recommendations = json.loads(result_text)
            except json.JSONDecodeError as parse_error:
                print(f"❌ JSON parsing failed: {parse_error}")
                print(f"   Error at position: {parse_error.pos if hasattr(parse_error, 'pos') else 'unknown'}")
                print(f"   Text around error: {result_text[max(0, parse_error.pos-50):parse_error.pos+50] if hasattr(parse_error, 'pos') else 'N/A'}")
                print(f"   Full response (first 1500 chars): {original_text[:1500]}")
                return []
            
            # Validate recommendations structure
            if not isinstance(recommendations, list):
                print(f"⚠️  WARNING: LLM returned non-list type: {type(recommendations)}")
                if isinstance(recommendations, dict):
                    print(f"   Converting dict to list...")
                    recommendations = [recommendations]
                else:
                    print(f"   Cannot convert {type(recommendations)} to list, returning empty")
                    recommendations = []
            
            print(f"✅ Parsed {len(recommendations)} recommendations from LLM")
            
            if len(recommendations) == 0:
                print(f"⚠️  ⚠️  ⚠️  CRITICAL: LLM returned empty recommendations array!")
                print(f"   Original response length: {len(original_text)}")
                print(f"   Parsed text length: {len(result_text)}")
                print(f"   Full original response:")
                print(f"   {'='*80}")
                print(f"   {original_text}")
                print(f"   {'='*80}")
            else:
                # Validate each recommendation has required fields
                valid_recommendations = []
                for i, rec in enumerate(recommendations):
                    if not isinstance(rec, dict):
                        print(f"   ⚠️  Recommendation {i} is not a dict: {type(rec)}")
                        continue
                    required_fields = ['priority', 'title', 'description']
                    missing = [f for f in required_fields if f not in rec]
                    if missing:
                        print(f"   ⚠️  Recommendation {i} missing fields: {missing}")
                        continue
                    valid_recommendations.append(rec)
                
                if len(valid_recommendations) < len(recommendations):
                    print(f"   ⚠️  Filtered {len(recommendations) - len(valid_recommendations)} invalid recommendations")
                recommendations = valid_recommendations
            
            return recommendations
        
        except json.JSONDecodeError as json_error:
            print(f"❌ JSON parsing error for recommendations: {json_error}")
            print(f"   Error details: {str(json_error)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000]}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500]}")
            import traceback
            traceback.print_exc()
            return []
        except Exception as e:
            print(f"❌ Error generating recommendations: {type(e).__name__}: {e}")
            print(f"   Error details: {str(e)}")
            if 'result_text' in locals():
                print(f"   Response text (first 1000 chars): {result_text[:1000] if 'result_text' in locals() else 'N/A'}")
            if 'original_text' in locals():
                print(f"   Original response (first 1500 chars): {original_text[:1500] if 'original_text' in locals() else 'N/A'}")
            import traceback
            traceback.print_exc()
            return []
    
    async def _create_compliance_timeline(
        self,
        jurisdictions: List[str],
        tax_year: int
    ) -> List[Dict]:
        """
        Create a timeline of all tax deadlines across jurisdictions
        """
        
        timeline = []
        
        # Search for deadline information
        for jurisdiction in jurisdictions:
            query = f"tax filing deadline payment deadline {jurisdiction} {tax_year}"
            query_embedding = await self.vectorizer.embed(query)
            
            # Convert embedding list to string format for pgvector
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Use f-string for embedding to avoid parameter binding issues with pgvector
            # Note: %% escapes % in f-strings for LIKE clauses
            cursor.execute(f"""
                SELECT chunk_text, section_reference
                FROM tax_laws
                WHERE jurisdiction = %s
                AND (chunk_text ILIKE '%%deadline%%' OR chunk_text ILIKE '%%due date%%')
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT 3
            """, (jurisdiction,))
            
            results = cursor.fetchall()
            cursor.close()
            
            if results:
                # Extract deadlines using LLM
                deadlines = await self._extract_deadlines(
                    jurisdiction,
                    results,
                    tax_year
                )
                timeline.extend(deadlines)
        
        # Sort by date
        timeline.sort(key=lambda x: x.get('date', '9999-12-31'))
        
        return timeline
    
    async def _extract_deadlines(
        self,
        jurisdiction: str,
        law_results: List[Dict],
        tax_year: int
    ) -> List[Dict]:
        """Extract specific deadlines from laws"""
        
        context = "\n\n".join([
            f"{law['section_reference']}\n{law['chunk_text']}"
            for law in law_results
        ])
        
        prompt = f"""Extract all tax-related deadlines for {jurisdiction} in {tax_year}.

LEGAL TEXT:
{context}

Return JSON array with specific dates:
[
  {{
    "jurisdiction": "{jurisdiction}",
    "event": "Individual tax return filing",
    "date": "YYYY-MM-DD",
    "description": "...",
    "importance": "critical" or "high" or "medium"
  }}
]
"""
        
        try:
            # Try to generate content, with fallback if model not available
            try:
                response = self.model.generate_content(prompt)
                result_text = response.text
            except Exception as model_error:
                error_str = str(model_error)
                if "404" in error_str or "not found" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"⚠️  Model not available, trying gemini-2.5-flash fallback...")
                    try:
                        fallback_model = genai.GenerativeModel('gemini-2.5-flash')
                        response = fallback_model.generate_content(prompt)
                        result_text = response.text
                    except Exception as e2:
                        try:
                            fallback_model = genai.GenerativeModel('gemini-2.0-flash-001')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                        except Exception as e3:
                            fallback_model = genai.GenerativeModel('gemini-flash-latest')
                            response = fallback_model.generate_content(prompt)
                            result_text = response.text
                else:
                    raise
            
            # Save original for debugging
            original_text = result_text
            
            # Extract JSON - improved parsing
            if '```json' in result_text:
                parts = result_text.split('```json')
                if len(parts) > 1:
                    json_part = parts[1].split('```')[0] if '```' in parts[1] else parts[1]
                    result_text = json_part
            elif '```' in result_text:
                parts = result_text.split('```')
                if len(parts) > 1:
                    result_text = parts[1]
            
            # Clean up the JSON string
            result_text = result_text.strip()
            result_text = result_text.strip(' \n\r\t')
            
            # Try to find JSON array in the text if it's not at the start
            if not result_text.startswith('['):
                import re
                array_match = re.search(r'\[.*\]', result_text, re.DOTALL)
                if array_match:
                    result_text = array_match.group(0)
            
            try:
                deadlines = json.loads(result_text)
            except json.JSONDecodeError as parse_error:
                print(f"❌ JSON parsing error for deadlines: {parse_error}")
                print(f"   Full response (first 1500 chars): {original_text[:1500]}")
                return []
            
            # Validate structure
            if not isinstance(deadlines, list):
                if isinstance(deadlines, dict):
                    deadlines = [deadlines]
                else:
                    return []
            
            return deadlines
        
        except Exception as e:
            print(f"❌ Error extracting deadlines: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def _store_planning_scenario(
        self,
        scenario_id: str,
        client_id: str,
        client_name: str,
        scenario_name: str,
        jurisdictions: List[str],
        income_sources: List[Dict],
        objectives: List[str],
        tax_year: int,
        analysis_results: Dict
    ):
        """Store planning scenario in database"""
        
        try:
            # Check if database connection is valid
            if self.db.closed:
                print(f"❌ Database connection is closed, cannot store scenario {scenario_id}")
                raise ConnectionError("Database connection is closed")
            
            cursor = self.db.cursor()
            print(f"📝 Attempting to store scenario {scenario_id} in database...")
            
            # First, ensure client profile exists (required by foreign key constraint)
            cursor.execute("SELECT id FROM client_profiles WHERE client_id = %s", (client_id,))
            client_exists = cursor.fetchone()
            if not client_exists:
                print(f"📝 Creating client profile for {client_id}...")
                cursor.execute("""
                    INSERT INTO client_profiles (
                        client_id, client_name, client_type,
                        primary_jurisdiction, income_sources
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (client_id) DO UPDATE SET
                        client_name = EXCLUDED.client_name,
                        primary_jurisdiction = EXCLUDED.primary_jurisdiction,
                        income_sources = EXCLUDED.income_sources
                """, (
                    client_id,
                    client_name,
                    'individual',  # Default client type
                    jurisdictions[0] if jurisdictions else None,
                    psycopg2.extras.Json(income_sources)
                ))
                print(f"✅ Created/updated client profile for {client_id}")
            
            # Store scenario - check if it already exists first
            cursor.execute("SELECT id FROM planning_scenarios WHERE scenario_id = %s", (scenario_id,))
            existing = cursor.fetchone()
            if existing:
                print(f"⚠️ Scenario {scenario_id} already exists, updating...")
                cursor.execute("""
                    UPDATE planning_scenarios SET
                        client_id = %s,
                        scenario_name = %s,
                        jurisdictions_involved = %s,
                        tax_year = %s,
                        objectives = %s,
                        scenario_description = %s,
                        analysis_results = %s
                    WHERE scenario_id = %s
                """, (
                    client_id,
                    scenario_name,
                    jurisdictions,
                    tax_year,
                    psycopg2.extras.Json(objectives),
                    json.dumps(income_sources),
                    psycopg2.extras.Json(analysis_results),
                    scenario_id
                ))
                print(f"✅ Updated scenario {scenario_id}")
            else:
                # Store scenario
                print(f"📝 Inserting new scenario {scenario_id}...")
                cursor.execute("""
                    INSERT INTO planning_scenarios (
                        scenario_id, client_id, scenario_name,
                        jurisdictions_involved, tax_year, objectives,
                        scenario_description, analysis_results
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    scenario_id,
                    client_id,
                    scenario_name,
                    jurisdictions,
                    tax_year,
                    psycopg2.extras.Json(objectives),
                    json.dumps(income_sources),
                    psycopg2.extras.Json(analysis_results)
                ))
                print(f"✅ Inserted scenario {scenario_id}")
            
            # Store exposures
            for exposure in analysis_results.get('tax_exposures', []):
                try:
                    if not isinstance(exposure, dict):
                        print(f"⚠️ Skipping invalid exposure (not a dict): {type(exposure)}")
                        continue
                    cursor.execute("""
                        INSERT INTO tax_exposures (
                            scenario_id, jurisdiction, exposure_type,
                            risk_level, estimated_impact_min, estimated_impact_max,
                            mitigation_strategies
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        scenario_id,
                        exposure.get('jurisdiction'),
                        exposure.get('exposure_type'),
                        exposure.get('risk_level'),
                        exposure.get('estimated_impact_min', 0),
                        exposure.get('estimated_impact_max', 0),
                        psycopg2.extras.Json(exposure.get('mitigation_strategies', []))
                    ))
                except Exception as e:
                    print(f"⚠️ Error storing exposure: {e}, exposure: {exposure}")
                    continue
            
            # Store recommendations
            for rec in analysis_results.get('recommendations', []):
                try:
                    if not isinstance(rec, dict):
                        print(f"⚠️ Skipping invalid recommendation (not a dict): {type(rec)}")
                        continue
                    cursor.execute("""
                        INSERT INTO planning_recommendations (
                            scenario_id, recommendation_type, priority,
                            title, description, expected_benefit,
                            implementation_steps, risks_and_considerations
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        scenario_id,
                        rec.get('recommendation_type'),
                        rec.get('priority'),
                        rec.get('title'),
                        rec.get('description'),
                        rec.get('expected_benefit'),
                        psycopg2.extras.Json(rec.get('implementation_steps', [])),
                        psycopg2.extras.Json(rec.get('risks_and_considerations', []))
                    ))
                except Exception as e:
                    print(f"⚠️ Error storing recommendation: {e}, rec: {rec}")
                    continue
        
            # Commit the transaction
            print(f"💾 Committing transaction for scenario {scenario_id}...")
            try:
                self.db.commit()
                print(f"✅ Successfully committed planning scenario {scenario_id} to database")
            except Exception as commit_error:
                print(f"❌ Error committing scenario: {commit_error}")
                import traceback
                traceback.print_exc()
                self.db.rollback()
                raise
            
            cursor.close()
            
            # Verify the scenario was stored
            verify_cursor = self.db.cursor()
            verify_cursor.execute("SELECT scenario_id FROM planning_scenarios WHERE scenario_id = %s", (scenario_id,))
            verify_result = verify_cursor.fetchone()
            verify_cursor.close()
            
            if verify_result:
                print(f"✅ Verified: Scenario {scenario_id} is now in database")
            else:
                print(f"⚠️ Warning: Scenario {scenario_id} commit succeeded but not found in database")
            
            print(f"✅ Successfully stored planning scenario {scenario_id} in database")
        except ConnectionError as conn_error:
            print(f"❌ Connection error in _store_planning_scenario: {conn_error}")
            if 'cursor' in locals():
                try:
                    cursor.close()
                except:
                    pass
            # Re-raise connection errors so they can be handled upstream
            raise
        except Exception as e:
            print(f"❌ Error in _store_planning_scenario: {e}")
            import traceback
            traceback.print_exc()
            if 'cursor' in locals():
                try:
                    self.db.rollback()
                    cursor.close()
                except:
                    pass
            # Re-raise the exception so we can see what's wrong
            raise