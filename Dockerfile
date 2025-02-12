FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir .[alembic] alembic

# Create a directory for alembic migrations
RUN mkdir -p /app/alembic/versions

# Add alembic to PATH
ENV PATH="/app/.local/bin:${PATH}"

# Make init script executable
RUN chmod +x /app/scripts/init_db.sh

# We do NOT define CMD here, or we define a default one that
# can be overridden by docker-compose's "command:" block.
CMD ["/bin/sh", "-c", "/app/scripts/init_db.sh && osm-meet-your-mappers --host 0.0.0.0 --port 8000"]
