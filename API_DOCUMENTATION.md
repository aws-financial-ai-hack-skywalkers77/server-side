# Tax Intelligence Platform - API Documentation for Frontend

**Base URL**: `http://localhost:8001` (or your deployed URL)

All endpoints return JSON responses. Error responses follow this format:
```json
{
  "detail": "Error message here"
}
```

---

## 🔍 WORKFLOW 1: Form Completeness Checker

### 1. Upload Tax Document
**Endpoint**: `POST /api/v1/workflow1/upload`

**Request**: `multipart/form-data`
- `file` (File, required): PDF file to upload
- `jurisdiction` (string, required): e.g., "US-NY", "US-CA"
- `form_code` (string, required): e.g., "IT-201", "1040"
- `tax_year` (integer, required): e.g., 2024
- `client_name` (string, optional): Client name
- `client_type` (string, optional, default: "individual"): "individual" or "business"

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Document uploaded successfully",
  "document_id": "DOC-4400BFA4",
  "extracted_data": {
    "form_type": "IT-201",
    "tax_year": 2024,
    "taxpayer_name": "John A. Smith",
    "taxpayer_ssn": "123-45-6789",
    "filing_status": "Single",
    "form_data": {},
    "line_items": [],
    "calculations": {},
    "schedules": []
  }
}
```

**Example cURL**:
```bash
curl -X POST "http://localhost:8001/api/v1/workflow1/upload" \
  -F "file=@form.pdf" \
  -F "jurisdiction=US-NY" \
  -F "form_code=IT-201" \
  -F "tax_year=2024" \
  -F "client_name=John Doe" \
  -F "client_type=individual"
```

---

### 2. Check Document Completeness
**Endpoint**: `POST /api/v1/workflow1/check/{document_id}`

**Request**: JSON body (optional)
```json
{
  "check_types": ["completeness", "calculations", "cross_reference", "jurisdiction_specific"]
}
```

**Query Parameters** (alternative to JSON body):
- `check_types` (array of strings, optional): Types of checks to run

**Response** (200 OK):
```json
{
  "document_id": "DOC-4400BFA4",
  "status": "issues_found",
  "total_issues": 3,
  "critical_issues": 1,
  "high_priority_issues": 1,
  "medium_priority_issues": 1,
  "low_priority_issues": 0,
  "issues": [
    {
      "id": 1,
      "check_type": "completeness",
      "status": "fail",
      "severity": "critical",
      "field_name": "taxpayer_name",
      "issue_description": "Taxpayer name is missing or invalid",
      "expected_value": "Valid name",
      "actual_value": "",
      "form_reference": "IT-201",
      "resolution_suggestion": "Provide a valid value for 'Taxpayer Name'",
      "is_resolved": false,
      "created_at": "2024-11-15T00:13:55"
    },
    {
      "id": 2,
      "check_type": "calculations",
      "status": "fail",
      "severity": "critical",
      "field_name": "total_income",
      "issue_description": "Calculation error in 'Total Income Calculation'",
      "expected_value": "50000.00",
      "actual_value": "45000.00",
      "form_reference": "IT-201 - Total Income Calculation",
      "resolution_suggestion": "Recalculate total_income. Expected: 50000.00, Found: 45000.00",
      "is_resolved": false,
      "created_at": "2024-11-15T00:13:55"
    }
  ]
}
```

**Example cURL**:
```bash
curl -X POST "http://localhost:8001/api/v1/workflow1/check/DOC-4400BFA4" \
  -H "Content-Type: application/json" \
  -d '{"check_types": ["completeness", "calculations", "cross_reference", "jurisdiction_specific"]}'
```

---

### 3. Get Document Issues
**Endpoint**: `GET /api/v1/workflow1/issues/{document_id}`

**Query Parameters**:
- `severity` (string, optional): Filter by severity ("critical", "high", "medium", "low")
- `resolved` (boolean, optional): Filter by resolved status (true/false)

**Response** (200 OK):
```json
{
  "document_id": "DOC-4400BFA4",
  "total_issues": 3,
  "issues": [
    {
      "id": 1,
      "check_type": "completeness",
      "status": "fail",
      "severity": "critical",
      "field_name": "taxpayer_name",
      "issue_description": "Taxpayer name is missing or invalid",
      "expected_value": "Valid name",
      "actual_value": "",
      "form_reference": "IT-201",
      "resolution_suggestion": "Provide a valid value for 'Taxpayer Name'",
      "is_resolved": false,
      "created_at": "2024-11-15T00:13:55"
    }
  ]
}
```

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow1/issues/DOC-4400BFA4?severity=critical&resolved=false"
```

