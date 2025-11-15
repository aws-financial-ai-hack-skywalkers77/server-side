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

**Purpose**: Helps tax professionals (CAs) understand differences between two tax jurisdictions. Perfect for CAs who know one jurisdiction and need to learn another quickly.

---

### 1. Create Jurisdiction Comparison
**Endpoint**: `POST /api/v1/workflow2/compare`

**Description**: Compares tax rules between two jurisdictions using AI-powered analysis. Extracts relevant laws from the knowledge base and identifies key differences.

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

**Request Parameters**:
- `base_jurisdiction` (string, required): The jurisdiction the CA already knows (e.g., "US-NY", "US-CA", "US-FED")
- `target_jurisdiction` (string, required): The jurisdiction the CA wants to learn (e.g., "US-CA", "US-NY", "EU-DE")
- `scope` (string, optional, default: "individual_income"): Type of tax to compare. Options: "individual_income", "corporate", "vat"
- `tax_year` (integer, optional, default: current year): Which year's tax laws to compare (e.g., 2024)
- `requested_by` (string, optional): User identifier (email, username, etc.)

**Response** (200 OK):
```json
{
  "comparison_id": "COMP-E0FD44E6",
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "scope": "individual_income",
  "tax_year": 2024,
  "created_at": "2024-11-15T00:13:55",
  "total_differences": 5,
  "critical_differences": 2,
  "important_differences": 2,
  "informational_differences": 1,
  "differences": [
    {
      "difference_type": "tax_rate",
      "category": "rates",
      "base_rule": "NY has progressive rates from 4% to 10.9%",
      "target_rule": "CA has progressive rates from 1% to 13.3%",
      "impact_level": "critical",
      "explanation": "CA has higher top marginal rate (13.3%) vs NY (10.9%), affecting high-income taxpayers",
      "examples": [
        "A taxpayer earning $200,000 would pay 10.9% in NY vs 13.3% in CA on income above $1M"
      ],
      "base_law_ids": [123, 124, 125],
      "target_law_ids": [456, 457, 458]
    },
    {
      "difference_type": "deduction",
      "category": "deductions",
      "base_rule": "NY standard deduction is $8,000 for single filers",
      "target_rule": "CA standard deduction is $5,202 for single filers",
      "impact_level": "important",
      "explanation": "NY offers higher standard deduction, reducing taxable income more",
      "examples": [
        "Single filer in NY can deduct $2,798 more than in CA"
      ],
      "base_law_ids": [126],
      "target_law_ids": [459]
    },
    {
      "difference_type": "filing_deadline",
      "category": "filing",
      "base_rule": "NY filing deadline is April 15",
      "target_rule": "CA filing deadline is April 15 (same as federal)",
      "impact_level": "informational",
      "explanation": "Both jurisdictions use the same filing deadline",
      "examples": [],
      "base_law_ids": [127],
      "target_law_ids": [460]
    }
  ],
  "learning_checklist": [
    {
      "category": "rates",
      "priority": "high",
      "title": "Master rates differences (CRITICAL)",
      "item_count": 2,
      "items": [
        "Understand CA's higher top marginal rate",
        "Learn CA's rate brackets"
      ]
    },
    {
      "category": "deductions",
      "priority": "medium",
      "title": "Learn deduction differences",
      "item_count": 1,
      "items": [
        "CA has lower standard deduction than NY"
      ]
    }
  ]
}
```

**Response Fields**:
- `comparison_id`: Unique identifier (format: `COMP-XXXXXXXX`)
- `total_differences`: Total number of differences found
- `critical_differences`: Count of critical differences
- `important_differences`: Count of important differences
- `informational_differences`: Count of informational differences
- `differences`: Array of difference objects, each containing:
  - `difference_type`: Type of difference (tax_rate, deduction, filing_deadline, etc.)
  - `category`: High-level category (rates, deductions, filing)
  - `base_rule`: How it works in the base jurisdiction
  - `target_rule`: How it works in the target jurisdiction
  - `impact_level`: "critical", "important", or "informational"
  - `explanation`: Why the difference matters
  - `examples`: Array of practical examples
  - `base_law_ids`: IDs of source laws from base jurisdiction
  - `target_law_ids`: IDs of source laws from target jurisdiction
