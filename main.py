from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import logging
import json
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config
from database import Database
from compliance_engine import ComplianceEngine
from document_processor import DocumentProcessor
from vectorizer import Vectorizer

# Tax Intelligence Platform imports
from services.core.vectorizer import Vectorizer as TaxVectorizer
from services.core.document_parser import TaxDocumentParser
from services.core.law_ingestion import LawIngestionService
from services.workflow1.completeness_checker import FormCompletenessChecker
from services.workflow2.comparison_engine import JurisdictionComparisonEngine
from services.workflow3.planning_engine import MultiJurisdictionPlanningEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize S3 client if S3 is enabled
s3_client = None
if Config.S3_ENABLED:
    try:
        import boto3
        from botocore.exceptions import ClientError
        if Config.AWS_ACCESS_KEY_ID and Config.AWS_SECRET_ACCESS_KEY:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
                region_name=Config.AWS_REGION
            )
        else:
            s3_client = boto3.client('s3', region_name=Config.AWS_REGION)
        logger.info("S3 client initialized")
    except ImportError:
        logger.warning("boto3 not installed. S3 functionality will be disabled.")
        s3_client = None
    except Exception as e:
        logger.warning(f"Failed to initialize S3 client: {e}. S3 functionality will be disabled.")
        s3_client = None

origins = [
    "*"
]

DEFAULT_BULK_LIMIT = 200


def upload_file_content_to_s3(file_content: bytes, s3_key: str, content_type: str = "application/pdf") -> str:
    """
    Upload file content directly to S3 bucket from memory.
    
    Args:
        file_content: File content as bytes
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of the file (default: application/pdf)
    
    Returns:
        Presigned S3 URL of the uploaded file (valid for 1 hour)
    
    Raises:
        Exception: If upload fails
    """
    if not s3_client:
        raise Exception("S3 client not initialized. Set S3_ENABLED=true and configure AWS credentials.")
    if not Config.S3_BUCKET_NAME:
        raise Exception("S3_BUCKET_NAME not configured")
    
    try:
        logger.info(f"Uploading file to S3: {s3_key}")
        s3_client.put_object(
            Bucket=Config.S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_content,
            ContentType=content_type
        )
        
        # Generate presigned URL (valid for 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=3600  # 1 hour
        )
        
        s3_uri = f"s3://{Config.S3_BUCKET_NAME}/{s3_key}"
        logger.info(f"Successfully uploaded file to S3: {s3_uri}")
        logger.info(f"Presigned URL generated (valid for 1 hour)")
        return presigned_url
    except ClientError as e:
        logger.error(f"Error uploading file to S3: {e}")
        raise Exception(f"Failed to upload file to S3: {str(e)}")


def get_presigned_url_for_s3_key(s3_key: str, expires_in: int = 10800) -> str:
    """
    Generate a presigned URL for an existing S3 object.
    
    Args:
        s3_key: S3 object key (path in bucket)
        expires_in: Expiration time in seconds (default: 10800 = 3 hours)
    
    Returns:
        Presigned S3 URL
    
    Raises:
        Exception: If URL generation fails
    """
    if not s3_client:
        raise Exception("S3 client not initialized. Set S3_ENABLED=true and configure AWS credentials.")
    if not Config.S3_BUCKET_NAME:
        raise Exception("S3_BUCKET_NAME not configured")
    
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=expires_in
        )
        logger.info(f"Generated presigned URL for S3 key: {s3_key} (valid for {expires_in} seconds)")
        return presigned_url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        raise Exception(f"Failed to generate presigned URL: {str(e)}")


app = FastAPI(title="Document Processing API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class ContractQueryRequest(BaseModel):
    query: str = Field(..., description="The search query text", min_length=1)
    id: Optional[int] = Field(default=None, description="Optional database ID to filter search to a specific contract")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum number of results to return")
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum similarity score (0.0 to 1.0)")

class BulkComplianceRequest(BaseModel):
    limit: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of invoices to process during this bulk run",
    )

class InvoiceListRequest(BaseModel):
    invoice_ids: List[int] = Field(
        ...,
        description="List of invoice database IDs to analyze",
        min_length=1,
    )

# ============================================================================
# Tax Intelligence Platform - Request Models
# ============================================================================

class ComparisonRequest(BaseModel):
    base_jurisdiction: str
    target_jurisdiction: str
    scope: str = "individual_income"
    tax_year: Optional[int] = None
    requested_by: Optional[str] = None

class ResearchRequest(BaseModel):
    base_jurisdiction: str
    target_jurisdiction: str
    topic: str
    tax_year: Optional[int] = None

class IncomeSource(BaseModel):
    type: str
    jurisdiction: str
    amount_range: str
    description: str

class PlanningScenarioRequest(BaseModel):
    client_id: str
    client_name: str
    scenario_name: str
    jurisdictions_involved: List[str]
    income_sources: List[IncomeSource]
    objectives: List[str]
    tax_year: Optional[int] = None

# Initialize components
db = Database()
document_processor = DocumentProcessor()
vectorizer = Vectorizer()
compliance_engine = ComplianceEngine(db=db, vectorizer=vectorizer)

# ============================================================================
# Tax Intelligence Platform - Lazy Initialization
# ============================================================================
_tax_vectorizer = None
_tax_document_parser = None
_tax_db_conn = None
_tax_law_service = None
_tax_workflow1 = None
_tax_workflow2 = None
_tax_workflow3 = None

