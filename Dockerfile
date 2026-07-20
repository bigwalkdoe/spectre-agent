FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY packages/ packages/
COPY apps/ apps/
COPY config/ config/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create config directory
RUN mkdir -p /root/.config/spectre

# Expose API port
EXPOSE 8000

# Default command
CMD ["spectre", "daemon", "start"]
