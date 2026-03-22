from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query, Body
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
import os
import re
import logging
import boto3
from pathlib import Path
from config import Config
from database import Database
from compliance_engine import ComplianceEngine
from document_processor import DocumentProcessor
from vectorizer import Vectorizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

origins = Config.CORS_ALLOW_ORIGINS or ["*"]

DEFAULT_BULK_LIMIT = 200

RAG_EXCERPT_MAX_LEN = 1200


def _contract_excerpt_for_sources(contract: dict, max_len: int = RAG_EXCERPT_MAX_LEN):
    text = contract.get("text") or contract.get("summary") or ""
    if not text:
        return "", False
    truncated = len(text) > max_len
    excerpt = text[:max_len] + ("..." if truncated else "")
    return excerpt, truncated

# Filenames like contract.pdf should not override ADE-extracted contract_id
_GENERIC_CONTRACT_UPLOAD_STEMS = frozenset(
    {"contract", "document", "file", "upload", "invoice", "untitled", "scan", "new"}
)


def _s3_invoice_pdf_basename(metadata: dict, upload_filename: str) -> str:
    """Prefer extracted invoice_id for the S3 object name so keys match the stored invoice number."""
    inv = (metadata.get("invoice_id") or "").strip()
    if inv:
        base = re.sub(r"[^a-zA-Z0-9._-]", "_", inv)
        if not base.lower().endswith(".pdf"):
            base = f"{base}.pdf"
        return base if base else "invoice.pdf"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", Path(upload_filename).name) or "invoice.pdf"


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
    invoice_ids: Optional[List[int]] = Field(
        default=None,
        description="Database primary keys (invoices.id). Use this or invoice_numbers.",
    )
    invoice_numbers: Optional[List[str]] = Field(
        default=None,
        description="Business invoice_id values (e.g. INV-2024-OM-004). Use this or invoice_ids.",
    )

    @model_validator(mode="after")
    def require_invoice_selection(self):
        ids = self.invoice_ids or []
        nums = self.invoice_numbers or []
        if not ids and not nums:
            raise ValueError(
                "Provide invoice_ids (database ids) and/or invoice_numbers (invoice_id strings)"
            )
        return self

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

@app.get("/invoices/by_invoice_id/{invoice_id}")
async def get_invoice_by_invoice_id(invoice_id: str):
    """
    Fetch invoice metadata by business invoice number (e.g. INV-2024-OM-004).
    Use this from UIs that list invoice_id; GET /invoices/{db_id} expects the numeric database id.
    """
    try:
        invoice = db.get_invoice_by_id(invoice_id)
        if not invoice:
            raise HTTPException(
                status_code=404,
                detail=f"Invoice with invoice_id '{invoice_id}' not found",
            )
        response_metadata = {
            "db_id": invoice.get("id"),
            "invoice_id": invoice.get("invoice_id"),
            "seller_name": invoice.get("seller_name"),
            "seller_address": invoice.get("seller_address"),
            "tax_id": invoice.get("tax_id"),
            "subtotal_amount": float(invoice.get("subtotal_amount", 0))
            if invoice.get("subtotal_amount")
            else 0.0,
            "tax_amount": float(invoice.get("tax_amount", 0))
            if invoice.get("tax_amount")
            else 0.0,
            "summary": invoice.get("summary"),
            "created_at": invoice.get("created_at").isoformat()
            if invoice.get("created_at")
            else None,
            "updated_at": invoice.get("updated_at").isoformat()
            if invoice.get("updated_at")
            else None,
        }
        return JSONResponse(
            status_code=200,
            content={"success": True, "metadata": response_metadata},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving invoice: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving invoice: {str(e)}",
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


@app.get("/invoices/by-invoice-id/{invoice_id}/pdf_url")
async def get_invoice_pdf_presigned_url_by_invoice_number(invoice_id: str):
    """
    Same as /invoices/{db_id}/pdf_url but resolves by business invoice_id (e.g. INV-2024-OM-004).
    Use when the UI only has the invoice number, not the database primary key.
    """
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice '{invoice_id}' not found",
        )
    invoice_db_id = inv.get("id")
    s3_key = db.get_invoice_s3_key(invoice_db_id)
    if not s3_key:
        raise HTTPException(
            status_code=404,
            detail="No PDF stored for this invoice. Upload with S3 enabled or check configuration.",
        )
    try:
        url = compliance_engine.pdf_highlighter.get_original_pdf_url(s3_key)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "invoice_db_id": invoice_db_id,
                "invoice_id": invoice_id,
                "url": url,
            },
        )
    except Exception as e:
        logger.error("Error generating presigned PDF URL: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/invoices/by-invoice-id/{invoice_id}/pdf")
