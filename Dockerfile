# 1. Use an official lightweight Python image
FROM python:3.14-slim

# 2. Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Set the working directory
WORKDIR /app

# 4. Install system dependencies (minimal)
# libmagic is often needed for file type detection in AI apps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 5. Install Python dependencies
# We copy requirements first to leverage Docker's cache layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy the rest of the application code
COPY . .

# 7. Run the web service using Uvicorn
# Cloud Run expects the container to listen on the port defined by the PORT env var
CMD exec uvicorn app.main:app --host 0.0.0.0 --port $PORT