- `learning_checklist`: Organized checklist to help CAs learn the target jurisdiction

**Processing Time**: 20-30 seconds (LLM processing)

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

**Example JavaScript**:
```javascript
const response = await fetch('http://localhost:8001/api/v1/workflow2/compare', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    base_jurisdiction: 'US-NY',
    target_jurisdiction: 'US-CA',
    scope: 'individual_income',
    tax_year: 2024,
    requested_by: 'user@example.com'
  })
});
const comparison = await response.json();
console.log(`Found ${comparison.total_differences} differences`);
```

**Error Responses**:
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: No tax laws found for specified jurisdictions
- `500 Internal Server Error`: Database or LLM error

---

### 2. Get Comparison
**Endpoint**: `GET /api/v1/workflow2/comparison/{comparison_id}`

**Description**: Retrieves a previously created comparison by its ID.

**Path Parameters**:
- `comparison_id` (string, required): The comparison ID (format: `COMP-XXXXXXXX`)

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
    "requested_by": "user@example.com",
    "comparison_results": {
      "differences": []
    },
    "created_at": "2024-11-15T00:13:55"
  },
  "differences": [
    {
      "id": 1,
      "comparison_id": "COMP-E0FD44E6",
      "difference_type": "tax_rate",
      "category": "rates",
      "base_rule": "NY has progressive rates from 4% to 10.9%",
      "target_rule": "CA has progressive rates from 1% to 13.3%",
      "impact_level": "critical",
      "explanation": "CA has higher top marginal rate",
      "examples": ["..."],
      "created_at": "2024-11-15T00:13:55"
    }
  ]
}
```

**Note**: The `differences` array may be empty if no differences were found. The `comparison_results` object contains the full comparison analysis stored in the database.

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow2/comparison/COMP-E0FD44E6"
```

**Example JavaScript**:
```javascript
const response = await fetch('http://localhost:8001/api/v1/workflow2/comparison/COMP-E0FD44E6');
const data = await response.json();
console.log(`Comparison: ${data.comparison.base_jurisdiction} vs ${data.comparison.target_jurisdiction}`);
console.log(`Differences: ${data.differences.length}`);
```

**Error Responses**:
- `404 Not Found`: Comparison ID not found

---

### 3. Research Specific Topic
**Endpoint**: `POST /api/v1/workflow2/research`

**Description**: Deep dive research on a specific tax topic across two jurisdictions. More focused than a full comparison.

**Request**: JSON body
```json
{
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "topic": "capital gains tax rates",
  "tax_year": 2024
}
```

