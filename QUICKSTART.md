# Quick Start Guide

## 5-Minute Setup

### Option 1: Docker (Recommended)

```bash
# Starts both the video-wall app and its mediamtx RTSP->HLS relay
docker-compose up -d

# View logs
docker-compose logs -f video-wall
docker-compose logs -f mediamtx
```

### Option 2: Local (Python)

```bash
# Create venv
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run mediamtx separately (native binary or `docker run`), pointed at
# mediamtx.yml in this repo - web_server.py talks to it over its REST API.

# Run the web server
python web_server.py
```

## First Run

1. **Edit config.yaml** with your camera URLs:
```yaml
streams:
  - 'rtsp://camera1:554/stream'
  - 'rtsp://camera2:554/stream'
  - 'rtsp://camera3:554/stream'
  - 'rtsp://camera4:554/stream'
```

2. **Open** `http://localhost:5002` in a browser
3. **Click "Start"** - this provisions mediamtx relay paths for each camera
4. **Watch your streams** in the browser-composited grid!

## Common Issues

| Issue | Solution |
|-------|----------|
| Streams won't connect | Check URL format, verify network access |
| High CPU usage | Reduce grid size, lower resolution |
| Memory issues | Decrease buffer size in config |
| No video display (Linux) | Set `export DISPLAY=:0` |
| Docker permission denied | Run with `sudo` or add user to docker group |

## Example RTSP URLs

```
# H.264
rtsp://admin:password@192.168.1.100:554/stream1

# Axis camera
rtsp://admin:password@axis-camera-ip/axis-media/media.amp

# ONVIF compliant
rtsp://192.168.1.100:554/Profile1

# VLC test stream
rtsp://devimages-cdn.apple.com/iphone/samples/bipbop/bipbopall.m3u8

# Local file (for testing)
file:///path/to/video.mp4
```

## Performance Tips

- **2×2 grid (4 streams)**: ~400MB RAM, 60% CPU
- **Keep streams at 1080p or lower**
- **Use 1280×720 output for weak hardware**
- **Run on dedicated machine for best results**

## Monitoring

Check stream health:
```bash
# View container logs
docker-compose logs video-wall

# Live monitoring
docker stats bbox-video-wall

# Access the app
# The web UI shows connection status for each stream
```

## Next Steps

- [ ] Configure your camera URLs
- [ ] Run in Docker or locally
- [ ] Test with your streams
- [ ] Adjust grid layout as needed
- [ ] Save your config
- [ ] Deploy to production

Need help? Check the full [README.md](README.md) for detailed documentation.
