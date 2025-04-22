# Use an official Python runtime as base image
FROM python:3.8-slim

# Set working directory
WORKDIR /app

# Copy requirements and setup files
COPY requirements.txt ./
COPY README.md ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install -e .

# Copy the rest of the application
COPY . .

# Expose port for FastAPI
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]