**Request Parameters**:
- `base_jurisdiction` (string, required): The jurisdiction the CA knows
- `target_jurisdiction` (string, required): The jurisdiction to research
- `topic` (string, required): Specific topic to research (e.g., "capital gains tax rates", "standard deduction", "filing deadlines")
- `tax_year` (integer, optional, default: current year): Which year's laws to research

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
      "source": "NY State Tax Law 2024",
      "section_reference": "Section 601"
    },
    {
      "jurisdiction": "US-CA",
      "information": "CA also treats capital gains as ordinary income, with rates from 1% - 13.3%",
      "source": "CA State Tax Law 2024",
      "section_reference": "Section 17041"
    }
  ],
  "comparison": "Both jurisdictions treat capital gains as ordinary income, but CA has higher top rates (13.3% vs 10.9%)",
  "key_differences": [
    "CA's top rate is 2.4 percentage points higher than NY's",
    "Both use progressive rate structures"
  ],
  "practical_implications": "High-income taxpayers in CA will pay more on capital gains than in NY"
}
```

**Processing Time**: 15-25 seconds (LLM processing)

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

**Example JavaScript**:
```javascript
const response = await fetch('http://localhost:8001/api/v1/workflow2/research', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    base_jurisdiction: 'US-NY',
    target_jurisdiction: 'US-CA',
    topic: 'capital gains tax rates',
    tax_year: 2024
  })
});
const research = await response.json();
console.log(`Topic: ${research.topic}`);
console.log(`Findings: ${research.findings.length} jurisdictions`);
```

**Error Responses**:
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: No information found for the topic
- `500 Internal Server Error`: Database or LLM error

---

## 📊 WORKFLOW 3: Multi-Jurisdiction Tax Planning

### 1. Create Planning Scenario
**Endpoint**: `POST /api/v1/workflow3/scenario`

**Description**: Creates a comprehensive multi-jurisdiction tax planning scenario that analyzes tax treaties, calculates tax exposures, generates optimization recommendations, identifies reporting requirements, and creates a compliance timeline.

**Request**: JSON body

**Request Parameters**:
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `client_id` | string | Yes | - | Unique identifier for the client (e.g., "CLIENT-001") |
| `client_name` | string | Yes | - | Full name of the client |
| `scenario_name` | string | Yes | - | Description of the planning scenario |
| `jurisdictions_involved` | array[string] | Yes | - | List of jurisdictions where client has income/operations (e.g., ["US-NY", "EU-DE", "IN-MH"]) |
| `income_sources` | array[object] | Yes | - | Array of income source objects (see structure below) |
| `objectives` | array[string] | Yes | - | Client's optimization objectives (e.g., ["minimize_tax", "avoid_double_taxation", "compliance"]) |
| `tax_year` | integer | No | Current year | Tax year for planning (e.g., 2024) |

**Income Source Object Structure**:
```json
{
  "type": "employment",              // Type: employment, rental_income, business_income, investment, freelance, pension
  "jurisdiction": "US-NY",           // Where this income is earned
  "amount_range": "100000-150000",   // Estimated income range (string format)
  "description": "Tech company salary"  // Brief description
}
```

**Request Example**:
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
      "description": "Berlin apartment rental"
    }
  ],
  "objectives": ["minimize_tax", "avoid_double_taxation", "compliance"],
  "tax_year": 2024
}
```

