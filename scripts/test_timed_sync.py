#!/usr/bin/env python3
"""
Test timed synchronization functionality

This script tests the new time-limited sync feature.
"""

import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_timed_sync():
    """Test sync with different time limits"""
    
    print("🧪 Testing timed synchronization...")
    print("=" * 50)
    
    try:
        from maya_sawa.core.people import sync_data
        
        # Test 1: 30 seconds limit
        print("Test 1: 30 seconds limit")
        start_time = time.time()
        result = sync_data(max_time_seconds=30)
        end_time = time.time()
        
        print(f"✅ Completed in {end_time - start_time:.1f}s")
        print(f"📊 Results: {result}")
        print()
        
        # Test 2: 10 seconds limit (should be very short)
        print("Test 2: 10 seconds limit")
        start_time = time.time()
        result = sync_data(max_time_seconds=10)
        end_time = time.time()
        
        print(f"✅ Completed in {end_time - start_time:.1f}s")
        print(f"📊 Results: {result}")
        print()
        
        # Test 3: 120 seconds limit (should process more)
        print("Test 3: 120 seconds limit")
        start_time = time.time()
        result = sync_data(max_time_seconds=120)
        end_time = time.time()
        
        print(f"✅ Completed in {end_time - start_time:.1f}s")
        print(f"📊 Results: {result}")
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_timed_sync() 