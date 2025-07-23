# config/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Local LLM configuration
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11435/api/generate")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:3b-instruct-fp16")

# Gemini API configuration
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent"
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY", None)

# FastEmbed model configuration
FASTEMBED_MODEL = os.getenv("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")
VECTOR_SIZE = 384  # Dimension for bge-small-en-v1.5

# Qdrant configuration
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "karmayogi_knowledge_base")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Opik configuration
OPIK_CONFIG = {
    "url": os.getenv("OPIK_API_URL"),
    "api_key": os.getenv("OPIK_API_KEY"),
    "workspace": os.getenv("OPIK_WORKSPACE"),
    "project": os.getenv("OPIK_PROJECT"),
    "use_local": False
}

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Application configuration
APP_CONFIG = {
    "title": "Karmayogi Bharat ADK Custom Agent API",
    "description": "API with custom agent routing to specialized sub-agents and chat history",
    "version": "5.1.0",
    "session_management": "Redis-based with conversation history",
    "llm_backend": "Local LLM (Ollama)",
    "sub_agents": [
        "user_profile_info_sub_agent",
        "generic_sub_agent",
        "user_profile_update_sub_agent"
    ]
}

# Chat history configuration
CHAT_HISTORY_CONFIG = {
    "limit": 6,  # Last 3 conversations (6 messages)
    "context_messages": 4,  # Messages to show in context
    "max_content_length": 200  # Max content length in history context
}