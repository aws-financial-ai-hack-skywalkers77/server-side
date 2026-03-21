# Document Processing Platform

A document processing API built with Landing AI ADE (Agentic Document Extraction) for extracting data from invoices and contracts, vectorizing the extracted data, and storing it in PostgreSQL on AWS.

## Features

- **Document Upload API**: RESTful endpoint for uploading PDF documents (invoices and contracts)
- **Landing AI ADE Integration**: Automated document extraction using Landing AI's ADE service
- **Vectorization**: Converts extracted metadata to embeddings using Google Gemini
- **PostgreSQL Storage**: Stores metadata and vectors in AWS RDS PostgreSQL with pgvector extension
- **Invoice Processing**: Extracts invoice data with the following fields:
  - invoice_id
  - seller_name
  - seller_address
  - tax_id
  - subtotal_amount
  - tax_amount
  - summary
- **Contract Processing**: Extracts contract data with the following fields:
  - contract_id
  - summary
  - text (full contract text)
- **RESTful GET Endpoints**: Retrieve invoices and contracts with pagination support
- **RAG Query Endpoint**: Query contracts using semantic search with LLM-generated answers (Retrieval-Augmented Generation)
- **Compliance Automation**: Gemini-powered RAG + deterministic rule engine for single invoice checks and scheduled bulk monitoring

## Setup

### Prerequisites

- Python 3.8+ (or Docker for containerized deployment)
- PostgreSQL database (AWS RDS) with pgvector extension
- Landing AI API key
- Google Gemini API key (for embeddings)

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
- `GEMINI_GENERATION_MODEL`: Gemini model for text generation/RAG (default: gemini-1.5-flash)
- `UPLOAD_DIR`: Temporary directory for file uploads (default: /tmp)
- `MAX_FILE_SIZE`: Maximum file size in bytes (default: 10485760 = 10MB)

### Database Setup

The application will automatically create the necessary tables on startup. Ensure your PostgreSQL database has the pgvector extension available.

### Docker Setup (Alternative)

You can also run the application using Docker. See [DOCKER.md](DOCKER.md) for detailed instructions.

**Quick start with Docker Compose:**
```bash
# Create .env file with your configuration
cp .env.example .env
# Edit .env with your API keys and database credentials

# Start services (API + PostgreSQL with pgvector)
docker-compose up -d

# View logs
docker-compose logs -f api
```

The API will be available at `http://localhost:8001`

## Running the API

Start the FastAPI server:

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8001` (default port)

## Testing

You can test the API using the provided test script:

```bash
# Test invoice upload
python test_api.py invoice path/to/your/invoice.pdf

# Test contract upload
python test_api.py contract path/to/your/contract.pdf
```

Or using curl:

```bash
# Upload invoice
curl -X POST "http://localhost:8001/upload_document" \
  -F "file=@invoice.pdf" \
  -F "document_type=invoice"

# Upload contract
curl -X POST "http://localhost:8001/upload_document" \
  -F "file=@contract.pdf" \
  -F "document_type=contract"
```

## API Endpoints

### Analyze Single Invoice (Compliance)

**POST** `/analyze_invoice/{invoice_id}`

Trigger compliance analysis for a specific invoice. The service:

- Retrieves invoice metadata and stored line items from PostgreSQL (AWS RDS)
- Runs pgvector similarity search to fetch relevant contract clauses
- Uses Gemini (RAG) to infer pricing rules from the contract
- Applies a deterministic rule engine to flag overcharges or policy violations

**Example Response:**
```json
{
  "invoice_id": "INV-00845",
  "status": "processed",
  "violations": [
    {
      "line_id": "L-004",
      "violation_type": "Price Cap Exceeded",
      "expected_price": 120.0,
      "actual_price": 140.0,
      "difference": 20.0,
      "contract_clause_reference": "Section 4.2.A"
    }
  ],
  "next_run_scheduled_in_hours": 4
}
```

### Analyze Invoices (Bulk Compliance)

**POST** `/analyze_invoices_bulk`

Executes the compliance pipeline across invoices that are either new or outdated (updated since their last compliance run). Intended for schedulers such as cron jobs, AWS EventBridge, or other orchestration tooling.

**Request Body (optional):**

- `limit` (default `200`): Maximum invoices to process during the run.

**Example Response:**
```json
{
  "status": "bulk_run_started",
  "invoices_in_queue": 238,
  "processed": 238,
  "failed": 0,
  "violations_detected": 17,
  "next_run_scheduled_in_hours": 4
}
```

### Upload Document

**POST** `/upload_document`

Upload a PDF document for processing (invoice or contract).

**Request Parameters:**
- `file`: PDF file (multipart/form-data, `File` type)
- `document_type`: Document type string (`"invoice"` or `"contract"`)

**Content-Type:** `multipart/form-data`

**Example using curl:**
```bash
# Upload invoice
curl -X POST "http://localhost:8001/upload_document" \
  -F "file=@invoice.pdf" \
  -F "document_type=invoice"

