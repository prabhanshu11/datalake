# Datalake Container
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    ffmpeg \
    bash \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv to /usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local" sh && \
    ln -s /usr/local/uv /usr/local/bin/uv && \
    ln -s /usr/local/uvx /usr/local/bin/uvx

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash datalake

# Set working directory
WORKDIR /app

# Copy dependency files first (for Docker layer caching)
COPY --chown=datalake:datalake pyproject.toml uv.lock ./

# Install Python dependencies
RUN /usr/local/bin/uv sync --frozen

# Copy application files
COPY --chown=datalake:datalake schema.sql main.py README.md ./
COPY --chown=datalake:datalake scripts/ ./scripts/
COPY --chown=datalake:datalake tests/ ./tests/

# Make scripts executable
RUN chmod +x ./scripts/*.sh

# Create necessary directories with proper ownership
RUN mkdir -p /app/logs /data && \
    chown -R datalake:datalake /app/logs /data

# Switch to non-root user
USER datalake

# Set environment variables (isolated per container)
ENV DATA_DIR=/data \
    DB_FILE=/data/datalake.db \
    LOG_DIR=/app/logs \
    PROJECT_ROOT=/app \
    SCHEMA_FILE=/app/schema.sql

# Expose volume mount points
VOLUME ["/data", "/app/logs"]

# Health check - verify database is accessible
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD [ -f "${DB_FILE}" ] && sqlite3 "${DB_FILE}" "SELECT 1;" > /dev/null || exit 1

# Default command - run tests
CMD ["/usr/local/bin/uv", "run", "pytest", "-v"]
