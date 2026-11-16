# syntax=docker/dockerfile:1
# Pinned by digest so a rebuild gets the same base; Dependabot (docker) bumps it.
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

# Install system dependencies required by Pillow, OpenJPEG, and fonts
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libopenjp2-7 \
    libopenblas0 \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    fonts-noto \
    fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (layer caching). Both files pin
# every package by hash, as the Pi installer does: the installer tools first
# (pip, setuptools, wheel), then the runtime lockfile. Some Pi-only packages
# (spidev, cysystemd) ship only as source, so a compiler and the systemd
# headers are installed for this step and removed after it.
COPY install/bootstrap-requirements.txt install/requirements.txt install/
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libsystemd-dev \
    pkg-config \
 && pip install --no-cache-dir --require-hashes -r install/bootstrap-requirements.txt \
 && pip install --no-cache-dir --require-hashes -r install/requirements.txt \
 && apt-get purge -y --auto-remove gcc libc6-dev libsystemd-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ src/
COPY VERSION VERSION

# Environment: force dev mode and disable hardware refresh
ENV INKYPI_ENV=dev \
    INKYPI_NO_REFRESH=1 \
    PYTHONPATH=src

EXPOSE 8080

# Create a non-root user and transfer ownership so the app runs unprivileged.
RUN useradd -m -u 1000 appuser \
 && chown -R appuser:appuser /app

USER appuser

# The slim image has no wget or curl, so probe /healthz (the always-OK
# liveness route) with the image's own Python. Dev mode serves on 8080.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz', timeout=4)"]

CMD ["python", "src/inkypi.py", "--dev", "--web-only"]