# Upload contract
curl -X POST "http://localhost:8001/upload_document" \
  -F "file=@contract.pdf" \
  -F "document_type=contract"
```

**Example using React/JavaScript (Fetch API):**
```javascript
const uploadDocument = async (file, documentType) => {
  const formData = new FormData();
  formData.append('file', file); // file is a File object from input
  formData.append('document_type', documentType); // 'invoice' or 'contract'

  try {
    const response = await fetch('http://localhost:8001/upload_document', {
      method: 'POST',
      body: formData,
      // Don't set Content-Type header, browser will set it with boundary
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log('Upload successful:', data);
    return data;
  } catch (error) {
    console.error('Upload failed:', error);
    throw error;
  }
};

// Usage in React component
const handleFileUpload = async (event) => {
  const file = event.target.files[0];
  if (!file) return;

  // Validate file type
  if (file.type !== 'application/pdf') {
    alert('Please upload a PDF file');
    return;
  }

  // Validate file size (10MB limit)
  if (file.size > 10 * 1024 * 1024) {
    alert('File size must be less than 10MB');
    return;
  }

  try {
    const result = await uploadDocument(file, 'invoice');
    console.log('Extracted metadata:', result.metadata);
  } catch (error) {
    console.error('Error uploading document:', error);
  }
};
```

**Example using React with Axios:**
```javascript
import axios from 'axios';

const uploadDocument = async (file, documentType) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('document_type', documentType);

  try {
    const response = await axios.post(
      'http://localhost:8001/upload_document',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 300000, // 5 minutes timeout for processing
      }
    );

    return response.data;
  } catch (error) {
    if (error.response) {
      // Server responded with error
      console.error('Error:', error.response.data);
      throw new Error(error.response.data.detail || 'Upload failed');
    } else if (error.request) {
      // Request made but no response
      console.error('No response:', error.request);
      throw new Error('Network error. Please check your connection.');
    } else {
      console.error('Error:', error.message);
      throw error;
    }
  }
};

// React component example
function DocumentUploader() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const file = formData.get('file');
    const documentType = formData.get('document_type');

    if (!file) {
      alert('Please select a file');
      return;
    }

    setUploading(true);
    try {
      const data = await uploadDocument(file, documentType);
      setResult(data);
      alert('Document uploaded successfully!');
    } catch (error) {
      alert(`Upload failed: ${error.message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input type="file" name="file" accept=".pdf" required />
      <select name="document_type" required>
        <option value="invoice">Invoice</option>
        <option value="contract">Contract</option>
      </select>
      <button type="submit" disabled={uploading}>
        {uploading ? 'Uploading...' : 'Upload Document'}
      </button>
      {result && (
        <div>
          <h3>Extracted Metadata:</h3>
          <pre>{JSON.stringify(result.metadata, null, 2)}</pre>
        </div>
      )}
    </form>
  );
}
```

**Response (Invoice):**
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

**Response (Contract):**
```json
{
  "success": true,
  "message": "Document processed successfully",
  "metadata": {
    "contract_id": "CONTRACT-2024-001",
    "summary": "Service agreement for software development",
    "text": "This Agreement is entered into on...",
    "created_at": "2024-01-15T10:30:00"
  }
}
```

### Get All Invoices

**GET** `/invoices`

Retrieve all invoices with pagination support.

**Query Parameters:**
- `limit` (optional): Number of invoices to return (1-1000, default: 100)
- `offset` (optional): Number of invoices to skip (default: 0)

**Example using curl:**
```bash
# Get first 10 invoices
curl "http://localhost:8001/invoices?limit=10&offset=0"

# Get next 10 invoices
curl "http://localhost:8001/invoices?limit=10&offset=10"
```

**Example using React/JavaScript:**
```javascript
const fetchInvoices = async (limit = 100, offset = 0) => {
  try {
    const response = await fetch(
      `http://localhost:8001/invoices?limit=${limit}&offset=${offset}`
    );
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching invoices:', error);
    throw error;
  }
};

