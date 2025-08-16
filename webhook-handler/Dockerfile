FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create logs directory
RUN mkdir -p logs

# Expose port (default)
EXPOSE 8090

# Run application using environment variable
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${WEBHOOK_HANDLER_PORT:-8090}"]