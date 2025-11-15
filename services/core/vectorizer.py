# services/core/vectorizer.py

from typing import List, Optional
import logging
import os
import asyncio
import time
from config import Config

logger = logging.getLogger(__name__)

class Vectorizer:
    """
    Vectorization service for tax intelligence platform.
    Supports OpenAI, Google Gemini, and local sentence-transformers models.
    Uses the model specified in EMBEDDING_MODEL environment variable.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize vectorizer with API key or local model
        
        Args:
            api_key: API key (OpenAI or Gemini). If None, reads from env vars.
                    If using local model, this is ignored.
        """
        self.embedding_model = Config.EMBEDDING_MODEL or 'all-MiniLM-L6-v2'
        self.provider = None
        self.api_key = None
        self.local_model = None
        
        # Check if using local sentence-transformers model
        # Local models don't have "models/" prefix or are common sentence-transformers model names
        local_model_names = ['all-minilm', 'all-mpnet', 'sentence-transformers', 'paraphrase', 'multi-qa', 'distilbert', 'roberta', 'bert']
        model_lower = self.embedding_model.lower()
        is_local_model = (
            not model_lower.startswith('models/') and 
            'text-embedding' not in model_lower and
            'embedding-001' not in model_lower and
            (any(name in model_lower for name in local_model_names) or 
             model_lower.startswith('sentence-transformers/') or
             '-' in self.embedding_model and not model_lower.startswith('models/'))
        )
        
        # If no API keys are provided, default to local model
        has_api_keys = any([Config.OPENAI_API_KEY, Config.GEMINI_API_KEY, api_key])
        
        if is_local_model or not has_api_keys:
            # Use local sentence-transformers model (free, no API needed)
            self.provider = 'local'
            try:
                from sentence_transformers import SentenceTransformer
                # Remove 'sentence-transformers/' prefix if present
                model_name = self.embedding_model.replace('sentence-transformers/', '')
                logger.info(f"Loading local embedding model: {model_name} (this may take a moment on first run)...")
                self.local_model = SentenceTransformer(model_name)
                logger.info(f"Local embedding model loaded successfully. Embedding dimension: {self.local_model.get_sentence_embedding_dimension()}")
            except ImportError:
                raise ImportError("sentence-transformers package is required for local embeddings. Install it with: pip install sentence-transformers")
            except Exception as e:
                logger.error(f"Error loading local model {model_name}: {e}")
                logger.info("Falling back to default model: all-MiniLM-L6-v2")
                self.embedding_model = 'all-MiniLM-L6-v2'
                self.local_model = SentenceTransformer('all-MiniLM-L6-v2')
        elif 'text-embedding' in self.embedding_model.lower() or 'ada' in self.embedding_model.lower():
            # OpenAI model
            self.provider = 'openai'
            self.api_key = api_key or Config.OPENAI_API_KEY or os.getenv('OPENAI_API_KEY')
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY must be provided or set in environment for OpenAI embeddings")
            try:
                import openai
                self.openai_client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("openai package is required. Install it with: pip install openai")
        else:
            # Google Gemini model
            self.provider = 'gemini'
            self.api_key = api_key or Config.GEMINI_API_KEY or os.getenv('GEMINI_API_KEY')
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY must be provided or set in environment for Gemini embeddings")
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.genai = genai
            except ImportError:
                raise ImportError("google-generativeai package is required. Install it with: pip install google-generativeai")
        
        self.last_request_time = 0
        self.min_request_interval = 0.1  # Minimum 100ms between requests (10 req/sec max)
        self.max_retries = 3
        self.retry_delay_base = 2  # Base delay for exponential backoff
        
        logger.info(f"Initialized vectorizer with {self.provider} provider, model: {self.embedding_model}")
    
    async def embed(self, text: str) -> List[float]:
        """
        Generate embedding vector for text (for queries)
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        if self.provider == 'local':
            return await self._embed_local(text)
        elif self.provider == 'openai':
            return await self._embed_openai(text)
        else:
            return await self._embed_gemini(text, task_type="RETRIEVAL_QUERY")
    
    async def _embed_local(self, text: str) -> List[float]:
        """Generate embedding using local sentence-transformers model"""
        try:
            if not text or not text.strip():
                raise ValueError("Cannot embed empty text")
            
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                self.local_model.encode,
                text
            )
            
            # Convert numpy array to list
            if hasattr(embedding, 'tolist'):
                embedding = embedding.tolist()
            elif hasattr(embedding, '__iter__') and not isinstance(embedding, str):
                embedding = list(embedding)
            else:
                raise ValueError(f"Unexpected embedding type: {type(embedding)}")
            
            # Validate embedding
            if not embedding:
                raise ValueError("Embedding is empty")
            if len(embedding) == 0:
                raise ValueError("Embedding has zero dimensions")
            
            logger.debug(f"Generated local embedding with {len(embedding)} dimensions")
            return embedding
        except Exception as e:
            logger.error(f"Error generating local embedding: {e}", exc_info=True)
            raise
    
    async def _embed_openai(self, text: str) -> List[float]:
        """Generate embedding using OpenAI"""
        try:
            # Rate limiting
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - time_since_last)
            
            self.last_request_time = time.time()
            
            # Use the model from config (e.g., text-embedding-3-small, text-embedding-3-large)
            # If model name starts with "models/", remove that prefix for OpenAI
            model_name = self.embedding_model.replace('models/', '') if self.embedding_model.startswith('models/') else self.embedding_model
            
            response = self.openai_client.embeddings.create(
                model=model_name,
                input=text
            )
            
            embedding = response.data[0].embedding
            logger.debug(f"Generated OpenAI embedding with {len(embedding)} dimensions")
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating OpenAI embedding: {e}")
            raise
    
    async def _embed_gemini(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
        """Generate embedding using Gemini"""
        try:
            result = self.genai.embed_content(
                model=self.embedding_model,
                content=text,
                task_type=task_type
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
            
            logger.debug(f"Generated Gemini embedding with {len(embedding)} dimensions")
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating Gemini embedding: {e}")
            raise
    
    async def embed_document(self, text: str) -> List[float]:
        """
        Generate embedding for document
        Includes rate limiting and retry logic for quota errors (for API providers).
        
        Args:
            text: Document text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        # Local models don't need retry logic
        if self.provider == 'local':
            return await self._embed_local(text)
        
        # Retry logic with exponential backoff for API providers
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                if self.provider == 'openai':
                    return await self._embed_openai(text)
                else:
                    return await self._embed_gemini(text, task_type="RETRIEVAL_DOCUMENT")
                    
            except Exception as e:
                last_exception = e
                error_str = str(e).lower()
                
                # Check if it's a quota/rate limit error
                if '429' in error_str or 'quota' in error_str or 'rate limit' in error_str or 'rate_limit' in error_str:
                    if attempt < self.max_retries - 1:
                        # Exponential backoff: wait 2^attempt seconds
                        wait_time = self.retry_delay_base ** attempt
                        provider_name = "OpenAI" if self.provider == 'openai' else "Gemini"
                        logger.warning(f"{provider_name} rate limit/quota error (attempt {attempt + 1}/{self.max_retries}). Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # Final attempt failed
                        provider_name = "OpenAI" if self.provider == 'openai' else "Gemini"
                        logger.error(f"{provider_name} quota exceeded after {self.max_retries} attempts.")
                        raise ValueError(
                            f"{provider_name} API quota exceeded. Please:\n"
                            "1. Check your API quota/usage\n"
                            "2. Wait for quota reset or upgrade your plan\n"
                            "3. Consider processing smaller documents or reducing chunk size"
                        ) from e
                else:
                    # Non-quota error, don't retry
                    logger.error(f"Error generating document embedding: {e}")
                    raise
        
        # If we get here, all retries failed
        raise last_exception

