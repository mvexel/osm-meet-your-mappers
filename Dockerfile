# Base
FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip

# Builder
FROM base AS builder
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# Runtime for API, backfill, and init_boundaries
FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*
COPY --from=builder /install /usr/local
COPY . .

FROM runtime AS api
RUN pip install -e .
EXPOSE 8000
CMD ["uvicorn", "osm_meet_your_mappers.api:app", "--host", "0.0.0.0", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "\"*\""]

FROM runtime AS init_boundaries
RUN apt-get update && apt-get install -y --no-install-recommends gdal-bin && rm -rf /var/lib/apt/lists/*
CMD ["python", "-m", "scripts.init_boundaries"]

FROM runtime AS backfill
CMD ["python", "-m", "scripts.backfill"]
