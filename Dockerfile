# Use an official Python runtime as base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements and setup files
COPY requirements.txt ./
COPY README.md ./

# adding volumn of knowledge base
VOLUME ./docs

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY src ./src


# Expose port for FastAPI
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
