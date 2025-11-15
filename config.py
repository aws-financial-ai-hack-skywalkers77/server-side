import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Landing AI ADE Configuration
    # Try both possible environment variable names
    LANDING_AI_API_KEY = os.getenv("LANDING_AI_API_KEY") or os.getenv("VISION_AGENT_API_KEY")
    
    # PostgreSQL Configuration
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    VERTEX_AI = os.getenv("VERTEX_AI")
    
    # Google Gemini Configuration for embeddings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/embedding-001")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))  # Gemini embedding-001 returns 3072 dimensions
    # Gemini model for text generation (RAG)
    # Options: "gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"
    GEMINI_GENERATION_MODEL = os.getenv("GEMINI_GENERATION_MODEL", "gemini-2.5-pro")
    
    # File upload configuration
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp")
    MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB default
    
    # AWS S3 Configuration (optional - for storing uploaded files)
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"

    # AWS S3 Configuration (optional - for storing uploaded files)
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"

    # AWS S3 Configuration (optional - for storing uploaded files)
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"