// Usage
const invoices = await fetchInvoices(10, 0);
console.log(`Total invoices: ${invoices.total}`);
console.log(`Returned: ${invoices.count}`);
invoices.invoices.forEach(invoice => {
  console.log(`Invoice ID: ${invoice.invoice_id}, Seller: ${invoice.seller_name}`);
});
```

**Response:**
```json
{
  "success": true,
  "count": 2,
  "total": 2,
  "limit": 100,
  "offset": 0,
  "invoices": [
    {
      "id": 1,
      "invoice_id": "INV-12345",
      "seller_name": "Acme Corp",
      "seller_address": "123 Main St, City, State 12345",
      "tax_id": "TAX-123456",
      "subtotal_amount": 1000.00,
      "tax_amount": 100.00,
      "summary": "Monthly services invoice",
      "created_at": "2024-01-15T10:30:00",
      "updated_at": "2024-01-15T10:30:00"
    }
  ]
}
```

### Get Invoice by ID

**GET** `/invoices/{invoice_id}`

Retrieve a specific invoice by its invoice_id.

**Example using curl:**
```bash
curl "http://localhost:8001/invoices/INV-12345"
```

**Example using React/JavaScript:**
```javascript
const fetchInvoiceById = async (invoiceId) => {
  try {
    const response = await fetch(
      `http://localhost:8001/invoices/${invoiceId}`
    );
    
    if (response.status === 404) {
      throw new Error('Invoice not found');
    }
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data.metadata;
  } catch (error) {
    console.error('Error fetching invoice:', error);
    throw error;
  }
};

// Usage
try {
  const invoice = await fetchInvoiceById('INV-12345');
  console.log('Invoice:', invoice);
} catch (error) {
  console.error('Failed to fetch invoice:', error.message);
}
```

**Response:**
```json
{
  "success": true,
  "metadata": {
    "id": 1,
    "invoice_id": "INV-12345",
    "seller_name": "Acme Corp",
    "seller_address": "123 Main St, City, State 12345",
    "tax_id": "TAX-123456",
    "subtotal_amount": 1000.00,
    "tax_amount": 100.00,
    "summary": "Monthly services invoice",
    "created_at": "2024-01-15T10:30:00",
    "updated_at": "2024-01-15T10:30:00"
  }
}
```

### Get All Contracts

**GET** `/contracts`

Retrieve all contracts with pagination support.

**Query Parameters:**
- `limit` (optional): Number of contracts to return (1-1000, default: 100)
- `offset` (optional): Number of contracts to skip (default: 0)

**Example using curl:**
```bash
curl "http://localhost:8001/contracts?limit=10&offset=0"
```

**Example using React/JavaScript:**
```javascript
const fetchContracts = async (limit = 100, offset = 0) => {
  try {
    const response = await fetch(
      `http://localhost:8001/contracts?limit=${limit}&offset=${offset}`
    );
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error fetching contracts:', error);
    throw error;
  }
};
```

**Response:**
```json
{
  "success": true,
  "count": 1,
  "total": 1,
  "limit": 100,
  "offset": 0,
  "contracts": [
    {
      "id": 1,
      "contract_id": "CONTRACT-2024-001",
      "summary": "Service agreement for software development",
      "text": "This Agreement is entered into on...",
      "created_at": "2024-01-15T10:30:00",
      "updated_at": "2024-01-15T10:30:00"
    }
  ]
}
```

### Get Contract by ID

**GET** `/contracts/{contract_id}`

Retrieve a specific contract by its contract_id.

**Example using curl:**
```bash
curl "http://localhost:8001/contracts/CONTRACT-2024-001"
```

**Example using React/JavaScript:**
```javascript
const fetchContractById = async (contractId) => {
  try {
    const response = await fetch(
      `http://localhost:8001/contracts/${contractId}`
    );
    
    if (response.status === 404) {
      throw new Error('Contract not found');
    }
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data.metadata;
  } catch (error) {
    console.error('Error fetching contract:', error);
    throw error;
  }
};
```

**Response:**
```json
{
  "success": true,
  "metadata": {
    "id": 1,
    "contract_id": "CONTRACT-2024-001",
    "summary": "Service agreement for software development",
    "text": "This Agreement is entered into on...",
    "created_at": "2024-01-15T10:30:00",
    "updated_at": "2024-01-15T10:30:00"
  }
}
```

### Query Contracts (RAG)

**POST** `/query_contracts`

Query contracts using RAG (Retrieval-Augmented Generation). This endpoint:
1. Searches contracts using semantic vector similarity
2. Uses an LLM (Gemini) to generate an answer based on retrieved contracts
3. Returns only the generated answer (not the source contracts)

**Request Body (JSON):**
- `query` (required): The search query text/question
- `id` (optional): Database ID to filter search to a specific contract
- `limit` (optional): Maximum number of contracts to retrieve (1-100, default: 10)
- `similarity_threshold` (optional): Minimum similarity score (0.0-1.0, default: 0.0)

**Content-Type:** `application/json`

**Example using curl:**
```bash
# Query all contracts
curl -X POST "http://localhost:8001/query_contracts" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the payment terms?"
  }'

