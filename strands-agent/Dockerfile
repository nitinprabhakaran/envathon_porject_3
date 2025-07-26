FROM python:3.11-slim

# Install system dependencies for ARM64
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install MCP servers
RUN git clone https://github.com/nguyenvanduocit/gitlab-mcp.git /mcp/gitlab-mcp && \
    cd /mcp/gitlab-mcp && npm install

RUN git clone https://github.com/sonarsource/sonarqube-mcp-server.git /mcp/sonarqube-mcp && \
    cd /mcp/sonarqube-mcp && pip install -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]