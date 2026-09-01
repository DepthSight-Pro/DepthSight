# Dockerfile

# Use official Python image as a base
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y build-essential libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# 1. Copy ONLY dependencies file
COPY requirements.txt ./

# 2. Install dependencies. This step will be cached.
# Playwright browsers are installed outside $HOME so the non-root runtime
# user can execute them.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install-deps && \
    playwright install
    
COPY . .

# Non-root runtime user; pre-create bind-mount targets with correct ownership.
RUN chmod +x ./docker-startup.sh && \
    useradd --uid 1000 --create-home depthsight && \
    mkdir -p /app/data /app/data_storage /app/logs && \
    chown -R depthsight:depthsight /app/data /app/data_storage /app/logs /opt/ms-playwright

# Writable cache dirs for libraries that insist on $HOME
ENV MPLCONFIGDIR=/tmp/matplotlib

USER depthsight

# Set the script as the entry point
ENTRYPOINT ["./docker-startup.sh"]
CMD ["gunicorn", "api.depthsight_api:app", "--workers", "5", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
