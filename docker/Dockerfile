# Lifelogger Docker Image
# Multi-stage build for smaller image size

FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY pyproject.toml ./
COPY lifelogger ./lifelogger/

RUN pip install --no-cache-dir build && \
    pip install --no-cache-dir -e .

# Production image
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Create non-root user
RUN useradd -m -u 1000 lifelogger && \
    chown -R lifelogger:lifelogger /app

USER lifelogger

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: run web server
CMD ["python", "-m", "uvicorn", "lifelogger.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

EXPOSE 8000
