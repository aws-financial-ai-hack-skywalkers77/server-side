# main.py - Complete FastAPI Application

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import uvicorn
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Import workflow services
from services.core.vectorizer import Vectorizer
from services.core.document_parser import TaxDocumentParser
from services.core.law_ingestion import LawIngestionService
from services.workflow1.completeness_checker import FormCompletenessChecker
from services.workflow2.comparison_engine import JurisdictionComparisonEngine
from services.workflow3.planning_engine import MultiJurisdictionPlanningEngine
from config import Config

# Load environment variables
load_dotenv()

# ============================================================================
# FastAPI App Configuration
# ============================================================================

app = FastAPI(
    title="Tax Intelligence Platform",
    description="AI-powered tax research, compliance checking, and planning platform for CAs",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Database Connection
# ============================================================================

def get_db_connection():
    """Create database connection to PostgreSQL/NeonDB"""
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            sslmode='require' if Config.DB_HOST and 'neon' in Config.DB_HOST.lower() else 'prefer',
            cursor_factory=RealDictCursor
        )
        # Enable pgvector extension
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        raise

# ============================================================================
# Initialize Services (lazy initialization)
# ============================================================================

# Global service instances (initialized on first use)
_vectorizer = None
_document_parser = None
_db_conn = None
_law_service = None
_workflow1 = None
_workflow2 = None
_workflow3 = None

def get_vectorizer():
    """Get or create vectorizer instance"""
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = Vectorizer(api_key=Config.GEMINI_API_KEY)
    return _vectorizer

def get_document_parser():
    """Get or create document parser instance"""
    global _document_parser
    if _document_parser is None:
        _document_parser = TaxDocumentParser(api_key=Config.LANDING_AI_API_KEY)
    return _document_parser

def get_db_conn():
    """Get or create database connection"""
    global _db_conn
    if _db_conn is None:
        _db_conn = get_db_connection()
    return _db_conn

def get_law_service():
    """Get or create law ingestion service"""
    global _law_service
    if _law_service is None:
        _law_service = LawIngestionService(get_db_conn(), get_vectorizer())
    return _law_service

