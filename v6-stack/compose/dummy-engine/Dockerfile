FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dummy_engine.py .

# Runs as root — Docker Compose v5.1.3 in non-swarm mode bind-mounts
# /run/secrets/* with host perms (0600 owner UID 1000). Phase ι/κ
# revisits this once the secret-mount story is settled.

EXPOSE 9100

ENTRYPOINT ["python", "-u", "dummy_engine.py"]
