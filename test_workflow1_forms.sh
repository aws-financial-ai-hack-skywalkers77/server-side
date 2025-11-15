#!/bin/bash
# Test script for Workflow 1 with form_it201_1.pdf, form_it201_2.pdf, and form_it201_3.pdf

echo "=== TESTING WORKFLOW 1 WITH FILLED FORMS ==="
echo ""

# Step 0: Update calculation rules for IT-201 form template
echo "Step 0: Updating calculation rules for IT-201 form template..."
echo "   Adding rule: total_income = wages + interest + dividends"
echo ""

CALC_UPDATE_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/admin/form-template/update-calculations" \
  -F "jurisdiction=US-NY" \
  -F "form_code=IT-201" \
  -F "tax_year=2024" \
  -F 'calculation_rules=[{"name":"Total Income Calculation","formula":"wages + interest + dividends","result_field":"total_income","description":"Total income should equal the sum of wages, interest, and dividends"}]')

CALC_UPDATE_SUCCESS=$(echo "$CALC_UPDATE_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print('SUCCESS' if d.get('success') else 'FAILED')" 2>/dev/null)

if [ "$CALC_UPDATE_SUCCESS" = "SUCCESS" ]; then
    echo "   ✅ Calculation rules updated successfully"
else
    echo "   ⚠️  Warning: Could not update calculation rules"
    echo "   Response: $CALC_UPDATE_RESPONSE"
    echo "   Continuing with tests anyway..."
fi
echo ""
echo ""

# Test form_it201_1.pdf
echo "1. Testing form_it201_1.pdf..."
echo "   Uploading..."
DOC1_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/upload" \
  -F "file=@form_it201_1.pdf" \
  -F "jurisdiction=US-NY" \
  -F "form_code=IT-201" \
  -F "tax_year=2024" \
  -F "client_name=Test Client 1" \
  -F "client_type=individual")

DOC1_ID=$(echo "$DOC1_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('document_id', 'ERROR'))" 2>/dev/null)

if [ "$DOC1_ID" = "ERROR" ] || [ -z "$DOC1_ID" ]; then
    echo "   ❌ Upload failed!"
    echo "   Response: $DOC1_RESPONSE"
else
    echo "   ✅ Uploaded: $DOC1_ID"
    echo ""
    echo "   Running completeness check..."
    sleep 2
    
    CHECK1_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/check/$DOC1_ID" \
      -H "Content-Type: application/json" \
      -d '{"check_types":["completeness","calculations","cross_reference","jurisdiction_specific"]}')
    
    echo "$CHECK1_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   Total Issues: {d.get(\"total_issues\", 0)}')
    print(f'   Status: {d.get(\"status\", \"N/A\")}')
    print(f'   Critical: {d.get(\"critical_issues\", 0)}, High: {d.get(\"high_priority_issues\", 0)}, Medium: {d.get(\"medium_priority_issues\", 0)}, Low: {d.get(\"low_priority_issues\", 0)}')
    issues = d.get('issues', [])
    if len(issues) > 0:
        print(f'   ')
        print(f'   Issues Found ({len(issues)}):')
        for i, issue in enumerate(issues[:15], 1):
            severity = issue.get('severity', 'N/A')
            field = issue.get('field_name', 'N/A')
            desc = issue.get('issue_description', 'N/A')
            print(f'      {i}. [{severity:8}] {field:20} - {desc[:70]}')
    else:
        print('   ✅ No issues found!')
except Exception as e:
    print(f'   ❌ Error parsing response: {e}')
    print('   Raw response:')
    sys.stdout.write(sys.stdin.read()[:500])
"
fi

echo ""
echo ""

# Test form_it201_2.pdf
echo "2. Testing form_it201_2.pdf..."
echo "   Uploading..."
DOC2_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/upload" \
  -F "file=@form_it201_2.pdf" \
  -F "jurisdiction=US-NY" \
  -F "form_code=IT-201" \
  -F "tax_year=2024" \
  -F "client_name=Test Client 2" \
  -F "client_type=individual")

DOC2_ID=$(echo "$DOC2_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('document_id', 'ERROR'))" 2>/dev/null)

if [ "$DOC2_ID" = "ERROR" ] || [ -z "$DOC2_ID" ]; then
    echo "   ❌ Upload failed!"
    echo "   Response: $DOC2_RESPONSE"
