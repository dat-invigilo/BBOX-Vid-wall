# mediamtx binary - copied in below rather than run as a separate container/module
FROM bluenviron/mediamtx:1.9.3-ffmpeg AS mediamtx

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

COPY --from=mediamtx /mediamtx /usr/local/bin/mediamtx

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY video_wall.py .
COPY mediamtx_client.py .
COPY web_server.py .
COPY video_recorder.py .
COPY ffmpeg_recorder.py .
COPY config.yaml .
COPY mediamtx.yml .
COPY entrypoint.sh .
COPY templates/ ./templates/
COPY static/ ./static/

RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

EXPOSE 5002 8554 8888 9997

ENTRYPOINT ["./entrypoint.sh"]
