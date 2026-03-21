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