async def redirect_invoice_pdf_by_invoice_number(invoice_id: str):
    """302 redirect to presigned PDF, keyed by business invoice_id."""
    inv = db.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice '{invoice_id}' not found",
        )
    invoice_db_id = inv.get("id")
    s3_key = db.get_invoice_s3_key(invoice_db_id)
    if not s3_key:
        raise HTTPException(
            status_code=404,
            detail="No PDF stored for this invoice. Upload with S3 enabled or check configuration.",
        )
    try:
        url = compliance_engine.pdf_highlighter.get_original_pdf_url(s3_key)
        return RedirectResponse(url=url, status_code=302)
    except Exception as e:
        logger.error("Error redirecting to PDF: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/invoices/{invoice_db_id}/pdf_url")
async def get_invoice_pdf_presigned_url(invoice_db_id: int):
    """
    Return a fresh presigned URL for this invoice's stored PDF in S3.
    Use this from the frontend with window.open(url) or <a href={url} target="_blank">
    so each invoice opens its own file (URLs are unique per invoice key).
    """
    s3_key = db.get_invoice_s3_key(invoice_db_id)
    if not s3_key:
        raise HTTPException(
            status_code=404,
            detail="No PDF stored for this invoice. Upload with S3 enabled or check configuration.",
        )
    try:
        url = compliance_engine.pdf_highlighter.get_original_pdf_url(s3_key)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "invoice_db_id": invoice_db_id,
                "url": url,
            },
        )
    except Exception as e:
        logger.error("Error generating presigned PDF URL: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/invoices/{invoice_db_id}/pdf")
async def redirect_invoice_pdf_to_s3(invoice_db_id: int):
    """HTTP redirect to the presigned S3 URL (browser navigation / open in new tab)."""
    s3_key = db.get_invoice_s3_key(invoice_db_id)
    if not s3_key:
        raise HTTPException(
            status_code=404,
            detail="No PDF stored for this invoice. Upload with S3 enabled or check configuration.",
        )
    try:
        url = compliance_engine.pdf_highlighter.get_original_pdf_url(s3_key)
        return RedirectResponse(url=url, status_code=302)
    except Exception as e:
        logger.error("Error redirecting to PDF: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/invoices/{invoice_db_id}/compliance_report/latest")
