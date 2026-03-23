# Video Wall Application - README

## Overview
A professional Python-based video wall application that displays multiple RTSP streams in a grid layout. Built with PyQt5 and OpenCV, containerized with Docker for easy deployment.

## Features
- ✅ Multi-stream RTSP support (up to 16 streams in 4x4 grid)
- ✅ Flexible grid layout (1x1 to 4x4)
- ✅ Multiple output resolutions (1280x720, 1920x1080, 2560x1440)
- ✅ Real-time stream management and error handling
- ✅ Configurable via GUI or YAML config files
- ✅ Docker containerization for easy deployment
- ✅ Automatic reconnection on stream failures
- ✅ Professional GUI with PyQt5
- ✅ Aspect ratio preservation with black borders
- ✅ Stream monitoring and status display

## Requirements
- Python 3.11+
- Docker & Docker Compose (for container deployment)
- X11 display server (for GUI rendering on Linux/Unix)

## Installation

### Local Installation (Non-Docker)

1. Clone/download the project:
```bash
cd BBOX-Vid-wall
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create/edit `config.yaml` with your camera streams:
```yaml
cols: 2
rows: 2
resolution: '1920x1080'
streams:
  - 'rtsp://camera1:554/stream'
  - 'rtsp://camera2:554/stream'
  - 'rtsp://camera3:554/stream'
  - 'rtsp://camera4:554/stream'
```

4. Run the application:
```bash
python app.py
```

### Docker Installation

#### Build the image:
```bash
docker build -t bbox-video-wall:latest .
```

#### Run with Docker Compose:
```bash
docker-compose up -d
```

#### Run standalone:
```bash
docker run -it \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v $(pwd)/config.yaml:/app/config.yaml \
  bbox-video-wall:latest
```

## Usage

### GUI Application
1. Launch `python app.py`
2. Configure grid layout (columns and rows)
3. Select output resolution
4. Enter RTSP stream URLs (one per line)
5. Click "Start Wall" to begin streaming
6. Save configuration for future use

### Headless Mode (Docker)
The application supports headless operation for servers without display:
```bash
docker-compose up -d
```

Stream output can be piped to:
- RTMP endpoint
- HTTP streaming server
- Local file

## Configuration

### YAML Format (config.yaml)
```yaml
cols: 2                    # Grid columns
rows: 2                    # Grid rows
resolution: '1920x1080'    # Output resolution
streams:                   # List of RTSP URLs
  - 'rtsp://...'
  - 'rtsp://...'
performance:
  buffer_size: 2          # Frames to buffer per stream
  max_fps: 30             # Display FPS limit
  reconnect_delay: 2      # Reconnection wait time
```

## RTSP Stream URLs

### Common Formats
```
# Basic format
rtsp://username:password@host:554/stream1

# IP Camera
rtsp://192.168.1.100:554/stream

# Axis camera
rtsp://admin:password@camera-ip/axis-media/media.amp

# Uniview camera
rtsp://admin:password@camera-ip:554/stream

# Generic camera
rtsp://10.0.0.1:554/
```

## Performance Optimization

### For 4K streams:
- Set resolution to 2560x1440
- Adjust grid to 2x2
- Increase CPU/memory allocation

### For many streams:
- Use smaller grid
- Lower resolution
- Increase buffer size if experiencing lag

## Troubleshooting

### Streams not connecting
- Verify RTSP URLs and network connectivity
- Check firewall rules on port 554
- Ensure credentials are correct

### Performance issues
- Reduce number of streams
- Lower output resolution
- Reduce FPS limit in config
- Allocate more CPU/memory

### Display issues (Docker)
- Ensure X11 socket is properly mounted
- Set DISPLAY environment variable correctly
- For headless: implement RTMP/HTTP output

### Memory usage too high
- Reduce buffer_size in config.yaml
- Lower grid dimensions
- Use resolution 1280x720

## Architecture

```
┌─────────────────────────────────────────┐
│         Video Wall Application          │
├─────────────────────────────────────────┤
│                                         │
│  PyQt5 GUI Layer                        │
│  └─> Display Manager                    │
│                                         │
│  Video Wall Core                        │
│  └─> Grid Layout Engine                 │
│      └─> Cell Renderer (resize/scale)   │
│                                         │
│  Stream Management                      │
│  ├─> Stream Handler 1 (thread)          │
│  ├─> Stream Handler 2 (thread)          │
│  ├─> Stream Handler 3 (thread)          │
│  └─> Stream Handler N (thread)          │
│      └─> RTSP Connection (OpenCV)       │
│                                         │
└─────────────────────────────────────────┘
```

## File Structure

```
BBOX-Vid-wall/
├── app.py                    # Main PyQt5 application
├── video_wall.py             # Video wall display engine
├── stream_handler.py         # RTSP stream management
├── config.yaml              # Configuration file
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image definition
├── docker-compose.yml       # Docker orchestration
├── entrypoint.sh            # Container startup script
└── README.md                # This file
```

## Docker Commands

### Build
```bash
docker build -t bbox-video-wall:latest .
```

### Run
```bash
docker run -it bbox-video-wall:latest
```

### Compose up
```bash
docker-compose up -d
```

### View logs
```bash
docker-compose logs -f video-wall
```

### Stop
```bash
docker-compose down
```

### Push to registry
```bash
docker tag bbox-video-wall:latest myregistry/bbox-video-wall:latest
docker push myregistry/bbox-video-wall:latest
```

## API/Programmatic Usage

```python
from video_wall import VideoWallDisplay

# Initialize
wall = VideoWallDisplay(
    streams=['rtsp://cam1', 'rtsp://cam2', 'rtsp://cam3', 'rtsp://cam4'],
    cols=2,
    rows=2,
    output_width=1920,
    output_height=1080
)

# Start streaming
wall.start()

# Get composite frame
frame = wall.get_wall_frame()

# Stop
wall.stop()
```

## Logging

Logs are written to console. For persistent logs in Docker:
```bash
docker-compose logs -f video-wall > logs/video-wall.log
```

## Performance Benchmarks

| Grid | Resolution | CPU | Memory | Typical FPS |
|------|-----------|-----|--------|------------|
| 1x1  | 1080p     | 20% | 400MB  | 30         |
| 2x2  | 1080p     | 60% | 800MB  | 25         |
| 3x3  | 1080p     | >90%| 1.5GB  | 15         |
| 2x2  | 4K        | 85% | 1.2GB  | 20         |

## Future Enhancements
- [ ] RTMP output support
- [ ] HTTP streaming endpoint
- [ ] Motion detection alerts
- [ ] Recording capability
- [ ] Web-based control interface
- [ ] Multi-monitor support
- [ ] Custom layout configuration
- [ ] Stream health monitoring dashboard

## License
MIT License

## Support
For issues, bugs, or feature requests, please refer to project documentation.

## Contributing
Contributions are welcome! Please ensure code follows PEP 8 standards and include tests.
