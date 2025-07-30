# main.py - ADK Custom Agent with Intent-based Routing and Chat History
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx
import opik
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.adk.sessions import InMemorySessionService
from opik.integrations.adk import OpikTracer
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

from agents.anonymous_customer_agent_router import AnonymousKarmayogiCustomerAgent
from agents.custom_agent_router import KarmayogiCustomerAgent
from utils.contentCache import get_cached_user_details, hash_cookie, get_cache_health
from utils.postgresql_enrollment_service import initialize_user_enrollments_in_postgresql, postgresql_service
from utils.redis_session_service import (
    redis_session_service,
    get_or_create_session,
    add_chat_message,
    update_session_data,
    ChatMessage,
)
from utils.userDetails import UserDetailsError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Local LLM configuration
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11435/api/generate")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:3b-instruct-fp16")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent"
# FastEmbed model configuration
EMBEDDING_MODEL_NAME = os.getenv("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")  # Fast and efficient model
VECTOR_SIZE = 384  # Dimension for bge-small-en-v1.5

QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "karmayogi_knowledge_base")
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY", None)

# Initialize Opik for HOST
# opik.configure(
#     url=os.getenv("OPIK_API_URL"),
#     api_key=os.getenv("OPIK_API_KEY"),
#     workspace=os.getenv("OPIK_WORKSPACE", "default"),
#     use_local=False
# )

opik.configure(
    url=os.getenv("OPIK_API_URL"),
    use_local=True
)

opik_tracer = OpikTracer(project_name=os.getenv("OPIK_PROJECT"))

# Global variables for user context and chat history
current_user_cookie = ""
user_context = None
current_chat_history: List[ChatMessage] = []

# Initialize Qdrant client
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY") if os.getenv("QDRANT_API_KEY") else None
)

_embedding_model = None


def _looks_like_verification_data(user_message: str) -> bool:
    """Check if user message looks like verification data (mobile number, OTP, etc.)"""
    message = user_message.strip()

    # Check if it's a mobile number (10 digits starting with 6-9)
    mobile_pattern = r'^\d{10}$'
    if re.match(mobile_pattern, message) and message.startswith(('6', '7', '8', '9')):
        return True

    # Check if it's an OTP (4-6 digits)
    otp_pattern = r'^\d{4,6}$'
    if re.match(otp_pattern, message):
        return True

    # Check if it's a simple "yes", "no", confirmation
    confirmation_patterns = [r'^(yes|no|ok|okay)$', r'^y$', r'^n$']
    if any(re.match(pattern, message.lower()) for pattern in confirmation_patterns):
        return True

    return False


def _is_general_platform_query(query: str) -> bool:
    """Enhanced detection for general platform queries that shouldn't be rephrased"""
    query_lower = query.lower().strip()

    # General question patterns
    general_patterns = [
        "what is", "what are", "what does", "what do",
        "how does", "how do", "how can i", "tell me about",
        "explain", "define", "meaning of", "purpose of",
        "benefits of", "features of", "difference between"
    ]

    # Platform-specific terms (from FAQ analysis)
    platform_terms = [
        "hub", "hubs", "karma points", "karmayogi", "mission karmayogi",
        "cbp", "competency", "competencies", "frac", "wpcas",
        "course", "program", "assessment", "certification", "badge",
        "learn hub", "discuss hub", "network hub", "competency hub", "career hub",
        "platform", "igot", "learning", "enrollment", "blended programs",
        "self-paced", "moderated courses", "leaderboard", "connections",
        "standalone assessments", "parichay", "work order"
    ]

    # Check if query starts with general pattern
    starts_with_general = any(query_lower.startswith(pattern) for pattern in general_patterns)

    # Check if query contains platform terms
    contains_platform_terms = any(term in query_lower for term in platform_terms)

    return starts_with_general and contains_platform_terms


