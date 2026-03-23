"""
FFmpeg-based RTSP Stream Handler - Manages individual RTSP stream connections using FFmpeg
Replaces OpenCV with FFmpeg for superior H.264 decoding and error recovery
"""
import subprocess
import threading
import time
from queue import Queue
from typing import Optional
import logging
import traceback
import numpy as np
import os
import fcntl
import shutil

logger = logging.getLogger(__name__)


class FFmpegStreamHandler:
    """Handles a single RTSP stream with FFmpeg subprocess and buffering"""
    
    def __init__(self, rtsp_url: str, stream_id: int, buffer_size: int = 2):
        self.rtsp_url = rtsp_url
        self.stream_id = stream_id
        self.buffer_size = buffer_size
        self.frame_queue = Queue(maxsize=buffer_size)
        
        self.process = None
        self.is_running = False
        self.thread = None
        self.last_frame = None
        self.connection_attempts = 0
        self.max_connection_attempts = 3
        self.stream_width = 0
        self.stream_height = 0
        self.fps = 30  # Default FPS
        
    def _probe_stream(self) -> bool:
        """Use ffprobe to get stream information before attempting to read"""
        # Skip probing for RTSP streams - they are slow and spam H.264 errors
        if self.rtsp_url.startswith('rtsp://'):
            logger.info(f"Stream {self.stream_id}: Skipping ffprobe for RTSP stream (using defaults: 1280x720 @ 30fps)")
            return False
        
        try:
            logger.info(f"Stream {self.stream_id}: Probing local stream with ffprobe: {self.rtsp_url}")
            
            # Build ffprobe command for local files only
            cmd = [
                'ffprobe',
                '-hide_banner',
                '-loglevel', 'error',
                '-max_probe_packets', '100',
                '-analyzeduration', '1000000',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate',
                '-of', 'csv=p=0',
                self.rtsp_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('['):
                        continue
                    
                    parts = line.split(',')
                    if len(parts) >= 3:
                        try:
                            self.stream_width = int(parts[0])
                            self.stream_height = int(parts[1])
                            fps_parts = parts[2].split('/')
                            self.fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) > 1 else float(fps_parts[0])
                            logger.info(f"Stream {self.stream_id}: Probed successfully - {self.stream_width}x{self.stream_height} @ {self.fps}fps")
                            return True
                        except (ValueError, IndexError):
                            continue
            
            logger.debug(f"Stream {self.stream_id}: ffprobe did not return stream info")
            return False
            
        except subprocess.TimeoutExpired:
            logger.debug(f"Stream {self.stream_id}: ffprobe timeout - will use defaults")
            return False
        except Exception as e:
            logger.debug(f"Stream {self.stream_id}: ffprobe error - {str(e)}")
            return False
    
    def connect(self) -> bool:
        """Establish connection to RTSP stream or local video file using FFmpeg"""
        try:
            logger.info(f"Stream {self.stream_id}: Attempting to connect to: {self.rtsp_url}")
            
            source = self.rtsp_url
            
            # Check if it's a local file path
            if os.path.isfile(self.rtsp_url):
                source = self.rtsp_url.replace('\\', '/')
                logger.info(f"Stream {self.stream_id}: Detected local file: {source}")
            elif not self.rtsp_url.startswith('rtsp://') and not self.rtsp_url.startswith('http'):
                if '\\' in self.rtsp_url:
                    source = self.rtsp_url.replace('\\', '/')
                    logger.warning(f"Stream {self.stream_id}: Converted path to forward slashes: {source}")
                    if not os.path.isfile(source):
                        logger.error(f"Stream {self.stream_id}: File not found: {self.rtsp_url}")
                        return False
            else:
                logger.debug(f"Stream {self.stream_id}: RTSP stream URL detected")
            
            # Probe stream first to get dimensions and FPS
            if not self._probe_stream():
                logger.warning(f"Stream {self.stream_id}: Could not probe stream, will attempt connection with default settings")
                self.stream_width = 1280
                self.stream_height = 720
                self.fps = 30
            
            # Build FFmpeg command for continuous frame output
            # FFmpeg will handle H.264 decoding with better error recovery
            cmd = [
                'ffmpeg',
                '-hide_banner',
                '-loglevel', 'warning',
                '-fflags', '+nobuffer',  # Minimize latency
                '-flags', 'low_delay',   # Low delay decoding
                '-i', source,
                '-vsync', 'drop',        # Drop frames if behind
                '-f', 'rawvideo',
                '-pix_fmt', 'bgr24',  # BGR24 for numpy compatibility
                '-vf', f'scale={self.stream_width}:{self.stream_height},fps=30',  # Scale and fps filter
                'pipe:1'                 # Output to stdout
            ]
            
            logger.debug(f"Stream {self.stream_id}: Starting FFmpeg process with command: {' '.join(cmd)}")
            
            # Verify FFmpeg is available
            try:
                import shutil
                ffmpeg_path = shutil.which('ffmpeg')
                if not ffmpeg_path:
                    logger.error(f"Stream {self.stream_id}: FFmpeg not found in PATH. Install FFmpeg or add to PATH.")
                    return False
                logger.debug(f"Stream {self.stream_id}: FFmpeg found at: {ffmpeg_path}")
            except Exception as e:
                logger.warning(f"Stream {self.stream_id}: Could not verify FFmpeg path: {str(e)}")
            
            # Start FFmpeg subprocess with retry logic for RTSP
            max_connection_attempts = 3
            for attempt in range(max_connection_attempts):
                logger.info(f"Stream {self.stream_id}: Connection attempt {attempt + 1}/{max_connection_attempts}")
                logger.info(f"Stream {self.stream_id}: Exact FFmpeg command: ffmpeg {' '.join(cmd[1:])}")
                
                # Pass through environment to ensure PATH and other vars are available
                env = os.environ.copy()
                
                # Create process with stderr read asynchronously to prevent deadlock
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=65536,  # Use reasonable buffer size for better performance
                    env=env  # Explicitly pass environment
                )
                
                # Start thread to read stderr asynchronously (prevents deadlock from stderr buffer filling)
                def read_stderr():
                    try:
                        while self.is_running and self.process and self.process.poll() is None:
                            try:
                                line = self.process.stderr.readline()
                                if not line:
                                    break
                                # Just discard stderr - H.264 warnings are normal
                            except:
                                break
                    except:
                        pass
                
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                stderr_thread.start()
                
                logger.info(f"Stream {self.stream_id}: FFmpeg process started (PID: {self.process.pid})")
                
                # Try to read first frame to verify connection
                frame_size = self.stream_width * self.stream_height * 3  # BGR24
                frame_data = b''
                start_time = time.time()
                timeout_seconds = 60  # Wait up to 60 seconds for first frame
                
                # Read data until we have a complete frame or timeout
                while len(frame_data) < frame_size:
                    # Check if process died
                    if self.process.poll() is not None:
                        # Process actually exited
                        _, stderr = self.process.communicate()
                        error_msg = stderr.decode('utf-8', errors='ignore')[-800:] if stderr else "No error output"
                        
                        elapsed = time.time() - start_time
                        logger.error(f"Stream {self.stream_id}: FFmpeg process died after {elapsed:.1f}s, got {len(frame_data)}/{frame_size} bytes")
                        logger.error(f"Stream {self.stream_id}: FFmpeg stderr:\n{error_msg}")
                        self._cleanup_process()
                        
                        if attempt < max_connection_attempts - 1:
                            logger.info(f"Stream {self.stream_id}: Retrying in 5 seconds...")
                            time.sleep(5)
                            break  # Try next attempt
                        else:
                            logger.error(f"Stream {self.stream_id}: Max connection attempts reached")
                            return False
                    
                    # Check timeout
                    if time.time() - start_time > timeout_seconds:
                        logger.error(f"Stream {self.stream_id}: Timeout waiting for first frame ({timeout_seconds}s), got {len(frame_data)}/{frame_size} bytes")
                        self._cleanup_process()
                        
                        if attempt < max_connection_attempts - 1:
                            logger.info(f"Stream {self.stream_id}: Retrying in 5 seconds...")
                            time.sleep(5)
                            break  # Try next attempt
                        else:
                            logger.error(f"Stream {self.stream_id}: Max connection attempts reached")
                            return False
                    
                    # Try to read data (blocking read with small buffer)
                    try:
                        # Read in chunks to avoid blocking too long
                        bytes_needed = frame_size - len(frame_data)
                        chunk_size = min(65536, bytes_needed)
                        chunk = self.process.stdout.read(chunk_size)
                        
                        if chunk:
                            frame_data += chunk
                            elapsed = time.time() - start_time
                            if elapsed > 5 and len(frame_data) % (frame_size // 4) == 0:  # Log every 25%
                                logger.debug(f"Stream {self.stream_id}: Reading frame... {elapsed:.1f}s elapsed, "
                                           f"{len(frame_data)}/{frame_size} bytes ({100*len(frame_data)//frame_size}%)")
                        else:
                            # EOF reached without getting full frame
                            logger.error(f"Stream {self.stream_id}: EOF reached, got {len(frame_data)}/{frame_size} bytes")
                            self._cleanup_process()
                            
                            if attempt < max_connection_attempts - 1:
                                logger.info(f"Stream {self.stream_id}: Retrying in 5 seconds...")
                                time.sleep(5)
                                break
                            else:
                                return False
                    except Exception as e:
                        logger.error(f"Stream {self.stream_id}: Error reading from FFmpeg stdout: {str(e)}")
                        self._cleanup_process()
                        
                        if attempt < max_connection_attempts - 1:
                            logger.info(f"Stream {self.stream_id}: Retrying in 5 seconds...")
                            time.sleep(5)
                            break
                        else:
                            return False
                
                # Check if we successfully got a frame
                if len(frame_data) == frame_size:
                    frame = np.frombuffer(frame_data, np.uint8).reshape((self.stream_height, self.stream_width, 3))
                    self.last_frame = frame
                    logger.info(f"Stream {self.stream_id}: Connected to {self.rtsp_url} "
                               f"({self.stream_width}x{self.stream_height} @ {self.fps}fps)")
                    self.connection_attempts = 0
                    return True
            
            # All attempts failed
            logger.error(f"Stream {self.stream_id}: Failed to establish connection after {max_connection_attempts} attempts")
            self._cleanup_process()
            return False
            
        except Exception as e:
            error_msg = f"Stream {self.stream_id}: Connection error - {str(e)}"
            if self.rtsp_url.startswith('rtsp://') and 'Connection refused' in str(e):
                error_msg += "\n  → RTSP server is not responding"
                error_msg += "\n  → Ensure the RTSP server is running on the specified host and port"
            logger.error(error_msg)
            logger.error(f"Stream {self.stream_id}: Traceback:\n{traceback.format_exc()}")
            self._cleanup_process()
            return False
    
    def _cleanup_process(self):
        """Clean up FFmpeg process"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
    
    def start(self):
        """Start the stream capture thread"""
        try:
            logger.info(f"Stream {self.stream_id}: start() called")
            
            if self.is_running:
                logger.warning(f"Stream {self.stream_id}: Already running, skipping start")
                return
            
            logger.info(f"Stream {self.stream_id}: Attempting connection via FFmpeg...")
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
        max_consecutive_failures = 60  # Increased tolerance for slow streams
        frame_size = self.stream_width * self.stream_height * 3
        frame_buffer = b''
        
        while self.is_running:
            try:
                if self.process is None or self.process.poll() is not None:
                    logger.debug(f"Stream {self.stream_id}: FFmpeg process died, attempting reconnection")
                    frame_buffer = b''
                    if not self.connect():
                        time.sleep(1)
                        continue
                
                # Read data from FFmpeg stdout (non-blocking)
                try:
                    # Read up to one frame size of data
                    chunk = self.process.stdout.read(frame_size)
                    
                    if chunk:
                        frame_buffer += chunk
                        consecutive_failures = 0
                        
                        # Process complete frames from buffer
                        while len(frame_buffer) >= frame_size:
                            frame_data = frame_buffer[:frame_size]
                            frame_buffer = frame_buffer[frame_size:]
                            
                            # Convert raw bytes to numpy array
                            frame = np.frombuffer(frame_data, np.uint8).reshape((self.stream_height, self.stream_width, 3))
                            self.last_frame = frame
                            
                            # Non-blocking put - discard oldest frame if queue is full
                            try:
                                self.frame_queue.put_nowait(frame)
                            except:
                                try:
                                    self.frame_queue.get_nowait()
                                    self.frame_queue.put_nowait(frame)
                                except:
                                    pass
                    else:
                        # No data available
                        consecutive_failures += 1
                        if consecutive_failures % 20 == 0:
                            logger.debug(f"Stream {self.stream_id}: No data from FFmpeg ({consecutive_failures} attempts)")
                        if consecutive_failures > max_consecutive_failures:
                            logger.warning(f"Stream {self.stream_id}: FFmpeg producing no output, reconnecting...")
                            frame_buffer = b''
                            self._cleanup_process()
                            consecutive_failures = 0
                        time.sleep(0.033)  # ~30ms
                        
                except (IOError, OSError):
                    # Non-blocking read with no data available
                    consecutive_failures += 1
                    time.sleep(0.033)
                    
            except Exception as e:
                logger.error(f"Stream {self.stream_id}: Capture error - {str(e)}")
                logger.error(f"Stream {self.stream_id}: Traceback:\n{traceback.format_exc()}")
                consecutive_failures += 1
                frame_buffer = b''
                time.sleep(1)
    
    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame from the stream"""
        try:
            frame = self.frame_queue.get_nowait()
            self.last_frame = frame
            return frame
        except:
            return self.last_frame
    
    def stop(self):
        """Stop the stream gracefully"""
        logger.info(f"Stream {self.stream_id}: stop() called")
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=2)
        self._cleanup_process()
        logger.info(f"Stream {self.stream_id}: Stopped")
