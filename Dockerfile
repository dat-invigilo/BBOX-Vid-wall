# Use full Python image for Flask web server
FROM python:3.11

# Install system dependencies for OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY video_wall.py .
COPY stream_handler.py .
COPY web_server.py .
COPY video_recorder.py .
COPY stream_recorder.py .
COPY config.yaml .
COPY templates/ ./templates/

ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

EXPOSE 5001

CMD ["python", "web_server.py"]
