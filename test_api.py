"""
Simple test script for the Document Processing API
Usage: python test_api.py <path_to_invoice.pdf>
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
        
        print(f"Uploading {pdf_path}...")
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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_api.py <path_to_invoice.pdf>")
        sys.exit(1)
    
    test_upload_invoice(sys.argv[1])

