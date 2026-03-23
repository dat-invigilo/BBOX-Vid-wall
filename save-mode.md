# Save Mode Implementation - Draft

## Overview

Save Mode enables automatic recording of all RTSP streams into MP4 videos with intelligent file rotation:
- **1-hour chunks**: Each stream is recorded into 1-hour segments
- **24-hour cycle**: After 24 hours, the oldest file (hour_0) is overwritten, creating a rolling 24-hour buffer
- **Per-stream recording**: Each stream records independently to avoid blocking or skipped frames

---

## Architecture

### File Structure
\`\`\`
recordings/
├── stream_0/
│   ├── stream_0_hour_0.mp4  (00:00-01:00, overwrites after 24h)
│   ├── stream_0_hour_1.mp4  (01:00-02:00)
│   ├── stream_0_hour_2.mp4  (02:00-03:00)
│   └── ... (up to hour_23)
├── stream_1/
│   ├── stream_1_hour_0.mp4
│   └── ...
└── metadata.json (rotation state)
\`\`\`

### Component Interaction
\`\`\`
VideoWallDisplay
    ↓
VideoWallRecorder (NEW)
    ↓
StreamRecorder (NEW) × N (one per stream)
    ↓
MP4 Writer (cv2.VideoWriter)
\`\`\`

---

## New Files to Create

### 1. \`video_recorder.py\` - Main Recording Orchestrator

**Responsibilities:**
- Manage recording state (active/inactive, current hour)
- Spawn \`StreamRecorder\` thread for each stream
- Handle rotation logic (every hour, every 24 hours)
- Track metadata (current session start, hour counter)
- Graceful shutdown and file cleanup

**Key Classes:**
\`\`\`python
class VideoWallRecorder:
    """Master recording controller for all streams"""
    
    def __init__(self, output_dir: str, fps: int = 30, width: int = 1920, height: int = 1080):
        self.output_dir = output_dir
        self.fps = fps
        self.width = width
        self.height = height
        self.recording_threads = []
        self.is_recording = False
        self.session_start_time = None
        self.current_hour = 0
        self.metadata = {}
        self.lock = threading.Lock()
    
    def start_recording(self, streams_list: List[str]):
        """Start recording all streams"""
        # Create output directories
        # Initialize metadata
        # Spawn StreamRecorder for each stream
        pass
    
    def stop_recording(self):
        """Stop all recording threads gracefully"""
        pass
    
    def _rotation_checker(self):
        """Background thread that checks hourly rotation"""
        pass
    
    def get_status(self) -> Dict:
        """Return recording status info"""
        pass
    
    def save_metadata(self):
        """Persist state to metadata.json"""
        pass
\`\`\`

### 2. \`stream_recorder.py\` - Per-Stream Recording

**Responsibilities:**
- Capture frames from a single stream
- Encode to MP4
- Handle hourly file rotation
- Handle stream disconnections gracefully

**Key Classes:**
\`\`\`python
class StreamRecorder:
    """Records a single stream with hourly rotation"""
    
    def __init__(self, stream_source: str, stream_id: int, output_dir: str, 
                 fps: int = 30, width: int = 1920, height: int = 1080):
        self.stream_source = stream_source
        self.stream_id = stream_id
        self.output_dir = output_dir
        self.fps = fps
        self.width = width
        self.height = height
        
        self.capture = None
        self.video_writer = None
        self.current_file = None
        self.current_hour = 0
        self.frame_count = 0
        self.is_recording = False
        self.thread = None
        self.rotation_event = threading.Event()
        self.lock = threading.Lock()
    
    def start(self):
        """Start recording thread"""
        pass
    
    def stop(self):
        """Stop recording gracefully"""
        pass
    
    def _record_loop(self):
        """Main recording loop"""
        # Connect to stream
        # Read frames
        # Write to MP4
        # Check rotation
        pass
    
    def _rotate_file(self, new_hour: int):
        """Rotate to next hourly file"""
        # Close current MP4 (finalize headers)
        # Open new MP4 file
        # Wrap hour counter (modulo 24)
        pass
    
    def _finalize_writer(self):
        """Properly close MP4 file"""
        pass
\`\`\`

---

## Configuration Updates

### \`config.yaml\` - New Save Mode Section

\`\`\`yaml
# ... existing config ...

# Save Mode - Recording
save_mode:
  enabled: false
  output_directory: './recordings'
  
  # Recording parameters
  fps: 30
  recording_width: 1920
  recording_height: 1080
  
  # Rotation policy
  chunk_duration_minutes: 60    # 1-hour chunks
  total_hours: 24               # Rolling 24-hour buffer
  
  # Codec settings
  codec: 'mp4v'                 # 'mp4v' (H.264) or 'DIVX'
  bitrate: '5000k'              # ffmpeg bitrate format
  
  # Cleanup/retention
  cleanup_incomplete: true      # Remove incomplete files on error
  disk_space_alert_gb: 10       # Alert if disk space below this
\`\`\`

---

## API Endpoints

### Start Recording
\`\`\`
POST /api/save-mode/start
Body: {
  "streams": ["rtsp://...", "rtsp://..."],
  "fps": 30,
  "output_dir": "./recordings"
}
Response: {"status": "recording", "streams": 2}
\`\`\`

### Stop Recording
\`\`\`
POST /api/save-mode/stop
Response: {"status": "stopped", "files_saved": 48}
\`\`\`

### Recording Status
\`\`\`
GET /api/save-mode/status
Response: {
  "enabled": true,
  "recording": true,
  "current_hour": 5,
  "streams_recording": 4,
  "disk_usage_gb": 45.2,
  "uptime_hours": 5.5,
  "metadata": {
    "stream_0": {"total_frames": 450000, "file_size_mb": 2340},
    "stream_1": {"total_frames": 450000, "file_size_mb": 2250}
  }
}
\`\`\`

### List Recordings
\`\`\`
GET /api/save-mode/files
Response: {
  "stream_0": [
    {"hour": 0, "file": "stream_0_hour_0.mp4", "size_mb": 2340, "duration_sec": 3600},
    {"hour": 1, "file": "stream_0_hour_1.mp4", "size_mb": 2250, "duration_sec": 3600}
  ]
}
\`\`\`

---

## Performance Estimate

| Resolution | FPS | Codec | MB/hour/stream | CPU % |
|-----------|-----|-------|----------------|-------|
| 1920x1080 | 30  | H.264 | 200-300        | 15-25 |
| 1280x720  | 30  | H.264 | 100-150        | 8-12  |

**24-Hour Storage (4 streams @ 1080p):** ~24-35 GB

---

## Deployment Steps

1. Create \`video_recorder.py\` (orchestrator)
2. Create \`stream_recorder.py\` (per-stream)
3. Update \`config.yaml\` with save_mode section
4. Add endpoints to \`web_server.py\`
5. Add UI controls to \`templates/index.html\`
6. Update \`docker-compose.yml\` with recordings volume
7. Test 1-hour rotation cycle
8. Verify MP4 playback

---

## Implementation Complexity

- **Moderate**: Core recorder logic is straightforward
- **Main challenge**: Proper MP4 file finalization at rotation boundaries
- **Key concern**: CPU load scaling with multiple simultaneous streams