**Response** (200 OK):
```json
{
  "scenario_id": "PLAN-03B05F76",
  "client_name": "John Doe",
  "scenario_name": "Remote worker with EU rental income",
  "jurisdictions": ["US-NY", "EU-DE"],
  "tax_year": 2024,
  "created_at": "2025-11-15T03:38:36.476069",
  "treaty_benefits_available": 1,
  "total_jurisdictions_with_exposure": 2,
  "high_priority_actions": 2,
  "estimated_total_exposure_min": 28300,
  "estimated_total_exposure_max": 43780,
  "analysis": {
    "treaties": [
      {
        "countries": ["US-NY", "EU-DE"],
        "treaty_exists": false,
        "implication": "No tax treaty - potential double taxation risk"
      }
    ],
    "exposures": [
      {
        "jurisdiction": "US-NY",
        "exposure_type": "primary_income",
        "risk_level": "medium",
        "estimated_impact_min": 23100,
        "estimated_impact_max": 31300,
        "primary_concerns": [
          "Significant combined tax burden from Federal, NY State, and NYC taxes",
          "Worldwide income taxation on all income sources"
        ],
        "mitigation_strategies": [
          "Utilize Foreign Tax Credit (FTC) for foreign taxes paid",
          "Optimize payroll withholding and pre-tax deductions"
        ]
      },
      {
        "jurisdiction": "EU-DE",
        "exposure_type": "double_taxation",
        "risk_level": "high",
        "estimated_impact_min": 5200,
        "estimated_impact_max": 12480,
        "primary_concerns": [
          "Double taxation of rental income by both jurisdictions",
          "High Tax Deducted at Source (TDS) requirements"
        ],
        "mitigation_strategies": [
          "Claim foreign tax credit in US return",
          "Apply for lower TDS certificate in foreign jurisdiction"
        ]
      }
    ],
    "reporting": [],
    "recommendations": [
      {
        "priority": "critical",
        "recommendation_type": "reporting",
        "title": "Claim US Foreign Tax Credit (FTC) for Foreign Taxes",
        "description": "As a US tax resident, claim Foreign Tax Credit on US federal return for income taxes paid to foreign country. This credit directly offsets US tax liability on foreign-source income.",
        "expected_benefit": "Direct reduction of US federal income tax liability, effectively eliminating or significantly reducing double taxation",
        "implementation_steps": [
          "Maintain meticulous records of all foreign rental income and taxes paid",
          "Calculate US taxable income from foreign sources",
          "Complete and file Form 1116 with annual US Federal income tax return",
          "Consult with tax professional specializing in international taxation"
        ],
        "risks_and_considerations": [
          "Incorrect calculation can lead to IRS audit and penalties",
          "FTC is limited to US tax on foreign source income",
          "Proper documentation is crucial for substantiating the credit claim"
        ],
        "timeline": "Annually, when preparing US Federal income tax returns (generally by April 15th)"
      },
      {
        "priority": "high",
        "recommendation_type": "timing",
        "title": "Schedule US Quarterly Estimated Tax Payments",
        "description": "Make quarterly estimated tax payments to IRS and potentially to NY State/NYC to cover US tax liability on foreign rental income and any potential shortfall from employment income withholding.",
        "expected_benefit": "Avoidance of costly underpayment penalties and improved cash flow management",
        "implementation_steps": [
          "Estimate total US federal, NY State, and NYC tax liability for the year",
          "Subtract expected withholding from US employment income",
          "Calculate remaining tax liability to be paid via estimated taxes",
          "Divide into four equal quarterly payments",
          "Make timely payments using Form 1040-ES"
        ],
        "timeline": "Immediately for current tax year, with payments due quarterly"
      }
    ],
    "timeline": []
  }
}
```

**Response Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `scenario_id` | string | Unique scenario identifier (format: `PLAN-XXXXXXXX`) |
| `client_name` | string | Client's full name |
| `scenario_name` | string | Description of the scenario |
| `jurisdictions` | array[string] | List of jurisdictions involved |
| `tax_year` | integer | Tax year for planning |
| `created_at` | string | ISO timestamp of scenario creation |
| `treaty_benefits_available` | integer | Number of applicable tax treaties found |
| `total_jurisdictions_with_exposure` | integer | Number of jurisdictions with calculated tax exposure |
| `high_priority_actions` | integer | Number of critical/high priority recommendations |
| `estimated_total_exposure_min` | number | Minimum estimated total tax exposure across all jurisdictions |
| `estimated_total_exposure_max` | number | Maximum estimated total tax exposure across all jurisdictions |
| `analysis.treaties` | array[object] | Tax treaty analysis results (see structure below) |
| `analysis.exposures` | array[object] | Tax exposure calculations per jurisdiction (see structure below) |
| `analysis.reporting` | array[object] | Reporting requirements (may be empty if no data found) |
| `analysis.recommendations` | array[object] | Optimization recommendations (see structure below) |
| `analysis.timeline` | array[object] | Compliance timeline with deadlines (may be empty if no data found) |

**Treaty Analysis Object**:
```json
{
  "countries": ["US-NY", "EU-DE"],           // Jurisdiction pair
  "treaty_exists": false,                    // Whether a tax treaty exists
  "treaty_name": "US-Germany Tax Treaty",    // Name of treaty (if exists)
  "effective_date": "1989-01-01",            // Treaty effective date (if exists)
  "key_provisions": "...",                    // Key treaty provisions (if exists)
  "benefits": ["Reduced withholding rates"],  // List of treaty benefits (if exists)
  "implication": "No tax treaty - potential double taxation risk"  // Implication for client
}
```

