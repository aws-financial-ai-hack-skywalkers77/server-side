# Document Processing Platform

A document processing API built with Landing AI ADE (Agentic Document Extraction) for extracting data from invoices and contracts, vectorizing the extracted data, and storing it in PostgreSQL on AWS.

## Features

- **Document Upload API**: RESTful endpoint for uploading PDF documents
- **Landing AI ADE Integration**: Automated document extraction using Landing AI's ADE service
- **Vectorization**: Converts extracted metadata to embeddings using OpenAI
- **PostgreSQL Storage**: Stores metadata and vectors in AWS RDS PostgreSQL with pgvector extension
- **Invoice Processing**: Currently supports invoice extraction with the following fields:
  - invoice_id
  - seller_name
  - seller_address
  - tax_id
  - subtotal_amount
  - tax_amount
  - summary

## Setup

### Prerequisites

- Python 3.8+
- PostgreSQL database (AWS RDS) with pgvector extension
- Landing AI API key
- OpenAI API key (for embeddings)

### Installation

1. Clone the repository and navigate to the project directory:
```bash
cd landingAI
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
```

Edit `.env` and fill in your configuration:
- `LANDING_AI_API_KEY` or `VISION_AGENT_API_KEY`: Your Landing AI API key (either name works)
- `DB_HOST`: Your AWS RDS PostgreSQL host
- `DB_PORT`: Database port (default: 5432)
- `DB_NAME`: Database name
- `DB_USER`: Database username
- `DB_PASSWORD`: Database password
- `GEMINI_API_KEY`: Your Google Gemini API key (get it from [Google AI Studio](https://aistudio.google.com/))
- `EMBEDDING_MODEL`: Embedding model (default: models/embedding-001 for Gemini)
- `EMBEDDING_DIMENSIONS`: Vector dimensions (default: 768 for Gemini embeddings)
- `UPLOAD_DIR`: Temporary directory for file uploads (default: /tmp)
- `MAX_FILE_SIZE`: Maximum file size in bytes (default: 10485760 = 10MB)

### Database Setup

The application will automatically create the necessary tables on startup. Ensure your PostgreSQL database has the pgvector extension available.

## Running the API

Start the FastAPI server:

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## Testing

You can test the API using the provided test script:

```bash
python test_api.py path/to/your/invoice.pdf
```

Or using curl:

```bash
curl -X POST "http://localhost:8000/upload_document" \
  -F "file=@invoice.pdf" \
  -F "document_type=invoice"
```

## API Endpoints

### Upload Document

**POST** `/upload_document`

Upload a PDF document for processing.

**Request:**
- `file`: PDF file (multipart/form-data)
- `document_type`: Document type (currently only "invoice" is supported)

**Example using curl:**
```bash
curl -X POST "http://localhost:8000/upload_document" \
  -F "file=@invoice.pdf" \
  -F "document_type=invoice"
```

**Response:**
```json
{
  "success": true,
  "message": "Document processed successfully",
  "metadata": {
    "invoice_id": "INV-12345",
    "seller_name": "Acme Corp",
    "seller_address": "123 Main St, City, State 12345",
    "tax_id": "TAX-123456",
    "subtotal_amount": 1000.00,
    "tax_amount": 100.00,
    "summary": "Monthly services invoice",
    "created_at": "2024-01-15T10:30:00"
  }
}
```

### Health Check

**GET** `/health`

Check API health status.

**Response:**
```json
{
  "status": "healthy"
}
```

## Project Structure

```
landingAI/
├── main.py                 # FastAPI application and endpoints
├── config.py              # Configuration management
├── database.py            # PostgreSQL database operations
├── document_processor.py  # Landing AI ADE integration
├── vectorizer.py          # Embedding generation
├── test_api.py           # Test script for API
├── requirements.txt       # Python dependencies
├── .gitignore            # Git ignore file
└── README.md             # This file
```

## Error Handling

The API includes comprehensive error handling for:
- Invalid file types
- File size limits
- Database connection errors
- Landing AI ADE extraction errors
- Vectorization errors

All errors are logged and returned with appropriate HTTP status codes.

## Future Enhancements

- Contract document processing support
- Batch document upload
- Document similarity search using vectors
- Document retrieval endpoints
- Authentication and authorization