---

### 4. Resolve Issue
**Endpoint**: `PATCH /api/v1/workflow1/resolve/{issue_id}`

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Issue marked as resolved"
}
```

**Example cURL**:
```bash
curl -X PATCH "http://localhost:8001/api/v1/workflow1/resolve/1"
```

---

## 🌍 WORKFLOW 2: Jurisdiction Comparison Engine

### 1. Create Jurisdiction Comparison
**Endpoint**: `POST /api/v1/workflow2/compare`

**Request**: JSON body
```json
{
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "scope": "individual_income",
  "tax_year": 2024,
  "requested_by": "user@example.com"
}
```

**Response** (200 OK):
```json
{
  "comparison_id": "COMP-E0FD44E6",
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "scope": "individual_income",
  "tax_year": 2024,
  "status": "completed",
  "summary": {
    "total_differences": 5,
    "critical_differences": 2,
    "high_priority_differences": 2,
    "medium_priority_differences": 1
  },
  "differences": [
    {
      "category": "tax_rates",
      "severity": "critical",
      "base_value": "Progressive: 4% - 10.9%",
      "target_value": "Progressive: 1% - 13.3%",
      "description": "NY has higher top marginal rate (10.9%) vs CA (13.3%)",
      "impact": "CA residents pay higher taxes on high income"
    },
    {
      "category": "deductions",
      "severity": "high",
      "base_value": "Standard deduction: $8,000",
      "target_value": "Standard deduction: $5,202",
      "description": "NY offers higher standard deduction",
      "impact": "NY residents can deduct more before calculating taxable income"
    }
  ],
  "created_at": "2024-11-15T00:13:55"
}
```

**Note**: The response structure may vary. When retrieved via GET endpoint, it returns:
```json
{
  "comparison": {
    "comparison_id": "COMP-E0FD44E6",
    "base_jurisdiction": "US-NY",
    "target_jurisdiction": "US-CA",
    "comparison_scope": "individual_income",
    "tax_year": 2024,
    "comparison_results": {
      "differences": []
    },
    "created_at": "2024-11-15T00:13:55"
  },
  "differences": []
}
```

**Example cURL**:
```bash
curl -X POST "http://localhost:8001/api/v1/workflow2/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "base_jurisdiction": "US-NY",
    "target_jurisdiction": "US-CA",
    "scope": "individual_income",
    "tax_year": 2024,
    "requested_by": "user@example.com"
  }'
```

---

### 2. Get Comparison
**Endpoint**: `GET /api/v1/workflow2/comparison/{comparison_id}`

**Response** (200 OK):
```json
{
  "comparison": {
    "id": 20,
    "comparison_id": "COMP-E0FD44E6",
    "base_jurisdiction": "US-NY",
    "target_jurisdiction": "US-CA",
    "comparison_scope": "individual_income",
    "tax_year": 2024,
    "requested_by": null,
    "comparison_results": {
      "differences": []
    },
    "created_at": "2024-11-15T00:13:55"
  },
  "differences": []
}
```

**Note**: The `differences` array may be empty if no differences are found. The `comparison_results` object contains the full comparison analysis.

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow2/comparison/COMP-E0FD44E6"
```

---

### 3. Research Specific Topic
**Endpoint**: `POST /api/v1/workflow2/research`

**Request**: JSON body
```json
{
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "topic": "capital gains tax rates",
  "tax_year": 2024
}
```

**Response** (200 OK):
```json
{
  "topic": "capital gains tax rates",
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "tax_year": 2024,
  "findings": [
    {
      "jurisdiction": "US-NY",
      "information": "NY treats capital gains as ordinary income, subject to state income tax rates (4% - 10.9%)",
      "source": "NY State Tax Law 2024"
    },
    {
      "jurisdiction": "US-CA",
      "information": "CA also treats capital gains as ordinary income, with rates from 1% - 13.3%",
      "source": "CA State Tax Law 2024"
    }
  ],
  "comparison": "Both jurisdictions treat capital gains as ordinary income, but CA has higher top rates"
}
```

**Example cURL**:
```bash
curl -X POST "http://localhost:8001/api/v1/workflow2/research" \
  -H "Content-Type: application/json" \
  -d '{
    "base_jurisdiction": "US-NY",
    "target_jurisdiction": "US-CA",
    "topic": "capital gains tax rates",
    "tax_year": 2024
  }'
```

---

## 📊 WORKFLOW 3: Multi-Jurisdiction Tax Planning

### 1. Create Planning Scenario
**Endpoint**: `POST /api/v1/workflow3/scenario`

