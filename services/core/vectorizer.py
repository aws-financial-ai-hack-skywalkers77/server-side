# services/core/vectorizer.py

import google.generativeai as genai
from typing import List, Optional
import logging
import os

logger = logging.getLogger(__name__)

class Vectorizer:
    """
    Vectorization service for tax intelligence platform.
    Uses Google Gemini for generating embeddings.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize vectorizer with Gemini API key
        
        Args:
            api_key: Google Gemini API key. If None, reads from GEMINI_API_KEY env var.
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY must be provided or set in environment")
        
        genai.configure(api_key=self.api_key)
        self.model = os.getenv('EMBEDDING_MODEL', 'models/embedding-001')
    
    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding vector for text
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            result = genai.embed_content(
                model=self.model,
                content=text,
                task_type="RETRIEVAL_QUERY"
            )
            
            # Extract embedding
            if hasattr(result, 'embedding'):
                embedding = result.embedding
            elif isinstance(result, dict):
                embedding = result.get('embedding', result)
            else:
                embedding = result
            
            # Ensure list format
            if not isinstance(embedding, list):
                if hasattr(embedding, 'values'):
                    embedding = embedding.values
                elif hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                    embedding = list(embedding)
                else:
                    raise ValueError(f"Unexpected embedding format: {type(embedding)}")
            
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise
    
    async def embed_document(self, text: str) -> List[float]:
        """
        Generate embedding for document (uses RETRIEVAL_DOCUMENT task type)
        
        Args:
            text: Document text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            result = genai.embed_content(
                model=self.model,
                content=text,
                task_type="RETRIEVAL_DOCUMENT"
            )
            
            # Extract embedding
            if hasattr(result, 'embedding'):
                embedding = result.embedding
            elif isinstance(result, dict):
                embedding = result.get('embedding', result)
            else:
                embedding = result
            
            # Ensure list format
            if not isinstance(embedding, list):
                if hasattr(embedding, 'values'):
                    embedding = embedding.values
                elif hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                    embedding = list(embedding)
                else:
                    raise ValueError(f"Unexpected embedding format: {type(embedding)}")
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating document embedding: {e}")
            raise

