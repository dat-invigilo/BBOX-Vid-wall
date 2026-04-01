# Use full Python image for Flask web server
FROM python:3.11

# Install system dependencies (FFmpeg for video processing, no more OpenCV)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY video_wall.py .
COPY ffmpeg_stream_handler.py .
COPY web_server.py .
COPY video_recorder.py .
COPY ffmpeg_recorder.py .
COPY config.yaml .
COPY templates/ ./templates/
COPY static/ ./static/

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

EXPOSE 5002

CMD ["python", "web_server.py"]
