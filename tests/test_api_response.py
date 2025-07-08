#!/usr/bin/env python3
"""
Test script to check API response format
"""

import httpx
import json

def test_wavo_api():
    """Test the API response for Wavo's profile"""
    url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-by-name"
    payload = {"name": "Wavo"}
    
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            print(f"Response status: {response.status_code}")
            print(f"Response type: {type(data)}")
            print(f"Response content: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # Check if data is a list or dict
            if isinstance(data, list):
                print(f"Data is a list with {len(data)} items")
                if data:
                    print(f"First item: {data[0]}")
            elif isinstance(data, dict):
                print(f"Data is a dict with keys: {list(data.keys())}")
            else:
                print(f"Data is neither list nor dict: {type(data)}")
                
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_wavo_api() 