# 2. ENHANCED REPHRASING FUNCTION
async def _rephrase_query_with_history(original_query: str, chat_history: List) -> str:
    """Enhanced rephrasing logic with better general query detection"""
    try:
        if not isinstance(chat_history, list):
            chat_history = []

        # PRIORITY 1: Don't rephrase general platform queries
        if _is_general_platform_query(original_query):
            logger.info(f"Skipping rephrasing for general platform query: '{original_query}'")
            return original_query

        # PRIORITY 2: Don't rephrase verification data
        if _looks_like_verification_data(original_query):
            logger.info(f"Skipping rephrasing for verification data: '{original_query}'")
            return original_query

        # PRIORITY 3: Check for workflow interruptions
        query_lower = original_query.lower().strip()

        # If user asks a completely different topic during a workflow, don't force context
        workflow_interruption_patterns = [
            "what is", "what are", "tell me about", "how does", "explain"
        ]

        is_workflow_interruption = any(
            query_lower.startswith(pattern) for pattern in workflow_interruption_patterns
        )

        if is_workflow_interruption and chat_history:
            recent_content = " ".join([msg.content.lower() for msg in chat_history[-2:]])

            # Check if we're in any workflow
            in_workflow = any(indicator in recent_content for indicator in [
                "otp", "verify", "mobile number", "awaiting", "enter the",
                "certificate issue", "course name", "ticket", "support"
            ])

            if in_workflow:
                logger.info(f"User asking new topic during workflow, not rephrasing: '{original_query}'")
                return original_query

        # Rest of the existing rephrasing logic for truly ambiguous queries...
        # (Only apply to queries that need contextual clarification)

        return original_query  # Default to not rephrasing unless clearly needed

    except Exception as e:
        logger.error(f"Error in rephrasing: {e}")
        return original_query


# 3. ENHANCED CLASSIFICATION RULES
ENHANCED_CLASSIFIER_INSTRUCTION = """
You are an advanced intent classifier for Karmayogi Bharat platform queries.

CRITICAL CLASSIFICATION PRIORITY:

**STEP 1: IDENTIFY GENERAL PLATFORM QUERIES (HIGHEST PRIORITY)**
These should ALWAYS be classified as GENERAL_SUPPORT, regardless of conversation context:

General Question Patterns + Platform Terms = GENERAL_SUPPORT:
- "What is/are [platform_term]?" → GENERAL_SUPPORT
- "How does [platform_feature] work?" → GENERAL_SUPPORT  
- "Tell me about [platform_concept]" → GENERAL_SUPPORT
- "Explain [platform_feature]" → GENERAL_SUPPORT

Platform Terms Include:
- hubs, hub, karma points, karmayogi, mission karmayogi
- cbp, competency, competencies, frac, wpcas
- learn hub, discuss hub, network hub, competency hub, career hub
- course, program, assessment, certification, badge
- platform, igot, learning, enrollment, blended programs
- self-paced, moderated courses, leaderboard, connections

EXAMPLES THAT ARE ALWAYS GENERAL_SUPPORT:
- "What are hubs?" → GENERAL_SUPPORT (even if in mobile update conversation)
- "What is karma points?" → GENERAL_SUPPORT
- "How does certification work?" → GENERAL_SUPPORT
- "Tell me about competency hub" → GENERAL_SUPPORT
- "What is learn hub?" → GENERAL_SUPPORT
- "Explain CBP" → GENERAL_SUPPORT

**STEP 2: IDENTIFY PERSONAL DATA QUERIES**
USER_PROFILE_INFO - Questions about user's personal data:
- "My courses", "My progress", "How many certificates do I have?"
- Must be asking for personal/user-specific information

**STEP 3: IDENTIFY ACTION REQUESTS**
USER_PROFILE_UPDATE - Requests to change/update personal data:
- "Update my mobile number", "Change my name"
- Must be actual requests to modify data, not questions about how to do it

**STEP 4: IDENTIFY PROBLEM REPORTS**
CERTIFICATE_ISSUES - Reports of specific problems:
- "I didn't get my certificate", "Wrong name on certificate"
- Must be reporting an actual problem, not asking general questions

TICKET_CREATION - Support/escalation requests:
- "Create a ticket", "Contact support", "I need help"
- Must be requesting human assistance or formal support

**STEP 5: CONTEXT ANALYSIS (LOWEST PRIORITY)**
Only use conversation context for genuinely ambiguous queries.
DO NOT override clear general platform questions with workflow context.

The structure of the question determines the classification, not the conversation context.

Respond with only: USER_PROFILE_INFO, USER_PROFILE_UPDATE, CERTIFICATE_ISSUES, TICKET_CREATION, or GENERAL_SUPPORT
"""


