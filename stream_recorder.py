"""
Stream Recorder - Per-stream MP4 recording with hourly rotation
"""
import cv2
import threading
import time
import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class StreamRecorder:
    """Records a single stream with configurable chunk rotation"""
    
    def __init__(self, stream_source: str, stream_id: int, output_dir: str,
                 chunk_duration_minutes: int = 60, total_rotation_minutes: int = 1440,
                 fps: int = 30, width: int = 1920, height: int = 1080):
        self.stream_source = stream_source
        self.stream_id = stream_id
        self.output_dir = output_dir
        self.chunk_duration_minutes = chunk_duration_minutes
        self.total_rotation_minutes = total_rotation_minutes
        self.total_chunks = max(1, total_rotation_minutes // chunk_duration_minutes)
        
        self.fps = fps
        self.width = width
        self.height = height
        
        self.capture = None
        self.video_writer = None
        self.current_file = None
        self.current_chunk = 0
        self.frame_count = 0
        self.is_recording = False
        self.thread = None
        self.last_rotation_time = None
        self.lock = threading.Lock()
        
        logger.info(f"Stream {stream_id}: Configured for {chunk_duration_minutes}min chunks, "
                   f"{total_rotation_minutes}min total rotation ({self.total_chunks} files)")
    
    def start(self):
        """Start recording thread"""
        if self.is_recording:
            return
        
        # Create output directory
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        self.is_recording = True
        self.last_rotation_time = time.time()
        self.current_chunk = 0
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()
        logger.info(f"Stream {self.stream_id}: Recording started")
    
    def stop(self):
        """Stop recording gracefully"""
        self.is_recording = False
        if self.thread:
            self.thread.join(timeout=5)
        self._finalize_writer()
        if self.capture:
            self.capture.release()
        logger.info(f"Stream {self.stream_id}: Recording stopped")
    
    def _connect_stream(self) -> bool:
        """Establish connection to stream"""
        try:
            source = self.stream_source
            
            # Handle local file paths
            if os.path.isfile(self.stream_source):
                source = self.stream_source.replace('\\', '/')
                logger.info(f"Stream {self.stream_id}: Using local file: {source}")
            
            self.capture = cv2.VideoCapture(source)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Try to skip corrupted/error frames at the beginning
            # Some RTSP streams have H.264 decoder errors at startup (PPS/slice header errors)
            # We need multiple retries with longer delays to let the stream stabilize
            logger.debug(f"Stream {self.stream_id}: Attempting to read first frame (may skip error frames)...")
            max_retries = 15  # Increased retries for stream startup stabilization
            frame_attempts = 0
            ret = False
            frame = None
            
            while not ret and frame_attempts < max_retries:
                ret, frame = self.capture.read()
                if not ret:
                    frame_attempts += 1
                    if frame_attempts < max_retries:
                        delay = 0.2 if frame_attempts < 5 else 0.5  # Longer delay after initial attempts
                        logger.debug(f"Stream {self.stream_id}: Frame read failed (attempt {frame_attempts}/{max_retries}), retrying in {delay}s...")
                        time.sleep(delay)
            
            if not ret:
                logger.warning(f"Stream {self.stream_id}: Failed to read any valid frames after {max_retries} attempts")
                self.capture.release()
                self.capture = None
                return False
            
            logger.debug(f"Stream {self.stream_id}: Valid frame read successfully (after {frame_attempts} attempts)")
            
            # Detect actual FPS from stream
            detected_fps = self.capture.get(cv2.CAP_PROP_FPS)
            if detected_fps > 0 and detected_fps != self.fps:
                logger.info(f"Stream {self.stream_id}: Detected FPS {detected_fps}, using instead of configured {self.fps}")
                self.fps = detected_fps
            else:
                logger.info(f"Stream {self.stream_id}: Using configured FPS {self.fps}")
            
            logger.info(f"Stream {self.stream_id}: Connected to {self.stream_source}")
            return True
            
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Connection failed - {str(e)}")
            return False
    
    def _rotate_file(self, chunk_index: int) -> bool:
        """Close current file and start new one"""
        try:
            # Finalize current writer
            if self.video_writer:
                self.video_writer.release()
                logger.info(f"Stream {self.stream_id}: Finalized chunk {self.current_chunk} - {self.frame_count} frames")
            
            # Calculate filename with modulo wrapping
            chunk_padded = chunk_index % self.total_chunks
            filename = f"stream_{self.stream_id}_chunk_{chunk_padded:03d}.mp4"
            filepath = os.path.join(self.output_dir, filename)
            
            # Initialize new VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(filepath, fourcc, self.fps, (self.width, self.height))
            
            if not self.video_writer.isOpened():
                logger.error(f"Stream {self.stream_id}: Failed to open video writer for {filepath}")
                return False
            
            self.current_file = filepath
            self.current_chunk = chunk_index
            self.frame_count = 0
            logger.info(f"Stream {self.stream_id}: Started chunk {chunk_padded} -> {filename} (FPS: {self.fps}, Resolution: {self.width}x{self.height})")
            return True
            
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Rotation error - {str(e)}")
            return False
    
    def _finalize_writer(self):
        """Safely close MP4 file"""
        try:
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Error finalizing writer - {str(e)}")
    
    def _record_loop(self):
        """Main recording loop with rotation and error handling"""
        consecutive_failures = 0
        max_consecutive_failures = 30
        
        while self.is_recording:
            try:
                # Check for rotation
                current_time = time.time()
                elapsed_seconds = current_time - self.last_rotation_time
                chunk_duration_seconds = self.chunk_duration_minutes * 60
                
                if elapsed_seconds >= chunk_duration_seconds:
                    self.current_chunk += 1
                    self._rotate_file(self.current_chunk)
                    self.last_rotation_time = current_time
                
                # Reconnect if needed
                if self.capture is None:
                    if not self._connect_stream():
                        time.sleep(2)
                        continue
                
                # Read frame
                ret, frame = self.capture.read()
                
                if not ret:
                    consecutive_failures += 1
                    if consecutive_failures > max_consecutive_failures:
                        logger.warning(f"Stream {self.stream_id}: Too many failures, reconnecting...")
                        self.capture.release()
                        self.capture = None
                        consecutive_failures = 0
                    time.sleep(0.1)
                    continue
                
                consecutive_failures = 0
                
                # Resize if needed
                if frame.shape[0] != self.height or frame.shape[1] != self.width:
                    frame = cv2.resize(frame, (self.width, self.height))
                
                # Ensure video writer is active
                if self.video_writer is None and not self._rotate_file(self.current_chunk):
                    time.sleep(1)
                    continue
                
                # Write frame
                self.video_writer.write(frame)
                self.frame_count += 1
                
            except Exception as e:
                logger.error(f"Stream {self.stream_id}: Recording loop error - {str(e)}")
                consecutive_failures += 1
                time.sleep(1)
    
    def get_status(self) -> dict:
        """Get current recording status"""
        with self.lock:
            return {
                'stream_id': self.stream_id,
                'recording': self.is_recording,
                'current_chunk': self.current_chunk,
                'frame_count': self.frame_count,
                'current_file': self.current_file
            }
    
    def list_files(self) -> list:
        """List all recorded files for this stream"""
        files = []
        try:
            output_path = Path(self.output_dir)
            if output_path.exists():
                for mp4_file in sorted(output_path.glob(f"stream_{self.stream_id}_chunk_*.mp4")):
                    stat = mp4_file.stat()
                    files.append({
                        'filename': mp4_file.name,
                        'path': str(mp4_file),
                        'size_mb': stat.st_size / (1024 * 1024),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: Error listing files - {str(e)}")
        
        return files
