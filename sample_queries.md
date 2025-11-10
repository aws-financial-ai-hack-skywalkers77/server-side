# Sample Queries for Invoice GET Endpoints

This document provides sample queries for testing the invoice retrieval endpoints.

## Base URL
```
http://localhost:8001
```

---

## 1. Get All Invoices

### Basic Request (Default: 100 invoices, offset 0)
```bash
curl http://localhost:8001/invoices
```

### With Pagination
```bash
# Get first 10 invoices
curl "http://localhost:8001/invoices?limit=10&offset=0"

# Get next 10 invoices
curl "http://localhost:8001/invoices?limit=10&offset=10"

# Get 50 invoices starting from offset 20
curl "http://localhost:8001/invoices?limit=50&offset=20"
```

### Using Python requests
```python
import requests

# Basic request
response = requests.get("http://localhost:8001/invoices")
print(response.json())

# With pagination
response = requests.get(
    "http://localhost:8001/invoices",
    params={"limit": 10, "offset": 0}
)
data = response.json()
print(f"Total invoices: {data['total']}")
print(f"Returned: {data['count']}")
for invoice in data['invoices']:
    print(f"Invoice ID: {invoice['invoice_id']}, Seller: {invoice['seller_name']}")
```

### Using JavaScript (fetch)
```javascript
// Basic request
fetch('http://localhost:8001/invoices')
  .then(response => response.json())
  .then(data => {
    console.log(`Total invoices: ${data.total}`);
    console.log(data.invoices);
  });

// With pagination
fetch('http://localhost:8001/invoices?limit=10&offset=0')
  .then(response => response.json())
  .then(data => {
    console.log(data);
  });
```

---

## 2. Get Invoice by invoice_id

### Basic Request
```bash
# Replace 'INV-12345' with an actual invoice_id from your database
curl http://localhost:8001/invoices/INV-12345
```

### Example with a real invoice ID
```bash
# If you have an invoice with ID "INV-2024-001"
curl http://localhost:8001/invoices/INV-2024-001
```

### Using Python requests
```python
import requests

invoice_id = "INV-12345"  # Replace with actual invoice_id
response = requests.get(f"http://localhost:8001/invoices/{invoice_id}")

if response.status_code == 200:
    data = response.json()
    invoice = data['metadata']
    print(f"Invoice ID: {invoice['invoice_id']}")
    print(f"Seller: {invoice['seller_name']}")
    print(f"Subtotal: ${invoice['subtotal_amount']}")
    print(f"Tax: ${invoice['tax_amount']}")
elif response.status_code == 404:
    print("Invoice not found")
else:
    print(f"Error: {response.status_code}")
```

### Using JavaScript (fetch)
```javascript
const invoiceId = 'INV-12345'; // Replace with actual invoice_id

fetch(`http://localhost:8001/invoices/${invoiceId}`)
  .then(response => {
    if (response.ok) {
      return response.json();
    } else if (response.status === 404) {
      throw new Error('Invoice not found');
    } else {
      throw new Error(`Error: ${response.status}`);
    }
  })
  .then(data => {
    const invoice = data.metadata;
    console.log(`Invoice ID: ${invoice.invoice_id}`);
    console.log(`Seller: ${invoice.seller_name}`);
    console.log(`Subtotal: $${invoice.subtotal_amount}`);
  })
  .catch(error => console.error(error));
```

---

## 3. Error Handling Examples

### Invoice Not Found (404)
```bash
curl http://localhost:8001/invoices/NONEXISTENT-ID
```

**Response:**
```json
{
  "detail": "Invoice with invoice_id 'NONEXISTENT-ID' not found"
}
```

### Invalid Pagination Parameters
```bash
# Invalid limit (must be 1-1000)
curl "http://localhost:8001/invoices?limit=0"
curl "http://localhost:8001/invoices?limit=2000"

# Invalid offset (must be >= 0)
curl "http://localhost:8001/invoices?offset=-1"
```

---

## 4. Complete Python Example

```python
import requests
import json

BASE_URL = "http://localhost:8001"

def get_all_invoices(limit=100, offset=0):
    """Get all invoices with pagination"""
    url = f"{BASE_URL}/invoices"
    params = {"limit": limit, "offset": offset}
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def get_invoice_by_id(invoice_id):
    """Get a specific invoice by invoice_id"""
    url = f"{BASE_URL}/invoices/{invoice_id}"
    
    response = requests.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()