**Tax Exposure Object**:
```json
{
  "jurisdiction": "US-NY",                    // Jurisdiction code
  "exposure_type": "primary_income",          // Type: primary_income, foreign_income, double_taxation
  "risk_level": "medium",                     // Risk level: high, medium, low
  "estimated_impact_min": 23100,              // Minimum estimated tax impact
  "estimated_impact_max": 31300,               // Maximum estimated tax impact
  "primary_concerns": [                       // Array of primary tax concerns
    "Significant combined tax burden...",
    "Worldwide income taxation..."
  ],
  "mitigation_strategies": [                  // Array of mitigation strategies
    "Utilize Foreign Tax Credit (FTC)...",
    "Optimize payroll withholding..."
  ]
}
```

**Recommendation Object**:
```json
{
  "priority": "critical",                     // Priority: critical, high, medium
  "recommendation_type": "reporting",         // Type: structure, timing, documentation, treaty_benefit, reporting, compliance
  "title": "Claim US Foreign Tax Credit...",  // Short title
  "description": "Detailed explanation...",   // Full description
  "expected_benefit": "Direct reduction...",  // What client gains
  "implementation_steps": [                   // Array of actionable steps
    "Maintain meticulous records...",
    "Calculate US taxable income..."
  ],
  "risks_and_considerations": [               // Array of risks/considerations
    "Incorrect calculation can lead to audit...",
    "FTC is limited to US tax on foreign source income"
  ],
  "timeline": "Annually, when preparing..."   // When to implement
}
```

**Notes**:
- Processing time: 30-60 seconds (multiple LLM calls and database queries)
- The `analysis.reporting` and `analysis.timeline` arrays may be empty if no relevant data is found in ingested tax laws
- All monetary values are in the currency of the respective jurisdiction
- Recommendations are prioritized: `critical` > `high` > `medium`

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
      },
      {
        "type": "rental_income",
        "jurisdiction": "EU-DE",
        "amount_range": "30000-40000",
        "description": "Berlin apartment rental"
      }
    ],
    "objectives": ["minimize_tax", "avoid_double_taxation", "compliance"],
    "tax_year": 2024
  }'
```

**Example JavaScript**:
```javascript
const response = await fetch('http://localhost:8001/api/v1/workflow3/scenario', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    client_id: 'CLIENT-001',
    client_name: 'John Doe',
    scenario_name: 'Remote worker with EU rental income',
    jurisdictions_involved: ['US-NY', 'EU-DE'],
    income_sources: [
      {
        type: 'employment',
        jurisdiction: 'US-NY',
        amount_range: '100000-150000',
        description: 'Tech company salary'
      },
      {
        type: 'rental_income',
        jurisdiction: 'EU-DE',
        amount_range: '30000-40000',
        description: 'Berlin apartment rental'
      }
    ],
    objectives: ['minimize_tax', 'avoid_double_taxation', 'compliance'],
    tax_year: 2024
  })
});
const scenario = await response.json();
console.log(`Scenario ID: ${scenario.scenario_id}`);
console.log(`Total exposures: ${scenario.total_jurisdictions_with_exposure}`);
console.log(`Recommendations: ${scenario.analysis.recommendations.length}`);
```

**Error Responses**:
- `400 Bad Request`: Invalid request parameters (missing required fields, invalid income source structure)
- `500 Internal Server Error`: Database error, LLM error, or connection timeout

---

### 2. Get Planning Scenario
**Endpoint**: `GET /api/v1/workflow3/scenario/{scenario_id}`

**Description**: Retrieves a previously created planning scenario with all stored analysis results, exposures, and recommendations from the database.

**Path Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scenario_id` | string | Yes | The scenario ID returned from the create endpoint (format: `PLAN-XXXXXXXX`) |