def get_tax_db_connection():
    """Create database connection for tax platform (uses same DB as main app)"""
    try:
        # Determine SSL mode based on database host
        ssl_mode = 'prefer'  # Default: try SSL, fallback to non-SSL
        if Config.DB_HOST:
            # NeonDB and cloud databases typically require SSL
            if any(keyword in Config.DB_HOST.lower() for keyword in ['neon', 'aws', 'rds', 'cloud']):
                ssl_mode = 'require'
        
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            sslmode=ssl_mode,
            cursor_factory=RealDictCursor,
            connect_timeout=10
        )
        # Ensure autocommit is False for transaction control
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
        return conn
    except Exception as e:
        logger.error(f"Error connecting to database for tax platform: {e}")
        raise

def get_tax_vectorizer():
    """Get or create tax vectorizer instance"""
    global _tax_vectorizer
    if _tax_vectorizer is None:
        # Vectorizer will auto-detect provider based on EMBEDDING_MODEL from config
        _tax_vectorizer = TaxVectorizer()
    return _tax_vectorizer

def get_tax_document_parser():
    """Get or create tax document parser instance"""
    global _tax_document_parser
    if _tax_document_parser is None:
        _tax_document_parser = TaxDocumentParser(api_key=Config.LANDING_AI_API_KEY)
    return _tax_document_parser

def get_tax_db_conn():
    """Get or create tax database connection"""
    global _tax_db_conn
    if _tax_db_conn is None or _tax_db_conn.closed:
        _tax_db_conn = get_tax_db_connection()
    return _tax_db_conn

def get_tax_law_service():
    """Get or create law ingestion service"""
    global _tax_law_service
    if _tax_law_service is None:
        _tax_law_service = LawIngestionService(get_tax_db_conn(), get_tax_vectorizer())
    return _tax_law_service

def get_tax_workflow1():
    """Get or create workflow 1 instance"""
    global _tax_workflow1
    if _tax_workflow1 is None:
        _tax_workflow1 = FormCompletenessChecker(
            get_tax_db_conn(), 
            get_tax_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _tax_workflow1

def get_tax_workflow2():
    """Get or create workflow 2 instance"""
    global _tax_workflow2, _tax_db_conn
    # Recreate if connection is closed
    if _tax_workflow2 is None or (_tax_db_conn and _tax_db_conn.closed):
        _tax_db_conn = None  # Force reconnection
        _tax_workflow2 = JurisdictionComparisonEngine(
            get_tax_db_conn(), 
            get_tax_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _tax_workflow2

def get_tax_workflow3():
    """Get or create workflow 3 instance"""
    global _tax_workflow3, _tax_db_conn
    # Recreate if connection is closed
    if _tax_workflow3 is None or (_tax_db_conn and _tax_db_conn.closed):
        _tax_db_conn = None  # Force reconnection
        _tax_workflow3 = MultiJurisdictionPlanningEngine(
            get_tax_db_conn(), 
            get_tax_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _tax_workflow3

def upload_file_content_to_s3(file_content: bytes, s3_key: str, content_type: str = "application/pdf") -> str:
    """
    Upload file content directly to S3 bucket from memory.
    
    Args:
        file_content: File content as bytes
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of the file (default: application/pdf)
    
    Returns:
        Presigned S3 URL of the uploaded file (valid for 1 hour)
    
    Raises:
        Exception: If upload fails
    """
    try:
        logger.info(f"Uploading file to S3: {s3_key}")
        s3_client.put_object(
            Bucket=Config.S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_content,
            ContentType=content_type
        )
        
        # Generate presigned URL (valid for 1 hour)
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=3600  # 1 hour
        )
        
        s3_uri = f"s3://{Config.S3_BUCKET_NAME}/{s3_key}"
        logger.info(f"Successfully uploaded file to S3: {s3_uri}")
        logger.info(f"Presigned URL generated (valid for 1 hour)")
        return presigned_url
    except ClientError as e:
        logger.error(f"Error uploading file to S3: {e}")
        raise Exception(f"Failed to upload file to S3: {str(e)}")

def get_presigned_url_for_s3_key(s3_key: str, expires_in: int = 10800) -> str:
    """
    Generate a presigned URL for an existing S3 object.
    
    Args:
        s3_key: S3 object key (path in bucket)
        expires_in: Expiration time in seconds (default: 10800 = 3 hours)
    
    Returns:
        Presigned S3 URL
    
    Raises:
        Exception: If URL generation fails
    """
    try:
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': Config.S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=expires_in
        )
        logger.info(f"Generated presigned URL for S3 key: {s3_key} (valid for {expires_in} seconds)")
        return presigned_url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}")
        raise Exception(f"Failed to generate presigned URL: {str(e)}")

# Create tables on startup
@app.on_event("startup")
async def startup_event():
    try:
        db.create_tables()
        logger.info("Application started successfully")
    except Exception as e:
        logger.warning(f"Database connection failed during startup: {e}")
        logger.warning("Server will start, but database operations will fail until connection is established.")
        logger.warning("Please check your database configuration and network connectivity.")
        # Don't raise - allow server to start even if DB is unavailable

@app.on_event("shutdown")
async def shutdown_event():
    db.close()
    logger.info("Application shutdown")

@app.get("/")
async def root():
    return {"message": "Document Processing API", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/invoices")
async def get_invoices(
    limit: int = Query(default=100, ge=1, le=1000, description="Number of invoices to return"),
    offset: int = Query(default=0, ge=0, description="Number of invoices to skip")
):
    """
    Get all invoices with pagination.
    
    Args:
        limit: Maximum number of invoices to return (1-1000, default: 100)
        offset: Number of invoices to skip (default: 0)
    
    Returns:
        JSON response with list of invoices and pagination info
    """
    try:
        invoices = db.get_all_invoices(limit=limit, offset=offset)
        total_count = db.get_invoices_count()
        
        # Format response
        formatted_invoices = []
        for invoice in invoices:
            formatted_invoices.append({
                'id': invoice.get('id'),
                'invoice_id': invoice.get('invoice_id'),
                'seller_name': invoice.get('seller_name'),
                'seller_address': invoice.get('seller_address'),
                'tax_id': invoice.get('tax_id'),
                'subtotal_amount': float(invoice.get('subtotal_amount', 0)) if invoice.get('subtotal_amount') else 0.0,
                'tax_amount': float(invoice.get('tax_amount', 0)) if invoice.get('tax_amount') else 0.0,
                'summary': invoice.get('summary'),
                's3_key': invoice.get('s3_key'),
                'created_at': invoice.get('created_at').isoformat() if invoice.get('created_at') else None,
                'updated_at': invoice.get('updated_at').isoformat() if invoice.get('updated_at') else None
            })
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "count": len(formatted_invoices),
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "invoices": formatted_invoices
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving invoices: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving invoices: {str(e)}"
        )

