FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py ./
COPY README.md ARCHITECTURE.md ./

# Create non-root user
RUN useradd -m -u 1000 gpsuser && \
    chown -R gpsuser:gpsuser /app

# Create logs directory
RUN mkdir -p /app/logs && chown gpsuser:gpsuser /app/logs

# Switch to non-root user
USER gpsuser

# Expose ports
EXPOSE 8000 5023 5024/udp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

# Run application
CMD ["python", "main.py"]
