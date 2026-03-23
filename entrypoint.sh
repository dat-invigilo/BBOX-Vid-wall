#!/bin/bash
set -e

# Video Wall Container Entrypoint Script

echo "======================================="
echo "Video Wall Container Starting..."
echo "======================================="

# Log environment
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"

# Optional: Run pytest if tests exist
if [ -f "test_app.py" ]; then
    echo "Running tests..."
    python -m pytest test_app.py -v || true
fi

# Execute the main application or passed command
if [ $# -eq 0 ]; then
    # Start the PyQt app with display support
    if [ ! -z "$DISPLAY" ]; then
        echo "Starting PyQt application on display: $DISPLAY"
        exec python app.py
    else
        echo "No display available. Set DISPLAY environment variable or use headless mode."
        exec python -c "from app import VideoWallApp; app = VideoWallApp(); app.run_headless()"
    fi
else
    # Execute passed command
    exec "$@"
fi
