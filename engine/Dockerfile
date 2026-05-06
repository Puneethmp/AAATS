FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build deps for numpy/pandas wheels (slim image lacks them by default)
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

COPY engine/requirements.txt /app/engine/requirements.txt
RUN pip install --no-cache-dir -r /app/engine/requirements.txt

# Strip build deps once wheels are installed (keeps image smaller)
RUN apt-get purge -y --auto-remove build-essential gcc \
 && rm -rf /var/lib/apt/lists/*

# Copy only the dirs the runner actually imports + the engine wrapper itself.
# Order matters for layer caching: stable deps first, code last.
COPY foundation/      /app/foundation/
COPY indicators/      /app/indicators/
COPY execution/       /app/execution/
COPY decision/        /app/decision/
COPY risk/            /app/risk/
COPY observability/   /app/observability/
COPY intelligence/    /app/intelligence/
COPY config/          /app/config/
COPY trading/         /app/trading/
COPY engine/          /app/engine/

# Run unprivileged. UID 10001 matches the watchdog's UID convention.
RUN useradd -u 10001 -m -s /bin/false aaats \
 && mkdir -p /app/data /app/logs \
 && chown -R aaats:aaats /app
USER 10001

ENV PYTHONPATH=/app

CMD ["python", "-u", "-m", "engine.v6_engine"]