# 4. ENHANCED FALLBACK CLASSIFICATION
def _enhanced_fallback_classification(self, user_message: str, chat_history: List[ChatMessage]) -> str:
    """Enhanced fallback with priority for general platform queries"""

    # HIGHEST PRIORITY: General platform queries
    if _is_general_platform_query(user_message):
        logger.info(f"Fallback: General platform query detected: '{user_message}'")
        return "GENERAL_SUPPORT"

    # Check for explicit action keywords (second priority)
    profile_update_keywords = [
        "update my", "change my", "modify my", "send otp", "verify otp",
        "generate otp", "reset password"
    ]

    if any(keyword in user_message.lower() for keyword in profile_update_keywords):
        return "USER_PROFILE_UPDATE"

    # Check for problem reports (third priority)
    problem_keywords = [
        "didn't get", "haven't received", "not received", "missing",
        "wrong name", "incorrect", "not working", "broken", "issue with"
    ]

    if any(keyword in user_message.lower() for keyword in problem_keywords):
        return "CERTIFICATE_ISSUES"

    # Check for support requests (fourth priority)
    support_keywords = [
        "create ticket", "support", "help", "escalate", "human",
        "manager", "complaint", "frustrated"
    ]

    if any(keyword in user_message.lower() for keyword in support_keywords):
        return "TICKET_CREATION"

    # Check for personal data queries (fifth priority)
    personal_keywords = ["my", "me", "i have", "show me my", "how many do i"]

    if any(keyword in user_message.lower() for keyword in personal_keywords):
        return "USER_PROFILE_INFO"

    # Default to general support for everything else
    return "GENERAL_SUPPORT"


# QDRANT INTEGRATION - START
def get_embedding_model():
    """Get or initialize the FastEmbed model"""
    global _embedding_model
    if _embedding_model is None:
        try:
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            logger.info(f"Successfully initialized SentenceTransformer model: {EMBEDDING_MODEL_NAME}")
        except Exception as e:
            logger.error(f"Failed to initialize SentenceTransformer model: {e}")
            raise
    return _embedding_model


async def initialize_qdrant_collection():
    """Initialize Qdrant collection with proper configuration"""
    try:
        # Check if collection exists
        collections = qdrant_client.get_collections()
        collection_names = [col.name for col in collections.collections]

        if QDRANT_COLLECTION_NAME not in collection_names:
            logger.info(f"Creating Qdrant collection: {QDRANT_COLLECTION_NAME}")

            # Create collection with vector configuration
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE
                ),
                optimizers_config=models.OptimizersConfigDiff(
                    default_segment_number=2,
                    memmap_threshold=20000,
                ),
                hnsw_config=models.HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                    full_scan_threshold=10000,
                ),
            )

            # Create payload index for text search fallback
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION_NAME,
                field_name="content",
                field_schema=models.PayloadSchemaType.TEXT
            )

            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION_NAME,
                field_name="category",
                field_schema=models.PayloadSchemaType.KEYWORD
            )

            logger.info("Qdrant collection created successfully")
        else:
            logger.info(f"Qdrant collection {QDRANT_COLLECTION_NAME} already exists")

    except Exception as e:
        logger.error(f"Error initializing Qdrant collection: {e}")
        raise


