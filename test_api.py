"""
Simple test script for the Document Processing API
Usage: 
    python test_api.py invoice <path_to_invoice.pdf>
    python test_api.py contract <path_to_contract.pdf>
"""
import sys
import requests
import os

def test_upload_invoice(pdf_path):
    """Test the upload_document endpoint with an invoice"""
    url = "http://localhost:8001/upload_document"
    
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return
    
    with open(pdf_path, 'rb') as f:
        files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
        data = {'document_type': 'invoice'}
        
        print(f"Uploading invoice: {pdf_path}...")
        try:
            # Add timeout to prevent hanging (5 minutes for document processing)
            response = requests.post(url, files=files, data=data, timeout=300)
            
            if response.status_code == 200:
                result = response.json()
                print("\n✅ Success!")
                print(f"Message: {result.get('message')}")
                print("\nExtracted Metadata:")
                metadata = result.get('metadata', {})
                for key, value in metadata.items():
                    print(f"  {key}: {value}")
            else:
                print(f"\n❌ Error: {response.status_code}")
                print(response.text)
        except requests.exceptions.ConnectionError:
            print("Error: Could not connect to API. Make sure the server is running on http://localhost:8001")
        except requests.exceptions.Timeout:
            print("Error: Request timed out. The document processing is taking longer than expected.")
            print("This might be due to:")
            print("  - Large document size")
            print("  - Slow API response from Landing AI")
            print("  - Network connectivity issues")
        except Exception as e:
            print(f"Error: {e}")

def test_upload_contract(pdf_path):
    """Test the upload_document endpoint with a contract"""
    url = "http://localhost:8001/upload_document"
    
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return
    
    with open(pdf_path, 'rb') as f:
        files = {'file': (os.path.basename(pdf_path), f, 'application/pdf')}
        data = {'document_type': 'contract'}
        
        print(f"Uploading contract: {pdf_path}...")
        try:
            # Add timeout to prevent hanging (5 minutes for document processing)
            response = requests.post(url, files=files, data=data, timeout=300)
            
            if response.status_code == 200:
                result = response.json()
                print("\n✅ Success!")
                print(f"Message: {result.get('message')}")
                print("\nExtracted Metadata:")
                metadata = result.get('metadata', {})
                for key, value in metadata.items():
                    # Truncate text field if it's too long
                    if key == 'text' and value and len(str(value)) > 200:
                        print(f"  {key}: {str(value)[:200]}... (truncated, full length: {len(str(value))} chars)")
                    else:
                        print(f"  {key}: {value}")
            else:
                print(f"\n❌ Error: {response.status_code}")
                print(response.text)
        except requests.exceptions.ConnectionError:
            print("Error: Could not connect to API. Make sure the server is running on http://localhost:8001")
        except requests.exceptions.Timeout:
            print("Error: Request timed out. The document processing is taking longer than expected.")
            print("This might be due to:")
            print("  - Large document size")
            print("  - Slow API response from Landing AI")
            print("  - Network connectivity issues")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python test_api.py invoice <path_to_invoice.pdf>")
        print("  python test_api.py contract <path_to_contract.pdf>")
        sys.exit(1)
    
    doc_type = sys.argv[1].lower()
    pdf_path = sys.argv[2]
    
    if doc_type == 'invoice':
        test_upload_invoice(pdf_path)
    elif doc_type == 'contract':
        test_upload_contract(pdf_path)
    else:
        print(f"Error: Unknown document type '{doc_type}'. Use 'invoice' or 'contract'")
        sys.exit(1)

