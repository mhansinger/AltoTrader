FROM python:3.11-slim

# Install only what's needed to build C extensions (e.g. pyarrow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r altotrader && useradd -r -g altotrader altotrader

WORKDIR /app

# Install the altotrader package from pyproject.toml
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy runtime files needed by the streamer
COPY Examples/ Examples/

# Ensure log directory is writable by non-root user
RUN mkdir -p logs && chown -R altotrader:altotrader /app

USER altotrader

CMD ["python", "Examples/run_update_service.py"]