@app.get("/invoices/{db_id}")
async def get_invoice_by_db_id(db_id: int):
    try:
        invoice = db.get_invoice_by_db_id(db_id)
        
        if not invoice:
            raise HTTPException(
                status_code=404,
                    detail=f"Invoice with database ID '{db_id}' not found"
            )
        
        # Format response
        response_metadata = {
            'db_id': invoice.get('id'),
            'invoice_id': invoice.get('invoice_id'),
            'seller_name': invoice.get('seller_name'),
            'seller_address': invoice.get('seller_address'),
            'tax_id': invoice.get('tax_id'),
            'subtotal_amount': float(invoice.get('subtotal_amount', 0)) if invoice.get('subtotal_amount') else 0.0,
            'tax_amount': float(invoice.get('tax_amount', 0)) if invoice.get('tax_amount') else 0.0,
            'summary': invoice.get('summary'),
            's3_key': invoice.get('s3_key'),
            'created_at': invoice.get('created_at').isoformat() if invoice.get('created_at') else None,
            'updated_at': invoice.get('updated_at').isoformat() if invoice.get('updated_at') else None
        }
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "metadata": response_metadata
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving invoice: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving invoice: {str(e)}"
        )

@app.get("/contracts")
async def get_contracts(
    limit: int = Query(default=100, ge=1, le=1000, description="Number of contracts to return"),
    offset: int = Query(default=0, ge=0, description="Number of contracts to skip")
):
    """
    Get all contracts with pagination.
    
    Args:
        limit: Maximum number of contracts to return (1-1000, default: 100)
        offset: Number of contracts to skip (default: 0)
    
    Returns:
        JSON response with list of contracts and pagination info
    """
    try:
        contracts = db.get_all_contracts(limit=limit, offset=offset)
        total_count = db.get_contracts_count()
        
        # Format response
        formatted_contracts = []
        for contract in contracts:
            formatted_contracts.append({
                'id': contract.get('id'),
                'contract_id': contract.get('contract_id'),
                'summary': contract.get('summary'),
                'text': contract.get('text'),
                's3_key': contract.get('s3_key'),
                'created_at': contract.get('created_at').isoformat() if contract.get('created_at') else None,
                'updated_at': contract.get('updated_at').isoformat() if contract.get('updated_at') else None
            })
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "count": len(formatted_contracts),
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "contracts": formatted_contracts
            }
        )
    except Exception as e:
        logger.error(f"Error retrieving contracts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving contracts: {str(e)}"
        )

@app.get("/contracts/{db_id}")
async def get_contract_by_db_id(db_id: int):
    """
    Get contract metadata by database ID.
    
    Args:
        db_id: The database ID to retrieve
    
    Returns:
        JSON response with contract metadata
    """
    try:
        contract = db.get_contract_by_db_id(db_id)
        
        if not contract:
            raise HTTPException(
                status_code=404,
                detail=f"Contract with database ID '{db_id}' not found"
            )
        
        # Format response
        response_metadata = {
            'db_id': contract.get('id'),
            'contract_id': contract.get('contract_id'),
            'summary': contract.get('summary'),
            'text': contract.get('text'),
            's3_key': contract.get('s3_key'),
            'created_at': contract.get('created_at').isoformat() if contract.get('created_at') else None,
            'updated_at': contract.get('updated_at').isoformat() if contract.get('updated_at') else None
        }
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "metadata": response_metadata
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving contract: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving contract: {str(e)}"
        )

