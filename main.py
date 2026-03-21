from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from config import Config
from database import Database
from document_processor import DocumentProcessor
from vectorizer import Vectorizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

origins = [
    "*"
]


app = FastAPI(title="Document Processing API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
db = Database()
document_processor = DocumentProcessor()
vectorizer = Vectorizer()

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
        
        # Vectorize the metadata
        vector = vectorizer.vectorize_metadata(metadata)
        
        # Store in database based on document type
        if doc_type == 'invoice':
            stored_record = db.insert_invoice(metadata, vector)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