async def get_latest_compliance_report_for_invoice(invoice_db_id: int):
    """
    Latest saved compliance row for this invoice, including llm_metadata.s3_url when present.
    """
    try:
        inv = db.get_invoice_by_db_id(invoice_db_id)
        if not inv:
            raise HTTPException(
                status_code=404,
                detail=f"Invoice with database ID '{invoice_db_id}' not found",
            )
        report = db.get_latest_compliance_report(invoice_db_id)
        if not report:
            raise HTTPException(
                status_code=404,
                detail="No compliance report found for this invoice. Run analyze first.",
            )
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "report": db._convert_decimals_to_float(dict(report)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error loading compliance report: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
        
        # Extract data using Landing AI ADE based on document type
        if doc_type == 'invoice':
            metadata = document_processor.extract_invoice_data(str(file_path))
        elif doc_type == 'contract':
            metadata = document_processor.extract_contract_data(str(file_path))
            # Prefer a meaningful upload filename as contract_id (user expectation); otherwise ADE extraction.
            stem_raw = Path(file.filename).stem.strip()
            stem_id = re.sub(r"[^a-zA-Z0-9._-]", "_", stem_raw) if stem_raw else ""
            if stem_id and stem_raw.lower() not in _GENERIC_CONTRACT_UPLOAD_STEMS:
                metadata["contract_id"] = stem_id
                logger.info("contract_id from upload filename: %s", stem_id)
            elif not (metadata.get("contract_id") or "").strip() and stem_id:
                metadata["contract_id"] = stem_id
                logger.info(
                    "contract_id missing from extraction; using upload filename stem: %s",
                    stem_id,
                )

        # Vectorize the metadata
        vector = vectorizer.vectorize_metadata(metadata)
        
        # Store in database based on document type
        if doc_type == 'invoice':
            stored_record = db.insert_invoice(metadata, vector)
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

            if Config.S3_ENABLED and Config.S3_BUCKET_NAME and invoice_db_id:
                try:
                    safe_name = _s3_invoice_pdf_basename(metadata, file.filename)
                    s3_key = f"invoices/{invoice_db_id}/{safe_name}"
                    s3 = boto3.client("s3", region_name=Config.AWS_REGION)
                    s3.put_object(
                        Bucket=Config.S3_BUCKET_NAME,
                        Key=s3_key,
                        Body=content,
                        ContentType="application/pdf",
                    )
                    db.set_invoice_s3_key(invoice_db_id, s3_key)
                    logger.info("Stored invoice PDF in S3: %s", s3_key)
                except Exception as upload_err:
                    logger.warning(
                        "Could not upload invoice PDF to S3 (compliance highlighting may be unavailable): %s",
                        upload_err,
                    )
            
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
                'created_at': stored_record.get('created_at').isoformat() if stored_record.get('created_at') else None
            }
        elif doc_type == 'contract':
            stored_record = db.insert_contract(metadata, vector)
            logger.info(f"Successfully processed and stored contract: {metadata.get('contract_id')}")
            
            # Return contract metadata
            response_metadata = {
                'contract_id': stored_record.get('contract_id'),
                'summary': stored_record.get('summary'),
                'text': stored_record.get('text'),
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
    Trigger compliance analysis for selected invoices.
    Pass invoice_ids (numeric DB ids), invoice_numbers (e.g. INV-2024-OM-004), or both.
    """
    try:
        resolved: List[int] = []
        seen: set = set()
        for db_id in request.invoice_ids or []:
            if db_id not in seen:
                seen.add(db_id)
                resolved.append(db_id)
        for number in request.invoice_numbers or []:
            label = (number or "").strip()
            if not label:
                continue
            inv = db.get_invoice_by_id(label)
            if not inv:
                raise HTTPException(
                    status_code=404,
                    detail=f"Invoice with invoice_id '{label}' not found",
                )
            iid = inv.get("id")
            if iid is not None and iid not in seen:
                seen.add(iid)
                resolved.append(iid)
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail="No invoices to analyze after resolving invoice_numbers / invoice_ids",
            )
        summary = compliance_engine.analyze_invoices_explicit(resolved)
        return JSONResponse(
            status_code=200,
            content=summary
        )
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error(f"Error analyzing invoices: {e}", exc_info=True)
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
                    "answer": "No relevant contracts found matching your query.",
                    "sources": [],
                    "disclaimer": "Answers reflect only the retrieved excerpts below; verify against the full agreement.",
                }
            )

        # Collect context texts for LLM and build audit-friendly sources
        context_texts = []
        contract_ids = []
        sources = []

        for contract in results:
            contract_text = contract.get("text") or contract.get("summary") or ""
            contract_id = contract.get("contract_id")
            sim = contract.get("similarity")
            try:
                sim_val = float(sim) if sim is not None else None
            except (TypeError, ValueError):
                sim_val = None

            excerpt, excerpt_truncated = _contract_excerpt_for_sources(contract)
            sources.append(
                {
                    "contract_db_id": contract.get("id"),
                    "contract_id": contract_id,
                    "similarity": sim_val,
                    "excerpt": excerpt,
                    "excerpt_truncated": excerpt_truncated,
                }
            )

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
            answer = f"Unable to generate answer: {str(e)}"

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "answer": answer,
                "sources": sources,
                "disclaimer": "Answers reflect only the retrieved excerpts below; verify against the full agreement.",
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

