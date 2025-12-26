"""
Metrics Consumer Service
Migrated from Voyeur project (metrics/connect.py and metrics/store.py).
Consumes WebSocket metrics and stores them in MongoDB.
"""

import time
import logging
import json
import threading
from datetime import datetime

try:
    import pymongo
    import websocket
except ImportError:
    pymongo = None
    websocket = None
    logging.warning("pymongo or websocket-client not installed. MetricsConsumer will be disabled.")

from ..core.config.config import Config

logger = logging.getLogger(__name__)

class MetricsConsumer:
    """
    Consumer for external metrics via WebSocket, storing to MongoDB.
    """
    _instance = None
    
    def __init__(self):
        self.up_data = []
        self._running = False
        self._thread = None
        self.ws = None
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = MetricsConsumer()
        return cls._instance

    def store_message_in_mongo(self, message):
        """Store the message in MongoDB."""
        if not pymongo:
            return
            
        if not Config.MONGODB_URI:
            logger.debug("MONGODB_URI not set, skipping Mongo storage")
            return

        client = None
        try:
            # Creating new client per request as per original implementation
            # For high throughput, a persistent client should be used instead
            client = pymongo.MongoClient(Config.MONGODB_URI)
            db = client[Config.MONGODB_DB]
            collection = db[Config.MONGODB_COLLECTION]

            # 解析 JSON 訊息
            data = json.loads(message)
            
            # 添加時間戳
            data['timestamp'] = datetime.utcnow()
            
            # 儲存到 MongoDB
            collection.insert_one(data)
            logger.debug("Message stored in MongoDB successfully")
            
        except Exception as e:
            logger.error(f"Error storing message in MongoDB: {e}")
        finally:
            if client:
                client.close()

    def on_message(self, ws, message):
        """Handle messages received from the WebSocket server."""
        # Log reduced message for debug
        log_msg = message[:200] + "..." if len(message) > 200 else message
        logger.debug(f"Received metrics message: {log_msg}")
        
        if not message.strip():
            return

        try:
            data = json.loads(message)
            self.up_data.append(data)
            
            # Store in Mongo
            self.store_message_in_mongo(message)
            
            # Log specific statistics
            if 'data' in data and 'http.server.requests' in data['data']:
                requests = data['data']['http.server.requests']
                
                # Handle case where value might be a JSON string (e.g. error message or stringified JSON)
                if isinstance(requests, str):
                    try:
                        requests_json = json.loads(requests)
                        if isinstance(requests_json, dict) and 'measurements' in requests_json:
                            requests = requests_json
                        else:
                            # It's a string but doesn't look like the metrics object we expect
                            # or it's an error message like "URI is not absolute"
                            pass
                    except json.JSONDecodeError:
                        # acceptable if it's just a plain string error
                        pass

                if isinstance(requests, dict):
                    for measurement in requests.get('measurements', []):
                        if measurement.get('statistic') == 'COUNT':
                            # Use debug level to avoid spamming logs
                            logger.debug(f"HTTP Requests Count: {measurement.get('value', 0)}")
            
            if len(self.up_data) >= 10:
                logger.info(f"Received and stored {len(self.up_data)} metrics messages")
                self.up_data.clear()
                
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON message: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in on_message: {e}")

    def on_error(self, ws, error):
        logger.error(f"Metrics WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.info(f"Metrics WebSocket connection closed: {close_status_code} - {close_msg}")

    def on_open(self, ws):
        logger.info("Metrics WebSocket connection opened successfully")

    def _run_websocket(self):
        """Run WebSocket client loop"""
        websocket_url = Config.get_voyeur_websocket_url()
        if not websocket_url:
            logger.error("WebSocket URL not configured, stopping MetricsConsumer")
            self._running = False
            return
            
        logger.info(f"Starting Metrics WebSocket connection to: {websocket_url}")
        
        while self._running:
            try:
                self.ws = websocket.WebSocketApp(
                    websocket_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                
                # blocking call
                self.ws.run_forever()
                
                if self._running:
                    logger.info("WebSocket connection lost, attempting to reconnect in 5 seconds...")
                    time.sleep(5)
            except Exception as e:
                logger.error(f"WebSocket client loop error: {e}")
                if self._running:
                    time.sleep(5)

    def start(self):
        """Start the metrics consumer in a background thread"""
        if not websocket or not pymongo:
            logger.warning("Missing dependencies (websocket-client, pymongo). MetricsConsumer cannot start.")
            return

        if self._running:
            logger.warning("MetricsConsumer is already running")
            return
            
        websocket_url = Config.get_voyeur_websocket_url()
        if not websocket_url:
            logger.warning("WEBSOCKET_TYMB or WEBSOCKET_HOST/PORT not configured. MetricsConsumer cannot start.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_websocket, daemon=True)
        self._thread.start()
        logger.info("MetricsConsumer service started")

    def stop(self):
        """Stop the metrics consumer"""
        self._running = False
        if self.ws:
            self.ws.close()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("MetricsConsumer service stopped")
