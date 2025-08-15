#!/usr/bin/env python3
"""
People and Weapons Data Synchronization Script

This script fetches data from the APIs and updates PostgreSQL tables
with embeddings for semantic search.

Usage:
    python scripts/sync_people_weapons.py

Environment Variables Required:
    - DB_HOST: Database host
    - DB_DATABASE: Database name  
    - DB_USERNAME: Database username
    - DB_PASSWORD: Database password
    - OPENAI_API_KEY: OpenAI API key for generating embeddings
"""

import os
import sys
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from maya_sawa.people import sync_data

def main():
    """Main function to run the data synchronization"""
    
    # Check required environment variables
    required_env_vars = [
        "DB_HOST",
        "DB_DATABASE",
        "DB_USERNAME", 
        "DB_PASSWORD",
        "OPENAI_API_KEY"
    ]
    
    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these environment variables before running the script.")
        sys.exit(1)
    
    try:
        print("Starting people and weapons data synchronization...")
        
        # Run the synchronization
        result = sync_data()
        
        print("Data synchronization completed successfully!")
        print(f"People records updated: {result['people_updated']}")
        print(f"Weapons records updated: {result['weapons_updated']}")
        print(f"Total records updated: {result['total_updated']}")
        
    except Exception as e:
        print(f"Error during data synchronization: {str(e)}")
        logging.error(f"Data synchronization failed: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 