# Stage 1: Build stage
FROM python:3.12-slim AS builder
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --upgrade pip

# Copy requirements (for caching) and install dependencies to a temporary location
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# Stage 2: Production image
FROM python:3.12-slim
WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from the builder stage
COPY --from=builder /install /usr/local

# Copy your application code
COPY . .

# Expose the port your app listens on
EXPOSE 8000

# Start the FastAPI app using Gunicorn with Uvicorn workers
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "osm_meet_your_mappers.api:app", "--bind", "0.0.0.0:8000", "--workers", "4"]
