#!/usr/bin/env python3
"""
Test script to check profile manager functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.profile_manager import ProfileManager

def test_profile_manager():
    """Test the profile manager functionality"""
    manager = ProfileManager()
    
    # Test fetching Wavo's profile
    print("Testing fetch_profile for Wavo...")
    profile = manager.fetch_profile("Wavo")
    print(f"fetch_profile returned: {profile}")
    
    if profile:
        print(f"Profile type: {type(profile)}")
        print(f"Profile keys: {list(profile.keys()) if isinstance(profile, dict) else 'Not a dict'}")
        
        # Test creating summary
        print("\nTesting create_profile_summary...")
        summary = manager.create_profile_summary(profile, "Wavo")
        print(f"Summary created: {len(summary)} characters")
        print(f"Summary preview: {summary[:200]}...")
        
        # Test get_other_profile_summary
        print("\nTesting get_other_profile_summary...")
        summary_result = manager.get_other_profile_summary("Wavo")
        print(f"get_other_profile_summary returned: {summary_result is not None}")
        if summary_result:
            print(f"Summary length: {len(summary_result)} characters")
    else:
        print("fetch_profile returned None!")

if __name__ == "__main__":
    test_profile_manager() 