async def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using FastEmbed"""
    try:
        model = get_embedding_model()
        embeddings_list = model.encode(texts).tolist()
        logger.info(f"Generated embeddings for {len(texts)} texts")
        return embeddings_list
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise


async def query_qdrant_with_fastembed(query: str, limit: int = 5, threshold: float = 0.7) -> List[Dict[str, Any]]:
    """Query Qdrant using FastEmbed embeddings"""
    try:
        # Generate embedding for the query
        query_embeddings = await generate_embeddings([query])
        query_vector = query_embeddings[0]

        # Search with vector similarity
        search_results = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            limit=limit,
            score_threshold=threshold,
            with_payload=True,
            with_vectors=False
        )

        # Process results
        knowledge_results = []
        for result in search_results:
            knowledge_results.append({
                "id": str(result.id),
                "content": result.payload.get("content", ""),
                "title": result.payload.get("title", ""),
                "category": result.payload.get("category", ""),
                "tags": result.payload.get("tags", []),
                "source": result.payload.get("source", ""),
                "score": float(result.score),
                "metadata": result.payload.get("metadata", {})
            })

        logger.info(f"Found {len(knowledge_results)} relevant results for query: {query[:50]}...")
        return knowledge_results

    except Exception as e:
        logger.error(f"Error querying Qdrant with FastEmbed: {e}")
        # Fallback to text search
        return await _fallback_text_search(query, limit)


async def _fallback_text_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fallback text search when vector search fails"""
    try:
        logger.info("Using fallback text search")

        search_results = qdrant_client.scroll(
            collection_name=QDRANT_COLLECTION_NAME,
            scroll_filter=models.Filter(
                should=[
                    models.FieldCondition(
                        key="content",
                        match=models.MatchText(text=query)
                    ),
                    models.FieldCondition(
                        key="title",
                        match=models.MatchText(text=query)
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False
        )[0]

        # Process results
        knowledge_results = []
        for result in search_results:
            knowledge_results.append({
                "id": str(result.id),
                "content": result.payload.get("content", ""),
                "title": result.payload.get("title", ""),
                "category": result.payload.get("category", ""),
                "tags": result.payload.get("tags", []),
                "source": result.payload.get("source", ""),
                "score": 0.5,  # Default score for text search
                "metadata": result.payload.get("metadata", {})
            })

        return knowledge_results

    except Exception as e:
        logger.error(f"Error in fallback text search: {e}")
        return []


async def _call_gemini_api(prompt: str) -> str:
    """Call Gemini API for text generation"""
    try:
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "topP": 0.9,
                "maxOutputTokens": 2000
            }
        }

        headers = {
            "Content-Type": "application/json"
        }
        logger.debug(f"INSIDE _call_gemini_api BEFORE HTTPX CALL, payload: {json.dumps(payload)}")
        # Add API key to URL if available
        url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}" if GEMINI_API_KEY else GEMINI_API_URL

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            logger.debug(f"INSIDE _call_gemini_api AFTER HTTPX CALL, response: {response.status_code}")
            if response.status_code == 200:
                response_data = response.json()
                if "candidates" in response_data and len(response_data["candidates"]) > 0:
                    content = response_data["candidates"][0].get("content", {})
                    parts = content.get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"]

            logger.error(f"Gemini API error: {response.status_code} - {response.text}")
            return ""

    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return ""


