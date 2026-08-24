FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set default env variables for production
ENV HOST=0.0.0.0
ENV PORT=8000
ENV RELOAD=false

# Expose port
EXPOSE 8000

# Run entrypoint
CMD ["python", "run.py"]
