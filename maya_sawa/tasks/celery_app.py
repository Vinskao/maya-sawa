"""
Celery Application Configuration

This module configures the Celery application for async task processing.

Author: Maya Sawa Team
Version: 0.1.0
"""

import os
import logging
from celery import Celery

from ..core.config.config import Config

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery('maya_sawa')

# Configure Celery
celery_app.conf.update(
    # Broker settings
    broker_url=Config.CELERY_BROKER_URL,
    result_backend=Config.CELERY_RESULT_BACKEND,
    
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task result settings
    task_track_started=True,
    result_expires=3600,  # Results expire after 1 hour
    
    # Worker settings
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    
    # Queue settings
    task_default_queue='maya_sawa',
    task_queues={
        'maya_sawa': {
            'exchange': 'maya_sawa',
            'routing_key': 'maya_sawa',
        },
        'maya_v2': {
            'exchange': 'maya_v2',
            'routing_key': 'maya_v2',
        },
    },
    
    # Task routing
    task_routes={
        'maya_sawa.tasks.ai_tasks.*': {'queue': 'maya_sawa'},
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(['maya_sawa.tasks'])

# Debug task
@celery_app.task(bind=True)
def debug_task(self):
    """Debug task for testing Celery connectivity"""
    logger.info(f'Request: {self.request!r}')
    return {'status': 'ok', 'message': 'Debug task completed'}



