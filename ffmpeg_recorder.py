"""
FFmpeg-based Stream Recorder - Records RTSP streams to MP4 files using FFmpeg
Replaces OpenCV VideoWriter with FFmpeg subprocess for better reliability
"""
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)


class FFmpegStreamRecorder:
    """Records a single RTSP stream to MP4 using FFmpeg"""
    
    def __init__(self, stream_source: str, stream_id: int, 
                 output_directory: str = './recordings',
                 fps: int = 30, width: int = 1920, height: int = 1080,
                 chunk_duration_minutes: int = 1,
                 total_rotation_minutes: int = 2):
        """
        Initialize stream recorder
        
        Args:
            stream_source: RTSP URL or local file path
            stream_id: Unique stream identifier
            output_directory: Where to save MP4 files
            fps: Frames per second for output
            width: Output video width
            height: Output video height
            chunk_duration_minutes: Duration of each recording chunk in minutes
            total_rotation_minutes: Total recording time before resetting
        """
        self.stream_source = stream_source
        self.stream_id = stream_id
        self.output_directory = output_directory
        self.fps = fps
        self.width = width
        self.height = height
        
        self.is_recording = False
        self.process = None
        self.thread = None
        self.current_chunk = 0
        self.last_rotation_time = None
        
        # Configuration
        self.chunk_duration_minutes = chunk_duration_minutes
        self.total_rotation_minutes = total_rotation_minutes
        
        logger.info(f"Stream {self.stream_id}: Recorder initialized for {stream_source}")
    
    def _get_output_filepath(self, chunk_index: int) -> str:
        """Generate output file path for chunk"""
        timestamp = int(time.time())
        filename = f"stream_{self.stream_id}_chunk_{chunk_index:04d}_{timestamp}.mp4"
        return os.path.join(self.output_directory, filename)
    
    def start(self):
        """Start recording thread"""
        if self.is_recording:
            logger.warning(f"Stream {self.stream_id}: Recording already in progress")
            return
        
        # Create output directory
        Path(self.output_directory).mkdir(parents=True, exist_ok=True)
        
        self.is_recording = True
        self.last_rotation_time = time.time()
        self.current_chunk = 0
        self.thread = threading.Thread(target=self._record_loop, daemon=True)
        self.thread.start()
        logger.info(f"Stream {self.stream_id}: Recording started")
    
    def stop(self):
        """Stop recording gracefully"""
        logger.info(f"Stream {self.stream_id}: Stopping recording...")
        self.is_recording = False
        if self.thread:
            self.thread.join(timeout=5)
        self._cleanup_process()
        logger.info(f"Stream {self.stream_id}: Recording stopped")
    
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
    
    def _start_ffmpeg_recording(self, output_file: str):
        """Start FFmpeg encoding to MP4"""
        try:
            # Place -t BEFORE -i to limit input duration (often more reliable for stream capture)
            # or keep it after to limit output. For RTSP, -t before -i often results in 
            # ffmpeg closing the input stream exactly at the time limit.
            cmd = [
                'ffmpeg',
                '-rtsp_transport', 'tcp' if self.stream_source.startswith('rtsp://') else 'auto',
                '-t', str(self.chunk_duration_minutes * 60),  # Duration limit
                '-i', self.stream_source,
                '-vf', f'scale={self.width}:{self.height}',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-y',
                output_file
            ]
            
            logger.debug(f"Stream {self.stream_id}: Starting FFmpeg recording: {' '.join(cmd)}")
            
            # Using stderr/stdout redirection to DEVNULL or a logger to avoid pipe buffer issues
            # that can cause FFmpeg to hang if the pipe isn't drained.
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            logger.info(f"Stream {self.stream_id}: Recording to {output_file} (PID: {self.process.pid})")
            
            # Wait for process to complete (duration/chunk timeout)
            start_time = time.time()
            self.process.wait()
            duration = time.time() - start_time
            
            # If FFmpeg exits too quickly (e.g. less than 5 seconds), it's likely a connection error
            if duration < 5:
                logger.warning(f"Stream {self.stream_id}: FFmpeg exited in {duration:.1f}s. Waiting before retry...")
                time.sleep(5)
            
            logger.info(f"Stream {self.stream_id}: FFmpeg process completed for chunk {self.current_chunk}")
            
        except Exception as e:
            logger.error(f"Stream {self.stream_id}: FFmpeg recording error - {str(e)}")
        finally:
            self._cleanup_process()
    
    def get_status(self):
        """Get current status of this recorder"""
        return {
            "is_recording": self.is_recording,
            "current_chunk": self.current_chunk,
            "last_rotation": self.last_rotation_time,
            "output_dir": self.output_directory
        }

    def _record_loop(self):
        """Main recording loop with chunk rotation"""
        logger.info(f"Stream {self.stream_id}: Recording loop started")
        
        while self.is_recording:
            try:
                output_file = self._get_output_filepath(self.current_chunk)
                
                logger.info(f"Stream {self.stream_id}: Recording chunk {self.current_chunk} to {output_file}")
                
                # Start FFmpeg recording for this chunk (duration is set in _start_ffmpeg_recording)
                self._start_ffmpeg_recording(output_file)
                
                # Check file was created and has data
                if os.path.exists(output_file) and os.path.getsize(output_file) > 1000:
                    logger.info(f"Stream {self.stream_id}: Chunk {self.current_chunk} completed successfully")
                else:
                    logger.warning(f"Stream {self.stream_id}: Chunk {self.current_chunk} may be incomplete or corrupted")
                
                # Check rotation policy
                elapsed_minutes = (time.time() - self.last_rotation_time) / 60
                if elapsed_minutes >= self.total_rotation_minutes:
                    logger.info(f"Stream {self.stream_id}: Total rotation time reached ({elapsed_minutes:.1f}m), resetting")
                    self.last_rotation_time = time.time()
                    self.current_chunk = 0
                else:
                    self.current_chunk += 1
                
                # Check disk space
                try:
                    stat = os.statvfs(self.output_directory)
                    free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                    if free_gb < 10:
                        logger.warning(f"Stream {self.stream_id}: Low disk space: {free_gb:.1f} GB remaining")
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"Stream {self.stream_id}: Recording loop error - {str(e)}")
                time.sleep(1)
        
        logger.info(f"Stream {self.stream_id}: Recording loop ended")


