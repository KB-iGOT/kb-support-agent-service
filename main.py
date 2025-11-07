# main.py - ADK Custom Agent with Intent-based Routing and Enhanced Logging
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from typing import Optional

import opik
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from google.adk.sessions import InMemorySessionService
from opik import opik_context
from opik.integrations.adk import OpikTracer
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from agents.anonymous_customer_agent_router import AnonymousKarmayogiCustomerAgent
from agents.custom_agent_router import KarmayogiCustomerAgent
from utils.common_utils import get_embedding_model, rephrase_query_with_history
from utils.contentCache import get_cached_user_details, hash_cookie
# Import the new logging configuration
from utils.logging_config import (
    get_access_logger,
    log_request,
    log_agent_activity,
    LogExecutionTime,
    setup_development_logging,
    setup_production_logging
)
from utils.postgresql_enrollment_service import initialize_user_enrollments_in_postgresql, postgresql_service
from utils.redis_connection_manager import (
    get_redis_manager,
    cleanup_redis_connections,
    get_redis_response,
    redis_health_check,
    set_redis_response
)
from utils.redis_session_service import (
    redis_session_service,
    get_or_create_session,
    add_chat_message,
    update_session_data,
)
from utils.request_context import RequestContext
from utils.translation_service import get_translation_context, translate_response_to_user_language, TranslationService
from utils.userDetails import UserDetailsError

load_dotenv()

# Setup logging based on environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.getenv("LOG_DIR", "logs")

if ENVIRONMENT == "production":
    setup_production_logging(LOG_DIR, LOG_LEVEL)
else:
    setup_development_logging(LOG_DIR, LOG_LEVEL)

# Get logger after setup
logger = logging.getLogger(__name__)
access_logger = get_access_logger()


# Reduce noise from Google GenAI function call warnings
logging.getLogger("google_genai.types").setLevel(logging.ERROR)


# Global ADK session service to prevent connection leaks
_global_adk_session_service: Optional[InMemorySessionService] = None

async def get_adk_session_service() -> InMemorySessionService:
    """Get or create the global ADK session service to prevent connection leaks."""
    global _global_adk_session_service
    if _global_adk_session_service is None:
        _global_adk_session_service = InMemorySessionService()
    return _global_adk_session_service

async def cleanup_adk_session_service():
    """Clean up the global ADK session service."""
    global _global_adk_session_service
    if _global_adk_session_service is not None:
        try:
            # If the session service has a cleanup method, call it
            if hasattr(_global_adk_session_service, 'close'):
                await _global_adk_session_service.close()
            elif hasattr(_global_adk_session_service, 'cleanup'):
                await _global_adk_session_service.cleanup()
            logger.info("✅ ADK session service cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up ADK session service: {e}")
        finally:
            _global_adk_session_service = None

# OPIK URL
# opik.configure(
#     url=os.getenv("OPIK_API_URL"),
#     api_key=os.getenv("OPIK_API_KEY"),
#     workspace=os.getenv("OPIK_WORKSPACE", "default"),
#     use_local=False
# )

# OPIK LOCAL - enable this for SERVER
opik.configure(
    url=os.getenv("OPIK_API_URL"),
    use_local=True,
)

opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