**Request**: JSON body
```json
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
```

**Response** (200 OK):
```json
{
  "scenario_id": "PLAN-6F031A60",
  "client_id": "CLIENT-001",
  "client_name": "John Doe",
  "scenario_name": "Remote worker with EU rental income",
  "jurisdictions_involved": ["US-NY", "EU-DE"],
  "tax_year": 2024,
  "status": "completed",
  "analysis": {
    "summary": "Multi-jurisdiction tax analysis for remote worker with rental income",
    "estimated_total_exposure_min": 25000,
    "estimated_total_exposure_max": 35000,
    "high_priority_actions": 3,
    "treaty_analysis": [
      {
        "treaty": "US-Germany Tax Treaty",
        "relevance": "high",
        "key_provisions": "Prevents double taxation on employment income",
        "impact": "US-NY employment income may be exempt from German tax"
      }
    ],
    "tax_exposures": [
      {
        "jurisdiction": "US-NY",
        "exposure_type": "state_income_tax",
        "estimated_amount_min": 8000,
        "estimated_amount_max": 12000,
        "risk_level": "medium",
        "description": "NY state tax on employment income"
      },
      {
        "jurisdiction": "EU-DE",
        "exposure_type": "rental_income_tax",
        "estimated_amount_min": 5000,
        "estimated_amount_max": 8000,
        "risk_level": "low",
        "description": "German tax on rental income"
      }
    ],
    "planning_recommendations": [
      {
        "priority": "high",
        "category": "treaty_benefits",
        "recommendation": "Claim US-Germany treaty benefits to avoid double taxation",
        "estimated_savings": "5000-8000",
        "action_items": [
          "File Form 8833 with US return",
          "Obtain German tax residency certificate"
        ]
      },
      {
        "priority": "medium",
        "category": "deductions",
        "recommendation": "Maximize foreign tax credit for German rental income tax",
        "estimated_savings": "2000-3000",
        "action_items": [
          "Document all German tax payments",
          "Calculate foreign tax credit on Form 1116"
        ]
      }
    ],
    "compliance_timeline": [
      {
        "jurisdiction": "US-NY",
        "deadline": "2025-04-15",
        "form": "IT-201",
        "description": "NY State income tax return"
      },
      {
        "jurisdiction": "EU-DE",
        "deadline": "2025-05-31",
        "form": "ESt 1",
        "description": "German income tax return"
      }
    ]
  },
  "created_at": "2024-11-15T00:13:55"
}
```

**Example cURL**:
```bash
curl -X POST "http://localhost:8001/api/v1/workflow3/scenario" \
  -H "Content-Type: application/json" \
  -d '{
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
      }
    ],
    "objectives": ["minimize_tax", "avoid_double_taxation"],
    "tax_year": 2024
  }'
```

---

### 2. Get Planning Scenario
**Endpoint**: `GET /api/v1/workflow3/scenario/{scenario_id}`

**Response** (200 OK):
```json
{
  "scenario": {
    "id": 26,
    "scenario_id": "PLAN-6F031A60",
    "client_id": "CLIENT-001",
    "scenario_name": "Remote worker with EU rental income",
    "jurisdictions_involved": ["US-NY", "EU-DE"],
    "tax_year": 2024,
    "scenario_description": "[{\"type\": \"employment\", \"jurisdiction\": \"US-NY\", ...}]",
    "objectives": ["minimize_tax", "avoid_double_taxation"],
    "constraints": null,
    "analysis_results": {
      "tax_exposures": [],
      "recommendations": [],
      "treaty_analysis": [],
      "compliance_timeline": [],
      "reporting_requirements": []
    },
    "created_at": "2024-11-15T00:13:55"
  },
  "exposures": [],
  "recommendations": []
}
```

**Note**: 
- The `analysis_results` object contains the full analysis nested inside the scenario
- The `exposures` and `recommendations` arrays at the root level are populated from the database tables
- Arrays may be empty if no exposures/recommendations were generated
- The `scenario_description` field contains a JSON string of income sources

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow3/scenario/PLAN-6F031A60"
```

---

### 3. Get Recommendations
**Endpoint**: `GET /api/v1/workflow3/recommendations/{scenario_id}`

**Query Parameters**:
- `priority` (string, optional): Filter by priority ("high", "medium", "low")

**Response** (200 OK):
```json
{
  "scenario_id": "PLAN-6F031A60",
  "total_recommendations": 3,
  "recommendations": [
    {
      "id": 1,
      "priority": "high",
      "category": "treaty_benefits",
      "recommendation": "Claim US-Germany treaty benefits to avoid double taxation",
      "estimated_savings": "5000-8000",
      "action_items": [
        "File Form 8833 with US return",
        "Obtain German tax residency certificate"
      ]
    }
  ]
}
```

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow3/recommendations/PLAN-6F031A60?priority=high"
```

