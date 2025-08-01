# main.py - ADK Custom Agent with Intent-based Routing and Chat History
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
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.adk.sessions import InMemorySessionService
from opik.integrations.adk import OpikTracer
from pydantic import BaseModel
from qdrant_client import QdrantClient

from agents.anonymous_customer_agent_router import AnonymousKarmayogiCustomerAgent
from agents.custom_agent_router import KarmayogiCustomerAgent
from utils.common_utils import get_embedding_model
from utils.contentCache import get_cached_user_details, hash_cookie
from utils.postgresql_enrollment_service import initialize_user_enrollments_in_postgresql, postgresql_service
from utils.redis_connection_manager import (
    get_redis_manager,
    cleanup_redis_connections,
    redis_health_check
)
from utils.redis_session_service import (
    redis_session_service,
    get_or_create_session,
    add_chat_message,
    update_session_data,
)
from utils.request_context import RequestContext
from utils.userDetails import UserDetailsError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Initialize Opik for HOST
# opik.configure(
#     url=os.getenv("OPIK_API_URL"),
#     api_key=os.getenv("OPIK_API_KEY"),
#     workspace=os.getenv("OPIK_WORKSPACE", "default"),
#     use_local=False
# )

opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

# Initialize Qdrant client
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY") if os.getenv("QDRANT_API_KEY") else None
)

_embedding_model = None

class StartChat(BaseModel):
    """
    Model for starting a chat session.
    """
    channel_id : str
    text : str | None = None
    audio : Optional[str] = None
    language: Optional[str] = None

# Request/Response models
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


@asynccontextmanager
async def lifespan(app):
    """✅ OPTIMIZED: Application lifespan with shared Redis connection management"""
    # Startup code
    logger.info("Starting up Karmayogi Bharat ADK Custom Agent...")

    try:
        # ✅ Initialize shared Redis connection manager first
        logger.info("Initializing shared Redis connection manager...")
        redis_manager = await get_redis_manager()
        redis_client = await redis_manager.get_redis_client()
        logger.info("✅ Shared Redis connection manager initialized successfully")

        await postgresql_service.initialize_pool()

        # Pre-warm embedding model
        get_embedding_model()

        logger.info("✅ Startup complete - Using optimized shared Redis connections")

    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise

    yield

    # ✅ OPTIMIZED SHUTDOWN
    logger.info("Shutting down with optimized cleanup...")
    try:
        # Close PostgreSQL connections
        await postgresql_service.close()
        logger.info("✅ PostgreSQL connections closed")

        # ✅ Close shared Redis connections (handles both cache and session service)
        await cleanup_redis_connections()
        logger.info("✅ Shared Redis connections cleaned up")

    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")

    logger.info("✅ Shutdown complete")

# 5. UPDATE FastAPI app initialization (replace existing)
app = FastAPI(
    title="Karmayogi Bharat ADK Custom Agent API",
    description="API with custom agent routing to specialized sub-agents, chat history, and anonymous user support",
    version="5.5.0",
    docs_url=None,
    lifespan=lifespan
)

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
        # Use shared Redis health check
        redis_health = await redis_health_check()

        # Test PostgreSQL service
        postgres_health = await postgresql_service.health_check()

        # Get connection statistics from shared manager
        redis_manager = await get_redis_manager()
        connection_stats = await redis_manager.get_connection_stats()

        return {
            "message": "Karmayogi Bharat ADK Custom Agent is running!",
            "version": "5.5.0",  # Updated version
            "agent_type": "ADK Custom Agent with Optimized Redis Connections",
            "session_management": "Redis-based with shared connection pool",
            "llm_backend": "Local LLM (Ollama)",
            "database": "PostgreSQL for enrollment queries",
            "ticket_system": "Zoho Desk integration",
            "tracing": "Opik enabled",

            # ✅ ENHANCED: Detailed Redis health information
            "redis_health": redis_health,
            "redis_connection_stats": connection_stats,
            "postgresql_health": postgres_health,

            # ✅ NEW: Optimization indicators
            "optimizations": {
                "shared_redis_pool": True,
                "connection_reuse": True,
                "optimized_startup": True,
                "centralized_cleanup": True
            }
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "message": "Health check failed",
            "error": str(e),
            "status": "unhealthy"
        }


# Updated helper functions for anonymous user detection
def _is_anonymous_user(user_id: str) -> bool:
    """
    Check if user is anonymous/non-logged in based on header format
    Expected format: 'anonymous-UUID-epoch'
    """
    if not user_id:
        return True

    # Check for explicit anonymous patterns
    if user_id.lower() in ["anonymous", "guest", "", "null", "undefined"]:
        return True

    # Check for the specific anonymous format: 'anonymous-UUID-epoch'
    anonymous_pattern = r'^anonymous-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}-\d+$'
    if re.match(anonymous_pattern, user_id, re.IGNORECASE):
        return True

    return False


