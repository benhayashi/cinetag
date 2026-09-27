FROM python:3.11-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DOCKER_CONTAINER=1
ENV VIDEO_DESCRIBER_DATA_DIR=/data

# Create mount points
RUN mkdir -p /data /media

EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5555/api/status || exit 1

ENTRYPOINT ["python", "app.py", "--host", "0.0.0.0", "--port", "5555"]