@app.post("/upload_document")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...)
):
    """
    Upload and process a document (invoice or contract).
    
    Args:
        file: The PDF file to process
        document_type: Type of document ('invoice' or 'contract')
    
    Returns:
        JSON response with extracted metadata
    """
    # Validate document type
    doc_type = document_type.lower()
    if doc_type not in ['invoice', 'contract']:
        raise HTTPException(
            status_code=400,
            detail=f"Document type '{document_type}' not supported. Supported types: 'invoice', 'contract'"
        )
    
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported"
        )
    
    # Save uploaded file temporarily
    upload_dir = Path(Config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / file.filename
    
    try:
        # Save file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            if len(content) > Config.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"File size exceeds maximum allowed size of {Config.MAX_FILE_SIZE} bytes"
                )
            buffer.write(content)
        
        logger.info(f"Processing document: {file.filename} (type: {document_type})")
        
        # Upload to S3 if enabled (optional)
        s3_key = None
        s3_url = None
        if Config.S3_ENABLED and s3_client:
            try:
                # Create S3 key with document type prefix and timestamp
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                s3_key = f"{doc_type}s/{timestamp}_{file.filename}"
                s3_url = upload_file_content_to_s3(content, s3_key)
                logger.info(f"File uploaded to S3: {s3_url}")
            except Exception as e:
                logger.warning(f"Failed to upload to S3: {e}. Continuing with local file storage.")
                s3_key = None
                s3_url = None
        
        # Extract data using Landing AI ADE based on document type
        if doc_type == 'invoice':
            metadata = document_processor.extract_invoice_data(str(file_path))
        elif doc_type == 'contract':
            metadata = document_processor.extract_contract_data(str(file_path))
        
        # Vectorize the metadata
        vector = vectorizer.vectorize_metadata(metadata)
        
        # Store in database based on document type
        if doc_type == 'invoice':
            stored_record = db.insert_invoice(metadata, vector, s3_key=s3_key)
            invoice_db_id = stored_record.get('id')
            
            # Store line items if they were extracted
            line_items = metadata.get('line_items', [])
            if line_items and invoice_db_id:
                try:
                    db.insert_invoice_line_items(invoice_db_id, line_items)
                    logger.info(f"Stored {len(line_items)} line items for invoice: {metadata.get('invoice_id')}")
                except Exception as e:
                    logger.warning(f"Failed to store line items for invoice {metadata.get('invoice_id')}: {e}")
                    # Don't fail the entire upload if line items fail
            
            logger.info(f"Successfully processed and stored invoice: {metadata.get('invoice_id')}")
            
            # Return invoice metadata
            response_metadata = {
                'invoice_id': stored_record.get('invoice_id'),
                'seller_name': stored_record.get('seller_name'),
                'seller_address': stored_record.get('seller_address'),
                'tax_id': stored_record.get('tax_id'),
                'subtotal_amount': float(stored_record.get('subtotal_amount', 0)) if stored_record.get('subtotal_amount') else 0.0,
                'tax_amount': float(stored_record.get('tax_amount', 0)) if stored_record.get('tax_amount') else 0.0,
                'summary': stored_record.get('summary'),
                'line_items_count': len(line_items),
                's3_key': stored_record.get('s3_key'),
                's3_url': s3_url if s3_url else None,
                'created_at': stored_record.get('created_at').isoformat() if stored_record.get('created_at') else None
            }
        elif doc_type == 'contract':
            stored_record = db.insert_contract(metadata, vector, s3_key=s3_key)
            logger.info(f"Successfully processed and stored contract: {metadata.get('contract_id')}")
            
            # Return contract metadata
            response_metadata = {
                'contract_id': stored_record.get('contract_id'),
                'summary': stored_record.get('summary'),
                'text': stored_record.get('text'),
                's3_key': stored_record.get('s3_key'),
                's3_url': s3_url if s3_url else None,
                'created_at': stored_record.get('created_at').isoformat() if stored_record.get('created_at') else None
            }
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Document processed successfully",
                "metadata": response_metadata
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing document: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing document: {str(e)}"
        )
    finally:
        # Clean up temporary file
        if file_path.exists():
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"Error removing temporary file: {e}")

@app.get("/documents/{document_type}/{db_id}/download_url")
async def get_document_download_url(
    document_type: str,
    db_id: int
):
    """
    Get a presigned S3 URL for downloading a document.
    
    Args:
        document_type: Type of document ('invoice' or 'contract')
        db_id: Database ID of the document
    
    Returns:
        JSON response with presigned URL (valid for 3 hours)
    """
    # Validate document type
    doc_type = document_type.lower()
    if doc_type not in ['invoice', 'contract']:
        raise HTTPException(
            status_code=400,
            detail=f"Document type '{document_type}' not supported. Supported types: 'invoice', 'contract'"
        )
    
    try:
        # Get S3 key from database
        if doc_type == 'invoice':
            s3_key = db.get_invoice_s3_key(db_id)
            if not s3_key:
                # Check if invoice exists
                invoice = db.get_invoice_by_db_id(db_id)
                if not invoice:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Invoice with database ID '{db_id}' not found"
                    )
                raise HTTPException(
                    status_code=404,
                    detail=f"Invoice with database ID '{db_id}' has no S3 key stored"
                )
        else:  # contract
            s3_key = db.get_contract_s3_key(db_id)
            if not s3_key:
                # Check if contract exists
                contract = db.get_contract_by_db_id(db_id)
                if not contract:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Contract with database ID '{db_id}' not found"
                    )
                raise HTTPException(
                    status_code=404,
                    detail=f"Contract with database ID '{db_id}' has no S3 key stored"
                )
        
        # Generate presigned URL
        presigned_url = get_presigned_url_for_s3_key(s3_key, expires_in=10800)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "document_type": doc_type,
                "db_id": db_id,
                "s3_key": s3_key,
                "presigned_url": presigned_url,
                "expires_in_seconds": 10800
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating download URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error generating download URL: {str(e)}"
        )

@app.post("/analyze_invoice/{invoice_db_id}")
async def analyze_invoice(invoice_db_id: int):
    """
    Trigger contract compliance analysis for a single invoice.
    """
    try:
        report = compliance_engine.analyze_invoice(invoice_db_id)
        return JSONResponse(
            status_code=200,
            content=report
        )
    except ValueError as ve:
        message = str(ve)
        status_code = 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status_code, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing invoice with database ID '{invoice_db_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing invoice with database ID '{invoice_db_id}': {str(e)}"
        )

@app.post("/analyze_invoices")
async def analyze_invoices(request: InvoiceListRequest = Body(...)):
    """
    Trigger compliance analysis for a list of invoice database IDs.
    """
    try:
        summary = compliance_engine.analyze_invoices_explicit(request.invoice_ids)
        return JSONResponse(
            status_code=200,
            content=summary
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing invoices '{request.invoice_ids}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error analyzing invoices: {str(e)}"
        )

@app.post("/analyze_invoices_bulk")
async def analyze_invoices_bulk(request: BulkComplianceRequest = Body(default=None)):
    """
    Run compliance analysis across outstanding invoices (scheduled/bulk mode).
    """
    try:
        limit = request.limit if request else DEFAULT_BULK_LIMIT
        summary = compliance_engine.analyze_invoices_bulk(limit=limit)
        return JSONResponse(
            status_code=200,
            content=summary
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running bulk invoice analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error running bulk invoice analysis: {str(e)}"
        )

