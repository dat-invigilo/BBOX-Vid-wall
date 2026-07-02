# Video Wall Application - README

## Overview
A Flask-based video wall control app that displays multiple RTSP camera streams
(including DeepStream BBOX overlay variants) in a browser grid. [mediamtx](https://github.com/bluenviron/mediamtx)
relays each camera's RTSP stream once and re-serves it as HLS; the browser
plays each cell directly from mediamtx via hls.js and composites the grid
itself with CSS. `web_server.py` is pure control-plane: it provisions
mediamtx's relay paths and drives recording, but never decodes or serves
video pixels itself.

See [mediamtx-migration.md](mediamtx-migration.md) for the design rationale.

## Features
- ✅ Multi-stream RTSP support in a configurable grid
- ✅ Per-stream BBOX/source toggle, swapped client-side with no restart needed
- ✅ Browser-side HLS playback (hls.js) - server never decodes video
- ✅ Fullscreen single-camera view
- ✅ Recording (Save Mode) with chunked/rotating MP4 output
- ✅ Docker containerization (`video-wall` + `mediamtx` services)
- ✅ Dev mode with local test video files for testing without cameras

## Requirements
- Python 3.11+
- Docker & Docker Compose (recommended deployment path)
- `ffmpeg` (installed in the Docker image; needed locally too if running without Docker)

## Installation

### Docker (recommended)

```bash
docker-compose up -d
```

This starts two services (see `docker-compose.yml`):
- `video-wall` - the Flask control-plane app (port 5002)
- `mediamtx` - the RTSP relay / HLS server (API :9997, RTSP :8554, HLS :8888)

Both use `network_mode: host` so they reach cameras and each other via
`127.0.0.1`.

### Local (non-Docker)

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run mediamtx separately (native binary or `docker run`), pointed at
   `mediamtx.yml` in this repo.

3. Edit `config.yaml` with your camera streams and mediamtx connection info
   (see the `mediamtx:` section).

4. Run the web server:
```bash
python web_server.py
```

5. Open `http://localhost:5002` in a browser.

## Usage

1. Open the web UI, configure grid layout (columns/rows) and resolution.
2. Enter RTSP stream URLs (or use test videos via Dev Mode).
3. Click **Start** - this provisions mediamtx paths for each camera and marks
   the wall running; the browser then builds a CSS grid of `<video>` elements
   playing each camera's HLS stream.
4. Use the kebab menu on each cell to toggle BBOX mode, start/stop recording,
   or go fullscreen.

## Configuration

### YAML Format (config.yaml)
```yaml
dev_mode: false
cols: 2                    # Grid columns
rows: 2                    # Grid rows
resolution: '1920x1080'    # Output resolution
streams:                   # List of RTSP URLs (used when DeepStream config parsing is unavailable)
  - 'rtsp://...'
test_vids:                 # Local files used when dev_mode: true
  - './test_videos/sample1.mp4'
performance:
  buffer_size: 2
  max_fps: 30
  reconnect_delay: 2
mediamtx:                  # Must match mediamtx.yml / docker-compose.yml
  api_url: 'http://127.0.0.1:9997'
  rtsp_port: 8554
  hls_port: 8888
save_mode:
  enabled: false
  output_directory: '/app/recordings'
  fps: 30
  recording_width: 1920
  recording_height: 1080
  chunk_duration_minutes: 30
  total_rotation_minutes: 180
```

In deployments where cameras come from a DeepStream pipeline, `web_server.py`
instead parses `/app/shared_volume/config.yaml` and the per-GPU DeepStream
`.txt` configs to discover camera + BBOX sink URLs automatically
(`parse_deepstream_uris()`); the `streams:` list above is only a fallback.

## RTSP Stream URLs

```
# Basic format
rtsp://username:password@host:554/stream1

# IP Camera
rtsp://192.168.1.100:554/stream

# Axis camera
rtsp://admin:password@camera-ip/axis-media/media.amp
```

## Troubleshooting

### Streams not connecting
- Verify RTSP URLs and network connectivity
- Check firewall rules on port 554
- Check mediamtx's own logs (`docker-compose logs -f mediamtx`) - it's what
  actually holds the upstream camera connection
- Confirm mediamtx's API is reachable from `video-wall` at the `mediamtx.api_url`
  configured in `config.yaml`

### Video grid shows nothing / spins forever
- Confirm mediamtx's HLS port (`8888` by default) is reachable from the
  browser, not just from the `video-wall` container
- Check the browser console for hls.js errors

### Recording not starting
- Recording pulls from mediamtx's relayed RTSP URL
  (`rtsp://127.0.0.1:{rtsp_port}/<path>`), not the original camera - confirm
  mediamtx has that path registered via `GET http://<host>:9997/v3/paths/list`

## Architecture

```
Browser (grid of <video> + hls.js)
    |  HLS (mediamtx :8888)
    v
mediamtx  <---- RTSP pull (once per camera) ---- Cameras / DeepStream sinks
    ^
    | REST API (mediamtx :9997) - path provisioning
    |
web_server.py (Flask, control-plane only)
    |
    +-- video_wall.py       - maps cameras -> mediamtx paths
    +-- mediamtx_client.py  - REST client for mediamtx's API
    +-- video_recorder.py / ffmpeg_recorder.py
            - records from mediamtx-relayed RTSP URLs, independent of the
              live view, to chunked/rotating MP4 files
```

## File Structure

```
BBOX-Vid-wall/
├── web_server.py             # Flask control-plane app
├── video_wall.py             # mediamtx path manager (camera -> HLS path mapping)
├── mediamtx_client.py        # REST client for mediamtx's control API
├── video_recorder.py         # Recording orchestration (chunking/rotation)
├── ffmpeg_recorder.py        # Per-stream ffmpeg recording subprocess
├── mediamtx.yml               # mediamtx server config
├── config.yaml                # App configuration
├── requirements.txt           # Python dependencies
├── Dockerfile                 # video-wall container image
├── docker-compose.yml         # video-wall + mediamtx services
├── templates/index.html       # Web UI (grid, controls, recording)
├── static/css/style.css
├── static/js/hls.min.js       # Vendored hls.js
└── README.md                  # This file
```

## Docker Commands

### Build
```bash
docker build -t bbox-video-wall:latest .
```

### Compose up (both services)
```bash
docker-compose up -d
```

### View logs
```bash
docker-compose logs -f video-wall
docker-compose logs -f mediamtx
```

### Stop
```bash
docker-compose down
```

## Logging

Logs are written to console. For persistent logs in Docker:
```bash
docker-compose logs -f video-wall > logs/video-wall.log
```

## License
MIT License