**Response** (200 OK):
```json
{
  "scenario": {
    "id": 26,
    "scenario_id": "PLAN-03B05F76",
    "client_id": "CLIENT-001",
    "scenario_name": "Remote worker with EU rental income",
    "jurisdictions_involved": ["US-NY", "EU-DE"],
    "tax_year": 2024,
    "scenario_description": "[{\"type\": \"employment\", \"jurisdiction\": \"US-NY\", \"amount_range\": \"100000-150000\", \"description\": \"Tech company salary\"}]",
    "objectives": ["minimize_tax", "avoid_double_taxation", "compliance"],
    "constraints": null,
    "analysis_results": {
      "tax_exposures": [],
      "recommendations": [],
      "treaty_analysis": [],
      "compliance_timeline": [],
      "reporting_requirements": []
    },
    "created_at": "2025-11-15T03:38:36.476069"
  },
  "exposures": [
    {
      "id": 1,
      "scenario_id": "PLAN-03B05F76",
      "jurisdiction": "US-NY",
      "exposure_type": "primary_income",
      "risk_level": "medium",
      "estimated_impact_min": 23100,
      "estimated_impact_max": 31300,
      "mitigation_strategies": ["Utilize Foreign Tax Credit...", "Optimize payroll withholding..."]
    },
    {
      "id": 2,
      "scenario_id": "PLAN-03B05F76",
      "jurisdiction": "EU-DE",
      "exposure_type": "double_taxation",
      "risk_level": "high",
      "estimated_impact_min": 5200,
      "estimated_impact_max": 12480,
      "mitigation_strategies": ["Claim foreign tax credit...", "Apply for lower TDS certificate..."]
    }
  ],
  "recommendations": [
    {
      "id": 1,
      "scenario_id": "PLAN-03B05F76",
      "recommendation_type": "reporting",
      "priority": "critical",
      "title": "Claim US Foreign Tax Credit (FTC) for Foreign Taxes",
      "description": "As a US tax resident, claim Foreign Tax Credit...",
      "expected_benefit": "Direct reduction of US federal income tax liability...",
      "implementation_steps": ["Maintain meticulous records...", "Calculate US taxable income..."],
      "risks_and_considerations": ["Incorrect calculation can lead to audit...", "FTC is limited..."],
      "timeline": "Annually, when preparing US Federal income tax returns..."
    }
  ]
}
```

**Response Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `scenario` | object | Full scenario record from database |
| `scenario.analysis_results` | object | Nested analysis results (may contain empty arrays) |
| `exposures` | array[object] | Tax exposures stored in database (populated from `tax_exposures` table) |
| `recommendations` | array[object] | Recommendations stored in database (populated from `planning_recommendations` table) |

**Notes**:
- The `scenario.analysis_results` object contains the original analysis data stored when the scenario was created
- The `exposures` and `recommendations` arrays at the root level are populated from separate database tables and may contain more detailed information
- Arrays may be empty if no exposures/recommendations were generated or stored
- The `scenario_description` field contains a JSON string representation of the income sources

**Example cURL**:
```bash
curl "http://localhost:8001/api/v1/workflow3/scenario/PLAN-03B05F76"
```

**Example JavaScript**:
```javascript
const response = await fetch('http://localhost:8001/api/v1/workflow3/scenario/PLAN-03B05F76');
const data = await response.json();
console.log(`Scenario: ${data.scenario.scenario_name}`);
console.log(`Exposures: ${data.exposures.length}`);
console.log(`Recommendations: ${data.recommendations.length}`);
```

**Error Responses**:
- `404 Not Found`: Scenario with the given ID does not exist

---

### 3. Get Recommendations
**Endpoint**: `GET /api/v1/workflow3/recommendations/{scenario_id}`

**Description**: Retrieves all recommendations for a specific scenario, optionally filtered by priority level.

