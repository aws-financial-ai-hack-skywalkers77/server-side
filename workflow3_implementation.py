# services/workflow3/planning_engine.py

import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import psycopg2.extras
from datetime import datetime
import uuid

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
        genai.configure(api_key=gemini_api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro')
    
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
        treaty_analysis = await self._analyze_tax_treaties(
            jurisdictions_involved
        )
        
        # 2. Calculate tax exposures in each jurisdiction
        tax_exposures = await self._calculate_tax_exposures(
            jurisdictions_involved,
            income_sources,
            treaty_analysis,
            tax_year
        )
        
        # 3. Identify reporting requirements
        reporting_requirements = await self._identify_reporting_requirements(
            jurisdictions_involved,
            income_sources,
            tax_year
        )
        
        # 4. Generate optimization recommendations
        recommendations = await self._generate_recommendations(
            client_name,
            jurisdictions_involved,
            income_sources,
            tax_exposures,
            treaty_analysis,
            objectives
        )
        
        # 5. Create compliance timeline
        compliance_timeline = await self._create_compliance_timeline(
            jurisdictions_involved,
            tax_year
        )
        
        # 6. Store scenario in database
        await self._store_planning_scenario(
            scenario_id,
            client_id,
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
        
        # 7. Generate executive summary
        summary = {
            'scenario_id': scenario_id,
            'client_name': client_name,
            'scenario_name': scenario_name,
            'jurisdictions': jurisdictions_involved,
            'tax_year': tax_year,
            'created_at': datetime.now().isoformat(),
            'treaty_benefits_available': len(treaty_analysis),
            'total_jurisdictions_with_exposure': len(tax_exposures),
            'high_priority_actions': len([r for r in recommendations if r['priority'] == 'critical']),
            'estimated_total_exposure_min': sum(e['estimated_impact_min'] for e in tax_exposures),
            'estimated_total_exposure_max': sum(e['estimated_impact_max'] for e in tax_exposures),
            'analysis': {
                'treaties': treaty_analysis,
                'exposures': tax_exposures,
                'reporting': reporting_requirements,
                'recommendations': recommendations,
                'timeline': compliance_timeline
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
        
        for jurisdiction in jurisdictions:
            # Get income sources in this jurisdiction
            local_income = [
                inc for inc in income_sources
                if inc.get('jurisdiction') == jurisdiction
            ]
            
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
                exposures.append(exposure_analysis)
        
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
            return None
        
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
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            
            return json.loads(result_text.strip())
        
        except Exception as e:
            print(f"❌ Error analyzing exposure for {jurisdiction}: {e}")
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
            
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT 
                    chunk_text,
                    section_reference,
                    document_title
                FROM tax_laws
                WHERE jurisdiction = %s
                AND law_category LIKE '%filing%'
                ORDER BY embedding <=> %s::vector
                LIMIT 5
            """, (jurisdiction, query_embedding))
            
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
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            
            return json.loads(result_text.strip())
        
        except Exception as e:
            print(f"❌ Error extracting requirements: {e}")
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
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            
            return json.loads(result_text.strip())
        
        except Exception as e:
            print(f"❌ Error generating recommendations: {e}")
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
            
            cursor = self.db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT chunk_text, section_reference
                FROM tax_laws
                WHERE jurisdiction = %s
                AND (chunk_text ILIKE '%deadline%' OR chunk_text ILIKE '%due date%')
                ORDER BY embedding <=> %s::vector
                LIMIT 3
            """, (jurisdiction, query_embedding))
            
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
            response = self.model.generate_content(prompt)
            result_text = response.text
            
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            
            return json.loads(result_text.strip())
        
        except Exception as e:
            print(f"❌ Error extracting deadlines: {e}")
            return []
    
    async def _store_planning_scenario(
        self,
        scenario_id: str,
        client_id: str,
        scenario_name: str,
        jurisdictions: List[str],
        income_sources: List[Dict],
        objectives: List[str],
        tax_year: int,
        analysis_results: Dict
    ):
        """Store planning scenario in database"""
        
        cursor = self.db.cursor()
        
        # Store scenario
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
        
        # Store exposures
        for exposure in analysis_results.get('tax_exposures', []):
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
        
        # Store recommendations
        for rec in analysis_results.get('recommendations', []):
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
        
        self.db.commit()
        cursor.close()
        
        print(f"✅ Stored planning scenario {scenario_id}")