# Helper function for local LLM calls
async def _call_local_llm(system_message: str, user_message: str) -> str:
    """Call local LLM with system and user messages"""
    payload = {
        "model": LOCAL_LLM_MODEL,
        "prompt": f"System: {system_message}\nUser: {user_message}",
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 4000
        }
    }
    logger.debug("INSIDE _call_local_llm BEFORE HTTPX CALL")
    async with httpx.AsyncClient(timeout=480.0) as client:
        try:
            response = await client.post(
                LOCAL_LLM_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            logger.debug(f"INSIDE _call_local_llm AFTER HTTPX CALL, response status: {response.status_code}")
            if response.status_code != 200:
                raise Exception(f"Local LLM API returned status {response.status_code}")

            response_data = response.json()
            # Ollama returns the result in the 'response' key
            return response_data.get("response", "")
        except Exception as e:
            logger.error(f"Error calling local LLM: {e}")
            return "I'm sorry, but I encountered an error while processing your request. Please try again later."


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
    # Startup code
    logger.info("Starting up Karmayogi Bharat ADK Custom Agent...")
    await initialize_qdrant_collection()
    await postgresql_service.initialize_pool()
    logger.info("Startup complete - Anonymous user support enabled")
    yield
    # Shutdown code
    logger.info("Shutting down...")
    await postgresql_service.close()
    await redis_session_service.shutdown()
    # Add this line if using the global cache instance:
    from utils.contentCache import user_cache
    await user_cache.shutdown()
    logger.info("Shutdown complete")

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
    """Health endpoint to verify server status including PostgreSQL and Zoho Desk."""
    # Test local LLM connection
    local_llm_available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(LOCAL_LLM_URL.replace('/api/generate', '/api/tags'))
            local_llm_available = response.status_code == 200
    except Exception:
        local_llm_available = False

    # Test Redis session service
    redis_health = await redis_session_service.health_check()

    # Test PostgreSQL service
    postgres_health = await postgresql_service.health_check()

    cache_health = await get_cache_health()

    return {
        "message": "Karmayogi Bharat ADK Custom Agent is running!",
        "version": "5.4.0",  # Updated version
        "agent_type": "ADK Custom Agent with Sub-Agent Routing, Chat History, PostgreSQL & Zoho Desk",
        "session_management": "Redis-based with conversation history",
        "llm_backend": "Local LLM (Ollama)",
        "database": "PostgreSQL for enrollment queries",
        "ticket_system": "Zoho Desk integration",
        "tracing": "Opik enabled",
        "local_llm_url": LOCAL_LLM_URL,
        "local_llm_model": LOCAL_LLM_MODEL,
        "local_llm_available": local_llm_available,
        "redis_session_health": redis_health,
        "postgresql_health": postgres_health,
        "cache_health": cache_health
    }

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
        # Check if user is anonymous using the specific header format
        is_anonymous = _is_anonymous_user(user_id)

        # Extract session information for anonymous users
        if is_anonymous:
            session_info = _extract_anonymous_session_info(user_id, cookie)
            logger.info(f"Anonymous user detected - Session ID: {session_info['session_id']}")
        else:
            session_info = {'is_anonymous': False}

        # Hash the cookie for secure storage (use session-specific hash for anonymous)
        if is_anonymous:
            cookie_hash = hash_cookie(session_info['session_id'])
        else:
            cookie_hash = hash_cookie(cookie)

        # Set global cookie for tool functions
        global current_user_cookie
        current_user_cookie = cookie if not is_anonymous else ""

        logger.info(
            f"Chat request started - User: {user_id} ({'Anonymous' if is_anonymous else 'Logged In'}), Channel: {channel}")

        # Validate required headers (relaxed for anonymous users)
        if not channel:
            raise HTTPException(
                status_code=400,
                detail="Missing required header: channel"
            )

        # Validate anonymous user header formats
        if is_anonymous:
            if not user_id.lower().startswith('anonymous-'):
                logger.warning(f"Anonymous user_id doesn't match expected format: {user_id}")
            if cookie and not cookie.lower().startswith('non-logged-in-user-'):
                logger.warning(f"Anonymous cookie doesn't match expected format: {cookie}")

        # Step 1: Get or create Redis session with proper session ID
        app_name = "karmayogi_bharat_support_bot"

        try:
            logger.info("Managing session with Redis...")

            # Use extracted session ID for anonymous users, original user_id for logged-in users
            if is_anonymous:
                effective_user_id = session_info['session_id']
                effective_cookie_hash = cookie_hash
            else:
                effective_user_id = user_id
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
                    "original_cookie": cookie[:50] + "..." if len(cookie) > 50 else cookie  # Truncate for logging
                }
            )

            if is_new_session:
                logger.info(
                    f"Created new Redis session for {'anonymous' if is_anonymous else 'logged in'} user: {session.session_id}")
            else:
                logger.info(f"Using existing Redis session: {session.session_id}")

        except Exception as session_error:
            logger.error(f"Redis session management error: {session_error}")
            raise HTTPException(
                status_code=500,
                detail=f"Session management failed: {str(session_error)}"
            )

        # Step 2: Handle user authentication differently for anonymous users
        global user_context

        if is_anonymous:
            logger.info("Setting up anonymous user context with session info...")
            user_context = _create_anonymous_user_context(session_info)
            cached_user_details = None
        else:
            # Regular authentication flow for logged-in users
            try:
                logger.info("Authenticating user and fetching details from cache...")
                cached_user_details, was_cached = await get_cached_user_details(
                    user_id, cookie, session_id=session.session_id
                )

                user_context = deepcopy(cached_user_details.to_dict())
                user_context['session_info'] = session_info  # Add session info

                if was_cached:
                    logger.info(
                        f"Used cached user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")
                else:
                    logger.info(
                        f"Fetched fresh user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")

            except UserDetailsError as e:
                logger.error(f"User authentication failed: {e}")
                raise HTTPException(
                    status_code=401,
                    detail=f"Authentication failed: {str(e)}"
                )
            except Exception as e:
                logger.error(f"Unexpected error during authentication: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Authentication service temporarily unavailable"
                )

        # Step 3: Initialize PostgreSQL enrollments (skip for anonymous users)
        if not is_anonymous and cached_user_details:
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

            if conversation_history:
                logger.info("Recent conversation context:")
                for i, msg in enumerate(conversation_history[-4:]):
                    logger.info(f"  {i + 1}. {msg.role}: {msg.content[:100]}...")

        except Exception as history_error:
            logger.warning(f"Failed to fetch conversation history: {history_error}")
            conversation_history = []

        # Set global chat history for tools to access
        global current_chat_history
        current_chat_history = conversation_history

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
                "user_id_format": "anonymous" if is_anonymous else "logged_in"
            }
        )

        if not user_message:
            logger.error("Failed to add user message to session")
            raise HTTPException(
                status_code=500,
                detail="Failed to record user message"
            )

        # Step 6: Create custom agent and route query
        logger.info(f"Creating custom agent for {'anonymous' if is_anonymous else 'logged in'} user...")

        # Create specialized customer agent for anonymous users
        if is_anonymous:
            customer_agent = AnonymousKarmayogiCustomerAgent(opik_tracer, current_chat_history, user_context)
        else:
            customer_agent = KarmayogiCustomerAgent(opik_tracer, current_chat_history, user_context)

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
            # Route the query through the custom agent
            bot_response = await customer_agent.route_query(
                chat_request.message,
                adk_session_service,
                adk_session_id,
                effective_user_id,
                conversation_history
            )

            if not bot_response:
                if is_anonymous:
                    bot_response = f"I apologize, but I didn't receive a proper response. As a guest user (Session: {session_info.get('session_uuid', 'Unknown')[:8]}...), I can help you with platform information and support requests. Please try again."
                else:
                    bot_response = "I apologize, but I didn't receive a proper response. Please try again."

        except Exception as e:
            logger.error(f"Error in custom agent routing: {e}")

            if is_anonymous:
                bot_response = f"I apologize, but I'm experiencing technical difficulties. As a guest user, I can help you learn about the Karmayogi platform and create support tickets. Please try your request again."
            else:
                enrollment_summary = user_context.get('enrollment_summary', {})
                enrollment_info = (f"You have {cached_user_details.course_count} courses and "
                                   f"{cached_user_details.event_count} events enrolled. "
                                   f"Karma Points: {enrollment_summary.get('karma_points', 0)}")
                bot_response = f"I apologize, but I'm experiencing technical difficulties. {enrollment_info} Please try your request again."

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
                "user_type": "anonymous" if is_anonymous else "logged_in"
            }
        )

        # Enhanced logging with session information
        if is_anonymous:
            logger.info(
                f"Anonymous session completed - Session UUID: {session_info.get('session_uuid', 'Unknown')[:8]}..., "
                f"Redis ID: {session.session_id}, Total Messages: {session.message_count + 2}")
        else:
            logger.info(
                f"Logged-in session completed - User: {user_id}, Redis ID: {session.session_id}, "
                f"Total Messages: {session.message_count + 2}")

        if mode is not None and mode == "start":
            if is_anonymous:
                bot_response = f"Starting new anonymous chat session. Session ID: {session_info.get('session_uuid', 'Unknown')[:8]}..."
            else:
                bot_response = "Starting new chat session."
            return {"message": bot_response}
        else:
            if isinstance(bot_response, str):
                bot_response = bot_response
            elif hasattr(bot_response, 'response'):
                bot_response = bot_response.response
            else:
                bot_response = "I apologize, but I didn't receive a proper response. Please try again."

        logger.debug(f"Returning response for {'anonymous' if is_anonymous else 'logged-in'} user: {bot_response[:100]} ...")
        return {"text": bot_response, "audio": audio_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)