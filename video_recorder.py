"""
Video Wall Recorder - Orchestrates multi-stream recording with rotation
"""
import threading
import time
import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional
from stream_recorder import StreamRecorder
from datetime import datetime

logger = logging.getLogger(__name__)


class VideoWallRecorder:
    """Master recording controller for all streams"""
    
    def __init__(self, output_dir: str = './recordings', 
                 chunk_duration_minutes: int = 60,
                 total_rotation_minutes: int = 1440,
                 fps: int = 30, width: int = 1920, height: int = 1080):
        self.output_dir = output_dir
        self.chunk_duration_minutes = chunk_duration_minutes
        self.total_rotation_minutes = total_rotation_minutes
        self.fps = fps
        self.width = width
        self.height = height
        
        self.recording_threads = {}  # {stream_id: StreamRecorder}
        self.is_recording = False
        self.session_start_time = None
        self.metadata = {}
        self.lock = threading.Lock()
        
        logger.info(f"VideoWallRecorder initialized: {chunk_duration_minutes}min chunks, "
                   f"{total_rotation_minutes}min rotation")
    
    def start_recording(self, streams_dict: Dict[int, str]) -> bool:
        """
        Start recording selected streams
        
        Args:
            streams_dict: {stream_id: stream_source_url, ...}
        """
        with self.lock:
            if self.is_recording:
                logger.warning("Recording already in progress")
                return False
            
            try:
                # Create output directory
                Path(self.output_dir).mkdir(parents=True, exist_ok=True)
                
                self.session_start_time = time.time()
                self.is_recording = True
                
                # Spawn recorder for each stream
                for stream_id, stream_source in streams_dict.items():
                    stream_output_dir = os.path.join(self.output_dir, f"stream_{stream_id}")
                    
                    recorder = StreamRecorder(
                        stream_source=stream_source,
                        stream_id=stream_id,
                        output_dir=stream_output_dir,
                        chunk_duration_minutes=self.chunk_duration_minutes,
                        total_rotation_minutes=self.total_rotation_minutes,
                        fps=self.fps,
                        width=self.width,
                        height=self.height
                    )
                    recorder.start()
                    self.recording_threads[stream_id] = recorder
                
                # Save metadata
                self._save_metadata()
                
                logger.info(f"Recording started for {len(streams_dict)} streams")
                return True
                
            except Exception as e:
                logger.error(f"Failed to start recording: {str(e)}")
                self.is_recording = False
                return False
    
    def stop_recording(self) -> bool:
        """Stop all recording threads gracefully"""
        with self.lock:
            if not self.is_recording:
                logger.warning("No recording in progress")
                return False
            
            try:
                # Stop all recorders
                for stream_id, recorder in self.recording_threads.items():
                    recorder.stop()
                
                self.is_recording = False
                self.recording_threads.clear()
                
                logger.info("Recording stopped for all streams")
                return True
                
            except Exception as e:
                logger.error(f"Error stopping recording: {str(e)}")
                return False
    
    def get_status(self) -> Dict:
        """Get current recording status"""
        with self.lock:
            status = {
                'enabled': True,
                'recording': self.is_recording,
                'streams': {},
                'uptime_seconds': 0
            }
            
            if self.is_recording and self.session_start_time:
                status['uptime_seconds'] = time.time() - self.session_start_time
            
            for stream_id, recorder in self.recording_threads.items():
                status['streams'][stream_id] = recorder.get_status()
            
            return status
    
    def list_recordings(self) -> Dict:
        """List all recorded files grouped by stream"""
        recordings = {}
        
        try:
            base_path = Path(self.output_dir)
            if base_path.exists():
                for stream_dir in base_path.iterdir():
                    if stream_dir.is_dir():
                        stream_id = stream_dir.name
                        files = []
                        
                        for mp4_file in sorted(stream_dir.glob("*.mp4")):
                            stat = mp4_file.stat()
                            files.append({
                                'filename': mp4_file.name,
                                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                'path': str(mp4_file)
                            })
                        
                        if files:
                            recordings[stream_id] = files
            
        except Exception as e:
            logger.error(f"Error listing recordings: {str(e)}")
        
        return recordings
    
    def get_disk_usage(self) -> float:
        """Get total disk usage in GB"""
        try:
            base_path = Path(self.output_dir)
            if not base_path.exists():
                return 0.0
            
            total_bytes = sum(f.stat().st_size for f in base_path.rglob('*') if f.is_file())
            return round(total_bytes / (1024 * 1024 * 1024), 2)
            
        except Exception as e:
            logger.error(f"Error calculating disk usage: {str(e)}")
            return 0.0
    
    def _save_metadata(self):
        """Save recording session metadata"""
        try:
            metadata = {
                'session_start': datetime.fromtimestamp(self.session_start_time).isoformat(),
                'chunk_duration_minutes': self.chunk_duration_minutes,
                'total_rotation_minutes': self.total_rotation_minutes,
                'streams': list(self.recording_threads.keys())
            }
            
            metadata_file = os.path.join(self.output_dir, 'metadata.json')
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving metadata: {str(e)}")
