#!/bin/bash

echo "=========================================="
echo "Testing All IT-201 Form Files"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results tracking
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Function to test a form
test_form() {
    local form_file=$1
    local expected_issues=$2
    local description=$3
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "${BLUE}📄 Testing: $form_file${NC}"
    echo "${BLUE}   Expected: $description${NC}"
    echo "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    # Check if file exists
    if [ ! -f "$form_file" ]; then
        echo "${RED}❌ ERROR: File not found: $form_file${NC}"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo ""
        return 1
    fi
    
    echo "1️⃣  Uploading form..."
    UPLOAD_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/upload" \
      -F "file=@$form_file" \
      -F "jurisdiction=US-NY" \
      -F "form_code=IT-201" \
      -F "tax_year=2024" \
      -F "client_name=Test Client" \
      -F "client_type=individual")
    
    DOC_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('document_id', ''))" 2>/dev/null)
    
    if [ -z "$DOC_ID" ]; then
        echo "${RED}❌ ERROR: Failed to upload document${NC}"
        echo "Response: $UPLOAD_RESPONSE"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo ""
        return 1
    fi
    
    echo "   ✅ Document ID: $DOC_ID"
    
    # Show extracted data
    echo ""
    echo "2️⃣  Extracted Data:"
    echo "$UPLOAD_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ed = data.get('extracted_data', {})
    print(f\"   Taxpayer Name: '{ed.get('taxpayer_name', 'N/A')}'\")
    print(f\"   Taxpayer SSN: '{ed.get('taxpayer_ssn', 'N/A')}'\")
    print(f\"   Filing Status: '{ed.get('filing_status', 'N/A')}'\")
    
    # Show income fields
    form_fields_json = ed.get('form_fields_json', '{}')
    if isinstance(form_fields_json, str):
        import json as j
        try:
            form_fields = j.loads(form_fields_json)
            print(f\"   Wages: {form_fields.get('wages', 'N/A')}\")
            print(f\"   Interest: {form_fields.get('interest', 'N/A')}\")
            print(f\"   Dividends: {form_fields.get('dividends', 'N/A')}\")
            print(f\"   Total Income: {form_fields.get('total_income', 'N/A')}\")
        except:
            print(f\"   Form Fields: {form_fields_json[:100]}...\")
except Exception as e:
    print(f\"   Error parsing: {e}\")
" 2>/dev/null
    
    echo ""
    echo "3️⃣  Waiting for processing (12 seconds)..."
    sleep 12
    
    echo ""
    echo "4️⃣  Running completeness check..."
    CHECK_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/check/$DOC_ID" \
      -H "Content-Type: application/json" \
      -d '{"check_types": ["required_fields", "calculations", "cross_reference", "jurisdiction_specific"]}')
    
    echo ""
    echo "5️⃣  Check Results:"
    echo "$CHECK_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    issues = data.get('issues', [])
    total_issues = data.get('total_issues', len(issues))
    
    print(f\"   Total Issues Found: {total_issues}\")
    print(f\"   Status: {data.get('status', 'N/A')}\")
    print(f\"   Critical Issues: {data.get('critical_issues', 0)}\")
    print(f\"   High Priority Issues: {data.get('high_priority_issues', 0)}\")
    print(f\"   Medium Priority Issues: {data.get('medium_priority_issues', 0)}\")
    print()
    
    if issues:
        print(\"   Issues Breakdown:\")
        required_issues = [i for i in issues if i.get('check_type') == 'required_fields']
        calc_issues = [i for i in issues if i.get('check_type') == 'calculations']
        cross_issues = [i for i in issues if i.get('check_type') == 'cross_reference']
        juris_issues = [i for i in issues if i.get('check_type') == 'jurisdiction_specific']
        
        if required_issues:
            print(f\"   📋 Required Fields: {len(required_issues)} issues\")
            for i in required_issues[:3]:
                print(f\"      - {i.get('field_name')}: {i.get('issue_description')}\")
        
        if calc_issues:
            print(f\"   🧮 Calculations: {len(calc_issues)} issues\")
            for i in calc_issues[:3]:
                print(f\"      - {i.get('field_name')}: {i.get('issue_description')}\")
                if i.get('expected_value') and i.get('actual_value'):
                    print(f\"        Expected: {i.get('expected_value')}, Actual: {i.get('actual_value')}\")
        
        if cross_issues:
            print(f\"   🔗 Cross-Reference: {len(cross_issues)} issues\")
        
        if juris_issues:
            print(f\"   📍 Jurisdiction-Specific: {len(juris_issues)} issues\")
    else:
        print(\"   ✅ No issues found!\")
except Exception as e:
    print(f\"   Error parsing response: {e}\")
    print(f\"   Raw response: {sys.stdin.read()[:200]}\")
" 2>/dev/null
    
    echo ""
    echo "6️⃣  Getting stored issues..."
    STORED_ISSUES=$(curl -s "http://localhost:8001/api/v1/workflow1/issues/$DOC_ID")
    
    STORED_COUNT=$(echo "$STORED_ISSUES" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('total_issues', 0))" 2>/dev/null)
    echo "   Stored Issues: $STORED_COUNT"
    
    # Evaluate test result
    echo ""
    echo "7️⃣  Test Evaluation:"
    
    # Check if expected issues match
    if [ "$expected_issues" = "none" ] || [ "$expected_issues" = "0" ]; then
        if [ "$STORED_COUNT" -eq 0 ]; then
            echo "${GREEN}   ✅ PASS: No issues found (as expected)${NC}"
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            echo "${YELLOW}   ⚠️  WARNING: Expected no issues, but found $STORED_COUNT issues${NC}"
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    else
        if [ "$STORED_COUNT" -gt 0 ]; then
            echo "${GREEN}   ✅ PASS: Issues detected (as expected)${NC}"
            PASSED_TESTS=$((PASSED_TESTS + 1))
        else
            echo "${RED}   ❌ FAIL: Expected issues, but none found${NC}"
            FAILED_TESTS=$((FAILED_TESTS + 1))
        fi
    fi
    
    echo ""
}

# Test form_it201_1.pdf (should be clean - all fields present and calculations correct)
test_form "form_it201_1.pdf" "none" "Clean form with all required fields and correct calculations"

# Test form_it201_2.pdf (should detect missing name)
test_form "form_it201_2.pdf" "name_missing" "Form with missing taxpayer name"

# Test form_it201_3.pdf (should detect calculation error)
test_form "form_it201_3.pdf" "calculation_error" "Form with calculation error in total_income"

# Summary
echo "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${BLUE}📊 Test Summary${NC}"
echo "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Total Tests: $TOTAL_TESTS"
echo "${GREEN}Passed: $PASSED_TESTS${NC}"
echo "${RED}Failed: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo "${RED}❌ Some tests failed${NC}"
    exit 1
fi