# Query with limit
curl -X POST "http://localhost:8001/query_contracts" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the payment terms?",
    "limit": 5
  }'

# Query specific contract by database ID
curl -X POST "http://localhost:8001/query_contracts" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the termination clauses?",
    "id": 5
  }'

# Query with similarity threshold
curl -X POST "http://localhost:8001/query_contracts" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the liability clauses?",
    "limit": 10,
    "similarity_threshold": 0.5
  }'
```

**Example using React/JavaScript:**
```javascript
const queryContracts = async (query, contractId = null, limit = 10) => {
  try {
    const payload = {
      query: query,
      limit: limit
    };
    
    if (contractId) {
      payload.id = contractId;
    }
    
    const response = await fetch('http://localhost:8001/query_contracts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error querying contracts:', error);
    throw error;
  }
};

// Usage
const result = await queryContracts("What are the payment terms?");
console.log("Answer:", result.answer);
```

**Example using React with Axios:**
```javascript
import axios from 'axios';

const queryContracts = async (query, options = {}) => {
  const { id, limit = 10, similarity_threshold = 0.0 } = options;
  
  const payload = {
    query: query,
    limit: limit,
    similarity_threshold: similarity_threshold
  };
  
  if (id) {
    payload.id = id;
  }
  
  try {
    const response = await axios.post(
      'http://localhost:8001/query_contracts',
      payload,
      {
        headers: { 'Content-Type': 'application/json' },
        timeout: 60000, // 1 minute timeout
      }
    );
    
    return response.data;
  } catch (error) {
    if (error.response) {
      console.error('Error:', error.response.data);
      throw new Error(error.response.data.detail || 'Query failed');
    } else {
      console.error('Error:', error.message);
      throw error;
    }
  }
};