@app.post("/query_contracts")
async def query_contracts(request: ContractQueryRequest = Body(...)):
    """
    Query contracts using RAG (Retrieval-Augmented Generation).
    This endpoint:
    1. Searches contracts using semantic vector similarity (only contracts, not invoices)
    2. Uses an LLM to generate an answer based on the retrieved contracts
    3. Returns both the generated answer and the source contracts
    
    Args:
        request: ContractQueryRequest containing:
            - query: The search query text/question
            - id: Optional database ID to filter search to a specific contract
            - limit: Maximum number of results (1-100, default: 10)
            - similarity_threshold: Minimum similarity score (0.0-1.0, default: 0.0)
    
    Returns:
        JSON response with:
            - success: Boolean indicating success
            - answer: LLM-generated answer based on retrieved contracts
    """
    try:
        # Validate query is not empty
        if not request.query or not request.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query text cannot be empty"
            )
        
        db_id = request.id
        log_msg = f"Processing contract query: '{request.query}'"
        if db_id:
            log_msg += f" (db_id: {db_id})"
        log_msg += f" (limit: {request.limit}, threshold: {request.similarity_threshold})"
        logger.info(log_msg)
        
        # Vectorize the query text
        query_vector = vectorizer.vectorize_query(request.query.strip())
        
        # Search contracts by similarity
        results = db.search_contracts_by_similarity(
            query_vector=query_vector,
            limit=request.limit,
            similarity_threshold=request.similarity_threshold,
            contract_id=db_id
        )
        
        # Check if we have any results
        if not results:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "answer": "No relevant contracts found matching your query."
                }
            )
        
        # Collect context texts for LLM
        context_texts = []
        contract_ids = []
        
        for contract in results:
            contract_text = contract.get('text') or contract.get('summary') or ''
            contract_id = contract.get('contract_id')
            
            # Collect context for LLM (use text if available, otherwise summary)
            if contract_text:
                context_texts.append(contract_text)
                contract_ids.append(contract_id)
        
        # Generate answer using LLM (RAG)
        try:
            answer = vectorizer.generate_answer(
                query=request.query.strip(),
                context_texts=context_texts,
                contract_ids=contract_ids if contract_ids else None
            )
        except Exception as e:
            logger.error(f"Error generating LLM answer: {e}", exc_info=True)
            # Return a more helpful error message that includes the actual error
            answer = f"Unable to generate answer: {str(e)}"
        
        # Return only success and answer
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "answer": answer
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error querying contracts: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error querying contracts: {str(e)}"
        )

@app.get("/documents/{document_type}/{db_id}/download_url")
async def get_document_download_url(
    document_type: str,
    db_id: int
):
    """
    Get a presigned S3 URL for downloading a document.
    
    Args:
        document_type: Type of document ('invoice' or 'contract')
        db_id: Database ID of the document
    
    Returns:
        JSON response with presigned URL (valid for 3 hours)
    """
    # Validate document type
    doc_type = document_type.lower()
    if doc_type not in ['invoice', 'contract']:
        raise HTTPException(
            status_code=400,
            detail=f"Document type '{document_type}' not supported. Supported types: 'invoice', 'contract'"
        )
    
    try:
        # Get S3 key from database
        if doc_type == 'invoice':
            s3_key = db.get_invoice_s3_key(db_id)
            if not s3_key:
                # Check if invoice exists
                invoice = db.get_invoice_by_db_id(db_id)
                if not invoice:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Invoice with database ID '{db_id}' not found"
                    )
                raise HTTPException(
                    status_code=404,
                    detail=f"S3 key not found for invoice with database ID '{db_id}'"
                )
        else:  # contract
            s3_key = db.get_contract_s3_key(db_id)
            if not s3_key:
                # Check if contract exists
                contract = db.get_contract_by_db_id(db_id)
                if not contract:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Contract with database ID '{db_id}' not found"
                    )
                raise HTTPException(
                    status_code=404,
                    detail=f"S3 key not found for contract with database ID '{db_id}'"
                )
        
        # Generate presigned URL (valid for 3 hours = 10800 seconds)
        presigned_url = get_presigned_url_for_s3_key(s3_key, expires_in=10800)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "document_type": doc_type,
                "db_id": db_id,
                "s3_key": s3_key,
                "presigned_url": presigned_url,
                "expires_in_seconds": 10800,
                "expires_in_hours": 3
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating download URL for {doc_type} {db_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error generating download URL: {str(e)}"
        )

# ============================================================================
# TAX INTELLIGENCE PLATFORM ENDPOINTS
# ============================================================================

