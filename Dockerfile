# =============================================================================
# Multi-Stage Dockerfile for Trading Bot
# Python 3.9 based with optimized build process
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder - Build dependencies and compile native extensions
# -----------------------------------------------------------------------------
FROM python:3.9-slim as builder

# Set working directory
WORKDIR /build

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    make \
    wget \
    curl \
    tar \
    automake \
    libtool \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install TA-Lib from source (required for technical analysis)
# Fix for ARM64 (Apple Silicon) build: update config.guess and config.sub using system files
RUN curl -L -o ta-lib-0.4.0-src.tar.gz https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz/download && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    cp /usr/share/misc/config.guess . && \
    cp /usr/share/misc/config.sub . && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Copy dependency files
COPY pyproject.toml .
COPY src/ src/

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install Python dependencies
# Using --no-cache-dir to reduce layer size
RUN pip install --no-cache-dir .

# -----------------------------------------------------------------------------
# Stage 2: Runtime - Minimal production image
# -----------------------------------------------------------------------------
FROM python:3.9-slim

# Metadata
LABEL maintainer="osangwon <your.email@example.com>"
LABEL description="Cryptocurrency Trading Bot with ICT Strategies"
LABEL version="0.1.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy TA-Lib library from builder
COPY --from=builder /usr/lib/libta_lib.* /usr/lib/
COPY --from=builder /usr/include/ta-lib/ /usr/include/ta-lib/

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create non-root user for security
RUN groupadd -r tradingbot && \
    useradd -r -g tradingbot -u 1000 -m -s /bin/bash tradingbot

# Set working directory
WORKDIR /app

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R tradingbot:tradingbot /app

# Copy application code
COPY --chown=tradingbot:tradingbot src/ /app/src/
COPY --chown=tradingbot:tradingbot alembic/ /app/alembic/
COPY --chown=tradingbot:tradingbot alembic.ini /app/
COPY --chown=tradingbot:tradingbot pyproject.toml /app/
COPY --chown=tradingbot:tradingbot README.md /app/
COPY --chown=tradingbot:tradingbot static/ /app/static/

# Copy entrypoint script
COPY --chown=tradingbot:tradingbot scripts/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER tradingbot

# Expose API port
EXPOSE 8000

# Health check - verify API server is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command
CMD ["python", "-m", "src"]