**Path Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scenario_id` | string | Yes | The scenario ID (format: `PLAN-XXXXXXXX`) |

**Query Parameters**:
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `priority` | string | No | - | Filter by priority: "critical", "high", or "medium" |

**Response** (200 OK):
```json
{
  "scenario_id": "PLAN-03B05F76",
  "count": 7,
  "recommendations": [
    {
      "id": 1,
      "scenario_id": "PLAN-03B05F76",
      "priority": "critical",
      "recommendation_type": "reporting",
      "title": "Claim US Foreign Tax Credit (FTC) for Foreign Taxes",
      "description": "As a US tax resident, claim Foreign Tax Credit on US federal income tax return for income taxes paid to foreign country...",
      "expected_benefit": "Direct reduction of US federal income tax liability on foreign rental income...",
      "implementation_steps": [
        "Maintain meticulous records of all foreign rental income and taxes paid",
        "Calculate US taxable income from foreign sources",
        "Complete and file Form 1116 with annual US Federal income tax return",
        "Consult with tax professional specializing in international taxation"
      ],
      "risks_and_considerations": [
        "Incorrect calculation can lead to IRS audit and penalties",
        "FTC is limited to US tax on foreign source income",
        "Proper documentation is crucial for substantiating the credit claim"
      ],
      "timeline": "Annually, when preparing US Federal income tax returns (generally by April 15th)",
      "created_at": "2025-11-15T03:38:36.476069"
    },
    {
      "id": 2,
      "scenario_id": "PLAN-03B05F76",
      "priority": "high",
      "recommendation_type": "timing",
      "title": "Schedule US Quarterly Estimated Tax Payments",
      "description": "Make quarterly estimated tax payments to IRS...",
      "expected_benefit": "Avoidance of costly underpayment penalties...",
      "implementation_steps": [
        "Estimate total US federal, NY State, and NYC tax liability for the year",
        "Subtract expected withholding from US employment income",
        "Calculate remaining tax liability to be paid via estimated taxes",
        "Divide into four equal quarterly payments",
        "Make timely payments using Form 1040-ES"
      ],
      "risks_and_considerations": [
        "Underestimating income can still lead to penalties",
        "Overpayment ties up cash that could be invested elsewhere"
      ],
      "timeline": "Immediately for current tax year, with payments due quarterly",
      "created_at": "2025-11-15T03:38:36.476069"
    }
  ]
}
```

**Response Fields**:
| Field | Type | Description |
|-------|------|-------------|
| `scenario_id` | string | The scenario ID |
| `count` | integer | Total number of recommendations returned (after filtering) |
| `recommendations` | array[object] | Array of recommendation objects (see structure above) |

**Example cURL**:
```bash
# Get all recommendations
curl "http://localhost:8001/api/v1/workflow3/recommendations/PLAN-03B05F76"

# Get only critical recommendations
curl "http://localhost:8001/api/v1/workflow3/recommendations/PLAN-03B05F76?priority=critical"

# Get only high priority recommendations
curl "http://localhost:8001/api/v1/workflow3/recommendations/PLAN-03B05F76?priority=high"
```

**Example JavaScript**:
```javascript
// Get all recommendations
const allResponse = await fetch('http://localhost:8001/api/v1/workflow3/recommendations/PLAN-03B05F76');
const allRecs = await allResponse.json();
console.log(`Total recommendations: ${allRecs.count}`);

// Get only critical recommendations
const criticalResponse = await fetch('http://localhost:8001/api/v1/workflow3/recommendations/PLAN-03B05F76?priority=critical');
const criticalRecs = await criticalResponse.json();
console.log(`Critical recommendations: ${criticalRecs.count}`);
```

**Error Responses**:
- `404 Not Found`: Scenario with the given ID does not exist
- `500 Internal Server Error`: Database error

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

**Last Updated**: November 15, 2025
**API Version**: 1.0.0

