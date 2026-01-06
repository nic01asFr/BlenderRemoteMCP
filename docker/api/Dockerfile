# API Gateway Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (for container management)
RUN curl -fsSL https://get.docker.com | sh

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main_mcp.py .
COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
# Note: For Docker socket access, container needs to run with appropriate group

EXPOSE 8000

CMD ["python", "main_mcp.py"]
