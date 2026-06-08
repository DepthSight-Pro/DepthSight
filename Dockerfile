# Dockerfile

# Use official Python image as a base
FROM python:3.14-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# 1. Copy ONLY dependencies file
COPY requirements.txt ./

# 2. Install dependencies. This step will be cached.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install-deps && \
    playwright install
    
COPY . .


# Make startup script executable
RUN chmod +x ./docker-startup.sh

# Set the script as the entry point
ENTRYPOINT ["./docker-startup.sh"]
CMD ["gunicorn", "api.depthsight_api:app", "--workers", "5", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
