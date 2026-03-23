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
            
            self.cap = cv2.VideoCapture(source)
            
            # Set connection timeout and buffer size
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            
            # Try to read one frame to verify connection
            ret, frame = self.cap.read()
            if not ret:
                logger.warning(f"Stream {self.stream_id}: Failed to read frame from {self.rtsp_url}")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                return False
            
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
            if self.cap:
                self.cap.release()
                self.cap = None
            return False
    
    def start(self):
        """Start the stream capture thread"""
        if self.is_running:
            return
        
        if not self.connect():
            logger.error(f"Stream {self.stream_id}: Failed to connect")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        logger.info(f"Stream {self.stream_id}: Capture thread started")
    
    def _capture_loop(self):
        """Main capture loop running in separate thread"""
        consecutive_failures = 0
        max_consecutive_failures = 30  # ~30 frames at 30fps
        
        while self.is_running:
            try:
                if self.cap is None:
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
                    if consecutive_failures > max_consecutive_failures:
                        logger.warning(f"Stream {self.stream_id}: Too many read failures, reconnecting...")
                        self.cap.release()
                        self.cap = None
                        consecutive_failures = 0
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"Stream {self.stream_id}: Capture error - {str(e)}")
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
