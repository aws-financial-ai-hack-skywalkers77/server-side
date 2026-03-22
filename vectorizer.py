import json
import logging
from dataclasses import replace
from typing import Any, Dict, List, Optional

import google.generativeai as genai
from config import Config
from evidence_validation import partition_rules_by_evidence
from retrieval_chunk import RetrievalChunk

logger = logging.getLogger(__name__)

_CHUNK_PROMPT_MAX = 2000


def _truncated_text(text: str, max_len: int = _CHUNK_PROMPT_MAX) -> str:
    if len(text) > max_len:
        return text[:max_len] + "... [truncated]"
    return text

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
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=Config.EMBEDDING_DIMENSIONS,
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
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=Config.EMBEDDING_DIMENSIONS,
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
            prompt = f"""You are an assistant that answers questions using ONLY the provided contract excerpts.

Rules:
- Cite the Contract ID when you state a specific fact (e.g. "Under Contract ID X, ...").
- If the answer is not supported by the excerpts, say clearly that the information is not in the provided text.
- Do not invent clauses, dates, amounts, or obligations that are not in the excerpts.
- Do not rely on general legal knowledge beyond what the excerpts say.

Contract Excerpts:
{context}

User Question: {query}

Answer clearly. If the excerpts are insufficient, say what is missing."""
            
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
        retrieval_chunks: Optional[List[RetrievalChunk]] = None,
        contract_contexts: Optional[list] = None,
    ) -> dict:
        """
        Use Gemini to derive structured pricing rules from tagged retrieval chunks.

        Each rule must include evidence_quotes pointing at chunk_index and verbatim text
        that appears in that chunk (validated programmatically).

        For backward compatibility, contract_contexts (list of strings) may be passed
        instead of retrieval_chunks; in that case evidence validation is skipped.
        """
        chunks_in: Optional[List[RetrievalChunk]] = retrieval_chunks
        if chunks_in is None and contract_contexts:
            chunks_in = [
                RetrievalChunk(
                    chunk_index=i,
                    contract_db_id=-1,
                    contract_id=None,
                    text=ctx,
                    context_source="legacy_string",
                )
                for i, ctx in enumerate(contract_contexts[:5])
            ]
        if not chunks_in:
            return {
                "rules": [],
                "rejected_rules": [],
                "notes": "No contract context provided",
                "parse_failed": False,
                "extraction_model": None,
                "rules_raw_count": 0,
                "validated_rules_count": 0,
            }

        # Align prompt text with validation (truncated the same way)
        truncated_chunks = [
            replace(c, text=_truncated_text(c.text)) for c in chunks_in[:5]
        ]

        # Build detailed invoice line items for matching
        invoice_line_items = []
        if invoice_metadata.get("line_items"):
            for idx, item in enumerate(invoice_metadata["line_items"][:10], 1):
                lid_raw = (item.get("line_id") or "").strip()
                line_label = lid_raw if lid_raw else f"row {idx+1} (no line number in extraction)"
                description = item.get("description") or ""
                service_code = item.get("service_code") or ""
                quantity = item.get("quantity", 1)
                unit_price = item.get("unit_price")
                total_price = item.get("total_price")

                line_str = f"Line {line_label}: {description}"
                if service_code:
                    line_str += f" (Service Code: {service_code})"
                line_str += f" | Quantity: {quantity} | Unit Price: ${unit_price} | Total: ${total_price}"
                invoice_line_items.append(line_str)
        else:
            subtotal = invoice_metadata.get("subtotal_amount", 0)
            if subtotal:
                invoice_line_items.append(
                    f"Invoice total (single synthesized line) | Quantity: 1 | Unit Price: ${subtotal} | Total: ${subtotal}"
                )

        chunk_blocks = []
        for c in truncated_chunks:
            chunk_blocks.append(
                f"=== CHUNK_INDEX: {c.chunk_index} | CONTRACT_DB_ID: {c.contract_db_id} | "
                f"CONTRACT_ID: {c.contract_id or 'unknown'} ===\n"
                f"{c.text}\n"
            )
        context_block = "\n\n".join(chunk_blocks)
        invoice_block = "\n".join(invoice_line_items) if invoice_line_items else "No line items available"

        prompt = f"""You are an expert contract compliance analyst. Extract PRECISE pricing rules from the chunks below for the invoice line items.

EVIDENCE REQUIREMENTS (mandatory for every rule):
- Each rule MUST include "evidence_quotes": an array of at least one object:
  {{ "chunk_index": <int matching CHUNK_INDEX above>, "verbatim_quote": "<exact substring from that chunk's text>" }}
- The verbatim_quote MUST be copy-pasted from the chunk text (it will be validated).

CRITICAL INSTRUCTIONS:
1. Extract pricing limits, caps, rates, and fees from the chunks only.
2. Extract EXACT NUMERIC VALUES from the contract text.
3. Include keywords or service_code to match invoice lines.
4. Use chunk_index from the headers to cite evidence.

EXAMPLE (structure only):
{{
  "rules": [
    {{
      "keywords": ["tree", "pruning"],
      "unit_price": 120,
      "price_cap": 120,
      "violation_type": "Unit Price Exceeds Contract Cap",
      "clause_reference": "Section named in chunk",
      "notes": "Cap from contract",
      "evidence_quotes": [{{ "chunk_index": 0, "verbatim_quote": "not to exceed $120 per tree" }}]
    }}
  ],
  "rationale": "Brief summary."
}}

RETRIEVED CONTRACT CHUNKS:
{context_block}

INVOICE LINE ITEMS:
{invoice_block}

Return ONLY valid JSON:
{{
  "rules": [
    {{
      "service_code": null,
      "keywords": [],
      "unit_price": null,
      "price_cap": null,
      "flat_fee": null,
      "tolerance_amount": null,
      "tolerance_percent": null,
      "violation_type": "string",
      "clause_reference": "string",
      "notes": "string",
      "evidence_quotes": [{{ "chunk_index": 0, "verbatim_quote": "..." }}]
    }}
  ],
  "rationale": "string"
}}

IMPORTANT: Return ONLY the JSON object. No markdown fences."""

        model, model_name = self._get_generative_model()

        logger.info("Requesting pricing rules from Gemini model '%s'", model_name)
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.8,
                },
            )
        except Exception as e:
            logger.warning("Error with generation_config, trying without: %s", e)
            response = model.generate_content(prompt)

        raw_text = self._extract_text_from_response(response)

        raw_text = raw_text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        legacy_mode = retrieval_chunks is None and contract_contexts is not None

        try:
            parsed = json.loads(raw_text)
            if "rules" not in parsed:
                parsed["rules"] = []
            raw_rules = parsed.get("rules") or []
            if not isinstance(raw_rules, list):
                raw_rules = []

            if legacy_mode:
                validated = raw_rules
                rejected: List[Dict[str, Any]] = []
            else:
                validated, rejected = partition_rules_by_evidence(raw_rules, truncated_chunks)

            logger.info(
                "Pricing rules: raw=%s validated=%s rejected=%s",
                len(raw_rules),
                len(validated),
                len(rejected),
            )
            out: Dict[str, Any] = {
                "rules": validated,
                "rejected_rules": rejected,
                "rationale": parsed.get("rationale"),
                "parse_failed": False,
                "extraction_model": model_name,
                "rules_raw_count": len(raw_rules),
                "validated_rules_count": len(validated),
            }
            return out
        except json.JSONDecodeError as decode_error:
            logger.error("Failed to parse pricing rules JSON: %s", decode_error)
            logger.error("Raw response (first 500 chars): %s", raw_text[:500])
            return {
                "rules": [],
                "rejected_rules": [],
                "notes": f"Failed to parse pricing rules JSON: {decode_error}",
                "raw_response": raw_text[:1000],
                "parse_failed": True,
                "extraction_model": model_name,
                "rules_raw_count": 0,
                "validated_rules_count": 0,
            }