translation_service = TranslationService()

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests"""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Extract user info from headers if available
        user_id = request.headers.get("user-id", "unknown")

        # Log request start
        logger.debug(f"Request started: {request.method} {request.url.path}")

        response = await call_next(request)

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Log request completion
        log_request(
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id if user_id != "unknown" else None
        )

        return response


class StartChat(BaseModel):
    """Model for starting a chat session."""
    channel_id: str
    text: str | None = None
    audio: Optional[str] = None
    language: Optional[str] = None
    tts_output: Optional[bool] = False


class ChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    channel: str
    message: str
    response: str
    timestamp: float


class FeedbackRequest(BaseModel):
    """Model for submitting user feedback on chat responses."""
    trace_id: Optional[str] = None
    thread_id: Optional[str] = None
    feedback_type: Optional[str] = None  # "thumbs_up" or "thumbs_down"
    comment: Optional[str] = None
    rating: Optional[float] = None  # Optional numeric rating (0-1)

    class Config:
        json_schema_extra = {
            "example": {
                "trace_id": "trace_abc123",
                "feedback_type": "thumbs_up",
                "comment": "Very helpful response!",
                "rating": 0.9
            }
        }


class FeedbackResponse(BaseModel):
    """Response model for feedback submission."""
    status: str
    message: str
    feedback_details: dict

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "message": "Feedback logged successfully",
                "feedback_details": {
                    "trace_id": "trace_abc123",
                    "feedback_type": "thumbs_up",
                    "timestamp": 1699564800.0
                }
            }
        }


@asynccontextmanager
async def lifespan(app):
    """✅ OPTIMIZED: Application lifespan with shared Redis connection management"""
    # Startup code
    logger.info("🚀 Starting up Karmayogi Bharat ADK Custom Agent...")
    logger.info(f"Environment: {ENVIRONMENT}")
    logger.info(f"Log Level: {LOG_LEVEL}")

    try:
        with LogExecutionTime("Redis Manager Initialization", "startup"):
            # ✅ Initialize shared Redis connection manager first
            logger.info("Initializing shared Redis connection manager...")
            redis_manager = await get_redis_manager()
            redis_client = await redis_manager.get_redis_client()
            logger.info("✅ Shared Redis connection manager initialized successfully")

        with LogExecutionTime("PostgreSQL Initialization", "startup"):
            await postgresql_service.initialize_pool()
            logger.info("✅ PostgreSQL connection pool initialized")

        with LogExecutionTime("Embedding Model Pre-warming", "startup"):
            # Pre-warm embedding model
            get_embedding_model()
            logger.info("✅ Embedding model pre-warmed")

        logger.info("✅ Startup complete - Using optimized shared Redis connections")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}", exc_info=True)
        raise

    yield

    # ✅ OPTIMIZED SHUTDOWN
    logger.info("🛑 Shutting down with optimized cleanup...")
    try:
        with LogExecutionTime("PostgreSQL Cleanup", "shutdown"):
            # Close PostgreSQL connections
            await postgresql_service.close()
            logger.info("✅ PostgreSQL connections closed")

        with LogExecutionTime("Redis Cleanup", "shutdown"):
            # ✅ Close shared Redis connections (handles both cache and session service)
            await cleanup_redis_connections()
            logger.info("✅ Shared Redis connections cleaned up")

        with LogExecutionTime("Bhashini HTTP Client Cleanup", "shutdown"):
            # Close Bhashini HTTP client
            from utils.translation_service import bhashini_translator
            await bhashini_translator.close()
            logger.info("✅ Bhashini HTTP client closed")

        with LogExecutionTime("Opik Tracer Cleanup", "shutdown"):
            # Flush Opik tracer to ensure all traces are sent
            opik_tracer.flush()
            opik.flush_tracker()
            logger.info("✅ Opik tracer flushed")

    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}", exc_info=True)

    logger.info("✅ Shutdown complete")


# Helper function to get current trace ID from Opik context
def get_current_trace_id() -> Optional[str]:
    """
    Safely retrieve the current trace ID from Opik context.
    Returns None if no trace is active or if there's an error.
    """
    try:
        current_trace = opik_context.get_current_trace()
        if current_trace and hasattr(current_trace, 'id'):
            return current_trace.id
        return None
    except Exception as e:
        logger.debug(f"Could not retrieve trace ID from Opik context: {e}")
        return None


# 5. UPDATE FastAPI app initialization (replace existing)
app = FastAPI(
    title="Karmayogi Bharat ADK Custom Agent API",
    description="API with custom agent routing to specialized sub-agents, chat history, and anonymous user support",
    version="5.7.0",  # Updated version with feedback support
    lifespan=lifespan
)

# Add middlewares
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """✅ OPTIMIZED: Health endpoint using shared Redis connection manager"""
    try:
        with LogExecutionTime("Health Check", "health"):
            # Use shared Redis health check
            redis_health = await redis_health_check()

            # Test PostgreSQL service
            postgres_health = await postgresql_service.health_check()

            # Get connection statistics from shared manager
            redis_manager = await get_redis_manager()
            connection_stats = await redis_manager.get_connection_stats()

            health_status = {
                "message": "Karmayogi Bharat ADK Custom Agent is running!",
                "version": "5.6.0",  # Updated version
                "agent_type": "ADK Custom Agent with Enhanced Logging",
                "session_management": "Redis-based with shared connection pool",
                "llm_backend": "Local LLM (vLLM with OpenAI-compatible API)",
                "database": "PostgreSQL for enrollment queries",
                "ticket_system": "Zoho Desk integration",
                "tracing": "Opik enabled",
                "environment": ENVIRONMENT,
                "log_level": LOG_LEVEL,

                # ✅ ENHANCED: Detailed Redis health information
                "redis_health": redis_health,
                "redis_connection_stats": connection_stats,
                "postgresql_health": postgres_health,

                # ✅ NEW: Optimization indicators
                "optimizations": {
                    "shared_redis_pool": True,
                    "connection_reuse": True,
                    "optimized_startup": True,
                    "centralized_cleanup": True,
                    "enhanced_logging": True,
                    "daily_log_rotation": True
                }
            }

            logger.debug("Health check completed successfully")
            return health_status

    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return {
            "message": "Health check failed",
            "error": str(e),
            "status": "unhealthy"
        }


# Updated helper functions for anonymous user detection
def _is_anonymous_user(user_id: str) -> bool:
    """Check if user is anonymous/non-logged in based on header format"""
    if not user_id:
        logger.debug("Empty user_id provided")
        return True

    # Check for explicit anonymous patterns
    if user_id.lower() in ["anonymous", "guest", "", "null", "undefined"]:
        logger.debug(f"Explicit anonymous user detected: {user_id}")
        return True

    # Check for the specific anonymous format: 'anonymous-UUID-epoch'
    anonymous_pattern = r'^anonymous-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}-\d+$'
    if re.match(anonymous_pattern, user_id, re.IGNORECASE):
        logger.debug(f"Anonymous pattern matched for user_id: {user_id}")
        return True

    logger.debug(f"User identified as logged-in: {user_id}")
    return False


def _extract_anonymous_session_info(user_id: str, cookie: str) -> dict:
    """Extract session information from anonymous user headers"""
    session_info = {
        'is_anonymous': True,
        'session_uuid': None,
        'session_epoch': None,
        'cookie_uuid': None,
        'cookie_epoch': None,
        'session_id': None
    }

    try:
        # Extract UUID and epoch from user_id
        if user_id and user_id.lower().startswith('anonymous-'):
            parts = user_id.split('-')
            if len(parts) >= 6:  # anonymous-UUID(5 parts)-epoch
                session_info['session_uuid'] = '-'.join(parts[1:6])  # Reconstruct UUID
                session_info['session_epoch'] = parts[6]

        # Extract UUID and epoch from cookie
        if cookie and cookie.lower().startswith('non-logged-in-user-'):
            parts = cookie.split('-')
            if len(parts) >= 7:  # non-logged-in-user-UUID(5 parts)-epoch
                session_info['cookie_uuid'] = '-'.join(parts[3:8])  # Reconstruct UUID
                session_info['cookie_epoch'] = parts[8]

        # Create a unique session identifier
        if session_info['session_uuid'] and session_info['session_epoch']:
            session_info['session_id'] = f"anon_{session_info['session_uuid']}_{session_info['session_epoch']}"

        logger.debug(f"Extracted anonymous session info: {session_info}")

    except Exception as e:
        logger.warning(f"Error parsing anonymous user headers: {e}")
        # Fallback to basic anonymous session
        session_info['session_id'] = f"anon_fallback_{int(datetime.now().timestamp())}"

    return session_info


def _create_anonymous_user_context(session_info: dict = None) -> dict:
    """Create minimal context for anonymous users with session info"""
    context = {
        'profile': {
            'firstName': 'Guest',
            'profileDetails': {
                'personalDetails': {
                    'primaryEmail': '',
                    'mobile': ''
                }
            }
        },
        'course_enrollments': [],
        'event_enrollments': [],
        'enrollment_summary': {
            'course_count': 0,
            'event_count': 0,
            'karma_points': 0
        },
        'session_info': session_info or {}
    }
    logger.debug(f"Created anonymous user context with session info")
    return context


@app.post("/chat/start")
async def start_chat(
        request: StartChat,
        user_id: str = Header(..., description="User ID from header"),
        cookie: str = Header(..., description="Cookie from header")
):
    """Endpoint to start a new chat session."""
    try:
        logger.info(f"Starting new chat session for user: {user_id}")

        if not request.text:
            chat_text = "Hello"
        else:
            chat_text = request.text.strip()

        # Pass language if present
        chat_request = ChatRequest(message=chat_text or "Hello", context={})
        return await chat(
            chat_request,
            "start",
            user_id=user_id,
            channel=request.channel_id,
            cookie=cookie,
            language=request.language
        )
    except Exception as e:
        logger.error(f"Error starting chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/chat/send")
async def continue_chat(
        request: StartChat,
        user_id: str = Header(..., description="User ID from header"),
        cookie: str = Header(..., description="Cookie from header")
):
    """Endpoint to continue an existing chat session."""
    try:
        logger.info(f"Continuing chat session for user: {user_id}")

        # Allow either text or audio (at least one required)
        if not (request.text or request.audio):
            raise HTTPException(status_code=400, detail="Either 'text' or 'audio' must be provided.")

        # Default language to 'en' if not provided
        lang = request.language or "en"

        # Check for tts_output flag
        tts_output = False
        if hasattr(request, 'tts_output'):
            tts_output = bool(request.tts_output)
        elif isinstance(request, dict):
            tts_output = bool(request.get('tts_output', False))

        # Debug: Uncomment if needed for troubleshooting
        # logger.debug(f"audio={bool(request.audio)}, tts_output={tts_output}")
        # If audio and tts_output, run TTS after response translation
        if request.audio and tts_output:
            from utils.translation_service import bhashini_translator, translate_response_to_user_language
            import base64
            # 1. ASR: transcribe audio
            transcript = await bhashini_translator.asr(base64.b64decode(request.audio), lang)
            # 2. Translate to English (if needed)
            from utils.translation_service import translate_to_english
            english_text = await translate_to_english(transcript, lang)
            # 3. LLM: get response in English
            chat_request = ChatRequest(message=english_text or "", context={})
            from agents.custom_agent_router import KarmayogiCustomerAgent
            # Use the same chat logic as before
            # For simplicity, call the chat endpoint and get the text response
            text_response = await chat(
                chat_request,
                "send",
                user_id=user_id,
                channel=request.channel_id,
                cookie=cookie,
                language=lang
            )
            # 4. Translate back to user language
            final_response = text_response.get("text", "")
            # 5. TTS: synthesize audio
            audio_bytes = await bhashini_translator.tts(final_response, lang)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            
            # Get trace_id and thread_id for feedback
            trace_id = get_current_trace_id()
            # thread_id should be from the session - need to extract it
            # We'll use the text_response which should have these IDs
            thread_id = text_response.get("thread_id")
            
            return {
                "text": final_response, 
                "audio": audio_b64,
                "thread_id": thread_id,
                "trace_id": trace_id
            }
        else:
            chat_request = ChatRequest(message=request.text or "", context={})
            return await chat(
                chat_request,
                "send",
                user_id=user_id,
                channel=request.channel_id,
                cookie=cookie,
                language=lang
            )
    except Exception as e:
        logger.error(f"Error continuing chat session: {e}", exc_info=True)
        # Log a sample curl for reproduction
        try:
            import json as _json
            curl_headers = f"-H 'user-id: {user_id}' -H 'cookie: {cookie}' -H 'Content-Type: application/json'"
            curl_payload = _json.dumps({
                "channel_id": "web",
                "text": getattr(locals().get('request', None), 'text', '<text>'),
                "language": getattr(locals().get('request', None), 'language', 'en')
            })
            logger.error(f"[CURL to reproduce /chat/send failure]:\ncurl -X POST '/chat/send' {curl_headers} -d '{curl_payload}'")
        except Exception as curl_e:
            logger.error(f"[CURL log error]: {curl_e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/anonymous/chat/start")
async def anonymous_start_chat(
        request: StartChat,
        user_id: str = Header(..., description="User ID from header"),
):
    """Endpoint to start a new anonymous chat session."""
    try:
        logger.info(f"Starting new anonymous chat session for user: {user_id}")

        if not request.text:
            chat_text = "Hello"
        else:
            chat_text = request.text.strip()

        chat_request = ChatRequest(message=chat_text or "Hello", context={})
        return await anonymous_chat(
            chat_request,
            "start",
            user_id=user_id,
            channel=request.channel_id,
            cookie=f"non-logged-in-user-{user_id}",
            language=request.language
        )
    except Exception as e:
        logger.error(f"Error starting anonymous chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/anonymous/chat/send")
async def anonymous_continue_chat(
        request: StartChat,
        user_id: str = Header(..., description="User ID from header")
):
    """Endpoint to continue an existing anonymous chat session."""
    try:
        logger.info(f"Continuing anonymous chat session for user: {user_id}")

        # Allow either text or audio (at least one required)
        if not (request.text or request.audio):
            raise HTTPException(status_code=400, detail="Either 'text' or 'audio' must be provided.")

        # Default language to 'en' if not provided
        lang = request.language or "en"

        # Check for tts_output flag
        tts_output = False
        if hasattr(request, 'tts_output'):
            tts_output = bool(request.tts_output)
        elif isinstance(request, dict):
            tts_output = bool(request.get('tts_output', False))

        # Debug: Uncomment if needed for troubleshooting
        # logger.debug(f"audio={bool(request.audio)}, tts_output={tts_output}")
        if request.audio and tts_output:
            from utils.translation_service import bhashini_translator, translate_response_to_user_language
            import base64
            transcript = await bhashini_translator.asr(base64.b64decode(request.audio), lang)
            from utils.translation_service import translate_to_english
            english_text = await translate_to_english(transcript, lang)
            chat_request = ChatRequest(message=english_text or "", context={})
            text_response = await anonymous_chat(
                chat_request,
                "send",
                user_id=user_id,
                channel=request.channel_id,
                cookie=f"non-logged-in-user-{user_id}",
                language=lang
            )
            final_response = text_response.get("text", "")
            audio_bytes = await bhashini_translator.tts(final_response, lang)
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            
            # Get trace_id and thread_id for feedback
            trace_id = get_current_trace_id()
            thread_id = text_response.get("thread_id")
            
            return {
                "text": final_response, 
                "audio": audio_b64,
                "thread_id": thread_id,
                "trace_id": trace_id
            }
        else:
            chat_request = ChatRequest(message=request.text or "", context={})
            return await anonymous_chat(
                chat_request,
                "send",
                user_id=user_id,
                channel=request.channel_id,
                cookie=f"non-logged-in-user-{user_id}",
                language=lang
            )
    except Exception as e:
        logger.error(f"Error continuing anonymous chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/anonymous/chat/direct")
async def anonymous_chat(
    chat_request: ChatRequest,
    mode: Optional[str] = None,
    user_id: str = Header(..., description="User ID from header"),
    channel: str = Header(..., description="Channel from header"),
    cookie: str = Header(..., description="Cookie from header"),
    language: Optional[str] = None
):
    """Chat endpoint for anonymous users with enhanced logging."""
    audio_url = None

    try:
        with LogExecutionTime(f"Anonymous Chat Processing - User: {user_id}", "chat"):
            # Check if user is anonymous using the specific header format
            is_anonymous = _is_anonymous_user(user_id)

            # Extract session information for anonymous users FIRST
            session_info = _extract_anonymous_session_info(user_id, cookie)
            
            # Ensure session_id is not None before hashing
            if not session_info.get('session_id'):
                session_info['session_id'] = f"anon_fallback_{int(datetime.now().timestamp())}"
            
            logger.info(f"Anonymous user detected - Session ID: {session_info['session_id']}")

            # Hash the cookie for secure storage (use session-specific hash for anonymous)
            cookie_hash = hash_cookie(session_info['session_id'])

            log_agent_activity(
                agent_name="AnonymousKarmayogiCustomerAgent",
                action="chat_start",
                user_id=user_id,
                details=f"Channel: {channel}, Message: {chat_request.message[:50]}..."
            )

            # Validate required headers (relaxed for anonymous users)
            if not channel:
                raise HTTPException(
                    status_code=400,
                    detail="Missing required header: channel"
                )

            # Validate anonymous user header formats
            if not user_id.lower().startswith('anonymous-'):
                logger.warning(f"Anonymous user_id doesn't match expected format: {user_id}")
                return {"message": f"Anonymous user_id doesn't match expected format: {user_id}"}

            if cookie and not cookie.lower().startswith('non-logged-in-user-'):
                logger.warning(f"Anonymous cookie doesn't match expected format: {cookie}")
                return {"message": f"Anonymous cookie doesn't match expected format: {cookie}"}

            # Step 1: Get or create Redis session with proper session ID
            app_name = "karmayogi_bharat_support_bot"

            try:
                with LogExecutionTime("Redis Session Management", "session"):
                    logger.info("Managing session with Redis...")

                    # Use extracted session ID for anonymous users
                    effective_user_id = session_info['session_id']
                    effective_cookie_hash = cookie_hash

                    session, is_new_session = await get_or_create_session(
                        app_name=app_name,
                        user_id=effective_user_id,
                        channel=channel,
                        cookie_hash=effective_cookie_hash,
                        initial_context={
                            "last_user_message": chat_request.message,
                            "request_context": chat_request.context or {},
                            "is_anonymous": is_anonymous,
                            "session_info": session_info,
                            "original_user_id": user_id,
                            "original_cookie": cookie[:50] + "..." if len(cookie) > 50 else cookie
                        }
                    )

                    if is_new_session:
                        logger.info(f"Created new Redis session for anonymous user: {session.session_id}")
                    else:
                        logger.info(f"Using existing Redis session: {session.session_id}")
                    
                    # Use session_id as thread_id for Opik trace grouping
                    thread_id = session.session_id

            except Exception as session_error:
                logger.error(f"Redis session management error: {session_error}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Session management failed: {str(session_error)}"
                )

            # Step 1.5: Get translation context with thread_id
            with LogExecutionTime("Language Detection and Translation", "translation"):
                translation_context = await get_translation_context(chat_request.message, language, thread_id=thread_id)
                logger.info(f"Translation context: {translation_context['language_name']} -> English")
                
                # Update session with translation context
                await update_session_data(
                    session.session_id,
                    context_updates={
                        "detected_language": translation_context['detected_language'],
                        "language_name": translation_context['language_name'],
                        "translation_context": translation_context
                    }
                )
            
            logger.info("Setting up anonymous user context with session info...")
            anonymous_user_context = _create_anonymous_user_context(session_info)

            # Step 3: Get conversation history
            try:
                with LogExecutionTime("Conversation History Retrieval", "history"):
                    logger.info("Fetching conversation history...")
                    conversation_history = await redis_session_service.get_conversation_history(
                        session.session_id, limit=6
                    )

                    logger.info(f"Retrieved {len(conversation_history)} messages from conversation history")

                    if conversation_history:
                        logger.debug("Recent conversation context:")
                        for i, msg in enumerate(conversation_history[-4:]):
                            logger.debug(f"  {i + 1}. {msg.role}: {msg.content[:100]}...")

            except Exception as history_error:
                logger.warning(f"Failed to fetch conversation history: {history_error}")
                conversation_history = []

            # Step 4: Create Request Context (THREAD-SAFE)
            request_context = RequestContext(
                user_id=effective_user_id,
                session_id=session.session_id,
                cookie=cookie,
                cookie_hash=cookie_hash,
                user_context=anonymous_user_context,
                chat_history=conversation_history,
                is_anonymous=is_anonymous,
                session_info=session_info
            )
            request_context.set_translation_context(translation_context)

            # Step 5: Add user message to session with enhanced metadata
            user_message = await add_chat_message(
                session.session_id,
                "user",
                chat_request.message,
                {
                    "timestamp": time.time(),
                    "channel": channel,
                    "is_anonymous": is_anonymous,
                    "session_uuid": session_info.get('session_uuid'),
                    "session_epoch": session_info.get('session_epoch'),
                    "user_id_format": "anonymous"
                }
            )

            if not user_message:
                logger.error("Failed to add user message to session")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to record user message"
                )
            

            if len(translation_context["english_message"].split()) < 4:
                rephrased_query = await rephrase_query_with_history(translation_context["english_message"], conversation_history)
            else:
                rephrased_query = translation_context["english_message"]
            logger.info(f"Anonymous chat:: Rephrased query: {rephrased_query}")

            # verify if redis has response for rephrased query
            redis_response = await get_redis_response(rephrased_query)
            logger.info(f"Anonymous chat:: redis_response: {redis_response}")
            if redis_response:
                logger.info("Found response in Redis cache")
                return {
                    "success": True,
                    "response": redis_response,
                    "has_relevant_info": True,
                }


            # Step 6: Create custom agent and route query (PASS CONTEXT)
            logger.info("Creating custom agent for anonymous user...")

            # ✅ FIXED: Pass RequestContext instead of separate parameters
            customer_agent = AnonymousKarmayogiCustomerAgent(opik_tracer, request_context)
            customer_agent.set_session_id(session.session_id)

            adk_session_service = await get_adk_session_service()
            adk_session_id = f"adk_{session.session_id}"

            # Check if ADK session already exists, if not create it
            existing_session = await adk_session_service.get_session(
                app_name="karmayogi_custom_agent",
                user_id=effective_user_id,
                session_id=adk_session_id
            )
            
            if existing_session is None:
                # Create ADK session with enhanced state
                await adk_session_service.create_session(
                    app_name="karmayogi_custom_agent",
                    user_id=effective_user_id,
                    session_id=adk_session_id,
                    state={
                        "redis_session_id": session.session_id,
                        "conversation_history_count": len(conversation_history),
                        "is_anonymous": is_anonymous,
                        "session_info": session_info,
                        "original_headers": {
                            "user_id": user_id,
                            "cookie": cookie[:50] + "..." if len(cookie) > 50 else cookie
                        }
                    }
                )
                logger.info(f"Created new ADK session for anonymous user: {adk_session_id}")
            else:
                logger.info(f"Using existing ADK session for anonymous user: {adk_session_id}")

            try:
                with LogExecutionTime("Agent Query Processing", "agent"):
                    # ✅ FIXED: Route the query through the custom agent (PASS CONTEXT)
                    bot_response = await customer_agent.route_query(
                        chat_request.message,
                        adk_session_service,
                        adk_session_id,
                        effective_user_id,
                        request_context
                    )

                    logger.info("Storing response in Redis cache for future requests")
                    await set_redis_response(rephrased_query, bot_response, 86400)

                    if not bot_response:
                        bot_response = f"I apologize, but I didn't receive a proper response. As a guest user (Session: {session_info.get('session_uuid', 'Unknown')[:8]}...), I can help you with platform information and support requests. Please try again."
            except Exception as e:
                logger.error(f"Error in custom agent routing: {e}", exc_info=True)
                bot_response = f"I apologize, but I'm experiencing technical difficulties. As a guest user, I can help you learn about the Karmayogi platform and create support tickets. Please try your request again."

            # Step 7: Add bot response to session with enhanced metadata
            await add_chat_message(
                session.session_id,
                "assistant",
                bot_response,
                {
                    "timestamp": time.time(),
                    "used_history_messages": len(conversation_history),
                    "is_anonymous": is_anonymous,
                    "session_uuid": session_info.get('session_uuid'),
                    "response_length": len(bot_response)
                }
            )

            # Step 8: Update session context with enhanced information
            await update_session_data(
                session.session_id,
                context_updates={
                    "last_interaction": time.time(),
                    "detected_language": translation_context['detected_language'],
                    "language_name": translation_context['language_name'],
                    "translation_context": translation_context,
                    "last_user_message": chat_request.message,
                    "last_bot_response": bot_response[:100] + "..." if len(bot_response) > 100 else bot_response,
                    "conversation_history_used": len(conversation_history),
                    "total_conversation_messages": session.message_count + 2,
                    "is_anonymous": is_anonymous,
                    "session_uuid": session_info.get('session_uuid'),
                    "session_epoch": session_info.get('session_epoch'),
                    "user_type": "anonymous"
                }
            )

            log_agent_activity(
                agent_name="AnonymousKarmayogiCustomerAgent",
                action="chat_complete",
                user_id=user_id,
                details=f"Response length: {len(bot_response)}, Session: {session.session_id}"
            )

            # Enhanced logging with session information
            logger.info(
                f"Anonymous session completed - Session UUID: {session_info.get('session_uuid', 'Unknown')[:8]}..., "
                f"Redis ID: {session.session_id}, Total Messages: {session.message_count + 2}")

            if mode is not None and mode == "start":
                bot_response = f"Starting new anonymous chat session. Session ID: {session_info.get('session_uuid', 'Unknown')[:8]}..."
                return {"message": bot_response}
            else:
                if isinstance(bot_response, str):
                    bot_response = bot_response
                elif hasattr(bot_response, 'response'):
                    bot_response = bot_response.response
                else:
                    bot_response = "I apologize, but I didn't receive a proper response. Please try again."

            # Step 7: Translate response back to user's language
            if translation_context['needs_translation'] and bot_response:
                with LogExecutionTime("Response Translation", "translation"):
                    final_response = await translate_response_to_user_language(
                        bot_response,
                        translation_context['detected_language'],
                        thread_id=thread_id
                    )
                    logger.info(f"Translated response back to {translation_context['language_name']}")
            else:
                final_response = bot_response

            # Get trace_id from Opik context for feedback support
            trace_id = get_current_trace_id()

            logger.debug(f"Returning response for anonymous user: {final_response[:100]}...")
            return {
                "text": final_response, 
                "audio": audio_url,
                "thread_id": thread_id,
                "trace_id": trace_id
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in anonymous chat endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/chat/direct")
async def chat(
    chat_request: ChatRequest,
    mode: Optional[str] = None,
    user_id: str = Header(..., description="User ID from header"),
    channel: str = Header(..., description="Channel from header"),
    cookie: str = Header(..., description="Cookie from header"),
    language: Optional[str] = None
):
    """Chat endpoint with custom agent routing and enhanced logging."""
    audio_url = None

    try:
        with LogExecutionTime(f"Chat Processing - User: {user_id}", "chat"):
            # Step 1: session management FIRST to get thread_id
            session_info = {'is_anonymous': False}
            cookie_hash = hash_cookie(cookie)

            log_agent_activity(
                agent_name="KarmayogiCustomerAgent",
                action="chat_start",
                user_id=user_id,
                details=f"Channel: {channel}, Message: {chat_request.message[:50]}..."
            )

            # Validate required headers
            if not channel:
                raise HTTPException(status_code=400, detail="Missing required header: channel")

            # Get or create Redis session
            app_name = "karmayogi_bharat_support_bot"

            try:
                with LogExecutionTime("Redis Session Management", "session"):
                    logger.info("Managing session with Redis...")
                    session, is_new_session = await get_or_create_session(
                        app_name=app_name,
                        user_id=user_id,
                        channel=channel,
                        cookie_hash=cookie_hash,
                        initial_context={
                            "last_user_message": chat_request.message,
                            "request_context": chat_request.context or {},
                            "is_anonymous": False,
                            "session_info": session_info,
                            "original_user_id": user_id,
                            "original_cookie": cookie[:50] + "..." if len(cookie) > 50 else cookie
                        }
                    )

                    logger.info(f"Using Redis session: {session.session_id}")
                    # Use session_id as thread_id for Opik trace grouping
                    thread_id = session.session_id

            except Exception as session_error:
                logger.error(f"Redis session management error: {session_error}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Session management failed: {str(session_error)}")

            # Step 2: Get translation context with thread_id
            with LogExecutionTime("Language Detection and Translation", "translation"):
                translation_context = await get_translation_context(chat_request.message, language, thread_id=thread_id)
                logger.info(f"Translation context: {translation_context['language_name']} -> English")
                
                # Update session with translation context
                await update_session_data(
                    session.session_id,
                    context_updates={
                        "detected_language": translation_context['detected_language'],
                        "language_name": translation_context['language_name'],
                        "translation_context": translation_context
                    }
                )

            # Step 3: Get user context
            try:
                with LogExecutionTime("User Authentication and Context Retrieval", "auth"):
                    logger.info("Authenticating user and fetching details from cache...")
                    cached_user_details, was_cached = await get_cached_user_details(
                        user_id, cookie, session_id=session.session_id
                    )

                    user_context = deepcopy(cached_user_details.to_dict())
                    user_context['session_info'] = session_info

                    if was_cached:
                        logger.info(
                            f"Used cached user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")
                    else:
                        logger.info(
                            f"Fetched fresh user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")

            except UserDetailsError as e:
                logger.error(f"User authentication failed: {e}")
                raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error during authentication: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Authentication service temporarily unavailable")

            try:
                with LogExecutionTime("PostgreSQL Enrollment Initialization", "postgres"):
                    logger.info("Initializing PostgreSQL enrollments...")
                    await initialize_user_enrollments_in_postgresql(
                        user_id=user_id,
                        session_id=session.session_id,
                        course_enrollments=cached_user_details.course_enrollments,
                        event_enrollments=cached_user_details.event_enrollments
                    )
                    logger.info("PostgreSQL enrollments initialized successfully")
            except Exception as postgres_error:
                logger.warning(f"Failed to initialize PostgreSQL enrollments: {postgres_error}")

            # Step 4: Get conversation history
            try:
                with LogExecutionTime("Conversation History Retrieval", "history"):
                    logger.info("Fetching conversation history...")
                    conversation_history = await redis_session_service.get_conversation_history(
                        session.session_id, limit=6
                    )

                    logger.info(f"Retrieved {len(conversation_history)} messages from conversation history")

            except Exception as history_error:
                logger.warning(f"Failed to fetch conversation history: {history_error}")
                conversation_history = []

            # Step 5: Create Request Context (THREAD-SAFE)
            request_context = RequestContext(
                user_id=user_id,
                session_id=session.session_id,
                cookie=cookie,
                cookie_hash=cookie_hash,
                user_context=user_context,
                chat_history=conversation_history,
                is_anonymous=False,
                session_info=session_info
            )
            request_context.set_translation_context(translation_context)

            # Step 6: Add user message to session
            user_message = await add_chat_message(
                session.session_id,
                "user",
                chat_request.message,
                {
                    "timestamp": time.time(),
                    "channel": channel,
                    "is_anonymous": False,
                    "user_id_format": "logged_in",
                    "detected_language": translation_context['detected_language'],
                    "language_name": translation_context['language_name'],
                    "english_translation": translation_context['english_message'],
                    "needs_translation": translation_context['needs_translation']
                }
            )

            if not user_message:
                logger.error("Failed to add user message to session")
                raise HTTPException(status_code=500, detail="Failed to record user message")

            # Step 7: Create custom agent and route query (PASS CONTEXT)
            logger.info("Creating custom agent...")
            customer_agent = KarmayogiCustomerAgent(opik_tracer, request_context)
            customer_agent.set_session_id(session.session_id)

            adk_session_service = await get_adk_session_service()
            adk_session_id = f"adk_{session.session_id}"

            # Check if ADK session already exists, if not create it
            existing_session = await adk_session_service.get_session(
                app_name="karmayogi_custom_agent",
                user_id=user_id,
                session_id=adk_session_id
            )
            
            if existing_session is None:
                await adk_session_service.create_session(
                    app_name="karmayogi_custom_agent",
                    user_id=user_id,
                    session_id=adk_session_id,
                    state={
                        "redis_session_id": session.session_id,
                        "conversation_history_count": len(conversation_history),
                        "is_anonymous": False,
                        "session_info": session_info,
                        "detected_language": translation_context['detected_language'],
                        "translation_context": translation_context
                    }
                )
                logger.info(f"Created new ADK session: {adk_session_id}")
            else:
                logger.info(f"Using existing ADK session: {adk_session_id}")


            try:
                with LogExecutionTime("Agent Query Processing", "agent"):
                    if chat_request.message == "Hello":
                        bot_response = (f"Hello {user_context.get('profile', {}).get('firstName', 'User')}! Welcome to Karmayogi Bharat support! I am here to assist with general platform queries and support. Please let me know how I can help you.")
                    else:
                        # Route the query through the custom agent (PASS CONTEXT)
                        bot_response = await customer_agent.route_query(
                            chat_request.message,
                            adk_session_service,
                            adk_session_id,
                            user_id,
                            request_context
                        )

                        if not bot_response:
                            bot_response = "I apologize, but I didn't receive a proper response. Please try again."

            except Exception as e:
                logger.error(f"Error in custom agent routing: {e}", exc_info=True)
                enrollment_summary = user_context.get('enrollment_summary', {})
                enrollment_info = (f"You have {cached_user_details.course_count} courses and "
                                   f"{cached_user_details.event_count} events enrolled. "
                                   f"Karma Points: {enrollment_summary.get('karma_points', 0)}")
                bot_response = f"I apologize, but I'm experiencing technical difficulties. {enrollment_info} Please try your request again."

            # Step 7: Add bot response to session
            logger.info("appending user chat history...")
            await add_chat_message(
                session.session_id,
                "assistant",
                bot_response,
                {
                    "timestamp": time.time(),
                    "used_history_messages": len(conversation_history),
                    "is_anonymous": False,
                    "response_length": len(bot_response)
                }
            )

            # Step 9: Update session context
            await update_session_data(
                session.session_id,
                context_updates={
                    "last_interaction": time.time(),
                    "last_user_message": chat_request.message,
                    "last_bot_response": bot_response[:100] + "..." if len(bot_response) > 100 else bot_response,
                    "conversation_history_used": len(conversation_history),
                    "total_conversation_messages": session.message_count + 2,
                    "is_anonymous": False,
                    "user_type": "logged_in",
                    "translation_used": translation_context['needs_translation']
                }
            )

            log_agent_activity(
                agent_name="KarmayogiCustomerAgent",
                action="chat_complete",
                user_id=user_id,
                details=f"Response length: {len(bot_response)}, Session: {session.session_id}"
            )

            logger.info(f"Logged-in session completed - User: {user_id}, Redis ID: {session.session_id}")

            if mode is not None and mode == "start":
                bot_response = "Starting new chat session."
                return {"message": bot_response}
            else:
                if isinstance(bot_response, str):
                    bot_response = bot_response
                elif hasattr(bot_response, 'response'):
                    bot_response = bot_response.response
                else:
                    bot_response = "I apologize, but I didn't receive a proper response. Please try again."

            # Step 7: Translate response back to user's language
            if translation_context['needs_translation'] and bot_response:
                with LogExecutionTime("Response Translation", "translation"):
                    final_response = await translate_response_to_user_language(
                        bot_response,
                        translation_context['detected_language'],
                        thread_id=thread_id
                    )
                    logger.info(f"Translated response back to {translation_context['language_name']}")
            else:
                final_response = bot_response

            # Get trace_id from Opik context for feedback support
            trace_id = get_current_trace_id()

        return {
            "text": final_response, 
            "audio": audio_url,
            "thread_id": thread_id,
            "trace_id": trace_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/feedback", response_model=FeedbackResponse, tags=["Feedback"])
async def submit_feedback(feedback: FeedbackRequest):
    """
    Submit user feedback for a chat response.
    
    This endpoint allows users to provide feedback on chat responses by submitting either:
    - **trace_id**: Feedback for a specific trace (single interaction)
    - **thread_id**: Feedback for an entire conversation thread
    
    **Feedback Types:**
    - `thumbs_up`: Positive feedback (maps to score 1.0)
    - `thumbs_down`: Negative feedback (maps to score 0.0)
    - Custom numeric rating (0-1 scale)
    
    **Example Usage:**
    ```json
    {
        "trace_id": "abc123",
        "feedback_type": "thumbs_up",
        "comment": "Very helpful response!",
        "rating": 0.9
    }
    ```
    
    At least one of `trace_id` or `thread_id` must be provided.
    """
    try:
        # Validate that at least one ID is provided
        if not feedback.trace_id and not feedback.thread_id:
            raise HTTPException(
                status_code=400,
                detail="At least one of 'trace_id' or 'thread_id' must be provided"
            )

        # Prepare feedback score based on feedback_type or rating
        feedback_value = None
        feedback_name = "user_feedback"
        
        if feedback.feedback_type:
            if feedback.feedback_type.lower() == "thumbs_up":
                feedback_value = 1.0
                feedback_name = "thumbs_up"
            elif feedback.feedback_type.lower() == "thumbs_down":
                feedback_value = 0.0
                feedback_name = "thumbs_down"
            else:
                raise HTTPException(
                    status_code=400,
                    detail="feedback_type must be either 'thumbs_up' or 'thumbs_down'"
                )
        elif feedback.rating is not None:
            if not (0 <= feedback.rating <= 1):
                raise HTTPException(
                    status_code=400,
                    detail="rating must be between 0 and 1"
                )
            feedback_value = feedback.rating
            feedback_name = "user_rating"
        elif feedback.comment:
            # Comment-only feedback without score
            feedback_value = None
            feedback_name = "user_comment"
        else:
            raise HTTPException(
                status_code=400,
                detail="At least one of 'feedback_type', 'rating', or 'comment' must be provided"
            )

        # Build feedback score dict
        feedback_score = {
            "name": feedback_name,
        }
        
        if feedback_value is not None:
            feedback_score["value"] = feedback_value
            
        if feedback.comment:
            feedback_score["reason"] = feedback.comment

        # Log feedback to Opik
        client = opik.Opik()
        
        if feedback.trace_id:
            # Log feedback for a specific trace
            logger.info(f"Logging trace feedback: trace_id={feedback.trace_id}, type={feedback.feedback_type}")
            
            client.log_traces_feedback_scores(
                scores=[
                    {
                        "id": feedback.trace_id,
                        **feedback_score
                    }
                ]
            )
            
            feedback_details = {
                "trace_id": feedback.trace_id,
                "feedback_name": feedback_name,
                "feedback_value": feedback_value,
                "comment": feedback.comment,
                "timestamp": time.time()
            }
            
            log_agent_activity(
                agent_name="FeedbackService",
                action="trace_feedback_logged",
                user_id="system",
                details=f"Trace: {feedback.trace_id}, Type: {feedback_name}"
            )
            
        elif feedback.thread_id:
            # Log feedback for a thread (conversation)
            logger.info(f"Logging thread feedback: thread_id={feedback.thread_id}, type={feedback.feedback_type}")
            
            # Get all traces in this thread from Opik and log feedback to the most recent one
            # This ensures feedback is tracked at the conversation level
            try:
                # Search for traces with this thread_id
                traces = client.search_traces(
                    project_name=os.getenv("OPIK_PROJECT"),
                    filter_string=f'thread_id = "{feedback.thread_id}"'
                )
                
                if traces and len(traces) > 0:
                    # Log feedback to the most recent trace in the thread
                    latest_trace = traces[0]  # Traces are returned newest first
                    
                    logger.info(f"Found {len(traces)} traces in thread, logging to latest: {latest_trace.id}")
                    
                    client.log_traces_feedback_scores(
                        scores=[
                            {
                                "id": latest_trace.id,
                                **feedback_score
                            }
                        ]
                    )
                    
                    feedback_details = {
                        "thread_id": feedback.thread_id,
                        "trace_id": latest_trace.id,
                        "traces_in_thread": len(traces),
                        "feedback_name": feedback_name,
                        "feedback_value": feedback_value,
                        "comment": feedback.comment,
                        "timestamp": time.time()
                    }
                else:
                    logger.warning(f"No traces found for thread_id: {feedback.thread_id}")
                    feedback_details = {
                        "thread_id": feedback.thread_id,
                        "feedback_name": feedback_name,
                        "feedback_value": feedback_value,
                        "comment": feedback.comment,
                        "timestamp": time.time(),
                        "note": "No traces found for this thread_id in Opik"
                    }
            except Exception as e:
                logger.error(f"Error searching traces for thread {feedback.thread_id}: {e}")
                # Still record the feedback attempt
                feedback_details = {
                    "thread_id": feedback.thread_id,
                    "feedback_name": feedback_name,
                    "feedback_value": feedback_value,
                    "comment": feedback.comment,
                    "timestamp": time.time(),
                    "note": f"Could not link to Opik trace: {str(e)}"
                }
            
            log_agent_activity(
                agent_name="FeedbackService",
                action="thread_feedback_logged",
                user_id="system",
                details=f"Thread: {feedback.thread_id}, Type: {feedback_name}"
            )

        logger.info(f"Feedback logged successfully: {feedback_details}")
        
        return FeedbackResponse(
            status="success",
            message="Feedback logged successfully to Opik",
            feedback_details=feedback_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to log feedback: {str(e)}"
        )


if __name__ == "__main__":
    logger.info("Starting Uvicorn server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)