from landingai_ade import LandingAIADE
from pathlib import Path
from config import Config
import logging
import json

logger = logging.getLogger(__name__)

class DocumentProcessor:
    def __init__(self):
        # Try both parameter names for API key compatibility
        self.ade_client = LandingAIADE(apikey=Config.LANDING_AI_API_KEY)
    
    def extract_contract_data(self, file_path):
        """
        Extract contract data using Landing AI ADE.
        Returns a dictionary with contract metadata.
        """
        try:
            # Parse the document
            logger.info(f"Parsing document: {file_path}")
            logger.info("Calling Landing AI ADE parse API... (this may take a while)")
            
            # Check if API key is set
            if not Config.LANDING_AI_API_KEY:
                raise ValueError("LANDING_AI_API_KEY is not set in environment variables")
            
            # Open file in binary mode for ADE
            with open(file_path, 'rb') as file:
                file_size = len(file.read())
                file.seek(0)  # Reset file pointer
                logger.info(f"File size: {file_size} bytes")
                
                logger.info("Sending request to Landing AI ADE...")
                response = self.ade_client.parse(
                    document=file,
                    model="dpt-2-latest"
                )
                logger.info("Received response from Landing AI ADE parse API")
                
            # Define the schema for contract extraction
            schema = {
                "type": "object",
                "properties": {
                    "contract_id": {
                        "type": "string",
                        "description": "The contract number or ID"
                    },
                    "summary": {
                        "type": "string",
                        "description": "A brief summary or description of the contract"
                    }
                },
                "required": ["contract_id", "summary"]
            }
            
            schema_json = json.dumps(schema)
            # Extract fields based on the schema
            logger.info("Extracting data using schema...")
            logger.info("Calling Landing AI ADE extract API... (this may take a while)")
            extraction_response = self.ade_client.extract(
                schema=schema_json,
                markdown=response.markdown,
                model="extract-latest"
            )
            logger.info("Received response from Landing AI ADE extract API")
            
            # Convert to dictionary format
            extracted_data = extraction_response.extraction
            
            # Ensure all fields are present with defaults
            metadata = {
                'contract_id': extracted_data.get('contract_id', ''),
                'summary': extracted_data.get('summary', '')
            }
            
            logger.info(f"Successfully extracted contract data: {metadata.get('contract_id')}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting contract data: {e}", exc_info=True)
            logger.error(f"Error type: {type(e).__name__}")
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise Exception("Landing AI ADE API request timed out. Please check your network connection and try again.")
            elif "api" in str(e).lower() and "key" in str(e).lower():
                raise Exception("Invalid or missing Landing AI API key. Please check your LANDING_AI_API_KEY environment variable.")
            else:
                raise
    
    def extract_invoice_data(self, file_path):
        """
        Extract invoice data using Landing AI ADE.
        Returns a dictionary with invoice metadata.
        """
        try:
            # Parse the document
            logger.info(f"Parsing document: {file_path}")
            logger.info("Calling Landing AI ADE parse API... (this may take a while)")
            
            # Check if API key is set
            if not Config.LANDING_AI_API_KEY:
                raise ValueError("LANDING_AI_API_KEY is not set in environment variables")
            
            # Open file in binary mode for ADE
            with open(file_path, 'rb') as file:
                file_size = len(file.read())
                file.seek(0)  # Reset file pointer
                logger.info(f"File size: {file_size} bytes")
                
                logger.info("Sending request to Landing AI ADE...")
                response = self.ade_client.parse(
                    document=file,
                    model="dpt-2-latest"
                )
                logger.info("Received response from Landing AI ADE parse API")
            
            # Define the schema for invoice extraction
            schema = {
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "The invoice number or ID"
                    },
                    "seller_name": {
                        "type": "string",
                        "description": "The name of the seller or vendor"
                    },
                    "seller_address": {
                        "type": "string",
                        "description": "The address of the seller"
                    },
                    "tax_id": {
                        "type": "string",
                        "description": "Tax identification number or VAT number"
                    },
                    "subtotal_amount": {
                        "type": "number",
                        "description": "The subtotal amount before tax"
                    },
                    "tax_amount": {
                        "type": "number",
                        "description": "The tax amount"
                    },
                    "summary": {
                        "type": "string",
                        "description": "A brief summary or description of the invoice"
                    }
                },
                "required": ["invoice_id", "seller_name", "subtotal_amount"]
            }
            
            schema_json = json.dumps(schema)
            # Extract fields based on the schema
            logger.info("Extracting data using schema...")
            logger.info("Calling Landing AI ADE extract API... (this may take a while)")
            extraction_response = self.ade_client.extract(
                schema=schema_json,
                markdown=response.markdown,
                model="extract-latest"
            )
            logger.info("Received response from Landing AI ADE extract API")
            
            # Convert to dictionary format
            extracted_data = extraction_response.extraction
            
            # Ensure all fields are present with defaults
            metadata = {
                'invoice_id': extracted_data.get('invoice_id', ''),
                'seller_name': extracted_data.get('seller_name', ''),
                'seller_address': extracted_data.get('seller_address', ''),
                'tax_id': extracted_data.get('tax_id', ''),
                'subtotal_amount': float(extracted_data.get('subtotal_amount', 0)) if extracted_data.get('subtotal_amount') else 0.0,
                'tax_amount': float(extracted_data.get('tax_amount', 0)) if extracted_data.get('tax_amount') else 0.0,
                'summary': extracted_data.get('summary', '')
            }
            
            logger.info(f"Successfully extracted invoice data: {metadata.get('invoice_id')}")

            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting invoice data: {e}", exc_info=True)
            logger.error(f"Error type: {type(e).__name__}")
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise Exception("Landing AI ADE API request timed out. Please check your network connection and try again.")
            elif "api" in str(e).lower() and "key" in str(e).lower():
                raise Exception("Invalid or missing Landing AI API key. Please check your LANDING_AI_API_KEY environment variable.")
            else:
                raise

