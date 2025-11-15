#!/bin/bash
# Comprehensive API Testing Script
# Tests all endpoints and validates JSON responses

BASE_URL="http://localhost:8001"
echo "=========================================="
echo "Testing Tax Intelligence Platform APIs"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

test_endpoint() {
    local name=$1
    local method=$2
    local url=$3
    local data=$4
    local expected_status=$5
    
    echo "Testing: $name"
    echo "  $method $url"
    
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$url")
    elif [ "$method" = "POST" ] || [ "$method" = "PATCH" ]; then
        if [[ "$data" == *"@form"* ]] || [[ "$data" == *"multipart"* ]]; then
            # File upload
            response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" $data)
        else
            # JSON body
            response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
                -H "Content-Type: application/json" \
                -d "$data")
        fi
    fi
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    # Validate JSON
    if echo "$body" | python3 -m json.tool > /dev/null 2>&1; then
        json_valid=true
    else
        json_valid=false
    fi
    
    # Check status code
    if [ "$http_code" = "$expected_status" ]; then
        status_ok=true
    else
        status_ok=false
    fi
    
    if [ "$status_ok" = true ] && [ "$json_valid" = true ]; then
        echo -e "  ${GREEN}✅ PASS${NC} (Status: $http_code, Valid JSON)"
        ((TESTS_PASSED++))
        echo "  Response preview:"
        echo "$body" | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d, indent=2))" 2>/dev/null | head -20
    else
        echo -e "  ${RED}❌ FAIL${NC}"
        if [ "$status_ok" = false ]; then
            echo "    Expected status: $expected_status, Got: $http_code"
        fi
        if [ "$json_valid" = false ]; then
            echo "    Invalid JSON response"
            echo "    Response: $body" | head -5
        fi
        ((TESTS_FAILED++))
    fi
    echo ""
}

# Test 1: Health Check
test_endpoint "Health Check" "GET" "$BASE_URL/health" "" "200"

# Test 2: List Jurisdictions
test_endpoint "List Jurisdictions" "GET" "$BASE_URL/api/search/jurisdictions" "" "200"

# Test 3: List Categories
test_endpoint "List Categories" "GET" "$BASE_URL/api/search/categories" "" "200"

# Test 4: Workflow 1 - Upload (if test file exists)
if [ -f "form_it201_1.pdf" ]; then
    echo "Testing Workflow 1 Upload..."
    UPLOAD_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/workflow1/upload" \
        -F "file=@form_it201_1.pdf" \
        -F "jurisdiction=US-NY" \
        -F "form_code=IT-201" \
        -F "tax_year=2024" \
        -F "client_name=Test Client" \
        -F "client_type=individual")
    
    if echo "$UPLOAD_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
        DOC_ID=$(echo "$UPLOAD_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('document_id', 'ERROR'))" 2>/dev/null)
        if [ "$DOC_ID" != "ERROR" ] && [ -n "$DOC_ID" ]; then
            echo -e "  ${GREEN}✅ Upload successful${NC} - Document ID: $DOC_ID"
            ((TESTS_PASSED++))
            
            # Test 5: Check Document
            sleep 2
            echo ""
            echo "Testing Workflow 1 Check..."
            CHECK_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/workflow1/check/$DOC_ID" \
                -H "Content-Type: application/json" \
                -d '{"check_types":["completeness","calculations"]}')
            
            if echo "$CHECK_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
                echo -e "  ${GREEN}✅ Check successful${NC}"
                ((TESTS_PASSED++))
                TOTAL_ISSUES=$(echo "$CHECK_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('total_issues', 0))" 2>/dev/null)
                echo "  Total issues found: $TOTAL_ISSUES"
            else
                echo -e "  ${RED}❌ Check failed - Invalid JSON${NC}"
                ((TESTS_FAILED++))
            fi
            
            # Test 6: Get Issues
            echo ""
            echo "Testing Get Issues..."
            ISSUES_RESPONSE=$(curl -s "$BASE_URL/api/v1/workflow1/issues/$DOC_ID")
            if echo "$ISSUES_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
                echo -e "  ${GREEN}✅ Get Issues successful${NC}"
                ((TESTS_PASSED++))
            else
                echo -e "  ${RED}❌ Get Issues failed - Invalid JSON${NC}"
                ((TESTS_FAILED++))
            fi
        else
            echo -e "  ${RED}❌ Upload failed${NC}"
            ((TESTS_FAILED++))
        fi
    else
        echo -e "  ${RED}❌ Upload failed - Invalid JSON${NC}"
        ((TESTS_FAILED++))
    fi
    echo ""
