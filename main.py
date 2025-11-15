from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import os
import logging
from pathlib import Path
from config import Config
from database import Database
from compliance_engine import ComplianceEngine
from document_processor import DocumentProcessor
from vectorizer import Vectorizer

# Configure logging first
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
        min_items=1,
    )

# Initialize components
db = Database()
document_processor = DocumentProcessor()
vectorizer = Vectorizer()
compliance_engine = ComplianceEngine(db=db, vectorizer=vectorizer)

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
<<<<<<< Current (Your changes)
=======
                's3_key': stored_record.get('s3_key'),
                's3_url': s3_url if s3_url else None,
>>>>>>> Incoming (Background Agent changes)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