# Example usage
if __name__ == "__main__":
    # Get all invoices
    print("Fetching all invoices...")
    all_invoices = get_all_invoices(limit=10)
    print(f"Total invoices: {all_invoices['total']}")
    print(f"Returned: {all_invoices['count']}\n")
    
    # Display first few invoices
    for invoice in all_invoices['invoices'][:3]:
        print(f"Invoice ID: {invoice['invoice_id']}")
        print(f"  Seller: {invoice['seller_name']}")
        print(f"  Amount: ${invoice['subtotal_amount']}")
        print()
    
    # Get a specific invoice (use an actual invoice_id from above)
    if all_invoices['invoices']:
        first_invoice_id = all_invoices['invoices'][0]['invoice_id']
        print(f"\nFetching invoice: {first_invoice_id}")
        invoice = get_invoice_by_id(first_invoice_id)
        if invoice:
            print(json.dumps(invoice, indent=2))
```

---

## 5. Using FastAPI Interactive Docs

You can also test the endpoints using FastAPI's built-in interactive documentation:

1. Start your server:
   ```bash
   python main.py
   ```

2. Open your browser and go to:
   ```
   http://localhost:8001/docs
   ```

3. You'll see an interactive Swagger UI where you can:
   - See all available endpoints
   - Test endpoints directly in the browser
   - See request/response schemas
   - Try different parameters

---

## 6. Response Format Examples

### GET /invoices Response
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
      "invoice_id": "INV-2024-001",
      "seller_name": "Acme Corporation",
      "seller_address": "123 Business St, City, State 12345",
      "tax_id": "TAX-123456789",
      "subtotal_amount": 1500.00,
      "tax_amount": 150.00,
      "summary": "Monthly services invoice",
      "created_at": "2024-11-10T10:30:00",
      "updated_at": "2024-11-10T10:30:00"
    },
    {
      "id": 2,
      "invoice_id": "INV-2024-002",
      "seller_name": "Tech Solutions Inc",
      "seller_address": "456 Tech Ave, City, State 67890",
      "tax_id": "TAX-987654321",
      "subtotal_amount": 2500.00,
      "tax_amount": 250.00,
      "summary": "Software license invoice",
      "created_at": "2024-11-10T11:00:00",
      "updated_at": "2024-11-10T11:00:00"
    }
  ]
}
```

### GET /invoices/{invoice_id} Response
```json
{
  "success": true,
  "metadata": {
    "id": 1,
    "invoice_id": "INV-2024-001",
    "seller_name": "Acme Corporation",
    "seller_address": "123 Business St, City, State 12345",
    "tax_id": "TAX-123456789",
    "subtotal_amount": 1500.00,
    "tax_amount": 150.00,
    "summary": "Monthly services invoice",
    "created_at": "2024-11-10T10:30:00",
    "updated_at": "2024-11-10T10:30:00"
  }
}
```

---

## 7. Quick Test Script

Save this as `test_get_endpoints.py`:

```python
#!/usr/bin/env python3
"""Quick test script for GET endpoints"""
import requests
import sys

BASE_URL = "http://localhost:8001"

def test_get_all_invoices():
    print("Testing GET /invoices...")
    try:
        response = requests.get(f"{BASE_URL}/invoices", params={"limit": 5})
        response.raise_for_status()
        data = response.json()
        print(f"✅ Success! Found {data['total']} total invoices")
        print(f"   Returned {data['count']} invoices\n")
        return data['invoices']
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

def test_get_invoice_by_id(invoice_id):
    print(f"Testing GET /invoices/{invoice_id}...")
    try:
        response = requests.get(f"{BASE_URL}/invoices/{invoice_id}")
        if response.status_code == 404:
            print(f"❌ Invoice '{invoice_id}' not found\n")
            return None
        response.raise_for_status()
        data = response.json()
        print(f"✅ Success! Found invoice:")
        print(f"   Invoice ID: {data['metadata']['invoice_id']}")
        print(f"   Seller: {data['metadata']['seller_name']}")
        print(f"   Amount: ${data['metadata']['subtotal_amount']}\n")
        return data['metadata']
    except Exception as e:
        print(f"❌ Error: {e}\n")
        return None

if __name__ == "__main__":
    print("=" * 50)
    print("Testing Invoice GET Endpoints")
    print("=" * 50)
    print()
    
    # Test getting all invoices
    invoices = test_get_all_invoices()
    
    # Test getting a specific invoice if we have any
    if invoices:
        first_invoice_id = invoices[0]['invoice_id']
        test_get_invoice_by_id(first_invoice_id)
    
    # Test with non-existent invoice
    test_get_invoice_by_id("NONEXISTENT-123")
    
    print("=" * 50)
    print("Tests complete!")
    print("=" * 50)
```

Run it with:
```bash
python test_get_endpoints.py
```

