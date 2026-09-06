FROM python:3.12-slim

# Install system dependencies including ffmpeg for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY backend/ /app/backend/
COPY static/ /app/static/

# Environment settings
ENV PORT=8080
ENV HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV USE_VERTEX_AI=true
ENV GCP_PROJECT=cjlinn-471522
ENV GCP_LOCATION=us-central1

# Ensure data and audio directory exist
RUN mkdir -p /app/data /app/data/audio

EXPOSE 8080

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