# Admin Endpoints
@app.post("/api/admin/ingest-law")
async def ingest_law_document(
    file: UploadFile = File(...),
    jurisdiction: str = Form(...),
    law_category: str = Form(...),
    document_title: Optional[str] = Form(None),
    document_source: Optional[str] = Form(None)
):
    """Admin endpoint to ingest a law document (PDF) into the knowledge base"""
    global _tax_db_conn, _tax_law_service
    
    try:
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        # Ensure we have a fresh database connection for this long-running operation
        # Reset the connection to avoid "connection already closed" errors
        if _tax_db_conn and _tax_db_conn.closed:
            _tax_db_conn = None
            _tax_law_service = None
        
        law_service = get_tax_law_service()
        result = await law_service.ingest_from_pdf(
            pdf_path=temp_path,
            jurisdiction=jurisdiction,
            law_category=law_category,
            document_title=document_title or file.filename,
            document_source=document_source
        )
        
        os.remove(temp_path)
        return {"success": True, "message": "Law document ingested successfully", "details": result}
    except Exception as e:
        logger.error(f"Error ingesting law document: {e}", exc_info=True)
        # Reset service on error to force reconnection
        _tax_law_service = None
        if _tax_db_conn and _tax_db_conn.closed:
            _tax_db_conn = None
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/laws")
async def list_laws(
    jurisdiction: Optional[str] = None,
    law_category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500)
):
    """List ingested law documents"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        query = "SELECT DISTINCT jurisdiction, law_category, document_title, COUNT(*) as chunk_count FROM tax_laws"
        conditions = []
        params = []
        
        if jurisdiction:
            conditions.append("jurisdiction = %s")
            params.append(jurisdiction)
        if law_category:
            conditions.append("law_category = %s")
            params.append(law_category)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " GROUP BY jurisdiction, law_category, document_title LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()
        
        return {"count": len(results), "laws": [dict(row) for row in results]}
    except Exception as e:
        logger.error(f"Error listing laws: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/form-template")
async def create_form_template(
    jurisdiction: str = Form(...),
    form_code: str = Form(...),
    form_name: str = Form(...),
    tax_year: int = Form(...),
    taxpayer_type: str = Form("individual"),
    description: Optional[str] = Form(None),
    required_fields: Optional[str] = Form("[]"),  # JSON string
    calculation_rules: Optional[str] = Form("[]"),  # JSON string
    dependencies: Optional[str] = Form("[]")  # JSON string
):
    """Admin endpoint to create a form template"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        # Parse JSON strings
        import json
        try:
            required_fields_json = json.loads(required_fields) if required_fields else []
            calculation_rules_json = json.loads(calculation_rules) if calculation_rules else []
            dependencies_json = json.loads(dependencies) if dependencies else []
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in form data: {str(e)}")
        
        cursor.execute("""
            INSERT INTO form_templates (
                jurisdiction, form_code, form_name, tax_year,
                taxpayer_type, description,
                required_fields, calculation_rules, dependencies
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            jurisdiction, form_code, form_name, tax_year,
            taxpayer_type, description,
            psycopg2.extras.Json(required_fields_json),
            psycopg2.extras.Json(calculation_rules_json),
            psycopg2.extras.Json(dependencies_json)
        ))
        
        template_id = cursor.fetchone()[0]
        db_conn.commit()
        cursor.close()
        
        return {
            "success": True,
            "message": "Form template created successfully",
            "template_id": template_id,
            "jurisdiction": jurisdiction,
            "form_code": form_code,
            "tax_year": tax_year
        }
    except Exception as e:
        logger.error(f"Error creating form template: {e}", exc_info=True)
        if db_conn:
            db_conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/form-template/update-calculations")
async def update_form_template_calculations(
    jurisdiction: str = Form(...),
    form_code: str = Form(...),
    tax_year: int = Form(...),
    calculation_rules: str = Form("[]")  # JSON string
):
    """Admin endpoint to update calculation rules for an existing form template"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        # Parse calculation rules JSON
        try:
            calculation_rules_json = json.loads(calculation_rules) if calculation_rules else []
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in calculation_rules: {str(e)}")
        
        # Update the template
        cursor.execute("""
            UPDATE form_templates
            SET calculation_rules = %s
            WHERE jurisdiction = %s AND form_code = %s AND tax_year = %s
            RETURNING id
        """, (
            psycopg2.extras.Json(calculation_rules_json),
            jurisdiction,
            form_code,
            tax_year
        ))
        
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Form template not found")
        
        # Handle both tuple and dict-like results
        if isinstance(result, dict):
            template_id = result.get('id') or result.get(0)
        else:
            template_id = result[0] if len(result) > 0 else None
        
        if not template_id:
            raise HTTPException(status_code=404, detail="Form template not found or update failed")
        db_conn.commit()
        cursor.close()
        
        return {
            "success": True,
            "template_id": template_id,
            "message": "Calculation rules updated successfully",
            "calculation_rules": calculation_rules_json
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error updating form template: {e}\n{error_details}")
        if db_conn:
            db_conn.rollback()
        # Provide more detailed error message
        error_msg = str(e) if str(e) and str(e) != "0" else f"Database error: {type(e).__name__}"
        raise HTTPException(status_code=500, detail=f"Error updating form template: {error_msg}")

# Workflow 1: Form Completeness Checker
@app.post("/api/v1/workflow1/upload")
async def upload_tax_document(
    file: UploadFile = File(...),
    jurisdiction: str = Form(...),
    form_code: str = Form(...),
    tax_year: int = Form(...),
    client_name: Optional[str] = Form(None),
    client_type: str = Form("individual")
):
    """Upload a tax document (PDF) for completeness checking"""
    try:
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        document_parser = get_tax_document_parser()
        
        # Try to extract data, but handle Landing AI errors gracefully
        # Landing AI may have schema validation issues or account balance issues
        extracted_data = None
        try:
            extracted_data = await document_parser.process_tax_document(temp_path, form_code=form_code)
        except HTTPException as http_error:
            # Landing AI client may raise HTTPException directly
            error_str = str(http_error.detail) if hasattr(http_error, 'detail') else str(http_error)
            logger.warning(f"Landing AI HTTP error: {error_str}")
            # Create fallback structure for any Landing AI HTTP errors
            extracted_data = {
                'form_type': form_code,
                'tax_year': tax_year,
                'taxpayer_name': client_name or '',
                'taxpayer_ssn': '',
                'filing_status': '',
                'form_data': {},
                'line_items': [],
                'calculations': {},
                'schedules': [],
                'extraction_note': f'Landing AI service error: {error_str[:150]}. Using basic structure from provided metadata.'
            }
        except Exception as parse_error:
            error_str = str(parse_error)
            logger.warning(f"Document parsing error: {error_str}")
            # Check for various Landing AI errors and create fallback structure
            landing_ai_errors = [
                'form_data', 'schema validation', 'properties must be defined', 
                'field extraction invalid', 'payment', 'balance', 'insufficient',
                'error code: 400', 'error code: 402'
            ]
            if any(keyword in error_str.lower() for keyword in landing_ai_errors):
                logger.info("Landing AI error detected. Creating basic document structure from provided metadata.")
                # Create basic extracted data from form metadata provided in the request
                extracted_data = {
                    'form_type': form_code,
                    'tax_year': tax_year,
                    'taxpayer_name': client_name or '',
                    'taxpayer_ssn': '',
                    'filing_status': '',
                    'form_data': {},
                    'line_items': [],
                    'calculations': {},
                    'schedules': [],
                    'extraction_note': f'Landing AI error encountered: {error_str[:100]}. Using basic structure from provided metadata.'
                }
            else:
                # Re-raise if it's a different error (file not found, etc.)
                logger.error(f"Unexpected parsing error: {parse_error}", exc_info=True)
                raise
        
        # Ensure we have extracted_data
        if not extracted_data:
            logger.warning("No extracted data returned, creating minimal structure")
            extracted_data = {
                'form_type': form_code,
                'tax_year': tax_year,
                'taxpayer_name': client_name or '',
                'taxpayer_ssn': '',
                'filing_status': '',
                'form_data': {},
                'line_items': [],
                'calculations': {},
                'schedules': []
            }
        
        import uuid
        document_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
        
        # Get a fresh database connection after the long parsing operation
        # The connection may have timed out during document parsing
        db_conn = None
        try:
            # Reset the global connection if it's closed
            global _tax_db_conn
            if _tax_db_conn and _tax_db_conn.closed:
                _tax_db_conn = None
            
            db_conn = get_tax_db_conn()
            
            # Check if connection is still valid
            if db_conn.closed:
                logger.warning("Database connection closed, creating new connection")
                _tax_db_conn = None
                db_conn = get_tax_db_conn()
            
            cursor = db_conn.cursor()
            cursor.execute("""
                INSERT INTO tax_documents (
                    document_id, jurisdiction, form_code, tax_year,
                    client_name, client_type, raw_file_path,
                    extracted_data, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                document_id, jurisdiction, form_code, tax_year,
                client_name, client_type, temp_path,
                psycopg2.extras.Json(extracted_data), 'uploaded'
            ))
            db_conn.commit()
            cursor.close()
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as db_error:
            # Connection error - try with a fresh connection
            logger.warning(f"Database connection error during insert: {db_error}, retrying with fresh connection")
            if db_conn:
                try:
                    db_conn.close()
                except:
                    pass
            
            # Reset global connection and get a new one
            _tax_db_conn = None
            db_conn = get_tax_db_conn()
            cursor = db_conn.cursor()
            cursor.execute("""
                INSERT INTO tax_documents (
                    document_id, jurisdiction, form_code, tax_year,
                    client_name, client_type, raw_file_path,
                    extracted_data, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                document_id, jurisdiction, form_code, tax_year,
                client_name, client_type, temp_path,
                psycopg2.extras.Json(extracted_data), 'uploaded'
            ))
            db_conn.commit()
            cursor.close()
        
        return {
            "success": True,
            "message": "Document uploaded successfully",
            "document_id": document_id,
            "extracted_data": extracted_data
        }
    except Exception as e:
        logger.error(f"Error uploading tax document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/workflow1/check/{document_id}")
async def check_document_completeness(
    document_id: str,
    check_types: Optional[List[str]] = Query(None)
):
    """Run completeness check on uploaded document"""
    try:
        workflow1 = get_tax_workflow1()
        result = await workflow1.check_document(document_id=document_id, check_types=check_types)
        return result
    except Exception as e:
        logger.error(f"Error checking document completeness: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow1/issues/{document_id}")
async def get_document_issues(
    document_id: str,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None
):
    """Get all issues for a document, optionally filtered"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        query = "SELECT * FROM completeness_checks WHERE document_id = %s"
        params = [document_id]
        
        if severity:
            query += " AND severity = %s"
            params.append(severity)
        if resolved is not None:
            query += " AND is_resolved = %s"
            params.append(resolved)
        
        query += " ORDER BY severity DESC, created_at DESC"
        cursor.execute(query, params)
        issues = cursor.fetchall()
        cursor.close()
        
        return {
            "document_id": document_id,
            "total_issues": len(issues),
            "issues": [dict(row) for row in issues]
        }
    except Exception as e:
        logger.error(f"Error getting document issues: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/v1/workflow1/resolve/{issue_id}")
async def resolve_issue(issue_id: int):
    """Mark an issue as resolved"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        cursor.execute("UPDATE completeness_checks SET is_resolved = TRUE WHERE id = %s", (issue_id,))
        db_conn.commit()
        cursor.close()
        return {"success": True, "message": "Issue marked as resolved"}
    except Exception as e:
        logger.error(f"Error resolving issue: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Workflow 2: Jurisdiction Comparison
@app.post("/api/v1/workflow2/compare")
async def create_jurisdiction_comparison(request: ComparisonRequest):
    """Create a comprehensive comparison between two jurisdictions"""
    global _tax_workflow2, _tax_db_conn
    try:
        # Ensure fresh database connection
        if _tax_db_conn and _tax_db_conn.closed:
            _tax_db_conn = None
            _tax_workflow2 = None
        
        workflow2 = get_tax_workflow2()
        result = await workflow2.create_comparison(
            base_jurisdiction=request.base_jurisdiction,
            target_jurisdiction=request.target_jurisdiction,
            scope=request.scope,
            tax_year=request.tax_year,
            requested_by=request.requested_by
        )
        return result
    except ConnectionError as conn_error:
        logger.error(f"Database connection error in comparison: {conn_error}", exc_info=True)
        # Reset connection on error
        _tax_db_conn = None
        _tax_workflow2 = None
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(conn_error)}")
    except Exception as e:
        logger.error(f"Error creating jurisdiction comparison: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow2/comparison/{comparison_id}")
async def get_comparison(comparison_id: str):
    """Retrieve a saved comparison"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        cursor.execute("SELECT * FROM jurisdiction_comparisons WHERE comparison_id = %s", (comparison_id,))
        comparison = cursor.fetchone()
        
        if not comparison:
            raise HTTPException(status_code=404, detail="Comparison not found")
        
        cursor.execute("""
            SELECT * FROM jurisdiction_differences
            WHERE comparison_id = %s
            ORDER BY impact_level DESC
        """, (comparison_id,))
        differences = cursor.fetchall()
        cursor.close()
        
        return {
            "comparison": dict(comparison),
            "differences": [dict(row) for row in differences]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting comparison: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/workflow2/research")
async def research_specific_topic(request: ResearchRequest):
    """Deep dive research on a specific topic across jurisdictions"""
    try:
        workflow2 = get_tax_workflow2()
        result = await workflow2.research_specific_topic(
            base_jurisdiction=request.base_jurisdiction,
            target_jurisdiction=request.target_jurisdiction,
            topic=request.topic,
            tax_year=request.tax_year
        )
        return result
    except Exception as e:
        logger.error(f"Error researching topic: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Workflow 3: Multi-Jurisdiction Planning
@app.post("/api/v1/workflow3/scenario")
async def create_planning_scenario(request: PlanningScenarioRequest):
    """Create a multi-jurisdiction tax planning scenario"""
    global _tax_workflow3, _tax_db_conn
    try:
        # Ensure fresh database connection
        if _tax_db_conn and _tax_db_conn.closed:
            _tax_db_conn = None
            _tax_workflow3 = None
        
        workflow3 = get_tax_workflow3()
        result = await workflow3.create_planning_scenario(
            client_id=request.client_id,
            client_name=request.client_name,
            scenario_name=request.scenario_name,
            jurisdictions_involved=request.jurisdictions_involved,
            income_sources=[dict(inc) for inc in request.income_sources],
            objectives=request.objectives,
            tax_year=request.tax_year
        )
        return result
    except IndexError as e:
        error_msg = f"IndexError (tuple index out of range): {str(e)}. This usually indicates a data structure mismatch. Check server logs for details."
        logger.error(f"IndexError in planning scenario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Error creating planning scenario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/api/v1/workflow3/scenario/{scenario_id}")
async def get_planning_scenario(scenario_id: str):
    """Retrieve a saved planning scenario"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM planning_scenarios WHERE scenario_id = %s", (scenario_id,))
        scenario = cursor.fetchone()
        
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
        
        # Convert to dict if needed
        if hasattr(scenario, 'keys'):
            scenario_dict = dict(scenario)
        else:
            scenario_dict = dict(scenario) if scenario else {}
        
        cursor.execute("SELECT * FROM tax_exposures WHERE scenario_id = %s ORDER BY risk_level DESC", (scenario_id,))
        exposures = cursor.fetchall()
        
        cursor.execute("SELECT * FROM planning_recommendations WHERE scenario_id = %s ORDER BY priority DESC", (scenario_id,))
        recommendations = cursor.fetchall()
        cursor.close()
        
        # Convert exposures and recommendations to dicts
        exposures_list = [dict(row) if hasattr(row, 'keys') else dict(row) for row in exposures] if exposures else []
        recommendations_list = [dict(row) if hasattr(row, 'keys') else dict(row) for row in recommendations] if recommendations else []
        
        return {
            "scenario": scenario_dict,
            "exposures": exposures_list,
            "recommendations": recommendations_list
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting planning scenario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow3/recommendations/{scenario_id}")
async def get_recommendations(scenario_id: str, priority: Optional[str] = None):
    """Get recommendations for a scenario, optionally filtered by priority"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        query = "SELECT * FROM planning_recommendations WHERE scenario_id = %s"
        params = [scenario_id]
        
        if priority:
            query += " AND priority = %s"
            params.append(priority)
        
        query += " ORDER BY priority DESC, created_at DESC"
        cursor.execute(query, params)
        recommendations = cursor.fetchall()
        cursor.close()
        
        return {
            "scenario_id": scenario_id,
            "count": len(recommendations),
            "recommendations": [dict(row) for row in recommendations]
        }
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# Search & Discovery
@app.get("/api/search/jurisdictions")
async def list_jurisdictions():
    """List all available jurisdictions in the system"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT DISTINCT jurisdiction, COUNT(*) as law_count
            FROM tax_laws
            GROUP BY jurisdiction
            ORDER BY jurisdiction
        """)
        results = cursor.fetchall()
        cursor.close()
        return {"jurisdictions": [dict(row) for row in results]}
    except Exception as e:
        logger.error(f"Error listing jurisdictions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search/categories")
async def list_categories(jurisdiction: Optional[str] = None):
    """List available law categories, optionally filtered by jurisdiction"""
    try:
        db_conn = get_tax_db_conn()
        cursor = db_conn.cursor()
        
        if jurisdiction:
            cursor.execute("""
                SELECT DISTINCT law_category, COUNT(*) as count
                FROM tax_laws
                WHERE jurisdiction = %s
                GROUP BY law_category
                ORDER BY law_category
            """, (jurisdiction,))
        else:
            cursor.execute("""
                SELECT DISTINCT law_category, COUNT(*) as count
                FROM tax_laws
                GROUP BY law_category
                ORDER BY law_category
            """)
        
        results = cursor.fetchall()
        cursor.close()
        return {"categories": [dict(row) for row in results]}
    except Exception as e:
        logger.error(f"Error listing categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