class FFmpegRecordingManager:
    """Master recording controller for all streams using FFmpeg"""
    
    def __init__(self, output_directory: str = './recordings'):
        """
        Initialize recording manager
        
        Args:
            output_directory: Base directory for all recordings
        """
        self.output_directory = output_directory
        self.recorders = {}
        logger.info("FFmpegRecordingManager initialized")
    
    def start_recording(self, streams_list):
        """Start recording all streams"""
        try:
            for i, stream_url in enumerate(streams_list):
                if stream_url and i not in self.recorders:
                    recorder = FFmpegStreamRecorder(
                        stream_url,
                        i,
                        output_directory=self.output_directory
                    )
                    recorder.start()
                    self.recorders[i] = recorder
            
            logger.info(f"Recording started for {len(self.recorders)} streams")
            return True
        except Exception as e:
            logger.error(f"Error starting recording: {str(e)}")
            return False
    
    def stop_recording(self):
        """Stop all recordings"""
        try:
            for recorder in self.recorders.values():
                if recorder:
                    recorder.stop()
            self.recorders.clear()
            logger.info("All recordings stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping recording: {str(e)}")
            return False
    
    def get_status(self):
        """Get recording status"""
        stream_details = {}
        for i, recorder in self.recorders.items():
            if recorder:
                stream_details[i] = recorder.get_status()
        
        return {
            "is_recording": len(self.recorders) > 0,
            "streams_recording": len(self.recorders),
            "output_directory": self.output_directory,
            "streams": stream_details
        }
