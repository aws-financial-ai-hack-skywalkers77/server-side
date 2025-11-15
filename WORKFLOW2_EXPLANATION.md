# Workflow 2: Jurisdiction Comparison Engine - Complete Explanation

## 🎯 **What Does Workflow 2 Do?**

**Workflow 2 helps tax professionals (CAs) understand differences between two tax jurisdictions.**

**Use Case Example:**
- A CA who knows New York (NY) tax law needs to learn California (CA) tax law
- Instead of reading hundreds of pages of CA tax documents, Workflow 2:
  1. Extracts key tax rules from both jurisdictions
  2. Uses AI to intelligently compare them
  3. Highlights the **key differences** the CA needs to know
  4. Generates a learning checklist

---

## 📥 **INPUTS (What You Provide)**

### Required Inputs:
```json
{
  "base_jurisdiction": "US-NY",        // The jurisdiction the CA already knows
  "target_jurisdiction": "US-CA",      // The jurisdiction the CA wants to learn
  "scope": "individual_income",        // Type of tax to compare
  "tax_year": 2024                     // Which year's tax laws to compare
}
```

### Optional Inputs:
- `requested_by`: User identifier (email, username, etc.)

### Input Parameters Explained:

1. **`base_jurisdiction`** (required):
   - The jurisdiction the CA is already familiar with
   - Examples: `"US-NY"`, `"US-CA"`, `"US-FED"`, `"EU-DE"`
   - This is what the system uses as the "baseline" for comparison

2. **`target_jurisdiction`** (required):
   - The jurisdiction the CA wants to learn about
   - Examples: `"US-CA"`, `"US-NY"`, `"EU-DE"`
   - This is what gets compared against the base

3. **`scope`** (optional, default: `"individual_income"`):
   - Type of tax to compare
   - Options: `"individual_income"`, `"corporate"`, `"vat"`, etc.
   - Determines which tax rules to extract

4. **`tax_year`** (optional, default: current year):
   - Which year's tax laws to compare
   - Example: `2024`
   - Important because tax laws change year-to-year

---

## 🔍 **WHAT IT COMPARES (The Process)**

### Step 1: Extract Tax Rules from Knowledge Base
The system searches the **ingested tax law documents** in the database for both jurisdictions:

**For Base Jurisdiction (e.g., US-NY):**
- Searches for: "individual_income tax filing requirements in US-NY"
- Searches for: "individual_income tax rates and brackets in US-NY"
- Searches for: "individual_income tax deductions and credits in US-NY"
- Searches for: "individual_income tax payment deadlines in US-NY"
- Searches for: "individual_income required forms and schedules in US-NY"

**For Target Jurisdiction (e.g., US-CA):**
- Same searches but for US-CA

**Result:** Gets relevant law sections/chunks from the knowledge base (the tax law PDFs you ingested earlier)

### Step 2: AI-Powered Comparison
Uses **Google Gemini LLM** to:
- Read the extracted rules from both jurisdictions
- Identify **key differences** between them
- Categorize differences by importance:
  - **CRITICAL**: Could lead to errors (different filing requirements, calculation methods)
  - **IMPORTANT**: Affects most taxpayers (rate structures, common deductions)
  - **INFORMATIONAL**: Terminology, form names

### Step 3: Generate Differences
For each difference found, the LLM provides:
- `difference_type`: Type of difference (tax_rate, deduction, filing_deadline, etc.)
- `category`: High-level category (rates, deductions, filing)
- `base_rule`: How it works in the base jurisdiction (e.g., "NY has rates 4% - 10.9%")
- `target_rule`: How it works in target jurisdiction (e.g., "CA has rates 1% - 13.3%")
- `impact_level`: critical, important, or informational
- `explanation`: Why the difference matters
- `examples`: Practical examples showing the difference

### Step 4: Generate Learning Checklist
Creates a checklist organized by category to help the CA learn the target jurisdiction

---

## 📤 **OUTPUT (What You Get Back)**

### Main Response Structure:
```json
{
  "comparison_id": "COMP-E0FD44E6",
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "scope": "individual_income",
  "tax_year": 2024,
  "status": "completed",
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
      ]
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
      ]
    },
    {
      "difference_type": "filing_deadline",
      "category": "filing",
      "base_rule": "NY filing deadline is April 15",
      "target_rule": "CA filing deadline is April 15 (same as federal)",
      "impact_level": "informational",
      "explanation": "Both jurisdictions use the same filing deadline",
      "examples": []
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
  ],
  "created_at": "2024-11-15T00:13:55"
}
```