// Usage in React component
function ContractQuery() {
  const [query, setQuery] = useState('');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    try {
      const result = await queryContracts(query);
      setAnswer(result.answer);
    } catch (error) {
      alert(`Query failed: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div>
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask a question about contracts..."
          required
        />
        <button type="submit" disabled={loading}>
          {loading ? 'Querying...' : 'Query'}
        </button>
      </form>
      {answer && (
        <div>
          <h3>Answer:</h3>
          <p>{answer}</p>
        </div>
      )}
    </div>
  );
}
```

**Response:**
```json
{
  "success": true,
  "answer": "Based on the retrieved contracts, the payment terms specify that invoices are due within 30 days of receipt. Payment should be made via wire transfer to the account specified in the contract. Late payments may incur a 1.5% monthly interest charge."
}
```

**No Results Found:**
```json
{
  "success": true,
  "answer": "No relevant contracts found matching your query."
}
```

**Error Response:**
```json
{
  "success": true,
  "answer": "Unable to generate answer: [error message]"
}
```

**Note:** This endpoint uses RAG (Retrieval-Augmented Generation) technology:
- It first retrieves relevant contracts using vector similarity search
- Then uses an LLM (Gemini) to generate a natural language answer based on the retrieved contracts
- Only the generated answer is returned, not the source contracts

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

## Client-Side Integration Examples

### Complete React Component Example

```jsx
import React, { useState } from 'react';
import axios from 'axios';

const API_BASE_URL = 'http://localhost:8001';

function DocumentManager() {
  const [file, setFile] = useState(null);
  const [documentType, setDocumentType] = useState('invoice');
  const [uploading, setUploading] = useState(false);
  const [invoices, setInvoices] = useState([]);
  const [contracts, setContracts] = useState([]);
  const [selectedInvoice, setSelectedInvoice] = useState(null);
  const [selectedContract, setSelectedContract] = useState(null);

  // Upload document
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);

    try {
      const response = await axios.post(
        `${API_BASE_URL}/upload_document`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: 300000, // 5 minutes
        }
      );
      alert('Document uploaded successfully!');
      // Refresh lists
      if (documentType === 'invoice') {
        fetchInvoices();
      } else {
        fetchContracts();
      }
    } catch (error) {
      alert(`Upload failed: ${error.response?.data?.detail || error.message}`);
    } finally {
      setUploading(false);
    }
  };

  // Fetch all invoices
  const fetchInvoices = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/invoices`);
      setInvoices(response.data.invoices);
    } catch (error) {
      console.error('Error fetching invoices:', error);
    }
  };

  // Fetch invoice by ID
  const fetchInvoiceById = async (invoiceId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/invoices/${invoiceId}`);
      setSelectedInvoice(response.data.metadata);
    } catch (error) {
      alert('Invoice not found');
    }
  };

  // Fetch all contracts
  const fetchContracts = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/contracts`);
      setContracts(response.data.contracts);
    } catch (error) {
      console.error('Error fetching contracts:', error);
    }
  };

  // Fetch contract by ID
  const fetchContractById = async (contractId) => {
    try {
      const response = await axios.get(`${API_BASE_URL}/contracts/${contractId}`);
      setSelectedContract(response.data.metadata);
    } catch (error) {
      alert('Contract not found');
    }
  };

  return (
    <div>
      <h2>Upload Document</h2>
      <form onSubmit={handleUpload}>
        <input
          type="file"
          accept=".pdf"
          onChange={(e) => setFile(e.target.files[0])}
          required
        />
        <select
          value={documentType}
          onChange={(e) => setDocumentType(e.target.value)}
        >
          <option value="invoice">Invoice</option>
          <option value="contract">Contract</option>
        </select>
        <button type="submit" disabled={uploading}>
          {uploading ? 'Uploading...' : 'Upload'}
        </button>
      </form>

      <h2>Invoices</h2>
      <button onClick={fetchInvoices}>Refresh Invoices</button>
      <ul>
        {invoices.map((invoice) => (
          <li key={invoice.id}>
            {invoice.invoice_id} - {invoice.seller_name}
            <button onClick={() => fetchInvoiceById(invoice.invoice_id)}>
              View Details
            </button>
          </li>
        ))}
      </ul>
      {selectedInvoice && (
        <div>
          <h3>Invoice Details</h3>
          <pre>{JSON.stringify(selectedInvoice, null, 2)}</pre>
        </div>
      )}

      <h2>Contracts</h2>
      <button onClick={fetchContracts}>Refresh Contracts</button>
      <ul>
        {contracts.map((contract) => (
          <li key={contract.id}>
            {contract.contract_id} - {contract.summary}
            <button onClick={() => fetchContractById(contract.contract_id)}>
              View Details
            </button>
          </li>
        ))}
      </ul>
      {selectedContract && (
        <div>
          <h3>Contract Details</h3>
          <pre>{JSON.stringify(selectedContract, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

export default DocumentManager;
```

### Using TypeScript with React

```typescript
// types.ts
export interface Invoice {
  id: number;
  invoice_id: string;
  seller_name: string;
  seller_address: string;
  tax_id: string;
  subtotal_amount: number;
  tax_amount: number;
  summary: string;
  created_at: string;
  updated_at: string;
}

export interface Contract {
  id: number;
  contract_id: string;
  summary: string;
  text: string;
  created_at: string;
  updated_at: string;
}

export interface UploadResponse {
  success: boolean;
  message: string;
  metadata: Invoice | Contract;
}

// api.ts
import axios from 'axios';
import { Invoice, Contract, UploadResponse } from './types';

const API_BASE_URL = 'http://localhost:8001';

export const uploadDocument = async (
  file: File,
  documentType: 'invoice' | 'contract'
): Promise<UploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('document_type', documentType);

  const response = await axios.post<UploadResponse>(
    `${API_BASE_URL}/upload_document`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    }
  );

  return response.data;
};

export const getInvoices = async (
  limit: number = 100,
  offset: number = 0
): Promise<{ invoices: Invoice[]; total: number }> => {
  const response = await axios.get(`${API_BASE_URL}/invoices`, {
    params: { limit, offset },
  });
  return response.data;
};

export const getInvoiceById = async (invoiceId: string): Promise<Invoice> => {
  const response = await axios.get(`${API_BASE_URL}/invoices/${invoiceId}`);
  return response.data.metadata;
};

export const getContracts = async (
  limit: number = 100,
  offset: number = 0
): Promise<{ contracts: Contract[]; total: number }> => {
  const response = await axios.get(`${API_BASE_URL}/contracts`, {
    params: { limit, offset },
  });
  return response.data;
};

export const getContractById = async (contractId: string): Promise<Contract> => {
  const response = await axios.get(`${API_BASE_URL}/contracts/${contractId}`);
  return response.data.metadata;
};
```

## Future Enhancements

- Batch document upload
- Document similarity search using vectors
- Advanced filtering and search capabilities
- Authentication and authorization
- Webhook support for async processing

