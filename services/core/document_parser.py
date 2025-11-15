# services/core/document_parser.py

from landingai_ade import LandingAIADE
from config import Config
from typing import Optional
import logging
import json
import os

logger = logging.getLogger(__name__)

class TaxDocumentParser:
    """
    Document parser for tax forms using Landing AI ADE.
    Extracts structured data from tax documents (PDFs).
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize parser with Landing AI API key
        
        Args:
            api_key: Landing AI API key. If None, reads from LANDING_AI_API_KEY env var.
        """
        self.api_key = api_key or Config.LANDING_AI_API_KEY
        if not self.api_key:
            raise ValueError("LANDING_AI_API_KEY must be provided or set in environment")
        
        self.ade_client = LandingAIADE(apikey=self.api_key)
    
    async def process_tax_document(self, pdf_path: str, form_code: str = None) -> dict:
        """
        Process a tax document PDF and extract structured data
        
        Args:
            pdf_path: Path to PDF file (local file path or URL)
            
        Returns:
            Dictionary with extracted form data
        """
        try:
            logger.info(f"Processing tax document: {pdf_path}")
            
            # Handle local file paths - Landing AI ADE may need absolute path or URL
            # Try absolute path first, then file:// protocol as fallback
            if pdf_path.startswith('http://') or pdf_path.startswith('https://'):
                document_url = pdf_path
            else:
                # Convert to absolute path
                abs_path = os.path.abspath(pdf_path)
                if not os.path.exists(abs_path):
                    raise FileNotFoundError(f"Tax document not found: {abs_path}")
                # Try absolute path first (some ADE versions accept this)
                # If that fails, we'll catch the error and try file:// protocol
                document_url = abs_path
            
            # Parse document
            response = None
            markdown_text = ""
            try:
                response = self.ade_client.parse(
                    document_url=document_url,
                    model="dpt-2-latest"
                )
                markdown_text = response.markdown if hasattr(response, 'markdown') else str(response)
            except Exception as parse_error:
                error_str = str(parse_error)
                # Check for payment/balance issues
                if 'payment' in error_str.lower() or 'balance' in error_str.lower() or 'insufficient' in error_str.lower():
                    logger.warning(f"Landing AI account balance issue: {parse_error}")
                    logger.info("Using fallback: creating document structure from provided metadata")
                    # Return early with basic structure
                    return {
                        'form_type': form_code or 'Unknown',
                        'tax_year': None,
                        'taxpayer_name': '',
                        'taxpayer_ssn': '',
                        'filing_status': '',
                        'form_data': {},
                        'line_items': [],
                        'calculations': {},
                        'schedules': [],
                        'extraction_note': 'Landing AI account balance insufficient. Using basic structure from provided metadata.'
                    }
                
                # If absolute path failed, try file:// protocol
                if not (document_url.startswith('http://') or document_url.startswith('https://')):
                    logger.warning(f"Direct path failed, trying file:// protocol: {parse_error}")
                    try:
                        document_url = f"file://{abs_path}"
                        response = self.ade_client.parse(
                            document_url=document_url,
                            model="dpt-2-latest"
                        )
                        markdown_text = response.markdown if hasattr(response, 'markdown') else str(response)
                    except Exception as retry_error:
                        logger.error(f"Both parse attempts failed: {retry_error}")
                        # Return basic structure if parsing completely fails
                        return {
                            'form_type': form_code or 'Unknown',
                            'tax_year': None,
                            'taxpayer_name': '',
                            'taxpayer_ssn': '',
                            'filing_status': '',
                            'form_data': {},
                            'line_items': [],
                            'calculations': {},
                            'schedules': [],
                            'extraction_note': f'Document parsing failed: {str(retry_error)}. Using basic structure.'
                        }
                else:
                    raise
            
            # Define a simple schema for Landing AI extract API
            # Try using Landing AI's extract API first - it's designed for structured extraction
            schema = {
                "type": "object",
                "properties": {
                    "taxpayer_name": {
                        "type": "string",
                        "description": "The actual name of the taxpayer as written in the form (not labels like 'on line below')"
                    },
                    "taxpayer_ssn": {
                        "type": "string",
                        "description": "Social Security Number in format XXX-XX-XXXX"
                    },
                    "filing_status": {
                        "type": "string",
                        "description": "Filing status: Single, Married Filing Jointly, Married Filing Separately, Head of Household, or Qualifying Widow(er)"
                    },
                    "wages": {
                        "type": "number",
                        "description": "Wages, salaries, tips amount"
                    },
                    "interest": {
                        "type": "number",
                        "description": "Interest income amount"
                    },
                    "dividends": {
                        "type": "number",
                        "description": "Dividend income amount"
                    },
                    "total_income": {
                        "type": "number",
                        "description": "Total income amount"
                    }
                }
            }
            
            # Try Landing AI extract API first
            if not markdown_text and response:
                markdown_text = response.markdown if hasattr(response, 'markdown') else str(response)
            
            extracted_data = {
                'form_type': form_code or 'Unknown',
                'tax_year': None,
                'taxpayer_name': '',
                'taxpayer_ssn': '',
                'filing_status': '',
                'form_fields_json': '{}',
                'line_items': [],
                'schedules': []
            }
            
            # Try Landing AI extract API
            landing_ai_extracted = False
            try:
                logger.info("Attempting Landing AI extract API with schema...")
                schema_json = json.dumps(schema)
                extraction_response = self.ade_client.extract(
                    schema=schema_json,
                    markdown=markdown_text,
                    model="extract-latest"
                )
                landing_ai_data = extraction_response.extraction
                logger.info(f"✅ Landing AI extract API returned: {landing_ai_data}")
                
                # Use Landing AI extracted data
                if isinstance(landing_ai_data, dict):
                    extracted_data['taxpayer_name'] = landing_ai_data.get('taxpayer_name', '').strip()
                    extracted_data['taxpayer_ssn'] = landing_ai_data.get('taxpayer_ssn', '').strip()
                    extracted_data['filing_status'] = landing_ai_data.get('filing_status', '').strip()
                    
                    # Store income fields
                    form_fields = {}
                    if landing_ai_data.get('wages') is not None:
                        form_fields['wages'] = float(landing_ai_data['wages'])
                    if landing_ai_data.get('interest') is not None:
                        form_fields['interest'] = float(landing_ai_data['interest'])
                    if landing_ai_data.get('dividends') is not None:
                        form_fields['dividends'] = float(landing_ai_data['dividends'])
                    if landing_ai_data.get('total_income') is not None:
                        form_fields['total_income'] = float(landing_ai_data['total_income'])
                    
                    if form_fields:
                        extracted_data['form_fields_json'] = json.dumps(form_fields)
                    
                    landing_ai_extracted = True
                    logger.info(f"✅ Landing AI extracted - name: '{extracted_data['taxpayer_name']}', SSN: '{extracted_data['taxpayer_ssn']}', status: '{extracted_data['filing_status']}'")
            except Exception as extract_error:
                error_str = str(extract_error)
                logger.warning(f"Landing AI extract API failed: {extract_error}")
                # Check if it's a schema validation error
                if 'schema' in error_str.lower() or 'validation' in error_str.lower():
                    logger.info("Schema validation error - will use LLM extraction instead")
                else:
                    logger.info("Landing AI extract failed - will use LLM extraction instead")
            
            # If Landing AI extract didn't work, try LLM extraction from markdown
            if not landing_ai_extracted:
                logger.info("Using LLM extraction from markdown (Landing AI extract API not available)")
                
                # Try to detect form type from markdown if form_code not provided
                if not form_code:
                    if 'IT-201' in markdown_text or 'Form IT-201' in markdown_text or 'it-201' in markdown_text.lower():
                        extracted_data['form_type'] = 'IT-201'
                    elif '1040' in markdown_text:
                        extracted_data['form_type'] = '1040'
                
                # Try to find tax year in markdown
                import re
                year_match = re.search(r'20\d{2}', markdown_text[:1000])
                if year_match:
                    try:
                        extracted_data['tax_year'] = int(year_match.group())
                    except:
                        pass
                
                # Try to extract form field values from markdown using LLM (more reliable than regex)
                logger.info(f"Markdown length: {len(markdown_text)} chars")
                logger.info(f"Markdown preview (first 2000 chars): {markdown_text[:2000]}")
                
                # First try LLM extraction, then fallback to pattern matching
                llm_extraction_attempted = False
                try:
                    logger.info("Attempting LLM extraction...")
                    await self._extract_fields_with_llm(markdown_text, extracted_data, form_code)
                    llm_extraction_attempted = True
                    logger.info("✅ LLM extraction completed successfully")
                except Exception as llm_error:
                    logger.warning(f"LLM extraction failed: {llm_error}")
                    import traceback
                    logger.warning(f"LLM error traceback: {traceback.format_exc()}")
                    logger.info("Falling back to pattern matching...")
                    self._extract_fields_from_markdown(markdown_text, extracted_data)
            else:
                # Landing AI extraction succeeded - set extraction method
                llm_extraction_attempted = False
            
            # Log what we extracted
            logger.info(f"Extracted data after parsing: taxpayer_name='{extracted_data.get('taxpayer_name', '')}', taxpayer_ssn='{extracted_data.get('taxpayer_ssn', '')}', filing_status='{extracted_data.get('filing_status', '')}'")
            
            # Store markdown metadata
            if landing_ai_extracted:
                extraction_method = 'landing_ai_extract_api'
                extraction_note = 'Landing AI extract API used for structured extraction'
            elif llm_extraction_attempted:
                extraction_method = 'llm_extraction'
                extraction_note = 'LLM extraction used'
            else:
                extraction_method = 'markdown_parsing_with_pattern_matching'
                extraction_note = 'Using markdown parsing with pattern matching to extract field values'
            
            # Only update form_fields_json if it's not already set (from Landing AI)
            if not landing_ai_extracted or 'form_fields_json' not in extracted_data or extracted_data['form_fields_json'] == '{}':
                extracted_data['form_fields_json'] = json.dumps({
                    'raw_markdown_length': len(markdown_text),
                    'extraction_method': extraction_method,
                    'note': extraction_note
                })
            
            # Parse form_fields_json if it's a JSON string
            form_data = {}
            form_fields_key = 'form_fields_json' if 'form_fields_json' in extracted_data else 'form_fields'
            if form_fields_key in extracted_data and extracted_data.get(form_fields_key):
                try:
                    form_data = json.loads(extracted_data[form_fields_key]) if isinstance(extracted_data[form_fields_key], str) else extracted_data[form_fields_key]
                except:
                    form_data = {}
            
            # Ensure all fields are present
            result = {
                'form_type': extracted_data.get('form_type', ''),
                'tax_year': extracted_data.get('tax_year'),
                'taxpayer_name': extracted_data.get('taxpayer_name', ''),
                'taxpayer_ssn': extracted_data.get('taxpayer_ssn', ''),
                'filing_status': extracted_data.get('filing_status', ''),
                'form_data': form_data,
                'line_items': extracted_data.get('line_items', []),
                'calculations': extracted_data.get('calculations', {}) if isinstance(extracted_data.get('calculations'), dict) else {},
                'schedules': extracted_data.get('schedules', [])
            }
            
            logger.info(f"Successfully extracted data from tax document")
            return result
            
        except Exception as e:
            logger.error(f"Error processing tax document: {e}", exc_info=True)
            raise
    
    async def _extract_fields_with_llm(self, markdown_text: str, extracted_data: dict, form_code: str = None):
        """
        Use LLM to extract structured data from markdown text.
        This is more reliable than regex pattern matching.
        """
        try:
            import google.generativeai as genai
            from config import Config
            gemini_api_key = Config.GEMINI_API_KEY
            if not gemini_api_key:
                raise ValueError("GEMINI_API_KEY not set - cannot use LLM extraction")
            genai.configure(api_key=gemini_api_key)
            model_name = Config.GEMINI_GENERATION_MODEL or 'gemini-1.5-pro'
            if model_name.startswith('models/'):
                model_name = model_name.replace('models/', '')
            model = genai.GenerativeModel(model_name)
            
            # Create a focused prompt with a sample of the markdown
            # Get first 8000 chars to include more form header info
            markdown_sample = markdown_text[:8000]
            
            prompt = f"""You are extracting data from a tax form (IT-201). Extract ONLY the actual values filled in the form, not labels or instructions.

Look for:
- Taxpayer Name: The actual name written in the form (usually after "Name:" or "Taxpayer Name:")
- SSN: The social security number in format XXX-XX-XXXX
- Filing Status: Check which box is marked (Single, Married Filing Jointly, etc.)
- Income amounts: Look for dollar amounts next to "Wages", "Interest", "Dividends", "Total Income"

IMPORTANT:
- Extract ONLY actual values, NOT labels like "on line below", "see instructions", etc.
- If a field is empty or not filled, return empty string or null
- For SSN, return in format XXX-XX-XXXX
- For filing status, return the exact status (Single, Married Filing Jointly, etc.)

Return ONLY a valid JSON object with these exact keys:
{{
  "taxpayer_name": "actual name from form or empty string if not found",
  "taxpayer_ssn": "SSN in XXX-XX-XXXX format or empty string if not found",
  "filing_status": "Single/Married Filing Jointly/Married Filing Separately/Head of Household/Qualifying Widow(er) or empty string",
  "wages": number or null,
  "interest": number or null,
  "dividends": number or null,
  "total_income": number or null
}}

Markdown text from form:
{markdown_sample}

Return ONLY the JSON object, no markdown formatting, no explanations."""

            logger.info("Calling Gemini LLM for field extraction...")
            response = model.generate_content(prompt)
            result_text = response.text.strip()
            logger.info(f"LLM response received ({len(result_text)} chars): {result_text[:500]}")
            
            # Extract JSON from response
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0]
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0]
            
            # Clean up the JSON string
            result_text = result_text.strip()
            # Remove any leading/trailing whitespace or newlines
            result_text = result_text.strip(' \n\r\t')
            
            # Parse JSON
            import json
            try:
                llm_data = json.loads(result_text)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to parse LLM JSON response: {json_err}")
                logger.error(f"Response text: {result_text}")
                raise ValueError(f"LLM returned invalid JSON: {json_err}")
            
            # Update extracted_data with LLM results (always update, even if empty)
            # This ensures we overwrite any previous regex-extracted values
            extracted_data['taxpayer_name'] = llm_data.get('taxpayer_name', '').strip()
            extracted_data['taxpayer_ssn'] = llm_data.get('taxpayer_ssn', '').strip()
            extracted_data['filing_status'] = llm_data.get('filing_status', '').strip()
            
            logger.info(f"LLM extracted - taxpayer_name: '{extracted_data['taxpayer_name']}', taxpayer_ssn: '{extracted_data['taxpayer_ssn']}', filing_status: '{extracted_data['filing_status']}'")
            
            # Store income fields in form_fields_json
            form_fields = {}
            if llm_data.get('wages') is not None:
                form_fields['wages'] = float(llm_data['wages'])
            if llm_data.get('interest') is not None:
                form_fields['interest'] = float(llm_data['interest'])
            if llm_data.get('dividends') is not None:
                form_fields['dividends'] = float(llm_data['dividends'])
            if llm_data.get('total_income') is not None:
                form_fields['total_income'] = float(llm_data['total_income'])
            
            if form_fields:
                extracted_data['form_fields_json'] = json.dumps(form_fields)
                logger.info(f"LLM extracted income fields: {form_fields}")
                
        except Exception as e:
            logger.warning(f"LLM extraction error: {e}")
            raise
    
    def _extract_fields_from_markdown(self, markdown_text: str, extracted_data: dict):
        """
        Extract form field values from markdown text using pattern matching.
        This is a fallback when schema extraction fails.
        """
        import re
        
        # Convert markdown to lowercase for case-insensitive matching
        markdown_lower = markdown_text.lower()
        
        # Pattern 1: Look for "Name:" or "Taxpayer Name:" followed by text
        # Try to find actual names (not labels like "on line below")
        name_patterns = [
            r'(?:taxpayer\s+)?name[:\s]+\n\s*([A-Z][A-Za-z\s,\.]{2,50}?)(?:\n|$|SSN|Social|First|Last|Date)',
            r'name[:\s]+\n\s*([A-Z][A-Za-z\s,\.]{2,50}?)(?:\n|$|SSN|Social)',
            r'(?:first\s+name|last\s+name)[:\s]+([A-Z][A-Za-z]{2,30})',
            # Look for patterns like "Name: John Smith" on same line
            r'name[:\s]+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)',
            # Look for capitalized words that look like names (2-4 words, each starting with capital)
            r'(?:name|taxpayer)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})(?:\s|$|\n)'
        ]
        for pattern in name_patterns:
            match = re.search(pattern, markdown_text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Filter out common false positives
                invalid_names = ['Name', 'Taxpayer', 'First', 'Last', 'on line below', 'line below', 
                               'see instructions', 'enter name', 'your name', 'above', 'below']
                if (len(name) > 2 and 
                    name.lower() not in [n.lower() for n in invalid_names] and
                    not name.lower().startswith('line') and
                    not name.lower().startswith('see') and
                    not name.lower().startswith('enter')):
                    extracted_data['taxpayer_name'] = name
                    logger.info(f"Extracted taxpayer_name from markdown: {name[:50]}")
                    break
        
        # Pattern 2: Look for SSN patterns (XXX-XX-XXXX or XXXXXXXXX)
        ssn_patterns = [
            r'(?:ssn|social\s+security\s+number)[:\s]+(\d{3}-\d{2}-\d{4})',
            r'(?:ssn|social\s+security\s+number)[:\s]+(\d{9})',
            r'\b(\d{3}-\d{2}-\d{4})\b',
            r'\b(\d{9})\b'
        ]
        for pattern in ssn_patterns:
            match = re.search(pattern, markdown_text, re.IGNORECASE)
            if match:
                ssn = match.group(1)
                # Format as XXX-XX-XXXX if it's 9 digits
                if len(ssn) == 9 and '-' not in ssn:
                    ssn = f"{ssn[:3]}-{ssn[3:5]}-{ssn[5:]}"
                extracted_data['taxpayer_ssn'] = ssn
                logger.info(f"Extracted taxpayer_ssn from markdown: {ssn}")
                break
        
        # Pattern 3: Look for filing status
        filing_status_patterns = [
            r'(?:filing\s+status|status)[:\s]+(single|married\s+filing\s+jointly|married\s+filing\s+separately|head\s+of\s+household|qualifying\s+widow)',
            r'\b(single|married|head\s+of\s+household|widow)\b',
            r'☑\s*(single|married|head\s+of\s+household)',
            r'\[X\]\s*(single|married|head\s+of\s+household)'
        ]
        for pattern in filing_status_patterns:
            match = re.search(pattern, markdown_text, re.IGNORECASE)
            if match:
                status = match.group(1).strip()
                extracted_data['filing_status'] = status.title()
                logger.info(f"Extracted filing_status from markdown: {status}")
                break
        
        # Pattern 4: Look for income amounts (wages, interest, dividends, total income)
        # Look for dollar amounts near keywords
        income_patterns = [
            (r'(?:wages|salary|salary\s+and\s+wages)[:\s\$]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', 'wages'),
            (r'(?:interest\s+income|interest)[:\s\$]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', 'interest'),
            (r'(?:dividends|dividend\s+income)[:\s\$]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', 'dividends'),
            (r'(?:total\s+income|adjusted\s+gross\s+income|agi)[:\s\$]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', 'total_income')
        ]
        
        # Initialize form_fields if needed
        if 'form_fields_json' not in extracted_data or extracted_data['form_fields_json'] == '{}':
            form_fields = {}
        else:
            try:
                form_fields = json.loads(extracted_data['form_fields_json']) if isinstance(extracted_data['form_fields_json'], str) else extracted_data['form_fields_json']
            except:
                form_fields = {}
        
        for pattern, field_name in income_patterns:
            match = re.search(pattern, markdown_text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '').replace('$', '')
                try:
                    amount = float(amount_str)
                    form_fields[field_name] = amount
                    logger.info(f"Extracted {field_name} from markdown: ${amount:,.2f}")
                except ValueError:
                    pass
        
        # Update form_fields_json with all extracted income fields
        if form_fields:
            extracted_data['form_fields_json'] = json.dumps(form_fields)
        
        # Also try to extract from line items if present
        # Look for numbered lines with amounts
        line_item_pattern = r'(?:line\s+)?(\d+)[:\s]+(?:.*?)[:\s\$]*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        line_matches = re.finditer(line_item_pattern, markdown_text, re.IGNORECASE)
        line_items = []
        for match in line_matches:
            line_num = match.group(1)
            amount_str = match.group(2).replace(',', '').replace('$', '')
            try:
                amount = float(amount_str)
                line_items.append({
                    'line_number': line_num,
                    'amount': amount,
                    'description': f'Line {line_num}'
                })
            except ValueError:
                pass
        
        if line_items:
            extracted_data['line_items'] = line_items
            logger.info(f"Extracted {len(line_items)} line items from markdown")

