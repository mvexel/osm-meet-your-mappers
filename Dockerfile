FROM python:3.12-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --upgrade pip && \
    pip install poetry

# Copy only the files needed for dependency installation
COPY pyproject.toml poetry.lock ./

# Install Python dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --only main

# Copy the rest of the application
COPY . .

# Install the package
RUN poetry install --only-root

EXPOSE 8000
CMD ["python"]
# Don't copy everything in development - we'll use volumes instead
