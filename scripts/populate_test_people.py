#!/usr/bin/env python3
"""
Script to populate test people data for Maya Sawa system
"""

import os
import sys
import json
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_sawa.core.database.connection_pool import get_pool_manager

def populate_test_people():
    """Populate test people data"""

    # Test people data
    test_people = [
        {
            'name': 'Maya',
            'name_original': 'Maya',
            'code_name': 'AI Assistant',
            'physic_power': 50,
            'magic_power': 80,
            'utility_power': 90,
            'race': 'AI',
            'gender': 'F',
            'height_cm': 170,
            'weight_kg': 60,
            'profession': 'AI Assistant',
            'combat': 'Intelligence',
            'personality': 'Helpful, knowledgeable, friendly',
            'interest': 'Technology, learning, helping others',
            'likes': 'Programming, data analysis, problem solving',
            'dislikes': 'Errors, inefficiency, confusion',
            'faction': 'Maya Sawa',
            'army_name': 'AI Division',
            'dept_name': 'Support',
            'age': 25,
            'updated_at': datetime.now()
        },
        {
            'name': 'Sorane',
            'name_original': 'Sorane',
            'code_name': 'Warrior Princess',
            'physic_power': 95,
            'magic_power': 70,
            'utility_power': 60,
            'race': 'Human',
            'gender': 'F',
            'height_cm': 175,
            'weight_kg': 65,
            'profession': 'Warrior',
            'combat': 'Swordsmanship',
            'personality': 'Brave, determined, protective',
            'interest': 'Combat training, strategy, leadership',
            'likes': 'Fighting, honor, loyalty',
            'dislikes': 'Cowardice, betrayal, injustice',
            'faction': 'Kingdom',
            'army_name': 'Royal Guard',
            'dept_name': 'Combat',
            'age': 28,
            'updated_at': datetime.now()
        },
        {
            'name': 'Alex',
            'name_original': 'Alex',
            'code_name': 'Tech Genius',
            'physic_power': 40,
            'magic_power': 60,
            'utility_power': 95,
            'race': 'Human',
            'gender': 'M',
            'height_cm': 180,
            'weight_kg': 75,
            'profession': 'Inventor',
            'combat': 'Technology',
            'personality': 'Innovative, analytical, curious',
            'interest': 'Inventions, research, technology',
            'likes': 'Building things, solving puzzles, learning',
            'dislikes': 'Ignorance, stagnation, bureaucracy',
            'faction': 'Inventors Guild',
            'army_name': 'Tech Corps',
            'dept_name': 'Research',
            'age': 32,
            'updated_at': datetime.now()
        },
        {
            'name': 'Luna',
            'name_original': 'Luna',
            'code_name': 'Mystic Healer',
            'physic_power': 45,
            'magic_power': 90,
            'utility_power': 85,
            'race': 'Elf',
            'gender': 'F',
            'height_cm': 165,
            'weight_kg': 55,
            'profession': 'Healer',
            'combat': 'Magic',
            'personality': 'Compassionate, wise, serene',
            'interest': 'Healing, meditation, nature',
            'likes': 'Peace, harmony, helping others',
            'dislikes': 'Violence, suffering, darkness',
            'faction': 'Mystic Order',
            'army_name': 'Healing Circle',
            'dept_name': 'Medical',
            'age': 150,
            'updated_at': datetime.now()
        },
        {
            'name': 'Drake',
            'name_original': 'Drake',
            'code_name': 'Shadow Assassin',
            'physic_power': 80,
            'magic_power': 40,
            'utility_power': 75,
            'race': 'Human',
            'gender': 'M',
            'height_cm': 185,
            'weight_kg': 85,
            'profession': 'Assassin',
            'combat': 'Stealth',
            'personality': 'Mysterious, focused, independent',
            'interest': 'Stealth, reconnaissance, precision',
            'likes': 'Night operations, strategy, solitude',
            'dislikes': 'Crowds, noise, betrayal',
            'faction': 'Shadow Guild',
            'army_name': 'Special Operations',
            'dept_name': 'Intelligence',
            'age': 35,
            'updated_at': datetime.now()
        }
    ]

    pool_manager = get_pool_manager()
    conn = None

    try:
        conn = pool_manager.get_people_postgres_connection()
        cursor = conn.cursor()

        for person in test_people:
            # Check if person already exists
            cursor.execute("SELECT name FROM people WHERE name = %s", (person['name'],))
            if cursor.fetchone():
                print(f"Person {person['name']} already exists, skipping...")
                continue

            # Insert person data
            query = """
            INSERT INTO people (
                name_original, code_name, name, physic_power, magic_power, utility_power,
                race, gender, height_cm, weight_kg, profession, combat, personality,
                interest, likes, dislikes, faction, army_name, dept_name, age, updated_at
            ) VALUES (
                %(name_original)s, %(code_name)s, %(name)s, %(physic_power)s, %(magic_power)s, %(utility_power)s,
                %(race)s, %(gender)s, %(height_cm)s, %(weight_kg)s, %(profession)s, %(combat)s, %(personality)s,
                %(interest)s, %(likes)s, %(dislikes)s, %(faction)s, %(army_name)s, %(dept_name)s, %(age)s, %(updated_at)s
            )
            """

            cursor.execute(query, person)
            print(f"Inserted person: {person['name']}")

        conn.commit()
        print(f"Successfully populated {len(test_people)} test people")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error populating test people: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            pool_manager.return_people_postgres_connection(conn)

if __name__ == "__main__":
    populate_test_people()
