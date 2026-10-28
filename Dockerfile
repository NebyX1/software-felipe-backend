# Validated Python 3.11 base, pinned for reproducible deployments.
FROM python:3.11-slim@sha256:ae952e0a57138a4317b9b61caaa19a8217c2f356803f8d7e63aad08769950937

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libmariadb-dev \
    pkg-config \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt requirements.lock ./
RUN pip install --upgrade pip && pip install -r requirements.lock

ENV FLASK_CONFIG=production
ENV BOOTSTRAP_ON_START=true
ENV DEMO_SEED_ON_START=false

# Copy project
COPY . .

# Make entrypoint executable
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Expose port
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-5000}/health || exit 1

# Run entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
