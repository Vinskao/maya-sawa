"""
Tasks Module

This module contains Celery tasks for asynchronous processing.
"""

from .celery_app import celery_app

__all__ = ['celery_app']



