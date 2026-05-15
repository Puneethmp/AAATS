# AAATS Deployment - Oracle Cloud Free Tier Optimized
# Python 3.11 slim image for minimal footprint

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs data/state data/checkpoints

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python scripts/health_check.py || exit 1

# No default CMD — every compose service supplies its own command
# (paper-crypto runs `trading/paper_loop.py`, dashboard runs `streamlit`,
# metrics runs `monitoring/metrics_exporter.py`). Forcing the override
# avoids resurrecting the deleted main.py orchestrator path.
CMD ["python", "-c", "raise SystemExit('No default CMD; supply one in docker-compose.yml')"]
