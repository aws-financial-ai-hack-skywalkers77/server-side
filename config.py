import os
import warnings
from dotenv import load_dotenv

load_dotenv()


def _resolve_embedding_model(raw: str | None) -> str:
    """
    Gemini embedContent model ids. Legacy models/embedding-001 was removed from
    the API (404 as of early 2026). Use models/gemini-embedding-001 (or
    models/gemini-embedding-2-preview for multimodal). text-embedding-* ids
    are not valid on the Gemini Developer API.
    """
    default = "models/gemini-embedding-001"
    if not raw or not raw.strip():
        return default
    m = raw.strip()
    if not m.startswith("models/"):
        m = f"models/{m.lstrip('/')}"
    lower = m.lower()
    if "text-embedding" in lower and "gemini-embedding" not in lower:
        warnings.warn(
            f"EMBEDDING_MODEL {raw!r} is not a supported Gemini embedding model; "
            f"using {default} instead. See https://ai.google.dev/gemini-api/docs/embeddings",
            UserWarning,
            stacklevel=2,
        )
        return default
    if lower == "models/embedding-001":
        warnings.warn(
            f"EMBEDDING_MODEL {raw!r} is no longer available on the Gemini API; "
            f"using {default} instead.",
            UserWarning,
            stacklevel=2,
        )
        return default
    return m


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
    EMBEDDING_MODEL = _resolve_embedding_model(os.getenv("EMBEDDING_MODEL"))
    # Must match pgvector column width; gemini-embedding-001 supports Matryoshka sizes (e.g. 768, 1536, 3072).
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
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
    S3_ENABLED = os.getenv("S3_ENABLED", "true").lower() == "true"