def get_workflow1():
    """Get or create workflow 1 instance"""
    global _workflow1
    if _workflow1 is None:
        _workflow1 = FormCompletenessChecker(
            get_db_conn(), 
            get_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _workflow1

def get_workflow2():
    """Get or create workflow 2 instance"""
    global _workflow2
    if _workflow2 is None:
        _workflow2 = JurisdictionComparisonEngine(
            get_db_conn(), 
            get_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _workflow2

def get_workflow3():
    """Get or create workflow 3 instance"""
    global _workflow3
    if _workflow3 is None:
        _workflow3 = MultiJurisdictionPlanningEngine(
            get_db_conn(), 
            get_vectorizer(), 
            Config.GEMINI_API_KEY
        )
    return _workflow3

# ============================================================================
# Pydantic Models
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

# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "Tax Intelligence Platform",
        "version": "1.0.0",
        "status": "operational",
        "workflows": {
            "workflow1": "Form Completeness Checker",
            "workflow2": "Jurisdiction Comparison Engine",
            "workflow3": "Multi-Jurisdiction Planning"
        },
        "documentation": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db_conn = get_db_conn()
        cursor = db_conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        
        return {
            "status": "healthy",
            "database": "connected",
            "workflows": {
                "workflow1": os.getenv('ENABLE_WORKFLOW1', 'true').lower() == 'true',
                "workflow2": os.getenv('ENABLE_WORKFLOW2', 'true').lower() == 'true',
                "workflow3": os.getenv('ENABLE_WORKFLOW3', 'true').lower() == 'true'
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )

# ============================================================================
# ADMIN ENDPOINTS - Law Ingestion
# ============================================================================

@app.post("/api/admin/ingest-law")
async def ingest_law_document(
    file: UploadFile = File(...),
    jurisdiction: str = Form(...),
    law_category: str = Form(...),
    document_title: Optional[str] = Form(None),
    document_source: Optional[str] = Form(None)
):
    """
    Admin endpoint to ingest a law document (PDF) into the knowledge base
    
    Example:
    - jurisdiction: "US-NY", "EU-DE", "UK"
    - law_category: "income_tax", "corporate_tax", "vat"
    """
    
    try:
        # Save uploaded file temporarily
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        # Ingest the law document
        law_service = get_law_service()
        result = await law_service.ingest_from_pdf(
            pdf_path=temp_path,
            jurisdiction=jurisdiction,
            law_category=law_category,
            document_title=document_title or file.filename,
            document_source=document_source
        )
        
        # Clean up
        os.remove(temp_path)
        
        return {
            "success": True,
            "message": "Law document ingested successfully",
            "details": result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/laws")
async def list_laws(
    jurisdiction: Optional[str] = None,
    law_category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500)
):
    """List ingested law documents"""
    
    db_conn = get_db_conn()
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
    
    return {
        "count": len(results),
        "laws": [dict(row) for row in results]
    }

# ============================================================================
# WORKFLOW 1 ENDPOINTS - Form Completeness Checker
# ============================================================================

@app.post("/api/v1/workflow1/upload")
async def upload_tax_document(
    file: UploadFile = File(...),
    jurisdiction: str = Form(...),
    form_code: str = Form(...),
    tax_year: int = Form(...),
    client_name: Optional[str] = Form(None),
    client_type: str = Form("individual")
):
    """
    Upload a tax document (PDF) for completeness checking
    
    Returns document_id for subsequent checking
    """
    
    try:
        # Save file temporarily
        temp_path = f"/tmp/{file.filename}"
        with open(temp_path, "wb") as f:
            f.write(await file.read())
        
        # Parse document with Landing AI
        document_parser = get_document_parser()
        extracted_data = await document_parser.process_tax_document(temp_path)
        
        # Generate document ID
        import uuid
        document_id = f"DOC-{uuid.uuid4().hex[:8].upper()}"
        
        # Store in database
        db_conn = get_db_conn()
        cursor = db_conn.cursor()
        cursor.execute("""
            INSERT INTO tax_documents (
                document_id, jurisdiction, form_code, tax_year,
                client_name, client_type, raw_file_path,
                extracted_data, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            document_id,
            jurisdiction,
            form_code,
            tax_year,
            client_name,
            client_type,
            temp_path,
            psycopg2.extras.Json(extracted_data),
            'uploaded'
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
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/workflow1/check/{document_id}")
async def check_document_completeness(
    document_id: str,
    check_types: Optional[List[str]] = Query(None)
):
    """
    Run completeness check on uploaded document
    
    check_types: ['required_fields', 'calculations', 'cross_reference', 'jurisdiction_specific']
    If not provided, runs all checks
    """
    
    try:
        workflow1 = get_workflow1()
        result = await workflow1.check_document(
            document_id=document_id,
            check_types=check_types
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow1/issues/{document_id}")
async def get_document_issues(
    document_id: str,
    severity: Optional[str] = None,
    resolved: Optional[bool] = None
):
    """Get all issues for a document, optionally filtered"""
    
    db_conn = get_db_conn()
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

@app.patch("/api/v1/workflow1/resolve/{issue_id}")
async def resolve_issue(issue_id: int):
    """Mark an issue as resolved"""
    
    db_conn = get_db_conn()
    cursor = db_conn.cursor()
    cursor.execute("""
        UPDATE completeness_checks
        SET is_resolved = TRUE
        WHERE id = %s
    """, (issue_id,))
    db_conn.commit()
    cursor.close()
    
    return {"success": True, "message": "Issue marked as resolved"}

# ============================================================================
# WORKFLOW 2 ENDPOINTS - Jurisdiction Comparison
# ============================================================================

@app.post("/api/v1/workflow2/compare")
async def create_jurisdiction_comparison(request: ComparisonRequest):
    """
    Create a comprehensive comparison between two jurisdictions
    
    Example:
    {
        "base_jurisdiction": "US-NY",
        "target_jurisdiction": "EU-DE",
        "scope": "individual_income",
        "tax_year": 2024
    }
    """
    
    try:
        workflow2 = get_workflow2()
        result = await workflow2.create_comparison(
            base_jurisdiction=request.base_jurisdiction,
            target_jurisdiction=request.target_jurisdiction,
            scope=request.scope,
            tax_year=request.tax_year,
            requested_by=request.requested_by
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow2/comparison/{comparison_id}")
async def get_comparison(comparison_id: str):
    """Retrieve a saved comparison"""
    
    db_conn = get_db_conn()
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT * FROM jurisdiction_comparisons
        WHERE comparison_id = %s
    """, (comparison_id,))
    
    comparison = cursor.fetchone()
    
    if not comparison:
        raise HTTPException(status_code=404, detail="Comparison not found")
    
    # Get differences
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

@app.post("/api/v1/workflow2/research")
async def research_specific_topic(request: ResearchRequest):
    """
    Deep dive research on a specific topic across jurisdictions
    
    Example:
    {
        "base_jurisdiction": "US-NY",
        "target_jurisdiction": "EU-FR",
        "topic": "Home office deduction rules for remote workers",
        "tax_year": 2024
    }
    """
    
    try:
        workflow2 = get_workflow2()
        result = await workflow2.research_specific_topic(
            base_jurisdiction=request.base_jurisdiction,
            target_jurisdiction=request.target_jurisdiction,
            topic=request.topic,
            tax_year=request.tax_year
        )
        
        return result
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# WORKFLOW 3 ENDPOINTS - Multi-Jurisdiction Planning
# ============================================================================

@app.post("/api/v1/workflow3/scenario")
async def create_planning_scenario(request: PlanningScenarioRequest):
    """
    Create a multi-jurisdiction tax planning scenario
    
    Example:
    {
        "client_id": "CLIENT-001",
        "client_name": "John Doe",
        "scenario_name": "Remote worker with EU rental income",
        "jurisdictions_involved": ["US-NY", "EU-DE"],
        "income_sources": [
            {
                "type": "employment",
                "jurisdiction": "US-NY",
                "amount_range": "100000-150000",
                "description": "Tech company salary"
            },
            {
                "type": "rental_income",
                "jurisdiction": "EU-DE",
                "amount_range": "30000-40000",
                "description": "Berlin apartment"
            }
        ],
        "objectives": ["minimize_tax", "avoid_double_taxation", "compliance"],
        "tax_year": 2024
    }
    """
    
    try:
        workflow3 = get_workflow3()
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
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow3/scenario/{scenario_id}")
async def get_planning_scenario(scenario_id: str):
    """Retrieve a saved planning scenario"""
    
    db_conn = get_db_conn()
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT * FROM planning_scenarios
        WHERE scenario_id = %s
    """, (scenario_id,))
    
    scenario = cursor.fetchone()
    
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    # Get exposures
    cursor.execute("""
        SELECT * FROM tax_exposures
        WHERE scenario_id = %s
        ORDER BY risk_level DESC
    """, (scenario_id,))
    exposures = cursor.fetchall()
    
    # Get recommendations
    cursor.execute("""
        SELECT * FROM planning_recommendations
        WHERE scenario_id = %s
        ORDER BY priority DESC
    """, (scenario_id,))
    recommendations = cursor.fetchall()
    
    cursor.close()
    
    return {
        "scenario": dict(scenario),
        "exposures": [dict(row) for row in exposures],
        "recommendations": [dict(row) for row in recommendations]
    }

@app.get("/api/v1/workflow3/recommendations/{scenario_id}")
async def get_recommendations(scenario_id: str, priority: Optional[str] = None):
    """Get recommendations for a scenario, optionally filtered by priority"""
    
    db_conn = get_db_conn()
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

# ============================================================================
# Search & Discovery Endpoints
# ============================================================================

@app.get("/api/search/jurisdictions")
async def list_jurisdictions():
    """List all available jurisdictions in the system"""
    
    db_conn = get_db_conn()
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT DISTINCT jurisdiction, COUNT(*) as law_count
        FROM tax_laws
        GROUP BY jurisdiction
        ORDER BY jurisdiction
    """)
    
    results = cursor.fetchall()
    cursor.close()
    
    return {
        "jurisdictions": [dict(row) for row in results]
    }

@app.get("/api/search/categories")
async def list_categories(jurisdiction: Optional[str] = None):
    """List available law categories, optionally filtered by jurisdiction"""
    
    db_conn = get_db_conn()
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
    
    return {
        "categories": [dict(row) for row in results]
    }

# ============================================================================
# Run Application
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv('API_PORT', 8000))
    uvicorn.run(
        "main_fastapi_app:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )