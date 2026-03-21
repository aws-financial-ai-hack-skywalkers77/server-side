import json
import logging
import google.generativeai as genai
from config import Config

logger = logging.getLogger(__name__)

class Vectorizer:
    def __init__(self):
        # Use GEMINI_API_KEY, fallback to VERTEX_AI if needed
        api_key = Config.GEMINI_API_KEY or Config.VERTEX_AI
        if not api_key:
            raise ValueError("GEMINI_API_KEY or VERTEX_AI must be set in environment variables")
        genai.configure(api_key=api_key)
        self.model = Config.EMBEDDING_MODEL
    
    def vectorize_metadata(self, metadata):
        """
        Convert metadata dictionary to a vector embedding using Gemini.
        Creates a text representation of the metadata and generates embeddings.
        Supports both invoice and contract metadata.
        """
        try:
            # Create a text representation of the metadata
            text_parts = []
            
            # Handle invoice metadata
            if metadata.get('invoice_id'):
                text_parts.append(f"Invoice ID: {metadata['invoice_id']}")
            if metadata.get('seller_name'):
                text_parts.append(f"Seller: {metadata['seller_name']}")
            if metadata.get('seller_address'):
                text_parts.append(f"Address: {metadata['seller_address']}")
            if metadata.get('tax_id'):
                text_parts.append(f"Tax ID: {metadata['tax_id']}")
            if metadata.get('subtotal_amount'):
                text_parts.append(f"Subtotal: {metadata['subtotal_amount']}")
            if metadata.get('tax_amount'):
                text_parts.append(f"Tax: {metadata['tax_amount']}")
            
            # Handle contract metadata
            if metadata.get('contract_id'):
                text_parts.append(f"Contract ID: {metadata['contract_id']}")
            if metadata.get('text'):
                # Include contract text (may be long, but that's okay for embeddings)
                text_parts.append(f"Text: {metadata['text']}")
            
            # Summary is common to both
            if metadata.get('summary'):
                text_parts.append(f"Summary: {metadata['summary']}")
            
            text = " | ".join(text_parts)
            
            # Generate embedding using Gemini
            result = genai.embed_content(
                model=self.model,
                content=text,
                task_type="RETRIEVAL_DOCUMENT"
            )
            
            # Extract the embedding vector
            # The google-generativeai package returns an EmbedContentResponse object
            # Check the actual structure of the response
            if hasattr(result, 'embedding'):
                if isinstance(result.embedding, dict):
                    embedding = result.embedding.get('values', result.embedding)
                else:
                    embedding = result.embedding
            elif isinstance(result, dict):
                embedding = result.get('embedding', result)
            else:
                embedding = result
            
            # Ensure we have a list
            if not isinstance(embedding, list):
                # Try to get values from the object
                if hasattr(embedding, 'values'):
                    embedding = embedding.values
                elif hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                    embedding = list(embedding)
                else:
                    raise ValueError(f"Unexpected embedding format: {type(embedding)}")
            
            # Log the actual dimensions for debugging
            logger.info(f"Generated embedding with {len(embedding)} dimensions")
            
            return embedding
        except Exception as e:
            logger.error(f"Error vectorizing metadata: {e}")
            raise
    
    def vectorize_query(self, query_text):
        """
        Convert a query string to a vector embedding using Gemini.
        This is used for semantic search queries.
        
        Args:
            query_text: The text query to vectorize
        
        Returns:
            List of floats representing the embedding vector
        """
        try:
            # Generate embedding using Gemini with RETRIEVAL_QUERY task type
            result = genai.embed_content(
                model=self.model,
                content=query_text,
                task_type="RETRIEVAL_QUERY"
            )
            
            # Extract the embedding vector
            if hasattr(result, 'embedding'):
                if isinstance(result.embedding, dict):
                    embedding = result.embedding.get('values', result.embedding)
                else:
                    embedding = result.embedding
            elif isinstance(result, dict):
                embedding = result.get('embedding', result)
            else:
                embedding = result
            
            # Ensure we have a list
            if not isinstance(embedding, list):
                if hasattr(embedding, 'values'):
                    embedding = embedding.values
                elif hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                    embedding = list(embedding)
                else:
                    raise ValueError(f"Unexpected embedding format: {type(embedding)}")
            
            logger.info(f"Generated query embedding with {len(embedding)} dimensions")
            
            return embedding
        except Exception as e:
            logger.error(f"Error vectorizing query: {e}")
            raise
    
    def _get_generative_model(self):
        """
        Initialize a Gemini generative model with graceful fallback to alt models.
        Returns (model_instance, model_name_used)
        """
        model_name = Config.GEMINI_GENERATION_MODEL
        logger.info(f"Attempting to use model: {model_name}")
        try:
            model = genai.GenerativeModel(model_name)
            return model, model_name
        except Exception as model_error:
            logger.error(f"Error initializing model '{model_name}': {model_error}")
            alternative_models = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"]
            for alt_model in alternative_models:
                if alt_model == model_name:
                    continue
                try:
                    logger.info(f"Trying alternative model: {alt_model}")
                    model = genai.GenerativeModel(alt_model)
                    logger.info(f"Successfully initialized model: {alt_model}")
                    return model, alt_model
                except Exception as alt_error:
                    logger.warning(
                        f"Failed to initialize alternative model '{alt_model}': {alt_error}"
                    )
                    continue
            raise ValueError(
                f"Could not initialize any Gemini model. Original error: {model_error}"
            )

    def _extract_text_from_response(self, response):
        """
        Extract textual content from Gemini response objects
        """
        # Method 1: Direct text attribute (most common)
        if hasattr(response, 'text') and response.text:
            return response.text

        # Method 2: Check candidates
        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content'):
                if hasattr(candidate.content, 'parts'):
                    text_parts = []
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        return ''.join(text_parts)
                elif hasattr(candidate.content, 'text') and candidate.content.text:
                    return candidate.content.text
                else:
                    return str(candidate.content)
            if hasattr(candidate, 'text') and candidate.text:
                return candidate.text
            return str(candidate)

        # Method 3: Check for prompt_feedback (might indicate safety blocking)
        if hasattr(response, 'prompt_feedback'):
            feedback = response.prompt_feedback
            logger.warning(f"Prompt feedback received: {feedback}")
            if hasattr(feedback, 'block_reason') and feedback.block_reason:
                raise ValueError(f"Content was blocked: {feedback.block_reason}")

        logger.error("Could not extract text from Gemini response")
        logger.error(f"Response type: {type(response)}")
        logger.error(
            f"Response attributes: {[attr for attr in dir(response) if not attr.startswith('_')]}"
        )
        if hasattr(response, '__dict__'):
            logger.error(f"Response dict: {response.__dict__}")
        raise ValueError("Could not extract answer from Gemini response")

    def generate_answer(self, query: str, context_texts: list, contract_ids: list = None):
        """
        Generate an answer to a query using retrieved contract contexts (RAG).
        
        Args:
            query: The user's query/question
            context_texts: List of contract text excerpts to use as context
            contract_ids: Optional list of contract IDs corresponding to context_texts
        
        Returns:
            Generated answer string
        """
        try:
            # Check if we have context
            if not context_texts:
                logger.warning("No context texts provided for answer generation")
                return "No contract context available to generate an answer."
            
            # Build the context from retrieved contracts
            context_parts = []
            for i, text in enumerate(context_texts):
                if contract_ids and i < len(contract_ids):
                    context_parts.append(f"Contract ID: {contract_ids[i]}\n{text}")
                else:
                    context_parts.append(f"Contract Excerpt {i+1}:\n{text}")
            
            context = "\n\n---\n\n".join(context_parts)
            
            # Build the prompt for the LLM
            prompt = f"""You are a helpful assistant that answers questions about contracts based on the provided contract excerpts.

Use the following contract excerpts to answer the user's question. If the information is not available in the provided excerpts, say so clearly.

Contract Excerpts:
{context}

User Question: {query}

Please provide a clear, accurate answer based on the contract excerpts above. If you reference specific information, mention which contract it comes from if available."""
            
            model, model_name = self._get_generative_model()

            # Generate response
            logger.info("Generating response from Gemini...")
            try:
                response = model.generate_content(prompt)
            except Exception as gen_error:
                logger.error(f"Error calling generate_content: {gen_error}")
                raise
            
            answer = self._extract_text_from_response(response)
            
            if not answer.strip():
                logger.error("Generated answer is empty after extraction")
                raise ValueError("Generated answer is empty")
            
            logger.info(f"Successfully generated answer using {model_name}")
            return answer.strip()
        except Exception as e:
            logger.error(f"Error generating answer: {e}", exc_info=True)
            raise

    def extract_pricing_rules(
        self,
        invoice_metadata: dict,
        contract_contexts: list,
    ) -> dict:
        """
        Use Gemini to derive structured pricing rules from contract contexts.

        Returns:
            Dictionary with keys:
                - rules: List of pricing rule dicts
                - rationale: Optional explanation text
        """
        if not contract_contexts:
            return {"rules": [], "notes": "No contract context provided"}

        # Build detailed invoice line items for matching
        invoice_line_items = []
        if invoice_metadata.get("line_items"):
            for idx, item in enumerate(invoice_metadata["line_items"][:10], 1):
                line_id = item.get("line_id") or f"L-{idx:03d}"
                description = item.get("description") or ""
                service_code = item.get("service_code") or ""
                quantity = item.get("quantity", 1)
                unit_price = item.get("unit_price")
                total_price = item.get("total_price")
                
                line_str = f"Line {line_id}: {description}"
                if service_code:
                    line_str += f" (Service Code: {service_code})"
                line_str += f" | Quantity: {quantity} | Unit Price: ${unit_price} | Total: ${total_price}"
                invoice_line_items.append(line_str)
        else:
            # Fallback for inferred line items
            subtotal = invoice_metadata.get("subtotal_amount", 0)
            if subtotal:
                invoice_line_items.append(f"Line L-001: Invoice Total | Quantity: 1 | Unit Price: ${subtotal} | Total: ${subtotal}")

        # Format contract contexts with clear separators
        formatted_contexts = []
        for idx, ctx in enumerate(contract_contexts[:5], 1):
            # Truncate very long contexts to focus on pricing clauses
            max_length = 2000
            if len(ctx) > max_length:
                ctx = ctx[:max_length] + "... [truncated]"
            formatted_contexts.append(f"=== CONTRACT CLAUSE {idx} ===\n{ctx}\n")

        context_block = "\n\n".join(formatted_contexts)
        invoice_block = "\n".join(invoice_line_items) if invoice_line_items else "No line items available"

        # Enhanced prompt with examples and explicit instructions
        prompt = f"""You are an expert contract compliance analyst. Your task is to extract PRECISE pricing rules from the contract clauses below that apply to the invoice line items.

CRITICAL INSTRUCTIONS:
1. Extract ALL pricing limits, caps, rates, and fees mentioned in the contract clauses
2. Match each invoice line item to relevant contract pricing rules
3. Extract EXACT NUMERIC VALUES (dollars, percentages, quantities) from the contract
4. If a contract mentions "$120 per tree" or "maximum $120 per unit", extract unit_price: 120
5. If a contract mentions "not to exceed $250" or "capped at $250", extract price_cap: 250
6. Include service codes, keywords, or descriptions that help match invoice lines to rules
7. Be aggressive in finding pricing constraints - look for words like "maximum", "cap", "limit", "not to exceed", "shall not exceed", "up to", "per unit", "per hour", etc.

EXAMPLE OUTPUT:
If contract says: "Routine tree pruning services shall be billed at a rate not to exceed $120 per tree. Emergency services may include a mobilization surcharge not to exceed $250."
And invoice has: "Line L-001: Willow tree pruning (12 trees @ $150 each)"

You should extract:
{{
  "rules": [
    {{
      "keywords": ["tree pruning", "pruning", "routine"],
      "unit_price": 120,
      "price_cap": 120,
      "violation_type": "Unit Price Exceeds Contract Cap",
      "clause_reference": "Section 4.2 - Routine Services Pricing",
      "notes": "Contract caps routine pruning at $120/tree"
    }},
    {{
      "keywords": ["emergency", "mobilization", "surcharge"],
      "price_cap": 250,
      "violation_type": "Mobilization Surcharge Exceeds Cap",
      "clause_reference": "Section 4.3 - Emergency Services",
      "notes": "Emergency mobilization surcharge capped at $250"
    }}
  ],
  "rationale": "Extracted unit price cap of $120/tree for routine pruning and $250 cap for emergency mobilization from contract clauses."
}}

CONTRACT CLAUSES:
{context_block}

INVOICE LINE ITEMS TO EVALUATE:
{invoice_block}

Now extract pricing rules from the contract clauses that apply to these invoice line items. Return ONLY valid JSON in this exact format:
{{
  "rules": [
    {{
      "service_code": "string or null - service identifier if mentioned",
      "keywords": ["array", "of", "matching", "terms"],
      "unit_price": number or null,
      "price_cap": number or null,
      "flat_fee": number or null,
      "tolerance_amount": number or null,
      "tolerance_percent": number or null,
      "violation_type": "string describing what violation occurs if exceeded",
      "clause_reference": "string - section/clause identifier from contract",
      "notes": "string - brief explanation"
    }}
  ],
  "rationale": "string - explanation of extracted rules"
}}

IMPORTANT: Return ONLY the JSON object. No markdown, no code blocks, no explanations outside the JSON."""

        model, model_name = self._get_generative_model()

        logger.info("Requesting pricing rules from Gemini model '%s'", model_name)
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,  # Lower temperature for more consistent extraction
                    "top_p": 0.8,
                }
            )
        except Exception as e:
            logger.warning(f"Error with generation_config, trying without: {e}")
            response = model.generate_content(prompt)
        
        raw_text = self._extract_text_from_response(response)
        
        # Clean up common JSON extraction issues
        raw_text = raw_text.strip()
        # Remove markdown code blocks if present
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        try:
            parsed = json.loads(raw_text)
            if "rules" not in parsed:
                parsed["rules"] = []
            # Validate and log extracted rules
            logger.info(f"Extracted {len(parsed.get('rules', []))} pricing rules from contract")
            for rule in parsed.get("rules", []):
                logger.debug(f"Rule: {rule.get('keywords', [])} -> unit_price={rule.get('unit_price')}, price_cap={rule.get('price_cap')}")
            return parsed
        except json.JSONDecodeError as decode_error:
            logger.error("Failed to parse pricing rules JSON: %s", decode_error)
            logger.error("Raw response (first 500 chars): %s", raw_text[:500])
            return {
                "rules": [],
                "notes": f"Failed to parse pricing rules JSON: {decode_error}",
                "raw_response": raw_text[:1000],  # Store first 1000 chars for debugging
            }