else
    echo "   ✅ Uploaded: $DOC2_ID"
    echo ""
    echo "   Running completeness check..."
    sleep 2
    
    CHECK2_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/check/$DOC2_ID" \
      -H "Content-Type: application/json" \
      -d '{"check_types":["completeness","calculations","cross_reference","jurisdiction_specific"]}')
    
    echo "$CHECK2_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   Total Issues: {d.get(\"total_issues\", 0)}')
    print(f'   Status: {d.get(\"status\", \"N/A\")}')
    print(f'   Critical: {d.get(\"critical_issues\", 0)}, High: {d.get(\"high_priority_issues\", 0)}, Medium: {d.get(\"medium_priority_issues\", 0)}, Low: {d.get(\"low_priority_issues\", 0)}')
    issues = d.get('issues', [])
    if len(issues) > 0:
        print(f'   ')
        print(f'   Issues Found ({len(issues)}):')
        for i, issue in enumerate(issues[:15], 1):
            severity = issue.get('severity', 'N/A')
            field = issue.get('field_name', 'N/A')
            desc = issue.get('issue_description', 'N/A')
            print(f'      {i}. [{severity:8}] {field:20} - {desc[:70]}')
    else:
        print('   ✅ No issues found!')
except Exception as e:
    print(f'   ❌ Error parsing response: {e}')
    print('   Raw response:')
    sys.stdout.write(sys.stdin.read()[:500])
"
fi



# Test form_it201_3.pdf
echo "3. Testing form_it201_3.pdf (with calculation error)..."
echo "   Uploading..."
DOC3_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/upload" \
  -F "file=@form_it201_3.pdf" \
  -F "jurisdiction=US-NY" \
  -F "form_code=IT-201" \
  -F "tax_year=2024" \
  -F "client_name=Test Client 3" \
  -F "client_type=individual")

DOC3_ID=$(echo "$DOC3_RESPONSE" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('document_id', 'ERROR'))" 2>/dev/null)

if [ "$DOC3_ID" = "ERROR" ] || [ -z "$DOC3_ID" ]; then
    echo "   ❌ Upload failed!"
    echo "   Response: $DOC3_RESPONSE"
else
    echo "   ✅ Uploaded: $DOC3_ID"
    echo ""
    echo "   Running completeness check (should detect calculation error)..."
    sleep 2
    
    CHECK3_RESPONSE=$(curl -s -X POST "http://localhost:8001/api/v1/workflow1/check/$DOC3_ID" \
      -H "Content-Type: application/json" \
      -d '{"check_types":["completeness","calculations","cross_reference","jurisdiction_specific"]}')
    
    echo "$CHECK3_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'   Total Issues: {d.get(\"total_issues\", 0)}')
    print(f'   Status: {d.get(\"status\", \"N/A\")}')
    print(f'   Critical: {d.get(\"critical_issues\", 0)}, High: {d.get(\"high_priority_issues\", 0)}, Medium: {d.get(\"medium_priority_issues\", 0)}, Low: {d.get(\"low_priority_issues\", 0)}')
    issues = d.get('issues', [])
    if len(issues) > 0:
        print(f'   ')
        print(f'   Issues Found ({len(issues)}):')
        for i, issue in enumerate(issues[:15], 1):
            severity = issue.get('severity', 'N/A')
            field = issue.get('field_name', 'N/A')
            desc = issue.get('issue_description', 'N/A')
            print(f'      {i}. [{severity:8}] {field:20} - {desc[:70]}')
    else:
        print('   ⚠️  No issues found! (Expected calculation error)')
except Exception as e:
    print(f'   ❌ Error parsing response: {e}')
    print('   Raw response:')
    sys.stdout.write(sys.stdin.read()[:500])
"
fi


echo ""
echo ""
echo "=== TEST SUMMARY ==="
echo ""
echo "To see detailed issues for each document, use:"
echo "  curl http://localhost:8001/api/v1/workflow1/issues/$DOC1_ID"
echo "  curl http://localhost:8001/api/v1/workflow1/issues/$DOC2_ID"
echo "  curl http://localhost:8001/api/v1/workflow1/issues/$DOC3_ID"
echo ""
echo "Document IDs:"
echo "  form_it201_1.pdf: $DOC1_ID"
echo "  form_it201_2.pdf: $DOC2_ID"
echo "  form_it201_3.pdf: $DOC3_ID (should have calculation error)"

