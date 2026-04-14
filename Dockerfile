# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

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

# Copy and install Python dependencies first (layer caching)
COPY install/requirements.txt install/requirements.txt
RUN pip install --no-cache-dir --upgrade pip wheel \
 && pip install --no-cache-dir -r install/requirements.txt

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:8080/ || exit 1

CMD ["python", "src/inkypi.py", "--dev", "--web-only"]
