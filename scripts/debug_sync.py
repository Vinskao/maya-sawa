#!/usr/bin/env python3
"""
Debug script for people and weapons synchronization

This script helps diagnose issues with the synchronization process
and embedding generation.
"""

import os
import sys
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import config
from maya_sawa.core.config import Config

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def check_environment():
    """Check environment variables"""
    print("=== Environment Variables Check ===")
    
    required_vars = [
        "POSTGRES_CONNECTION_STRING",
        "OPENAI_API_KEY"
    ]
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if "password" in var.lower() or "key" in var.lower():
                masked_value = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                print(f"✅ {var}: {masked_value}")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: NOT SET")
    
    print()

def check_openai():
    """Check OpenAI API connection"""
    print("=== OpenAI API Check ===")
    
    try:
        from openai import OpenAI
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("❌ OPENAI_API_KEY not set")
            return False
        
        client = OpenAI(api_key=api_key)
        
        # Test with a simple embedding request
        response = client.embeddings.create(
            model="text-embedding-ada-002",
            input="test"
        )
        
        embedding = response.data[0].embedding
        print(f"✅ OpenAI API working - Generated embedding with {len(embedding)} dimensions")
        return True
        
    except Exception as e:
        print(f"❌ OpenAI API error: {str(e)}")
        return False
    
    print()

def check_database():
    """Check database connection"""
    print("=== Database Connection Check ===")
    
    try:
        from maya_sawa.core.connection_pool import get_pool_manager
        
        pool_manager = get_pool_manager()
        conn = pool_manager.get_postgres_connection()
        
        if conn:
            cursor = conn.cursor()
            
            # Check if tables exist
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('people', 'weapon')
            """)
            
            tables = cursor.fetchall()
            print(f"✅ Database connected")
            print(f"✅ Found tables: {[table[0] for table in tables]}")
            
            # Check table structure
            for table in ['people', 'weapon']:
                cursor.execute(f"""
                    SELECT column_name, data_type 
                    FROM information_schema.columns 
                    WHERE table_name = '{table}'
                    ORDER BY ordinal_position
                """)
                
                columns = cursor.fetchall()
                print(f"📋 {table} table columns:")
                for col in columns:
                    print(f"   - {col[0]}: {col[1]}")
            
            # Check if there's any data
            cursor.execute("SELECT COUNT(*) FROM people")
            people_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM weapon")
            weapon_count = cursor.fetchone()[0]
            
            print(f"📊 Current data count:")
            print(f"   - people: {people_count} records")
            print(f"   - weapon: {weapon_count} records")
            
            cursor.close()
            pool_manager.return_postgres_connection(conn)
            return True
            
        else:
            print("❌ Could not get database connection")
            return False
            
    except Exception as e:
        print(f"❌ Database error: {str(e)}")
        return False
    
    print()

def test_api_connection():
    """Test API connections"""
    print("=== API Connection Test ===")
    
    try:
        import httpx
        
        # Test people API
        people_url = f"{Config.PUBLIC_API_BASE_URL}/tymb/people/get-all"
        with httpx.Client(timeout=10.0) as client:
            response = client.post(people_url)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ People API working - Got {len(data)} records")
            else:
                print(f"❌ People API error - Status: {response.status_code}")
        
        # Test weapons API
        weapons_url = f"{Config.PUBLIC_API_BASE_URL}/tymb/weapons"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(weapons_url)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Weapons API working - Got {len(data)} records")
            else:
                print(f"❌ Weapons API error - Status: {response.status_code}")
                
    except Exception as e:
        print(f"❌ API connection error: {str(e)}")
    
    print()

def test_sync_process():
    """Test the actual sync process"""
    print("=== Sync Process Test ===")
    
    try:
        from maya_sawa.core.people import PeopleWeaponManager
        
        manager = PeopleWeaponManager()
        
        # Test fetching data
        print("Fetching people data...")
        people_data = manager.fetch_people_data()
        print(f"✅ Fetched {len(people_data)} people records")
        
        print("Fetching weapons data...")
        weapons_data = manager.fetch_weapons_data()
        print(f"✅ Fetched {len(weapons_data)} weapons records")
        
        # Test embedding generation
        if people_data:
            print("Testing embedding generation...")
            person = people_data[0]
            embedding_text = manager.create_people_text_for_embedding(person)
            print(f"📝 Sample embedding text: {embedding_text[:100]}...")
            
            embedding = manager.generate_embedding(embedding_text)
            if embedding:
                print(f"✅ Embedding generated - {len(embedding)} dimensions")
            else:
                print("❌ Failed to generate embedding")
        
        # Test database update (just one record)
        if people_data and weapons_data:
            print("Testing database update...")
            try:
                people_count = manager.update_people_table(people_data[:1])
                weapons_count = manager.update_weapons_table(weapons_data[:1])
                print(f"✅ Database update successful - People: {people_count}, Weapons: {weapons_count}")
            except Exception as e:
                print(f"❌ Database update failed: {str(e)}")
        
    except Exception as e:
        print(f"❌ Sync process error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print()

def main():
    """Run all diagnostic checks"""
    print("🔍 Maya Sawa Sync Diagnostic Tool")
    print("=" * 50)
    
    check_environment()
    check_openai()
    check_database()
    test_api_connection()
    test_sync_process()
    
    print("=" * 50)
    print("Diagnostic complete!")

if __name__ == "__main__":
    main() 