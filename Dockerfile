# Use an official Python runtime as base image
FROM python:3.10-slim
# RUN apt-get update && apt-get install -y ffmpeg
# Set working directory
WORKDIR /app

# Copy requirements and setup files
COPY requirements.txt ./
COPY README.md ./

# adding volumn of knowledge base
VOLUME ./docs

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY iGOTassistant ./iGOTassistant


# Expose port for FastAPI
EXPOSE 8000

# Command to run the application
#CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8000", "--session_db_url", "postgresql://postgres:mysecretpassword@localhost:5432/adk"]
CMD ["uvicorn", "iGOTassistant.main:app", "--host","0.0.0.0", "--port", "8000"]
# , "0.0.0.0", "--port", "8000", "--session_db_url", "postgresql://postgres:mysecretpassword@localhost:5432/adk"]
# CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8000", "--session_db_url", "postgresql://postgres:mysecretpassword@172.17.25.197:5432/adk"]
