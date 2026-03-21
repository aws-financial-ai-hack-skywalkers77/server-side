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