else
    echo -e "${YELLOW}⚠️  Skipping Workflow 1 upload test (form_it201_1.pdf not found)${NC}"
    echo ""
fi

# Test 7: Workflow 2 - Compare
echo "Testing Workflow 2 Compare..."
COMPARE_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/workflow2/compare" \
    -H "Content-Type: application/json" \
    -d '{
        "base_jurisdiction": "US-NY",
        "target_jurisdiction": "US-CA",
        "scope": "individual_income",
        "tax_year": 2024
    }')

if echo "$COMPARE_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
    COMP_ID=$(echo "$COMPARE_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('comparison_id', 'ERROR'))" 2>/dev/null)
    if [ "$COMP_ID" != "ERROR" ] && [ -n "$COMP_ID" ]; then
        echo -e "  ${GREEN}✅ Compare successful${NC} - Comparison ID: $COMP_ID"
        ((TESTS_PASSED++))
        
        # Test 8: Get Comparison
        sleep 2
        echo ""
        echo "Testing Get Comparison..."
        GET_COMP_RESPONSE=$(curl -s "$BASE_URL/api/v1/workflow2/comparison/$COMP_ID")
        if echo "$GET_COMP_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
            echo -e "  ${GREEN}✅ Get Comparison successful${NC}"
            ((TESTS_PASSED++))
        else
            echo -e "  ${RED}❌ Get Comparison failed - Invalid JSON${NC}"
            ((TESTS_FAILED++))
        fi
    else
        echo -e "  ${RED}❌ Compare failed${NC}"
        ((TESTS_FAILED++))
    fi
else
    echo -e "  ${RED}❌ Compare failed - Invalid JSON${NC}"
    ((TESTS_FAILED++))
fi
echo ""

# Test 9: Workflow 3 - Create Scenario
echo "Testing Workflow 3 Create Scenario..."
SCENARIO_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/workflow3/scenario" \
    -H "Content-Type: application/json" \
    -d '{
        "client_id": "TEST-001",
        "client_name": "Test Client",
        "scenario_name": "Test Scenario",
        "jurisdictions_involved": ["US-NY"],
        "income_sources": [
            {
                "type": "employment",
                "jurisdiction": "US-NY",
                "amount_range": "50000-60000",
                "description": "Test income"
            }
        ],
        "objectives": ["minimize_tax"],
        "tax_year": 2024
    }')

if echo "$SCENARIO_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
    SCENARIO_ID=$(echo "$SCENARIO_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('scenario_id', 'ERROR'))" 2>/dev/null)
    if [ "$SCENARIO_ID" != "ERROR" ] && [ -n "$SCENARIO_ID" ]; then
        echo -e "  ${GREEN}✅ Create Scenario successful${NC} - Scenario ID: $SCENARIO_ID"
        ((TESTS_PASSED++))
        
        # Test 10: Get Scenario
        sleep 2
        echo ""
        echo "Testing Get Scenario..."
        GET_SCENARIO_RESPONSE=$(curl -s "$BASE_URL/api/v1/workflow3/scenario/$SCENARIO_ID")
        if echo "$GET_SCENARIO_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
            echo -e "  ${GREEN}✅ Get Scenario successful${NC}"
            ((TESTS_PASSED++))
        else
            echo -e "  ${RED}❌ Get Scenario failed - Invalid JSON${NC}"
            ((TESTS_FAILED++))
        fi
        
        # Test 11: Get Recommendations
        echo ""
        echo "Testing Get Recommendations..."
        REC_RESPONSE=$(curl -s "$BASE_URL/api/v1/workflow3/recommendations/$SCENARIO_ID")
        if echo "$REC_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
            echo -e "  ${GREEN}✅ Get Recommendations successful${NC}"
            ((TESTS_PASSED++))
        else
            echo -e "  ${RED}❌ Get Recommendations failed - Invalid JSON${NC}"
            ((TESTS_FAILED++))
        fi
    else
        echo -e "  ${RED}❌ Create Scenario failed${NC}"
        ((TESTS_FAILED++))
    fi
else
    echo -e "  ${RED}❌ Create Scenario failed - Invalid JSON${NC}"
    ((TESTS_FAILED++))
fi
echo ""

# Summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "${GREEN}Tests Passed: $TESTS_PASSED${NC}"
echo -e "${RED}Tests Failed: $TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed. Check the output above.${NC}"
    exit 1
fi

