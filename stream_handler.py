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
                # RTSP stream - will attempt connection as-is
                logger.debug(f"Stream {self.stream_id}: RTSP stream URL detected")
            
            logger.debug(f"Stream {self.stream_id}: Creating VideoCapture with source: {source}")
            
            # For RTSP streams, explicitly set the backend to avoid CAP_IMAGES fallback
            if self.rtsp_url.startswith('rtsp://'):
                # Use CAP_FFMPEG backend for RTSP streams
                self.cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
                logger.debug(f"Stream {self.stream_id}: Using CAP_FFMPEG backend for RTSP stream")
            else:
                self.cap = cv2.VideoCapture(source)
            
            logger.debug(f"Stream {self.stream_id}: VideoCapture object created")
            
            # Set connection timeout and buffer size
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            
            # Additional properties for better H.264 decoding robustness
            # Enable low-latency mode to skip corrupted frames faster
            self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)  # 5 sec timeout on open
            
            # For RTSP streams with H.264 issues, try hardware acceleration if available
            # This may help skip corrupted frames more gracefully
            try:
                # Try CUDA acceleration (if available)
                self.cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_CUDA)
                logger.debug(f"Stream {self.stream_id}: Enabled CUDA acceleration for H.264 decoding")
            except:
                try:
                    # Fallback to MFX (Intel Quick Sync) if CUDA unavailable
                    self.cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_MFX)
                    logger.debug(f"Stream {self.stream_id}: Enabled MFX acceleration for H.264 decoding")
                except:
                    logger.debug(f"Stream {self.stream_id}: Hardware acceleration not available, using software decoding")
            
            # For RTSP streams with severe H.264 decoder issues, let the stream warm up
            # before attempting to read. This gives the server time to stabilize output.
            logger.debug(f"Stream {self.stream_id}: Waiting 2s for stream stabilization...")
            time.sleep(2)
            
            # Try to skip corrupted/error frames at the beginning
            # Some RTSP streams have H.264 decoder errors at startup (PPS/slice header errors)
            # We need many retries with longer delays to let the stream recover
            logger.debug(f"Stream {self.stream_id}: Attempting to read first frame (may skip error frames)...")
            max_retries = 10000  # Increased retries for grossly corrupted streams
            frame_attempts = 0
            ret = False
            frame = None
            
            while not ret and frame_attempts < max_retries:
                ret, frame = self.cap.read()
                if not ret:
                    frame_attempts += 1
                    if frame_attempts < max_retries:
                        # Aggressive backoff: more patient with corrupted streams
                        if frame_attempts <= 10:
                            delay = 0.05  # Quick initial retries
                        elif frame_attempts <= 50:
                            delay = 0.1
                        elif frame_attempts <= 200:
                            delay = 0.2
                        else:
                            delay = 0.5
                        
                        if frame_attempts % 100 == 0:
                            logger.debug(f"Stream {self.stream_id}: Frame read attempts: {frame_attempts}/{max_retries}, still waiting for valid H.264 frames...")
                        time.sleep(delay)
            
            if not ret:
                error_msg = f"Stream {self.stream_id}: Failed to read any valid frames after {max_retries} attempts from {self.rtsp_url}"
                if self.rtsp_url.startswith('rtsp://'):
                    error_msg += "\n  → RTSP Connection Issue: Verify the server is running and accessible"
                    error_msg += "\n  → Check: Is the RTSP server at this address running?"
                    error_msg += "\n  → Alternative: Enable dev_mode in config.yaml to use test videos instead"
                logger.warning(error_msg)
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
            error_msg = f"Stream {self.stream_id}: Connection error - {str(e)}"
            if self.rtsp_url.startswith('rtsp://') and 'Connection refused' in str(e):
                error_msg += "\n  → RTSP server is not responding (Connection refused)"
                error_msg += "\n  → Ensure the RTSP server is running on the specified host and port"
                error_msg += "\n  → For development, use dev_mode: true in config.yaml to test with local files"
            logger.error(error_msg)
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
