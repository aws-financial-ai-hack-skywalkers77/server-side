import os
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

class Config:
    # Landing AI ADE Configuration
    # Try both possible environment variable names
    LANDING_AI_API_KEY = os.getenv("LANDING_AI_API_KEY") or os.getenv("VISION_AGENT_API_KEY")
    
    # PostgreSQL Configuration
    # Support both DATABASE_URL and individual variables
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL:
        # Parse DATABASE_URL if provided
        parsed = urlparse(DATABASE_URL)
        DB_HOST = parsed.hostname
        DB_PORT = str(parsed.port) if parsed.port else "5432"
        DB_NAME = parsed.path.lstrip('/').split('?')[0]  # Remove query params
        DB_USER = parsed.username
        DB_PASSWORD = parsed.password
    else:
        # Fall back to individual variables
        DB_HOST = os.getenv("DB_HOST")
        DB_PORT = os.getenv("DB_PORT", "5432")
        DB_NAME = os.getenv("DB_NAME")
        DB_USER = os.getenv("DB_USER")
        DB_PASSWORD = os.getenv("DB_PASSWORD")
    VERTEX_AI = os.getenv("VERTEX_AI")
    
    # Google Gemini Configuration for embeddings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    # Embedding model configuration (supports OpenAI, Gemini, or local sentence-transformers)
    # For local models, use names like: "all-MiniLM-L6-v2", "all-mpnet-base-v2", "paraphrase-MiniLM-L6-v2"
    # For OpenAI: "text-embedding-3-small", "text-embedding-3-large"
    # For Gemini: "models/embedding-001"
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")  # Default to free local model
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "384"))  # Default for all-MiniLM-L6-v2
    # OpenAI Configuration for embeddings (alternative to Gemini)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    # Gemini model for text generation (RAG)
    # Options: "gemini-2.5-flash" (stable, recommended), "gemini-2.0-flash-001", "gemini-flash-latest"
    # Note: Use models that are actually available in your API key
    GEMINI_GENERATION_MODEL = os.getenv("GEMINI_GENERATION_MODEL", "gemini-2.5-flash")
    
    # File upload configuration
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp")
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB default
    
    # AWS S3 Configuration
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "landing-ai-aws-hack")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

