# Quick Start Guide

## 5-Minute Setup

### Option 1: Docker (Recommended)

**On Linux/Mac:**
```bash
# Build
docker build -t bbox-video-wall .

# Or use script
bash build.sh

# Run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f
```

**On Windows:**
```cmd
# Build
docker build -t bbox-video-wall .

# Or use script
build.bat

# Run
docker-compose up -d

# View logs
docker-compose logs -f video-wall
```

### Option 2: Local (Python)

**Linux/Mac:**
```bash
# Setup environment
bash setup-dev.sh

# Activate environment
source venv/bin/activate

# Run app
python app.py
```

**Windows:**
```cmd
# Create venv
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run app
python app.py
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

2. **Launch the app**
3. **Click "Start Wall"** in the GUI
4. **Watch your streams** in a beautiful grid!

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

## CLI Usage (Headless)

```bash
# From config file
python cli.py --config config.yaml --headless

# With command-line args
python cli.py --streams rtsp://cam1 rtsp://cam2 \
              --cols 2 --rows 2 \
              --width 1920 --height 1080 \
              --headless

# Output to file
python cli.py --streams rtsp://cam1 rtsp://cam2 \
              --output wall.mp4 \
              --headless
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
# The GUI shows connection status for each stream
```

## Next Steps

- [ ] Configure your camera URLs
- [ ] Run in Docker or locally
- [ ] Test with your streams
- [ ] Adjust grid layout as needed
- [ ] Save your config
- [ ] Deploy to production

Need help? Check the full [README.md](README.md) for detailed documentation.
