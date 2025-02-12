# Build stage
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY . .

# Create a directory for alembic migrations
RUN mkdir -p /app/alembic/versions

# Make init script executable
RUN chmod +x /app/scripts/init_db.sh

# Install the package in editable mode
RUN pip install -e .

# Create a non-root user and switch to it
RUN useradd -m appuser
USER appuser

# We do NOT define CMD here, or we define a default one that
# can be overridden by docker-compose's "command:" block.
CMD ["/bin/sh", "-c", "/app/scripts/init_db.sh && osm-meet-your-mappers --host 0.0.0.0 --port 8000"]
