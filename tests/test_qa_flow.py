#!/usr/bin/env python3
"""
Test script to simulate the exact QA flow for recognition questions
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.qa_chain import QAChain
from maya_sawa.core.name_detector import NameDetector
from maya_sawa.core.name_adapter import NameAdapter

def test_qa_flow():
    """Test the exact QA flow for recognition questions"""
    
    # Test the question
    query = "你認識Wavo嗎？"
    print(f"Testing question: {query}")
    
    # Test name detector
    print("\n=== Testing NameDetector ===")
    name_detector = NameDetector()
    detected_names = name_detector.detect_all_queried_names(query)
    print(f"detect_all_queried_names returned: {detected_names}")
    
    # Test name adapter
    print("\n=== Testing NameAdapter ===")
    name_adapter = NameAdapter()
    is_recognition = name_adapter.is_recognition_question(query)
    print(f"is_recognition_question: {is_recognition}")
    
    if is_recognition:
        extracted_names = name_adapter.extract_names_from_recognition_question(query)
        print(f"extract_names_from_recognition_question: {extracted_names}")
    
    # Test the flow logic
    print("\n=== Testing Flow Logic ===")
    if detected_names:
        print("Path 1: detected_names is not empty")
    else:
        print("Path 1: detected_names is empty")
        
        if is_recognition:
            print("Path 2: is_recognition_question is True")
            if extracted_names:
                print(f"Path 2: extracted_names: {extracted_names}")
                
                # Test profile manager for each extracted name
                from maya_sawa.core.profile_manager import ProfileManager
                profile_manager = ProfileManager()
                
                for name in extracted_names:
                    print(f"\nTesting profile for: {name}")
                    profile_summary = profile_manager.get_other_profile_summary(name)
                    if profile_summary:
                        print(f"✅ Profile found for {name}")
                        print(f"Summary length: {len(profile_summary)} characters")
                    else:
                        print(f"❌ No profile found for {name}")
            else:
                print("Path 2: extracted_names is empty")
        else:
            print("Path 2: is_recognition_question is False")

if __name__ == "__main__":
    test_qa_flow() 