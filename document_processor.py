from landingai_ade import LandingAIADE
from pathlib import Path
from config import Config
import logging
import json
from difflib import SequenceMatcher

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
                    "vendor_name": {
                        "type": "string",
                        "description": "The name of the vendor, supplier, or service provider party to this contract. This is critical for matching contracts to invoices."
                    },
                    "effective_date": {
                        "type": "string",
                        "description": "The date when the contract becomes effective or starts (format: YYYY-MM-DD or as written in contract)"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Contract start date if different from effective date (format: YYYY-MM-DD or as written)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Contract end date or expiration date (format: YYYY-MM-DD or as written). Leave empty if contract has no end date."
                    },
                    "pricing_sections": {
                        "type": "string",
                        "description": "Extract all pricing-related clauses, sections, and terms from the contract. Include rate schedules, pricing tables, unit prices, caps, limits, and any pricing rules. This should be a comprehensive extraction of all pricing information."
                    },
                    "service_types": {
                        "type": "array",
                        "description": "List of service types, service categories, or service descriptions covered by this contract",
                        "items": {
                            "type": "string"
                        }
                    },
                    "summary": {
                        "type": "string",
                        "description": "A brief summary or description of the contract"
                    },
                    "text": {
                        "type": "string",
                        "description": "The complete full text of the entire contract. Include all sections, clauses, appendices, and schedules. This is the complete document text."
                    },
                    "clauses": {
                        "type": "array",
                        "description": "Array of individual clauses or sections from the contract. Extract numbered sections, clauses, or distinct contractual provisions. Each clause should be a separate object. If the contract has clear section numbering (e.g., 'Section 4.2', 'Clause 3.1'), extract those. If not clearly numbered, extract distinct paragraphs or provisions as separate clauses.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "clause_id": {
                                    "type": "string",
                                    "description": "Clause identifier such as section number, clause number, or reference (e.g., 'Section 4.2', 'Clause 3.1', 'Article 5', 'Schedule A'). If not explicitly numbered, use a descriptive identifier."
                                },
                                "clause_type": {
                                    "type": "string",
                                    "description": "Type or category of the clause. Common types: 'pricing', 'payment_terms', 'service_description', 'liability', 'termination', 'scope_of_work', 'deliverables', 'sla', 'warranty', 'intellectual_property', 'confidentiality', 'general_terms'. If uncertain, use 'general'.",
                                    "enum": ["pricing", "payment_terms", "service_description", "liability", "termination", "scope_of_work", "deliverables", "sla", "warranty", "intellectual_property", "confidentiality", "general_terms", "general"]
                                },
                                "section_title": {
                                    "type": "string",
                                    "description": "Title or heading of the section containing this clause (e.g., 'Routine Services Pricing', 'Payment Terms', 'Service Level Agreement')"
                                },
                                "clause_text": {
                                    "type": "string",
                                    "description": "The complete text content of this clause or section. Include all details, conditions, and provisions within this clause."
                                },
                                "page_number": {
                                    "type": "number",
                                    "description": "Page number where this clause appears in the contract (if available)"
                                }
                            },
                            "required": ["clause_text"]
                        }
                    }
                },
                "required": ["contract_id", "text"]
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
                'vendor_name': extracted_data.get('vendor_name', ''),
                'effective_date': extracted_data.get('effective_date', ''),
                'start_date': extracted_data.get('start_date', ''),
                'end_date': extracted_data.get('end_date', ''),
                'pricing_sections': extracted_data.get('pricing_sections', ''),
                'service_types': extracted_data.get('service_types', []),
                'summary': extracted_data.get('summary', ''),
                'text': extracted_data.get('text', ''),
                'clauses': extracted_data.get('clauses', [])
            }
            
            # Log extraction results
            clauses_count = len(metadata.get('clauses', []))
            if clauses_count > 0:
                logger.info(f"Extracted {clauses_count} clauses for contract {metadata.get('contract_id')}")
            else:
                logger.info(f"No clauses extracted for contract {metadata.get('contract_id')}, will use full text")
            
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
    
    def _match_line_items_to_chunks(self, line_items, chunks):
        """
        Match extracted line items to chunks to extract bounding box coordinates.
        Returns line items with pdf_location metadata added.
        """
        # Collect all diagnostic logs to output at once (API calls are expensive)
        diagnostic_logs = []
        
        try:
            if not chunks:
                logger.warning("No chunks provided for bounding box extraction")
                return line_items
            
            # Build a list of chunks with their text and grounding info
            chunk_data = []
            
            for idx, chunk in enumerate(chunks):
                chunk_diag = {
                    'chunk_idx': idx,
                    'type': str(type(chunk)),
                    'has_markdown': False,
                    'has_grounding': False,
                    'has_box': False,
                    'text_length': 0,
                    'bbox': None,
                    'page': None,
                    'errors': []
                }
                
                # Extract text from markdown
                text = ""
                import re
                
                try:
                    text = chunk.markdown
                    chunk_diag['has_markdown'] = True
                except (AttributeError, TypeError) as e:
                    chunk_diag['errors'].append(f"markdown access: {e}")
                    try:
                        text = getattr(chunk, 'markdown', None) or ""
                        if text:
                            chunk_diag['has_markdown'] = True
                    except Exception as e2:
                        chunk_diag['errors'].append(f"getattr markdown: {e2}")
                        if isinstance(chunk, dict):
                            text = chunk.get('markdown') or chunk.get('text', '')
                            if text:
                                chunk_diag['has_markdown'] = True
                
                # Clean markdown - remove HTML tags and anchors
                if text:
                    text = re.sub(r'<[^>]+>', '', text).strip()
                    chunk_diag['text_length'] = len(text)
                
                # Extract grounding
                grounding_obj = None
                try:
                    grounding_obj = chunk.grounding
                    chunk_diag['has_grounding'] = True
                except (AttributeError, TypeError) as e:
                    chunk_diag['errors'].append(f"grounding access: {e}")
                    try:
                        grounding_obj = getattr(chunk, 'grounding', None)
                        if grounding_obj:
                            chunk_diag['has_grounding'] = True
                    except Exception as e2:
                        chunk_diag['errors'].append(f"getattr grounding: {e2}")
                        if isinstance(chunk, dict):
                            grounding_obj = chunk.get('grounding')
                            if grounding_obj:
                                chunk_diag['has_grounding'] = True
                
                # Process grounding object
                if grounding_obj:
                    # Extract box
                    box_obj = None
                    try:
                        box_obj = grounding_obj.box
                        chunk_diag['has_box'] = True
                    except (AttributeError, TypeError) as e:
                        chunk_diag['errors'].append(f"box access: {e}")
                        try:
                            box_obj = getattr(grounding_obj, 'box', None)
                            if box_obj:
                                chunk_diag['has_box'] = True
                        except Exception as e2:
                            chunk_diag['errors'].append(f"getattr box: {e2}")
                            if isinstance(grounding_obj, dict):
                                box_obj = grounding_obj.get('box')
                                if box_obj:
                                    chunk_diag['has_box'] = True
                    
                    # Extract page
                    page = 0
                    try:
                        page = getattr(grounding_obj, 'page', 0)
                    except (AttributeError, TypeError):
                        if isinstance(grounding_obj, dict):
                            page = grounding_obj.get('page', 0)
                    chunk_diag['page'] = page
                    
                    if box_obj:
                        # Extract coordinates
                        left = top = right = bottom = 0
                        try:
                            left = box_obj.left
                            top = box_obj.top
                            right = box_obj.right
                            bottom = box_obj.bottom
                        except (AttributeError, TypeError) as e:
                            chunk_diag['errors'].append(f"coords direct access: {e}")
                            try:
                                left = getattr(box_obj, 'left', 0)
                                top = getattr(box_obj, 'top', 0)
                                right = getattr(box_obj, 'right', 0)
                                bottom = getattr(box_obj, 'bottom', 0)
                            except Exception as e2:
                                chunk_diag['errors'].append(f"coords getattr: {e2}")
                                if isinstance(box_obj, dict):
                                    left = box_obj.get('left') or box_obj.get('l', 0)
                                    top = box_obj.get('top') or box_obj.get('t', 0)
                                    right = box_obj.get('right') or box_obj.get('r', 0)
                                    bottom = box_obj.get('bottom') or box_obj.get('b', 0)
                        
                        chunk_diag['bbox'] = {'left': left, 'top': top, 'right': right, 'bottom': bottom}
                        
                        # Store chunk data
                        chunk_data.append({
                            'text': text.lower().strip(),
                            'box': {
                                'left': left,
                                'top': top,
                                'right': right,
                                'bottom': bottom
                            },
                            'page': page,
                            'original_text': text
                        })
                
                diagnostic_logs.append(chunk_diag)
            
            # Match each line item to chunks
            matching_logs = []
            for line_item in line_items:
                if 'metadata' not in line_item:
                    line_item['metadata'] = {}
                
                # Try to find matching chunk by description
                description = (line_item.get('description') or '').lower().strip()
                service_code = (line_item.get('service_code') or '').lower().strip()
                
                best_match = None
                best_score = 0.0
                
                for chunk in chunk_data:
                    chunk_text = chunk['text']
                    
                    # Calculate similarity scores
                    desc_score = SequenceMatcher(None, description, chunk_text).ratio() if description else 0
                    
                    # Also check if service code appears in chunk text
                    service_score = 0.0
                    if service_code and service_code in chunk_text:
                        service_score = 0.5
                    
                    # Combined score
                    score = max(desc_score, service_score)
                    
                    # Prefer chunks that contain key pricing terms
                    if any(term in chunk_text for term in ['$', 'price', 'total', 'amount', 'cost']):
                        score += 0.1
                    
                    if score > best_score:
                        best_score = score
                        best_match = chunk
                
                # If we found a reasonable match (similarity > 0.3), add bounding box
                if best_match and best_score > 0.3:
                    box = best_match['box']
                    page = best_match['page']
                    
                    # Extract bounding box coordinates
                    # ADE uses normalized coordinates (0-1) with left, top, right, bottom
                    left = box.get('left', 0)
                    top = box.get('top', 0)
                    right = box.get('right', 0)
                    bottom = box.get('bottom', 0)
                    
                    # Store in metadata
                    line_item['metadata']['pdf_location'] = {
                        'page_number': page + 1,  # Convert 0-indexed to 1-indexed
                        'bbox': {
                            'left': left,
                            'top': top,
                            'right': right,
                            'bottom': bottom
                        },
                        'normalized': True,
                        'coordinate_system': 'normalized_0_1'
                    }
                    matching_logs.append({
                        'line_item': description[:50],
                        'service_code': service_code,
                        'matched': True,
                        'score': best_score,
                        'bbox': {'left': left, 'top': top, 'right': right, 'bottom': bottom},
                        'page': page + 1
                    })
                else:
                    matching_logs.append({
                        'line_item': description[:50],
                        'service_code': service_code,
                        'matched': False,
                        'score': best_score
                    })
            
            # Output all diagnostic logs at once
            logger.info("=" * 80)
            logger.info("BOUNDING BOX EXTRACTION DIAGNOSTICS")
            logger.info("=" * 80)
            logger.info(f"Total chunks received: {len(chunks)}")
            logger.info(f"Chunks with bounding box data: {len(chunk_data)}")
            logger.info("")
            
            # Chunk extraction details
            for diag in diagnostic_logs:
                status = "✓" if diag['bbox'] else "✗"
                logger.info(f"Chunk {diag['chunk_idx']}: {status} Type={diag['type']}, "
                          f"Markdown={diag['has_markdown']}, Grounding={diag['has_grounding']}, "
                          f"Box={diag['has_box']}, TextLen={diag['text_length']}, "
                          f"Page={diag['page']}, BBox={diag['bbox']}")
                if diag['errors']:
                    for err in diag['errors']:
                        logger.info(f"  Error: {err}")
            
            logger.info("")
            logger.info(f"Line items matched: {len([m for m in matching_logs if m['matched']])} out of {len(matching_logs)}")
            for match_log in matching_logs:
                if match_log['matched']:
                    logger.info(f"  ✓ '{match_log['line_item']}' -> Score: {match_log['score']:.2f}, "
                              f"Page: {match_log['page']}, BBox: {match_log['bbox']}")
                else:
                    logger.info(f"  ✗ '{match_log['line_item']}' -> No match (best score: {match_log['score']:.2f})")
            logger.info("=" * 80)
            
            return line_items
        except Exception as e:
            logger.error(f"Error matching line items to chunks for bounding boxes: {e}", exc_info=True)
            # Return line items without bounding boxes if matching fails
            return line_items
    
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
                    },
                    "full_text": {
                        "type": "string",
                        "description": "The complete text content of the invoice as extracted from the document. Include all line items, descriptions, quantities, prices, and any other details visible on the invoice."
                    },
                    "line_items": {
                        "type": "array",
                        "description": "Array of individual line items from the invoice",
                        "items": {
                            "type": "object",
                            "properties": {
                                "line_id": {
                                    "type": "string",
                                    "description": "Line item identifier or number (e.g., 'L-001', '1', 'Item 1')"
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Description of the service or product"
                                },
                                "service_code": {
                                    "type": "string",
                                    "description": "Service code, SKU, or product code if available"
                                },
                                "quantity": {
                                    "type": "number",
                                    "description": "Quantity of items or units"
                                },
                                "unit_price": {
                                    "type": "number",
                                    "description": "Price per unit"
                                },
                                "total_price": {
                                    "type": "number",
                                    "description": "Total price for this line item (quantity × unit_price)"
                                }
                            },
                            "required": ["description"]
                        }
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
            
            # Extract line items
            line_items = extracted_data.get('line_items', [])
            
            # Match line items to chunks to get bounding boxes
            chunks = None
            if hasattr(response, 'chunks'):
                chunks = response.chunks
            elif hasattr(response, '__dict__') and 'chunks' in response.__dict__:
                chunks = response.__dict__['chunks']
            
            if chunks:
                line_items = self._match_line_items_to_chunks(line_items, chunks)
                matched_count = len([li for li in line_items if li.get('metadata', {}).get('pdf_location')])
                logger.info(f"Matched {matched_count} out of {len(line_items)} line items with bounding boxes")
            else:
                logger.warning("No chunks found in response - bounding boxes unavailable")
            
            # Ensure metadata exists for all line items (even if empty)
            for line_item in line_items:
                if 'metadata' not in line_item:
                    line_item['metadata'] = {}
                logger.debug(f"Line item metadata before return: {line_item.get('metadata')}")
            
            # Ensure all fields are present with defaults
            metadata = {
                'invoice_id': extracted_data.get('invoice_id', ''),
                'seller_name': extracted_data.get('seller_name', ''),
                'seller_address': extracted_data.get('seller_address', ''),
                'tax_id': extracted_data.get('tax_id', ''),
                'subtotal_amount': float(extracted_data.get('subtotal_amount', 0)) if extracted_data.get('subtotal_amount') else 0.0,
                'tax_amount': float(extracted_data.get('tax_amount', 0)) if extracted_data.get('tax_amount') else 0.0,
                'summary': extracted_data.get('summary', ''),
                'full_text': extracted_data.get('full_text', ''),
                'line_items': line_items
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

