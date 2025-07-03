#!/usr/bin/env python3
"""
Stop all sync tasks immediately

This script stops all running sync tasks to prevent infinite loops.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def stop_sync():
    """Stop all sync tasks"""
    try:
        from maya_sawa.core.scheduler import ArticleSyncScheduler
        
        print("🛑 Stopping all sync tasks...")
        
        # Create scheduler instance and stop tasks
        scheduler = ArticleSyncScheduler()
        await scheduler.stop_periodic_sync()
        
        print("✅ All sync tasks stopped successfully!")
        
    except Exception as e:
        print(f"❌ Error stopping sync tasks: {str(e)}")

if __name__ == "__main__":
    asyncio.run(stop_sync()) 