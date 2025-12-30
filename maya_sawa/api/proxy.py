"""
External API Proxy Service
Provides proxy endpoints for external APIs to bypass CORS restrictions.
"""

import logging
import httpx
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# HTTP client with extended timeout configuration for slow APIs
# Some external APIs (like Heroku) can be slow to respond
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(60.0, connect=10.0),  # 60s total, 10s connect
    follow_redirects=True
)


@router.get("/leetcode-stats/{username}")
async def get_leetcode_stats(
    username: str,
    api_url: Optional[str] = Query(
        default="https://leetcode-stats-api.herokuapp.com",
        description="LeetCode Stats API base URL"
    )
):
    """
    Proxy endpoint for LeetCode statistics API.
    
    This endpoint acts as a proxy to bypass CORS restrictions when
    fetching LeetCode user statistics from the frontend.
    
    Args:
        username: LeetCode username
        api_url: Base URL of the LeetCode Stats API (default: herokuapp.com)
    
    Returns:
        JSON response from LeetCode Stats API
        
    Example:
        GET /maya-sawa/proxy/leetcode-stats/Vinskao
    """
    try:
        # Construct the full API URL
        full_url = f"{api_url.rstrip('/')}/{username}"
        
        logger.info(f"Proxying LeetCode stats request for user: {username}")
        logger.debug(f"Requesting URL: {full_url}")
        
        # Make the request to the external API with retry logic
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                logger.debug(f"Attempt {attempt + 1}/{max_retries + 1} to fetch LeetCode stats")
                response = await http_client.get(full_url)
                break  # Success, exit retry loop
            except httpx.TimeoutException:
                if attempt < max_retries:
                    logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                    continue
                else:
                    raise  # Re-raise on final attempt
        
        # Check if the request was successful
        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"LeetCode user '{username}' not found"
            )
        
        if response.status_code != 200:
            logger.error(f"LeetCode API returned status {response.status_code}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"External API error: {response.status_code}"
            )
        
        # Return the JSON response
        return response.json()
        
    except httpx.TimeoutException:
        logger.error(f"Timeout when requesting LeetCode stats for {username}")
        raise HTTPException(
            status_code=504,
            detail="Request to LeetCode API timed out"
        )
    except httpx.RequestError as e:
        logger.error(f"Request error: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to LeetCode API: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in leetcode-stats proxy: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal proxy error: {str(e)}"
        )


@router.on_event("shutdown")
async def shutdown_event():
    """Clean up HTTP client on shutdown"""
    await http_client.aclose()

