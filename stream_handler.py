"""
RTSP Stream Handler - Manages individual RTSP stream connections and frame capture
"""
import cv2
import threading
import time
from queue import Queue
from typing import Optional
import logging
import os
import traceback

logger = logging.getLogger(__name__)


class RTSPStreamHandler:
    """Handles a single RTSP stream with buffering and frame management"""
    
    def __init__(self, rtsp_url: str, stream_id: int, buffer_size: int = 2):
        self.rtsp_url = rtsp_url
        self.stream_id = stream_id
        self.buffer_size = buffer_size
        self.frame_queue = Queue(maxsize=buffer_size)
        
        self.cap = None
        self.is_running = False
        self.thread = None
        self.last_frame = None
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.stream_width = 0
        self.stream_height = 0
        self.fps = 0
        
    def connect(self) -> bool:
        """Establish connection to RTSP stream or local video file"""
        try:
            logger.info(f"Stream {self.stream_id}: Attempting to connect to: {self.rtsp_url}")
            # Handle file paths - convert backslashes to forward slashes for OpenCV
            source = self.rtsp_url
            
            # Check if it's a local file path
            if os.path.isfile(self.rtsp_url):
                # Convert Windows backslashes to forward slashes for OpenCV compatibility
                source = self.rtsp_url.replace('\\', '/')
                logger.info(f"Stream {self.stream_id}: Detected local file: {source}")
            elif not self.rtsp_url.startswith('rtsp://') and not self.rtsp_url.startswith('http'):
                # If path doesn't exist but looks like it should, try converting it
                if '\\' in self.rtsp_url:
                    source = self.rtsp_url.replace('\\', '/')
                    logger.warning(f"Stream {self.stream_id}: Converted path to forward slashes: {source}")
                    if not os.path.isfile(source.replace('/', '\\')):
                        logger.error(f"Stream {self.stream_id}: File not found: {self.rtsp_url}")
                        return False
            else:
                # For RTSP streams, use TCP transport for reliability (instead of UDP)
                if source.startswith('rtsp://'):
                    source = source.replace('rtsp://', 'rtsp://', 1)
                    # Use URL option for TCP transport
                    logger.info(f"Stream {self.stream_id}: Using TCP transport for RTSP stream")
            
            logger.debug(f"Stream {self.stream_id}: Creating VideoCapture with source: {source}")
            self.cap = cv2.VideoCapture(source)
            logger.debug(f"Stream {self.stream_id}: VideoCapture object created")
            
            # Set connection timeout and buffer size
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            
            # Try to skip corrupted/error frames at the beginning
            logger.debug(f"Stream {self.stream_id}: Attempting to read first frame (may skip error frames)...")
            max_retries = 5
            frame_attempts = 0
            ret = False
            frame = None
            
            while not ret and frame_attempts < max_retries:
                ret, frame = self.cap.read()
                if not ret:
                    frame_attempts += 1
                    if frame_attempts < max_retries:
                        logger.debug(f"Stream {self.stream_id}: Frame read failed (attempt {frame_attempts}/{max_retries}), retrying...")
                        time.sleep(0.1)  # Brief delay before retry
            
            if not ret:
                logger.warning(f"Stream {self.stream_id}: Failed to read any valid frames after {max_retries} attempts from {self.rtsp_url}")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                return False
            
            logger.debug(f"Stream {self.stream_id}: Valid frame read successfully (after {frame_attempts} attempts)")
            # Get stream properties
            self.stream_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.stream_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            logger.info(f"Stream {self.stream_id}: Connected to {self.rtsp_url} "
                       f"({self.stream_width}x{self.stream_height} @ {self.fps}fps)")
            
            self.last_frame = frame
            self.connection_attempts = 0
            return True
            
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Connection error - {str(e)}")
            logger.error(f"Stream {self.stream_id}: Traceback:\n{traceback.format_exc()}")
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
    
    def start(self):
        """Start the stream capture thread"""
        try:
            logger.info(f"Stream {self.stream_id}: start() called")
            
            if self.is_running:
                logger.warning(f"Stream {self.stream_id}: Already running, skipping start")
                return
            
            logger.info(f"Stream {self.stream_id}: Attempting connection...")
            if not self.connect():
                logger.error(f"Stream {self.stream_id}: Failed to connect, will not start capture thread")
                return
            
            logger.info(f"Stream {self.stream_id}: Connection successful, starting capture thread")
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            logger.info(f"Stream {self.stream_id}: Capture thread started successfully")
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Exception in start(): {str(e)}")
            logger.error(f"Stream {self.stream_id}: Traceback:\n{traceback.format_exc()}")
            self.is_running = False
    
    def _capture_loop(self):
        """Main capture loop running in separate thread"""
        logger.info(f"Stream {self.stream_id}: _capture_loop started")
        consecutive_failures = 0
        max_consecutive_failures = 30  # ~30 frames at 30fps
        
        while self.is_running:
            try:
                if self.cap is None:
                    logger.debug(f"Stream {self.stream_id}: cap is None, attempting reconnection")
                    if not self.connect():
                        time.sleep(1)
                        continue
                
                ret, frame = self.cap.read()
                
                if ret:
                    self.last_frame = frame
                    consecutive_failures = 0
                    
                    # Non-blocking put - discard oldest frame if queue is full
                    try:
                        self.frame_queue.put_nowait(frame)
                    except:
                        # Queue is full, remove oldest frame
                        try:
                            self.frame_queue.get_nowait()
                            self.frame_queue.put_nowait(frame)
                        except:
                            pass
                else:
                    consecutive_failures += 1
                    if consecutive_failures % 10 == 0:  # Log every 10 failures
                        logger.debug(f"Stream {self.stream_id}: Read failed {consecutive_failures} times")
                    if consecutive_failures > max_consecutive_failures:
                        logger.warning(f"Stream {self.stream_id}: Too many read failures, reconnecting...")
                        self.cap.release()
                        self.cap = None
                        consecutive_failures = 0
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Stream {self.stream_id}: Capture error - {str(e)}")
                logger.error(f"Stream {self.stream_id}: Traceback:\n{traceback.format_exc()}")
                consecutive_failures += 1
                time.sleep(1)
    
    def get_frame(self) -> Optional[tuple]:
        """Get the latest frame from the stream"""
        try:
            frame = self.frame_queue.get_nowait()
            self.last_frame = frame
            return frame
        except:
            return self.last_frame
    
    def stop(self):
        """Stop the stream capture"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.cap:
            self.cap.release()
        logger.info(f"Stream {self.stream_id}: Stopped")
