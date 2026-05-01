FROM python:3.11-slim

WORKDIR /app

# supervisor for process management
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (slim cloud set)
COPY requirements.cloud.txt .
RUN pip install --no-cache-dir -r requirements.cloud.txt

# Copy project
COPY . .

# Env: data + logs on the persistent volume (/app/data mounted by fly.toml)
ENV AAATS_DATA=/app/data \
    AAATS_LOGS=/app/data/logs \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Pre-create dirs (volume mount will overlay /app/data at runtime)
RUN mkdir -p /app/data/logs

EXPOSE 8501

COPY supervisord.conf /etc/supervisor/conf.d/aaats.conf

CMD ["/usr/bin/supervisord", "-n"]
