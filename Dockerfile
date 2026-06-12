FROM python:3.10-slim

# Install system dependencies INCLUDING build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    g++ \
    gcc \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

COPY . .

# Change ownership of app directory
RUN chown -R appuser:appuser /app
# Switch to non-root user
USER appuser

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
