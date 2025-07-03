"""
People and Weapons Data Management Module

This module handles fetching people and weapons data from external APIs
and updating PostgreSQL tables with embeddings for semantic search.

Features:
- Fetch people data from API
- Fetch weapons data from API  
- Generate embeddings for semantic search
- Update PostgreSQL tables with data and embeddings
- Handle data validation and error processing

Author: Maya Sawa Team
Version: 0.1.0
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import httpx
from psycopg2.extras import RealDictCursor
import psycopg2

# Import connection pool
from .connection_pool import get_pool_manager

# Import OpenAI for embeddings
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI library not available. Embeddings will not be generated.")

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class PeopleWeaponManager:
    """
    People and Weapons Data Manager
    
    Handles fetching data from APIs and updating PostgreSQL tables
    with embeddings for semantic search capabilities.
    """
    
    def __init__(self):
        """Initialize the manager with connection pool and OpenAI client"""
        self.pool_manager = get_pool_manager()
        
        # Initialize OpenAI client for embeddings
        if OPENAI_AVAILABLE:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                self.openai_client = OpenAI(api_key=api_key)
            else:
                logger.warning("OPENAI_API_KEY not found. Embeddings will not be generated.")
                self.openai_client = None
        else:
            self.openai_client = None
    
    def fetch_people_data(self) -> List[Dict[str, Any]]:
        """
        Fetch people data from the API
        
        Returns:
            List[Dict[str, Any]]: List of people data
        """
        url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-all"
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Successfully fetched {len(data)} people records")
                return data
        except Exception as e:
            logger.error(f"Failed to fetch people data: {str(e)}")
            raise
    
    def fetch_weapons_data(self) -> List[Dict[str, Any]]:
        """
        Fetch weapons data from the API
        
        Returns:
            List[Dict[str, Any]]: List of weapons data
        """
        url = "https://peoplesystem.tatdvsonorth.com/tymb/weapons"
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Successfully fetched {len(data)} weapons records")
                return data
        except Exception as e:
            logger.error(f"Failed to fetch weapons data: {str(e)}")
            raise
    
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for given text using OpenAI
        
        Args:
            text (str): Text to generate embedding for
            
        Returns:
            Optional[List[float]]: Embedding vector or None if failed
        """
        if not self.openai_client or not text:
            return None
        
        # Limit text length to prevent excessive token usage
        max_text_length = 8000  # OpenAI text-embedding-ada-002 limit is 8191 tokens
        if len(text) > max_text_length:
            text = text[:max_text_length]
            logger.warning(f"Text truncated to {max_text_length} characters for embedding generation")
        
        try:
            response = self.openai_client.embeddings.create(
                model="text-embedding-ada-002",
                input=text
            )
            embedding = response.data[0].embedding
            
            # Validate embedding dimensions
            if len(embedding) != 1536:
                logger.warning(f"Unexpected embedding dimensions: {len(embedding)}, expected 1536")
            
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            return None
    
    def create_people_text_for_embedding(self, person: Dict[str, Any]) -> str:
        """
        Create text representation of person data for embedding generation
        
        Args:
            person (Dict[str, Any]): Person data
            
        Returns:
            str: Text representation for embedding
        """
        text_parts = []
        
        # Basic information
        if person.get('name'):
            text_parts.append(f"Name: {person['name']}")
        if person.get('nameOriginal'):
            text_parts.append(f"Original Name: {person['nameOriginal']}")
        if person.get('codeName'):
            text_parts.append(f"Code Name: {person['codeName']}")
        
        # Physical attributes
        if person.get('race'):
            text_parts.append(f"Race: {person['race']}")
        if person.get('gender'):
            text_parts.append(f"Gender: {person['gender']}")
        if person.get('heightCm'):
            text_parts.append(f"Height: {person['heightCm']}cm")
        if person.get('weightKg'):
            text_parts.append(f"Weight: {person['weightKg']}kg")
        if person.get('age'):
            text_parts.append(f"Age: {person['age']}")
        
        # Power stats
        if person.get('physicPower'):
            text_parts.append(f"Physical Power: {person['physicPower']}")
        if person.get('magicPower'):
            text_parts.append(f"Magic Power: {person['magicPower']}")
        if person.get('utilityPower'):
            text_parts.append(f"Utility Power: {person['utilityPower']}")
        
        # Personal details
        if person.get('profession'):
            text_parts.append(f"Profession: {person['profession']}")
        if person.get('job'):
            text_parts.append(f"Job: {person['job']}")
        if person.get('personality'):
            text_parts.append(f"Personality: {person['personality']}")
        if person.get('interest'):
            text_parts.append(f"Interests: {person['interest']}")
        if person.get('likes'):
            text_parts.append(f"Likes: {person['likes']}")
        if person.get('dislikes'):
            text_parts.append(f"Dislikes: {person['dislikes']}")
        if person.get('favoriteFoods'):
            text_parts.append(f"Favorite Foods: {person['favoriteFoods']}")
        
        # Organizational info
        if person.get('faction'):
            text_parts.append(f"Faction: {person['faction']}")
        if person.get('armyName'):
            text_parts.append(f"Army: {person['armyName']}")
        if person.get('deptName'):
            text_parts.append(f"Department: {person['deptName']}")
        
        return " | ".join(text_parts)
    
    def create_weapon_text_for_embedding(self, weapon: Dict[str, Any]) -> str:
        """
        Create text representation of weapon data for embedding generation
        
        Args:
            weapon (Dict[str, Any]): Weapon data
            
        Returns:
            str: Text representation for embedding
        """
        text_parts = []
        
        # Basic weapon info
        if weapon.get('name'):
            text_parts.append(f"Owner: {weapon['name']}")
        if weapon.get('weapon'):
            text_parts.append(f"Weapon: {weapon['weapon']}")
        if weapon.get('attributes'):
            text_parts.append(f"Attributes: {weapon['attributes']}")
        
        # Damage stats
        if weapon.get('baseDamage'):
            text_parts.append(f"Base Damage: {weapon['baseDamage']}")
        if weapon.get('bonusDamage'):
            text_parts.append(f"Bonus Damage: {weapon['bonusDamage']}")
        
        # Attributes
        if weapon.get('bonusAttributes'):
            text_parts.append(f"Bonus Attributes: {', '.join(weapon['bonusAttributes'])}")
        if weapon.get('stateAttributes'):
            text_parts.append(f"State Attributes: {', '.join(weapon['stateAttributes'])}")
        
        return " | ".join(text_parts)
    
    def update_people_table(self, people_data: List[Dict[str, Any]], max_time_seconds: int = 60) -> int:
        """
        Update people table with fetched data and embeddings
        
        Args:
            people_data (List[Dict[str, Any]]): List of people data
            max_time_seconds (int): Maximum time to process in seconds (default: 60)
            
        Returns:
            int: Number of records updated
        """
        import time
        
        conn = None
        updated_count = 0
        embedding_count = 0
        start_time = time.time()
        total_records = len(people_data)
        
        try:
            logger.info(f"Starting to process {total_records} people records (max time: {max_time_seconds}s)")
            
            conn = self.pool_manager.get_postgres_connection()
            cursor = conn.cursor()
            
            for i, person in enumerate(people_data):
                # Check time limit
                elapsed_time = time.time() - start_time
                if elapsed_time >= max_time_seconds:
                    logger.info(f"Time limit reached ({elapsed_time:.1f}s). Processed {i}/{total_records} records")
                    break
                
                try:
                    # Generate embedding text
                    embedding_text = self.create_people_text_for_embedding(person)
                    embedding = self.generate_embedding(embedding_text)
                    
                    if embedding:
                        embedding_count += 1
                    
                    # Prepare data for insertion/update
                    data = {
                        'name_original': person.get('nameOriginal'),
                        'code_name': person.get('codeName'),
                        'name': person.get('name'),
                        'physic_power': person.get('physicPower'),
                        'magic_power': person.get('magicPower'),
                        'utility_power': person.get('utilityPower'),
                        'dob': person.get('dob'),
                        'race': person.get('race'),
                        'attributes': person.get('attributes'),
                        'gender': person.get('gender'),
                        'ass_size': person.get('assSize'),
                        'boobs_size': person.get('boobsSize'),
                        'height_cm': person.get('heightCm'),
                        'weight_kg': person.get('weightKg'),
                        'profession': person.get('profession'),
                        'combat': person.get('combat'),
                        'favorite_foods': person.get('favoriteFoods'),
                        'job': person.get('job'),
                        'physics': person.get('physics'),
                        'known_as': person.get('knownAs'),
                        'personality': person.get('personality'),
                        'interest': person.get('interest'),
                        'likes': person.get('likes'),
                        'dislikes': person.get('dislikes'),
                        'concubine': person.get('concubine'),
                        'faction': person.get('faction'),
                        'army_id': person.get('armyId'),
                        'army_name': person.get('armyName'),
                        'dept_id': person.get('deptId'),
                        'dept_name': person.get('deptName'),
                        'origin_army_id': person.get('originArmyId'),
                        'origin_army_name': person.get('originArmyName'),
                        'gave_birth': person.get('gaveBirth'),
                        'email': person.get('email'),
                        'age': person.get('age'),
                        'proxy': person.get('proxy'),
                        'embedding': embedding,
                        'updated_at': datetime.now()
                    }
                    
                    # Use UPSERT (INSERT ... ON CONFLICT UPDATE)
                    query = """
                    INSERT INTO people (
                        name_original, code_name, name, physic_power, magic_power, utility_power,
                        dob, race, attributes, gender, ass_size, boobs_size, height_cm, weight_kg,
                        profession, combat, favorite_foods, job, physics, known_as, personality,
                        interest, likes, dislikes, concubine, faction, army_id, army_name,
                        dept_id, dept_name, origin_army_id, origin_army_name, gave_birth,
                        email, age, proxy, embedding, updated_at
                    ) VALUES (
                        %(name_original)s, %(code_name)s, %(name)s, %(physic_power)s, %(magic_power)s, %(utility_power)s,
                        %(dob)s, %(race)s, %(attributes)s, %(gender)s, %(ass_size)s, %(boobs_size)s, %(height_cm)s, %(weight_kg)s,
                        %(profession)s, %(combat)s, %(favorite_foods)s, %(job)s, %(physics)s, %(known_as)s, %(personality)s,
                        %(interest)s, %(likes)s, %(dislikes)s, %(concubine)s, %(faction)s, %(army_id)s, %(army_name)s,
                        %(dept_id)s, %(dept_name)s, %(origin_army_id)s, %(origin_army_name)s, %(gave_birth)s,
                        %(email)s, %(age)s, %(proxy)s, %(embedding)s, %(updated_at)s
                    )
                    ON CONFLICT (name) DO UPDATE SET
                        name_original = EXCLUDED.name_original,
                        code_name = EXCLUDED.code_name,
                        physic_power = EXCLUDED.physic_power,
                        magic_power = EXCLUDED.magic_power,
                        utility_power = EXCLUDED.utility_power,
                        dob = EXCLUDED.dob,
                        race = EXCLUDED.race,
                        attributes = EXCLUDED.attributes,
                        gender = EXCLUDED.gender,
                        ass_size = EXCLUDED.ass_size,
                        boobs_size = EXCLUDED.boobs_size,
                        height_cm = EXCLUDED.height_cm,
                        weight_kg = EXCLUDED.weight_kg,
                        profession = EXCLUDED.profession,
                        combat = EXCLUDED.combat,
                        favorite_foods = EXCLUDED.favorite_foods,
                        job = EXCLUDED.job,
                        physics = EXCLUDED.physics,
                        known_as = EXCLUDED.known_as,
                        personality = EXCLUDED.personality,
                        interest = EXCLUDED.interest,
                        likes = EXCLUDED.likes,
                        dislikes = EXCLUDED.dislikes,
                        concubine = EXCLUDED.concubine,
                        faction = EXCLUDED.faction,
                        army_id = EXCLUDED.army_id,
                        army_name = EXCLUDED.army_name,
                        dept_id = EXCLUDED.dept_id,
                        dept_name = EXCLUDED.dept_name,
                        origin_army_id = EXCLUDED.origin_army_id,
                        origin_army_name = EXCLUDED.origin_army_name,
                        gave_birth = EXCLUDED.gave_birth,
                        email = EXCLUDED.email,
                        age = EXCLUDED.age,
                        proxy = EXCLUDED.proxy,
                        embedding = EXCLUDED.embedding,
                        updated_at = EXCLUDED.updated_at
                    """
                    
                    cursor.execute(query, data)
                    updated_count += 1
                    
                    # Log progress every 10 records or every 10 seconds
                    if (i + 1) % 10 == 0 or elapsed_time % 10 < 1:
                        progress = (i + 1) / total_records * 100
                        logger.info(f"Progress: {i + 1}/{total_records} ({progress:.1f}%) - {elapsed_time:.1f}s elapsed")
                    
                except Exception as e:
                    logger.error(f"Failed to process person {person.get('name', 'unknown')}: {str(e)}")
                    continue  # Continue with next record instead of failing completely
            
            conn.commit()
            final_time = time.time() - start_time
            logger.info(f"People sync completed: {updated_count}/{total_records} records processed in {final_time:.1f}s with {embedding_count} embeddings")
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to update people table: {str(e)}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.pool_manager.return_postgres_connection(conn)
        

    
    def update_weapons_table(self, weapons_data: List[Dict[str, Any]], max_time_seconds: int = 60) -> int:
        """
        Update weapons table with fetched data and embeddings
        
        Args:
            weapons_data (List[Dict[str, Any]]): List of weapons data
            max_time_seconds (int): Maximum time to process in seconds (default: 60)
            
        Returns:
            int: Number of records updated
        """
        import time
        
        conn = None
        updated_count = 0
        embedding_count = 0
        start_time = time.time()
        total_records = len(weapons_data)
        
        try:
            logger.info(f"Starting to process {total_records} weapons records (max time: {max_time_seconds}s)")
            
            conn = self.pool_manager.get_postgres_connection()
            cursor = conn.cursor()
            
            for i, weapon in enumerate(weapons_data):
                # Check time limit
                elapsed_time = time.time() - start_time
                if elapsed_time >= max_time_seconds:
                    logger.info(f"Time limit reached ({elapsed_time:.1f}s). Processed {i}/{total_records} records")
                    break
                
                try:
                    # Generate embedding text
                    embedding_text = self.create_weapon_text_for_embedding(weapon)
                    embedding = self.generate_embedding(embedding_text)
                    
                    if embedding:
                        embedding_count += 1
                    
                    # Prepare data for insertion/update
                    data = {
                        'name': weapon.get('name'),
                        'weapon': weapon.get('weapon'),
                        'attributes': weapon.get('attributes'),
                        'base_damage': weapon.get('baseDamage'),
                        'bonus_damage': weapon.get('bonusDamage'),
                        'bonus_attributes': weapon.get('bonusAttributes'),
                        'state_attributes': weapon.get('stateAttributes'),
                        'embedding': embedding,
                        'updated_at': datetime.now()
                    }
                    
                    # Use UPSERT (INSERT ... ON CONFLICT UPDATE)
                    query = """
                    INSERT INTO weapon (
                        name, weapon, attributes, base_damage, bonus_damage,
                        bonus_attributes, state_attributes, embedding, updated_at
                    ) VALUES (
                        %(name)s, %(weapon)s, %(attributes)s, %(base_damage)s, %(bonus_damage)s,
                        %(bonus_attributes)s, %(state_attributes)s, %(embedding)s, %(updated_at)s
                    )
                    ON CONFLICT (name, weapon) DO UPDATE SET
                        attributes = EXCLUDED.attributes,
                        base_damage = EXCLUDED.base_damage,
                        bonus_damage = EXCLUDED.bonus_damage,
                        bonus_attributes = EXCLUDED.bonus_attributes,
                        state_attributes = EXCLUDED.state_attributes,
                        embedding = EXCLUDED.embedding,
                        updated_at = EXCLUDED.updated_at
                    """
                    
                    cursor.execute(query, data)
                    updated_count += 1
                    
                    # Log progress every 10 records or every 10 seconds
                    if (i + 1) % 10 == 0 or elapsed_time % 10 < 1:
                        progress = (i + 1) / total_records * 100
                        logger.info(f"Progress: {i + 1}/{total_records} ({progress:.1f}%) - {elapsed_time:.1f}s elapsed")
                    
                except Exception as e:
                    logger.error(f"Failed to process weapon {weapon.get('weapon', 'unknown')}: {str(e)}")
                    continue  # Continue with next record instead of failing completely
            
            conn.commit()
            final_time = time.time() - start_time
            logger.info(f"Weapons sync completed: {updated_count}/{total_records} records processed in {final_time:.1f}s with {embedding_count} embeddings")
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to update weapons table: {str(e)}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                self.pool_manager.return_postgres_connection(conn)
        
        return updated_count
    
    def sync_all_data(self, max_time_seconds: int = 60) -> Dict[str, int]:
        """
        Sync all data from APIs to PostgreSQL tables
        
        Args:
            max_time_seconds (int): Maximum time to process in seconds (default: 60)
            
        Returns:
            Dict[str, int]: Dictionary with counts of updated records
        """
        import time
        
        start_time = time.time()
        logger.info(f"Starting data synchronization (max time: {max_time_seconds}s)...")
        
        try:
            # Fetch data from APIs
            people_data = self.fetch_people_data()
            weapons_data = self.fetch_weapons_data()
            
            # Calculate remaining time for each table
            elapsed_time = time.time() - start_time
            remaining_time = max(0, max_time_seconds - elapsed_time)
            
            # Update tables with time limits
            people_count = self.update_people_table(people_data, max_time_seconds=int(remaining_time * 0.6))  # 60% of remaining time
            weapons_count = self.update_weapons_table(weapons_data, max_time_seconds=int(remaining_time * 0.4))  # 40% of remaining time
            
            total_time = time.time() - start_time
            
            result = {
                'people_updated': people_count,
                'weapons_updated': weapons_count,
                'total_updated': people_count + weapons_count,
                'total_time_seconds': round(total_time, 1),
                'people_data_count': len(people_data),
                'weapons_data_count': len(weapons_data)
            }
            
            logger.info(f"Data synchronization completed in {total_time:.1f}s: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Data synchronization failed: {str(e)}")
            raise

# ==================== 全局管理器實例 ====================
_manager = None

def get_manager():
    """
    Get the global PeopleWeaponManager instance (lazy loading)
    
    Returns:
        PeopleWeaponManager: Global manager instance
    """
    global _manager
    if _manager is None:
        _manager = PeopleWeaponManager()
    return _manager

def sync_data(max_time_seconds: int = 60):
    """
    Convenience function to sync all data
    
    Args:
        max_time_seconds (int): Maximum time to process in seconds (default: 60)
        
    Returns:
        Dict[str, int]: Dictionary with counts of updated records
    """
    manager = get_manager()
    return manager.sync_all_data(max_time_seconds=max_time_seconds)
