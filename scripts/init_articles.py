import os
import glob
import re
import httpx
import asyncio
import json
from datetime import datetime

# Configuration
FRONTEND_CONTENT_PATH = "/Users/vinskao/001-project/ty-multiverse/ty-multiverse-frontend/src/content/work/*.md"
BACKEND_BATCH_URL = "http://localhost:8000/maya-sawa/paprika/articles/batch"

def parse_frontmatter(content):
    """Simple frontmatter parser"""
    match = re.match(r'^---(.*?)---(.*)', content, re.DOTALL)
    if not match:
        return {}, content
    
    fm_text = match.group(1)
    body = match.group(2).strip()
    
    metadata = {}
    for line in fm_text.strip().split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            metadata[key.strip()] = val.strip().strip('"').strip("'")
            
    return metadata, body

async def init_articles():
    files = glob.glob(FRONTEND_CONTENT_PATH)
    print(f"Found {len(files)} articles in {FRONTEND_CONTENT_PATH}")
    
    articles_payload = []
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                metadata, body = parse_frontmatter(content)
                
                # Extract metadata
                file_date_str = metadata.get('publishDate', datetime.now().isoformat())
                
                articles_payload.append({
                    "file_path": os.path.basename(file_path),
                    "content": body,
                    "file_date": file_date_str
                })
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
    
    print(f"Pushing {len(articles_payload)} articles to {BACKEND_BATCH_URL}...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                BACKEND_BATCH_URL,
                json=articles_payload,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                print("Successfully initialized articles!")
                result = response.json()
                print(f"Result: Created {result.get('created', 0)}, Updated {result.get('updated', 0)}, Skipped {result.get('skipped', 0)}")
            else:
                print(f"Failed to initialize articles. Status code: {response.status_code}")
                print(f"Response: {response.text}")
        except Exception as e:
            print(f"Error during push: {str(e)}")

if __name__ == "__main__":
    asyncio.run(init_articles())
