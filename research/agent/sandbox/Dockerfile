# Stage B sandbox image: just Python + the two libraries strategies may use.
# Versions match the research machine so pickled price snapshots load identically.
# Build (needs network once):  python -m research.agent.sandbox build
# Every run then starts with --network none, read-only filesystem, no capabilities,
# memory/CPU/process limits and a hard timeout (see research/agent/sandbox.py).
FROM python:3.12-slim
RUN pip install --no-cache-dir pandas==2.3.1 numpy==2.2.5 && \
    useradd --no-create-home --uid 10001 sandbox
USER sandbox
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
