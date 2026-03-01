# ── Build stage ──
FROM python:3.13-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output for logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ── Install OS-level dependencies needed by some Python packages ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# ── Install Python dependencies first (layer caching) ──
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# ── Copy entire project ──
COPY . /app

# ── Expose API port ──
EXPOSE 8000

# ── Default entrypoint ──
CMD ["python", "-m", "backend.src.main"]
