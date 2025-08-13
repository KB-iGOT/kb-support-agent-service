# Karmayogi Bharat Support Bot

[![Version](https://img.shields.io/badge/version-5.6.0-blue.svg)](https://github.com/your-repo/karmayogi-support-bot)
[![Python](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An intelligent conversational AI support bot for the Karmayogi Bharat learning platform, featuring intent-based routing, multi-language support, and comprehensive user assistance capabilities.

## 🚀 Features

### Core Capabilities
- **Intent-based Query Routing**: Automatically classifies and routes user queries to specialized sub-agents
- **Multi-language Support**: Automatic language detection and translation (Hindi/English)
- **Thread-safe Architecture**: Concurrent user support with isolated request contexts
- **Anonymous User Support**: Full functionality for non-logged users
- **Real-time Feedback System**: User feedback collection and analytics

### Specialized Support Areas
- **Profile Management**: Name, email, and mobile number updates with OTP verification
- **Course Progress**: Technical issue resolution for course consumption problems
- **Certificate Support**: Certificate reissue, name corrections, and QR code issues
- **Ticket Management**: Integrated support ticket creation via Zoho Desk
- **General Platform Help**: Comprehensive platform guidance and information

### Technical Features
- **Advanced Data Integration**: PostgreSQL, Redis, Qdrant vector database
- **LLM Integration**: Gemini 2.0 Flash with local LLM fallback
- **Performance Optimization**: Connection pooling, caching, parallel processing
- **Comprehensive Logging**: Structured logging with performance monitoring
- **Health Monitoring**: Detailed system health checks and metrics

## 📋 Prerequisites

- Python 3.9+
- Redis 6.0+
- PostgreSQL 12+
- Qdrant 1.0+
- Access to Karmayogi platform APIs
- Google Cloud account (for translation and Gemini)
- Zoho Desk account (for ticketing)
- Local LLM setup (Ollama recommended)

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-repo/karmayogi-support-bot.git
cd karmayogi-support-bot
```

### 2. Create Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Configuration
Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Core Application
ENVIRONMENT=development
LOG_LEVEL=INFO
LOG_DIR=logs

# Database Connections
POSTGRESQL_URL=postgresql://user:password@localhost:5432/karmayogi_db
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=your_qdrant_key

# External APIs
KARMAYOGI_API_KEY=your_karmayogi_api_key
GOOGLE_API_KEY=your_google_api_key

# Zoho Desk Integration
ZOHO_REFRESH_TOKEN=your_zoho_refresh_token
ZOHO_CLIENT_ID=your_zoho_client_id
ZOHO_CLIENT_SECRET=your_zoho_client_secret
ZOHO_ORG_ID=your_org_id
ZOHO_DEPARTMENT_ID=your_department_id

# LLM Configuration
LOCAL_LLM_URLS=http://localhost:11434/api/generate
LOCAL_LLM_MODEL=llama3.2:3b-instruct-fp16
GEMINI_API_URL=https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent

# Service URLs
learning_service_url=https://api.karmayogi.gov.in
lms_service_url=https://lms.karmayogi.gov.in
```

### 5. Database Setup

**PostgreSQL:**
```sql
-- Create database
CREATE DATABASE karmayogi_db;

-- Create tables (run the SQL scripts in sql/migrations/)
\i config/karmayogi_db.sql
\i config/feedback.sql
```

**Redis:**
```bash
# Start Redis server
redis-server

# Verify connection
redis-cli ping
```

**Qdrant:**
```bash
# Start Qdrant server
docker run -p 6333:6333 qdrant/qdrant

# Verify connection
curl http://localhost:6333/health
```

### 6. Local LLM Setup (Ollama)

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull required model
ollama pull llama3.2:3b-instruct-fp16

# Start Ollama server
ollama serve
```

## 🚀 Running the Application

### Development Mode
```bash
python main.py
```

### Production Mode
```bash
# Using uvicorn directly
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# Using gunicorn (recommended for production)
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Docker Setup
```bash
# Build image
docker build -t karmayogi-support-bot .

# Run container
docker run -d \
  --name support-bot \
  -p 8000:8000 \
  --env-file .env \
  karmayogi-support-bot
```

### Docker Compose
```bash
# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f support-bot
```

## 📖 API Documentation

### Health Check
```bash
curl http://localhost:8000/health
```

### Chat Endpoints

**Start Chat (Authenticated Users):**
```bash
curl -X POST "http://localhost:8000/chat/start" \
  -H "Content-Type: application/json" \
  -H "user-id: your_user_id" \
  -H "cookie: your_auth_cookie" \
  -H "channel: web" \
  -d '{
    "channel_id": "web",
    "text": "Hello, I need help with my profile"
  }'
```

**Continue Chat:**
```bash
curl -X POST "http://localhost:8000/chat/send" \
  -H "Content-Type: application/json" \
  -H "user-id: your_user_id" \
  -H "cookie: your_auth_cookie" \
  -H "channel: web" \
  -d '{
    "channel_id": "web",
    "text": "I want to update my mobile number"
  }'
```

**Anonymous Chat:**
```bash
curl -X POST "http://localhost:8000/anonymous/chat/start" \
  -H "Content-Type: application/json" \
  -H "user-id: anonymous-uuid-timestamp" \
  -d '{
    "channel_id": "web",
    "text": "What is Karmayogi platform?"
  }'
```

**Submit Feedback:**
```bash
curl -X POST "http://localhost:8000/feedback/submit" \
  -H "Content-Type: application/json" \
  -H "user-id: your_user_id" \
  -H "cookie: your_auth_cookie" \
  -H "channel: web" \
  -d '{
    "message_id": "msg_uuid",
    "feedback_type": "upvote",
    "feedback_comment": "Very helpful response"
  }'
```

## 🏗️ Architecture Overview

### System Components

```
          ┌─────────────────┐         ┌─────────────────┐
          │   Client Apps   │         │   Web Interface │
          │                 │         │                 │
          └─────────────────┘         └─────────────────┘
                    │                           │
                    └───────────────────────────┘
                                 │
                         ┌─────────────────┐
                         │   FastAPI       │
                         │   Application   │
                         └─────────────────┘
                                 │
                         ┌─────────────────┐
                         │  Translation    │
                         │  Service        │
                         └─────────────────┘
                                 │
                         ┌─────────────────┐
                         │  Intent         │
                         │  Classifier     │
                         └─────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ Profile Info    │  │ Certificate     │  │ Course Progress │
│ Sub-Agent       │  │ Issue Sub-Agent │  │ Sub-Agent       │........
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                         ┌─────────────────┐
                         │   Data Layer    │
                         │ Redis|PostgreSQL│
                         │ Qdrant|APIs     │
                         └─────────────────┘
```

### Intent Classification

The system automatically routes queries to specialized sub-agents:

1. **USER_PROFILE_INFO**: Personal data and enrollment queries
2. **USER_PROFILE_UPDATE**: Profile modification requests
3. **CERTIFICATE_ISSUES**: Certificate-related problems
4. **COURSE_PROGRESS_ISSUES**: Technical course consumption issues
5. **TICKET_CREATION**: Support ticket requests
6. **GENERAL_SUPPORT**: Platform information queries

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `ENVIRONMENT` | Application environment | No | `development` |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `POSTGRESQL_URL` | PostgreSQL connection string | Yes | - |
| `REDIS_URL` | Redis connection string | Yes | - |
| `KARMAYOGI_API_KEY` | Karmayogi platform API key | Yes | - |
| `GOOGLE_API_KEY` | Google services API key | Yes | - |
| `ZOHO_REFRESH_TOKEN` | Zoho OAuth refresh token | Yes | - |
| `LOCAL_LLM_URLS` | Comma-separated LLM URLs | No | `http://localhost:11434/api/generate` |



## 📊 Monitoring and Observability

### Health Monitoring

The application provides comprehensive health endpoints:

```bash
# System health
curl http://localhost:8000/health

# Response includes:
{
  "status": "healthy",
  "version": "5.6.0",
  "redis_health": {"connected": true, "ping": "PONG"},
  "postgresql_health": {"status": "healthy"},
  "connection_stats": {
    "redis_pool_size": 10,
    "postgres_pool_size": 10
  }
}
```

### Logging

Structured logging with multiple levels:

```python
# Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Log categories: startup, chat, agent, database, external_api
# Performance tracking: execution time, request duration

# Example log entry:
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "category": "chat",
  "operation": "intent_classification",
  "user_id": "user_123",
  "session_id": "session_456",
  "duration_ms": 150,
  "message": "Query routed to certificate_issue_agent"
}
```

### Performance Metrics

Key metrics tracked:
- Number of tokens generated
- Number of LLM calls

## 🔒 Security

### Data Protection
- Sensitive data masking in logs
- Thread-safe request context isolation
- Secure OTP generation and verification
- API rate limiting and timeout management

### Authentication
- Header-based user authentication
- Session-based state management
- Anonymous user session isolation

### Input Validation
- Request payload validation
- XSS protection
- SQL injection prevention
- Data sanitization

## 🚀 Deployment

### Production Deployment

**Docker Deployment:**
```bash
# Production Docker Compose
docker-compose -f docker-compose.prod.yml up -d
```

**Kubernetes Deployment:**
```yaml
# See kubernetes/ directory for complete manifests
kubectl apply -f kubernetes/
```

**Environment Setup:**
```bash
# Production environment variables
export ENVIRONMENT=production
export LOG_LEVEL=INFO
export WORKERS=4
```

### Scaling Considerations

- **Horizontal Scaling**: Multiple application instances behind load balancer
- **Database Scaling**: Read replicas for PostgreSQL, Redis clustering
- **Caching Strategy**: Multi-level caching with TTL optimization
- **Resource Management**: Memory and CPU optimization

## 🛠️ Troubleshooting

### Common Issues

**Database Connection Issues:**
```bash
# Check PostgreSQL connection
psql $POSTGRESQL_URL -c "SELECT 1;"

# Check Redis connection
redis-cli -u $REDIS_URL ping
```

**LLM Processing Issues:**
```bash
# Check Ollama status
curl http://localhost:11434/api/tags

# Check Gemini API
curl -H "Authorization: Bearer $GOOGLE_API_KEY" \
  "https://generativelanguage.googleapis.com/v1beta/models"
```

**Translation Service Issues:**
```bash
# Test Google Translate API
curl -X POST \
  "https://translation.googleapis.com/language/translate/v2?key=$GOOGLE_API_KEY" \
  -d "q=hello&target=hi"
```

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python main.py
```

### Log Analysis

```bash
# View real-time logs
tail -f logs/app.log

# Search for specific operations
grep "certificate_issue" logs/app.log

# Performance analysis
grep "duration_ms" logs/app.log | sort -k6 -n
```


## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Install development dependencies
pip install -r requirements.txt

# Install pre-commit hooks
pre-commit install

# Run code formatting
black .
isort .

# Run linting
flake8 .
pylint src/
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.



## 📞 Support

For support and questions:
- Create an issue in this repository
- Contact the development team
- Check the documentation in the `docs/` directory

---

**Version**: 5.6.0  
**Last Updated**: 2024-01-15  
**Maintained by**: Karmayogi Development Team
