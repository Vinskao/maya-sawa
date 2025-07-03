#!/usr/bin/env python3
"""
Test API endpoints with correct HTTP methods
"""

import httpx
import json

def test_apis():
    """Test both APIs with correct HTTP methods"""
    
    print("🔍 Testing API endpoints...")
    print("=" * 50)
    
    # Test people API (POST)
    print("Testing people API (POST)...")
    people_url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-all"
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(people_url)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ People API working - Got {len(data)} records")
                
                # Show first record as sample
                if data:
                    print(f"📝 Sample record: {json.dumps(data[0], indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ People API error - Status: {response.status_code}")
                print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ People API error: {str(e)}")
    
    print()
    
    # Test weapons API (GET)
    print("Testing weapons API (GET)...")
    weapons_url = "https://peoplesystem.tatdvsonorth.com/tymb/weapons"
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(weapons_url)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Weapons API working - Got {len(data)} records")
                
                # Show first record as sample
                if data:
                    print(f"📝 Sample record: {json.dumps(data[0], indent=2, ensure_ascii=False)}")
            else:
                print(f"❌ Weapons API error - Status: {response.status_code}")
                print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Weapons API error: {str(e)}")
    
    print("=" * 50)
    print("API test complete!")

if __name__ == "__main__":
    test_apis() 