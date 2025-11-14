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
    
    async def process_tax_document(self, pdf_path: str) -> dict:
        """
        Process a tax document PDF and extract structured data
        
        Args:
            pdf_path: Path to PDF file (local file path or URL)
            
        Returns:
            Dictionary with extracted form data
        """
        try:
            logger.info(f"Processing tax document: {pdf_path}")
            
            # Parse document
            response = self.ade_client.parse(
                document_url=pdf_path if pdf_path.startswith('http') else f"file://{pdf_path}",
                model="dpt-2-latest"
            )
            
            # Define schema for tax form extraction
            schema = {
                "type": "object",
                "properties": {
                    "form_type": {
                        "type": "string",
                        "description": "Type of tax form (e.g., 'Form 1040', 'Schedule C')"
                    },
                    "tax_year": {
                        "type": "integer",
                        "description": "Tax year for this form"
                    },
                    "taxpayer_name": {
                        "type": "string",
                        "description": "Name of taxpayer"
                    },
                    "taxpayer_ssn": {
                        "type": "string",
                        "description": "Social Security Number or Tax ID"
                    },
                    "filing_status": {
                        "type": "string",
                        "description": "Filing status (e.g., 'Single', 'Married Filing Jointly')"
                    },
                    "form_data": {
                        "type": "object",
                        "description": "All form fields and their values as key-value pairs",
                        "additionalProperties": True
                    },
                    "line_items": {
                        "type": "array",
                        "description": "Array of line items from schedules or forms",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_number": {"type": "string"},
                                "description": {"type": "string"},
                                "amount": {"type": "number"}
                            }
                        }
                    },
                    "calculations": {
                        "type": "object",
                        "description": "Calculated values and totals from the form",
                        "additionalProperties": True
                    },
                    "schedules": {
                        "type": "array",
                        "description": "List of attached schedules (e.g., 'Schedule A', 'Schedule C')",
                        "items": {"type": "string"}
                    }
                },
                "required": ["form_type", "form_data"]
            }
            
            # Extract data using schema
            schema_json = json.dumps(schema)
            extraction_response = self.ade_client.extract(
                schema=schema_json,
                markdown=response.markdown,
                model="extract-latest"
            )
            
            extracted_data = extraction_response.extraction
            
            # Ensure all fields are present
            result = {
                'form_type': extracted_data.get('form_type', ''),
                'tax_year': extracted_data.get('tax_year'),
                'taxpayer_name': extracted_data.get('taxpayer_name', ''),
                'taxpayer_ssn': extracted_data.get('taxpayer_ssn', ''),
                'filing_status': extracted_data.get('filing_status', ''),
                'form_data': extracted_data.get('form_data', {}),
                'line_items': extracted_data.get('line_items', []),
                'calculations': extracted_data.get('calculations', {}),
                'schedules': extracted_data.get('schedules', [])
            }
            
            logger.info(f"Successfully extracted data from tax document")
            return result
            
        except Exception as e:
            logger.error(f"Error processing tax document: {e}", exc_info=True)
            raise

