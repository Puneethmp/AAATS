"""
scripts/health_http_server.py  —  HTTP /health endpoint for Docker healthcheck
==============================================================================

PURPOSE
-------
Wraps the existing `scripts/health_check.run_health_check()` function in a
small FastAPI server so docker-compose `healthcheck:` can hit a URL and get
a clean 200/503 + JSON body instead of running the CLI inside the container.

Closes the "container marked UNHEALTHY due to missing health_check.py wiring"
issue (per memory: aaats-paper-crypto UNHEALTHY).

DESIGN
------
- Single endpoint: GET /health
- 200 + {"status": "OK", ...}      → all checks green
- 200 + {"status": "WARNING", ...} → at least one warning (still healthy)
- 503 + {"status": "CRITICAL", ...} → at least one critical (unhealthy)
- Background thread is NOT used. Each request runs all checks synchronously.
  Health checks are cheap (file stat, dir listing, psutil) — under 200ms.

DEPLOYMENT
----------
1. Add to docker-compose service `aaats-paper-crypto`:
     healthcheck:
       test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
       interval: 30s
       timeout: 5s
       retries: 3
       start_period: 60s
2. Expose port 8002 from container (no host publish needed — internal only).
3. Run inside the container alongside the trader:
     python scripts/health_http_server.py &
   OR run as separate sidecar container sharing /app/data volume.

The server binds to 0.0.0.0:8002 by default. Override with $HEALTH_PORT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add parent directory to path so we can import scripts/ and foundation/
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from scripts.health_check import run_health_check

app = FastAPI(
    title="AAATS Health",
    version="1.0",
    description="Internal health endpoint for Docker healthcheck wiring.",
)


@app.get("/health")
def health() -> Response:
    """
    Run full health check; return JSON.

    HTTP status:
      200  → OK or WARNING (container considered healthy)
      503  → CRITICAL (container marked unhealthy by Docker)
    """
    results = run_health_check(verbose=False)
    status = results.get("overall_status", "UNKNOWN")
    http_code = 503 if status == "CRITICAL" else 200
    return JSONResponse(content=results, status_code=http_code)


@app.get("/health/live")
def liveness() -> dict[str, str]:
    """
    Liveness probe — minimal. Returns 200 as long as the HTTP server itself
    is responding. Used by Kubernetes-style liveness vs readiness split.
    """
    return {"status": "alive"}


@app.get("/")
def root() -> dict[str, str]:
    """Bare endpoint so a curl with no path doesn't 404."""
    return {
        "service": "aaats-health",
        "endpoints": ["/health", "/health/live"],
    }


def main() -> None:
    import uvicorn
    port = int(os.environ.get("HEALTH_PORT", "8002"))
    host = os.environ.get("HEALTH_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