---

## 🔄 **COMPARISON SOURCE (What It Compares Against)**

**Workflow 2 compares against the TAX LAW DOCUMENTS in your knowledge base:**

1. **Source**: The tax law PDFs you ingested using `/api/admin/ingest-law`
   - Examples: NY State Income Tax Instructions 2024, CA Tax Law 2024, etc.
   - These are stored in the `tax_laws` table with vector embeddings

2. **How it finds relevant rules**:
   - Uses **vector similarity search** (RAG - Retrieval-Augmented Generation)
   - Searches for rules related to: filing requirements, tax rates, deductions, deadlines, forms
   - Returns the most relevant law sections/chunks

3. **What gets compared**:
   - Tax rates and brackets
   - Deduction amounts and eligibility
   - Filing deadlines
   - Required forms
   - Calculation methods
   - Exemptions and thresholds
   - Payment requirements

---

## 💡 **REAL-WORLD EXAMPLE**

### Scenario:
A CA in New York needs to help a client who moved to California. The CA knows NY tax law but needs to understand CA differences quickly.

### Input:
```json
{
  "base_jurisdiction": "US-NY",
  "target_jurisdiction": "US-CA",
  "scope": "individual_income",
  "tax_year": 2024
}
```

### What Happens:
1. System searches knowledge base for NY tax rules (filing, rates, deductions, etc.)
2. System searches knowledge base for CA tax rules (same topics)
3. AI compares the rules and finds differences like:
   - CA has higher top tax rate (13.3% vs 10.9%)
   - NY has higher standard deduction ($8,000 vs $5,202)
   - Different form requirements
   - Different deduction eligibility rules

### Output:
A structured list of differences with:
- What's different
- Why it matters
- Practical examples
- A learning checklist

---

## 🎯 **KEY FEATURES**

1. **Intelligent Comparison**: Uses AI to understand context, not just keyword matching
2. **Prioritized Differences**: Critical vs Important vs Informational
3. **Practical Focus**: Only shows differences that matter for tax preparation
4. **Learning Checklist**: Helps CAs systematically learn the new jurisdiction
5. **Stored Results**: Comparison is saved and can be retrieved later

---

## ⚠️ **IMPORTANT NOTES**

1. **Requires Ingested Laws**: The system needs tax law documents in the knowledge base
   - If you haven't ingested laws for a jurisdiction, it won't find rules to compare
   - Use `/api/admin/ingest-law` to ingest tax law PDFs first

2. **Quality Depends on Knowledge Base**:
   - More comprehensive laws = better comparisons
   - Current knowledge base has: US-NY, US-CA, US-FED, US-DE (Germany)

3. **LLM Dependency**:
   - Uses Google Gemini to analyze and compare
   - Requires `GEMINI_API_KEY` to be set
   - May take 10-30 seconds to complete

4. **Differences May Be Empty**:
   - If jurisdictions are very similar
   - If LLM doesn't find meaningful differences
   - If knowledge base doesn't have enough relevant laws

---

## 🚀 **HOW TO USE IT**

### Step 1: Make sure you have laws ingested
```bash
# Check what jurisdictions you have
curl "http://localhost:8001/api/search/jurisdictions"
```

### Step 2: Create a comparison
```bash
curl -X POST "http://localhost:8001/api/v1/workflow2/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "base_jurisdiction": "US-NY",
    "target_jurisdiction": "US-CA",
    "scope": "individual_income",
    "tax_year": 2024
  }'
```

### Step 3: Get the comparison later
```bash
# Use the comparison_id from Step 2
curl "http://localhost:8001/api/v1/workflow2/comparison/COMP-E0FD44E6"
```

---

## 📊 **SUMMARY**

| Aspect | Details |
|--------|---------|
| **Purpose** | Help CAs learn differences between two tax jurisdictions |
| **Input** | Base jurisdiction, target jurisdiction, scope, tax year |
| **Compares** | Tax laws from knowledge base (ingested PDFs) |
| **Output** | List of differences with explanations, examples, and learning checklist |
| **Use Case** | CA knows NY, needs to learn CA quickly |
| **Technology** | Vector search (RAG) + LLM (Gemini) for intelligent comparison |

---

**Last Updated**: November 15, 2024