---

## 🔍 UTILITY ENDPOINTS

### 1. List Jurisdictions
**Endpoint**: `GET /api/search/jurisdictions`

**Response** (200 OK):
```json
{
  "jurisdictions": [
    {
      "jurisdiction": "US-NY",
      "display_name": "New York State",
      "country": "United States"
    },
    {
      "jurisdiction": "US-CA",
      "display_name": "California",
      "country": "United States"
    },
    {
      "jurisdiction": "EU-DE",
      "display_name": "Germany",
      "country": "Germany"
    }
  ]
}
```

---

### 2. List Law Categories
**Endpoint**: `GET /api/search/categories`

**Query Parameters**:
- `jurisdiction` (string, optional): Filter by jurisdiction

**Response** (200 OK):
```json
{
  "categories": [
    {
      "law_category": "income_tax",
      "count": 150
    },
    {
      "law_category": "tax_treaty",
      "count": 25
    }
  ]
}
```

---

## ⚠️ ERROR RESPONSES

All endpoints may return these error responses:

**400 Bad Request**:
```json
{
  "detail": "Invalid JSON in calculation_rules: Expecting value: line 1 column 1 (char 0)"
}
```

**404 Not Found**:
```json
{
  "detail": "Form template not found"
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Error message here"
}
```

---

## 📝 NOTES FOR FRONTEND

1. **File Uploads**: Use `multipart/form-data` for file uploads (Workflow 1 upload endpoint)

2. **Async Operations**: Some endpoints (especially Workflow 1 check and Workflow 3 scenario creation) may take 10-30 seconds. Show loading indicators.

3. **Error Handling**: Always check for `detail` field in responses for error messages.

4. **Document IDs**: Document IDs are in format `DOC-XXXXXXXX` (8 hex characters)

5. **Comparison IDs**: Comparison IDs are in format `COMP-XXXXXXXX`

6. **Scenario IDs**: Scenario IDs are in format `PLAN-XXXXXXXX`

7. **Severity Levels**: Use these for styling:
   - `critical`: Red
   - `high`: Orange
   - `medium`: Yellow
   - `low`: Blue

8. **Status Values**:
   - `uploaded`: Document uploaded, not yet checked
   - `issues_found`: Check completed, issues found
   - `no_issues`: Check completed, no issues
   - `completed`: Analysis/scenario completed
   - `pending`: Analysis in progress

---

## 🚀 QUICK START EXAMPLES

### Complete Workflow 1 Flow:
```javascript
// 1. Upload document
const uploadResponse = await fetch('http://localhost:8001/api/v1/workflow1/upload', {
  method: 'POST',
  body: formData // FormData with file and metadata
});
const { document_id } = await uploadResponse.json();

// 2. Check completeness
const checkResponse = await fetch(`http://localhost:8001/api/v1/workflow1/check/${document_id}`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    check_types: ['completeness', 'calculations', 'cross_reference', 'jurisdiction_specific']
  })
});
const checkResult = await checkResponse.json();

// 3. Get issues
const issuesResponse = await fetch(`http://localhost:8001/api/v1/workflow1/issues/${document_id}`);
const issues = await issuesResponse.json();
```

### Complete Workflow 2 Flow:
```javascript
// Create comparison
const compareResponse = await fetch('http://localhost:8001/api/v1/workflow2/compare', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    base_jurisdiction: 'US-NY',
    target_jurisdiction: 'US-CA',
    scope: 'individual_income',
    tax_year: 2024
  })
});
const comparison = await compareResponse.json();
```

### Complete Workflow 3 Flow:
```javascript
// Create scenario
const scenarioResponse = await fetch('http://localhost:8001/api/v1/workflow3/scenario', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    client_id: 'CLIENT-001',
    client_name: 'John Doe',
    scenario_name: 'Multi-jurisdiction planning',
    jurisdictions_involved: ['US-NY', 'EU-DE'],
    income_sources: [
      {
        type: 'employment',
        jurisdiction: 'US-NY',
        amount_range: '100000-150000',
        description: 'Salary'
      }
    ],
    objectives: ['minimize_tax', 'compliance'],
    tax_year: 2024
  })
});
const scenario = await scenarioResponse.json();
```

---

**Last Updated**: November 15, 2024
**API Version**: 1.0.0

