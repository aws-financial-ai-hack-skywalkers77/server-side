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

        invoice_details = []
        if invoice_metadata.get("seller_name"):
            invoice_details.append(f"Vendor: {invoice_metadata['seller_name']}")
        if invoice_metadata.get("invoice_id"):
            invoice_details.append(f"Invoice ID: {invoice_metadata['invoice_id']}")
        if invoice_metadata.get("summary"):
            invoice_details.append(f"Summary: {invoice_metadata['summary']}")

        if invoice_metadata.get("line_items"):
            for item in invoice_metadata["line_items"][:5]:
                line_desc = item.get("description") or ""
                unit_price = item.get("unit_price")
                quantity = item.get("quantity")
                invoice_details.append(
                    f"Line Item: {line_desc}; unit_price={unit_price}; quantity={quantity}"
                )

        context = "\n\n---\n\n".join(contract_contexts)
        invoice_block = "\n".join(invoice_details)

        prompt = f"""
You are a contract compliance analyst. Use the contract clauses below to derive pricing rules that should be enforced against the provided invoice context. Return your findings strictly as JSON.

Contract Clauses:
{context}

Invoice Context:
{invoice_block}

Return JSON with the following structure:
{{
  "rules": [
    {{
      "service_code": "optional code that identifies the service",
      "keywords": ["list", "of", "phrases"] optional,
      "unit_price": number or null,
      "price_cap": number or null,
      "flat_fee": number or null,
      "tolerance_amount": number optional,
      "tolerance_percent": number optional,
      "violation_type": "string describing the violation if exceeded",
      "clause_reference": "Contract section or clause identifier",
      "notes": "Optional clarifying notes"
    }}
  ],
  "rationale": "Brief explanation of how the rules were derived"
}}

Do not include any additional text outside of the JSON payload.
"""

        model, model_name = self._get_generative_model()

        logger.info("Requesting pricing rules from Gemini model '%s'", model_name)
        response = model.generate_content(prompt)
        raw_text = self._extract_text_from_response(response)

        try:
            parsed = json.loads(raw_text)
            if "rules" not in parsed:
                parsed["rules"] = []
            return parsed
        except json.JSONDecodeError as decode_error:
            logger.error("Failed to parse pricing rules JSON: %s", decode_error)
            return {
                "rules": [],
                "notes": f"Failed to parse pricing rules JSON: {decode_error}",
                "raw_response": raw_text,
            }