def _extract_anonymous_session_info(user_id: str, cookie: str) -> dict:
    """
    Extract session information from anonymous user headers
    user_id format: 'anonymous-UUID-epoch'
    cookie format: 'non-logged-in-user-UUID-epoch'
    """
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

        logger.info(
            f"Extracted anonymous session info: UUID={session_info['session_uuid']}, Epoch={session_info['session_epoch']}")

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
    return context


@app.post("/chat/start")
async def start_chat(
    request: StartChat,
    user_id: str = Header(..., description="User ID from header"),
    cookie: str = Header(..., description="Cookie from header")
):
    """Endpoint to start a new chat session."""
    try:
        if not request.text:
            chat_text = "Hello"
        else:
            chat_text = request.text.strip()

        chat_request = ChatRequest(message=chat_text or "Hello", context={})
        return await chat(
            chat_request,
            "start",
            user_id=user_id,
            channel=request.channel_id,
            cookie=cookie
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/chat/send")
async def continue_chat(
    request: StartChat,
    user_id: str = Header(..., description="User ID from header"),
    cookie: str = Header(..., description="Cookie from header")
):
    """Endpoint to continue an existing chat session."""
    try:
        if not request.text:
            raise HTTPException(status_code=400, detail="Message text cannot be empty")

        chat_request = ChatRequest(message=request.text or "", context={})
        return await chat(
            chat_request,
            "send",
            user_id=user_id,
            channel=request.channel_id,
            cookie=cookie
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/anonymous/chat/start")
async def anonymous_start_chat(
    request: StartChat,
    user_id: str = Header(..., description="User ID from header"),
):
    """Endpoint to start a new chat session."""
    try:
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
            cookie=f"non-logged-in-user-{user_id}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@app.post("/anonymous/chat/send")
async def anonymous_continue_chat(
    request: StartChat,
    user_id: str = Header(..., description="User ID from header")
):
    """Endpoint to continue an existing chat session."""
    try:
        if not request.text:
            raise HTTPException(status_code=400, detail="Message text cannot be empty")

        chat_request = ChatRequest(message=request.text or "", context={})
        return await anonymous_chat(
            chat_request,
            "send",
            user_id=user_id,
            channel=request.channel_id,
            cookie=f"non-logged-in-user-{user_id}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e



@app.post("/anonymous/chat/direct")
async def anonymous_chat(
        chat_request: ChatRequest,
        mode: Optional[str] = None,
        user_id: str = Header(..., description="User ID from header"),
        channel: str = Header(..., description="Channel from header"),
        cookie: str = Header(..., description="Cookie from header")
):
    """Chat endpoint with custom agent routing and chat history context (THREAD-SAFE)."""
    audio_url = None
    try:
        # Check if user is anonymous using the specific header format
        is_anonymous = _is_anonymous_user(user_id)

        # Extract session information for anonymous users
        session_info = _extract_anonymous_session_info(user_id, cookie)
        logger.info(f"Anonymous user detected - Session ID: {session_info['session_id']}")

        # Hash the cookie for secure storage (use session-specific hash for anonymous)
        cookie_hash = hash_cookie(session_info['session_id'])

        logger.info(
            f"Chat request started - User: {user_id} ({'Anonymous' if is_anonymous else 'Logged In'}), Channel: {channel}")

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
                logger.info(
                    f"Created new Redis session for anonymous user: {session.session_id}")
            else:
                logger.info(f"Using existing Redis session: {session.session_id}")

        except Exception as session_error:
            logger.error(f"Redis session management error: {session_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Session management failed: {str(session_error)}"
            )

        anonymous_user_context = None

        if is_anonymous:
            logger.info("Setting up anonymous user context with session info...")
            anonymous_user_context = _create_anonymous_user_context(session_info)  # Local variable now
            cached_user_details = None

        # Step 3: Get conversation history
        try:
            logger.info("Fetching conversation history...")
            conversation_history = await redis_session_service.get_conversation_history(
                session.session_id, limit=6
            )

            logger.info(f"Retrieved {len(conversation_history)} messages from conversation history")

            if conversation_history:
                logger.info("Recent conversation context:")
                for i, msg in enumerate(conversation_history[-4:]):
                    logger.info(f"  {i + 1}. {msg.role}: {msg.content[:100]}...")

        except Exception as history_error:
            logger.warning(f"Failed to fetch conversation history: {history_error}")
            conversation_history = []

        # Step 4: Create Request Context (THREAD-SAFE)
        request_context = RequestContext(
            user_id=effective_user_id,  # Use effective_user_id for anonymous users
            session_id=session.session_id,
            cookie=cookie,
            cookie_hash=cookie_hash,
            user_context=anonymous_user_context,
            chat_history=conversation_history,
            is_anonymous=is_anonymous,
            session_info=session_info
        )

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

        # Step 6: Create custom agent and route query (PASS CONTEXT)
        logger.info("Creating custom agent for anonymous user...")

        # ✅ FIXED: Pass RequestContext instead of separate parameters
        customer_agent = AnonymousKarmayogiCustomerAgent(opik_tracer, request_context)

        customer_agent.set_session_id(session.session_id)

        adk_session_service = InMemorySessionService()
        adk_session_id = f"adk_{session.session_id}"

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

        try:
            # ✅ FIXED: Route the query through the custom agent (PASS CONTEXT)
            bot_response = await customer_agent.route_query(
                chat_request.message,
                adk_session_service,
                adk_session_id,
                effective_user_id,
                request_context  # Pass context instead of separate parameters
            )

            if not bot_response:
                bot_response = f"I apologize, but I didn't receive a proper response. As a guest user (Session: {session_info.get('session_uuid', 'Unknown')[:8]}...), I can help you with platform information and support requests. Please try again."

        except Exception as e:
            logger.error(f"Error in custom agent routing: {e}")
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

        logger.debug(f"Returning response for anonymous user: {bot_response[:100]} ...")
        return {"text": bot_response, "audio": audio_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in anonymous chat endpoint: {e}")
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
        cookie: str = Header(..., description="Cookie from header")
):
    """Chat endpoint with custom agent routing and chat history context."""
    audio_url = None
    try:
        session_info = {'is_anonymous': False}
        cookie_hash = hash_cookie(cookie)

        # Validate required headers
        if not channel:
            raise HTTPException(status_code=400, detail="Missing required header: channel")

        # Step 1: Get or create Redis session
        app_name = "karmayogi_bharat_support_bot"

        try:
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

        except Exception as session_error:
            logger.error(f"Redis session management error: {session_error}")
            raise HTTPException(status_code=500, detail=f"Session management failed: {str(session_error)}")

        # Step 2: Get user context
        try:
            logger.info("Authenticating user and fetching details from cache...")
            cached_user_details, was_cached = await get_cached_user_details(
                user_id, cookie, session_id=session.session_id
            )

            user_context = deepcopy(cached_user_details.to_dict())
            user_context['session_info'] = session_info

            if was_cached:
                logger.info(f"Used cached user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")
            else:
                logger.info(f"Fetched fresh user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")

        except UserDetailsError as e:
            logger.error(f"User authentication failed: {e}")
            raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            raise HTTPException(status_code=500, detail="Authentication service temporarily unavailable")

        # Step 3: Initialize PostgreSQL enrollments
        try:
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

        # Step 6: Add user message to session
        user_message = await add_chat_message(
            session.session_id,
            "user",
            chat_request.message,
            {
                "timestamp": time.time(),
                "channel": channel,
                "is_anonymous": False,
                "user_id_format": "logged_in"
            }
        )

        if not user_message:
            logger.error("Failed to add user message to session")
            raise HTTPException(status_code=500, detail="Failed to record user message")

        # Step 7: Create custom agent and route query (PASS CONTEXT)
        logger.info("Creating custom agent...")
        customer_agent = KarmayogiCustomerAgent(opik_tracer, request_context)
        customer_agent.set_session_id(session.session_id)

        adk_session_service = InMemorySessionService()
        adk_session_id = f"adk_{session.session_id}"

        await adk_session_service.create_session(
            app_name="karmayogi_custom_agent",
            user_id=user_id,
            session_id=adk_session_id,
            state={
                "redis_session_id": session.session_id,
                "conversation_history_count": len(conversation_history),
                "is_anonymous": False,
                "session_info": session_info
            }
        )

        try:
            # Route the query through the custom agent (PASS CONTEXT)
            bot_response = await customer_agent.route_query(
                chat_request.message,
                adk_session_service,
                adk_session_id,
                user_id,
                request_context  # Pass context instead of using globals
            )

            if not bot_response:
                bot_response = "I apologize, but I didn't receive a proper response. Please try again."

        except Exception as e:
            logger.error(f"Error in custom agent routing: {e}")
            enrollment_summary = user_context.get('enrollment_summary', {})
            enrollment_info = (f"You have {cached_user_details.course_count} courses and "
                               f"{cached_user_details.event_count} events enrolled. "
                               f"Karma Points: {enrollment_summary.get('karma_points', 0)}")
            bot_response = f"I apologize, but I'm experiencing technical difficulties. {enrollment_info} Please try your request again."

        # Step 8: Add bot response to session
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
                "user_type": "logged_in"
            }
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

        return {"text": bot_response, "audio": audio_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)