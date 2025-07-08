#!/usr/bin/env python3
"""
Test script to check name adapter functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.name_adapter import NameAdapter

def test_name_adapter():
    """Test the name adapter functionality"""
    adapter = NameAdapter()
    
    # Test recognition question detection
    question = "你認識Wavo嗎？"
    print(f"Question: {question}")
    
    is_recognition = adapter.is_recognition_question(question)
    print(f"Is recognition question: {is_recognition}")
    
    if is_recognition:
        extracted_names = adapter.extract_names_from_recognition_question(question)
        print(f"Extracted names: {extracted_names}")
        
        for name in extracted_names:
            normalized = adapter.normalize_name(name)
            print(f"Original: '{name}' -> Normalized: '{normalized}'")

if __name__ == "__main__":
    test_name_adapter() 