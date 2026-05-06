FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py formatters.py digest.py .

# Runs as root — Compose v5 non-swarm bind-mounts secrets with host perms.
# Phase ι/κ revisits this once the secret-mount story is settled.

EXPOSE 8080

ENTRYPOINT ["python", "-u", "bot.py"]
