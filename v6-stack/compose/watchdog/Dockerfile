FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watchdog.py .

# Runs as root — required because Docker Compose v5.1.3 in non-swarm mode
# bind-mounts the secret file with host perms (mode 0600 owner UID 1000),
# and a docker.sock-using container is host-root-equivalent regardless.
# Phase ι/κ revisits this once we have a stable secret-mount story.

ENTRYPOINT ["python", "-u", "watchdog.py"]
