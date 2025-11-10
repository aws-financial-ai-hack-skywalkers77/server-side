import google.generativeai as genai
from config import Config
import logging

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

