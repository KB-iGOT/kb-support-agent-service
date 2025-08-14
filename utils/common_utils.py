# common_utils.py - Common utility functions for ADK Custom Agent
import json
import logging
import os
import re
import time
import asyncio

from qdrant_client import QdrantClient
from typing import Optional, List, Dict, Any
from sentence_transformers import SentenceTransformer
import httpx

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
GEMINI_API_URL = os.getenv("GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-001:generateContent")
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY", None)
# FastEmbed model configuration
EMBEDDING_MODEL_NAME = os.getenv("FASTEMBED_MODEL", "BAAI/bge-small-en-v1.5")  # Fast and efficient model
VECTOR_SIZE = 384  # Dimension for bge-small-en-v1.5

# Initialize Qdrant client
qdrant_client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY") if os.getenv("QDRANT_API_KEY") else None
)

_embedding_model = None

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


async def rephrase_query_with_history(original_query: str, chat_history: List) -> str:
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

        return original_query

    except Exception as e:
        logger.error(f"Error in rephrasing: {e}")
        return original_query

async def call_gemini_api(prompt: str) -> str:
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


# Local LLM configuration

raw_urls = os.getenv("LOCAL_LLM_URLS")

if raw_urls:
    split_urls = raw_urls.split(",")

# Your existing load_llm_urls function here...
def load_llm_urls():
    """Load LLM URLs from environment variable (comma-separated)"""
    # Get comma-separated URLs from environment
    urls_env = os.getenv("LOCAL_LLM_URLS", "").strip()

    if urls_env:
        # Split by comma and strip whitespace, filter out empty strings
        urls = []
        raw_split = urls_env.split(",")

        for i, url in enumerate(raw_split):
            url = url.strip()

            if url:
                # Validate URL format
                if not (url.startswith("http://") or url.startswith("https://")):
                    continue
                urls.append(url)

        if urls:
            return urls
        else:
            print("ERROR: No valid URLs found in LOCAL_LLM_URLS")
    else:
        print("INFO: LOCAL_LLM_URLS not set or empty")

    # Default fallback URLs
    default_urls = [
        "http://localhost:11434/api/generate"
    ]
    logger.info(f"INFO: Using default URLs: {default_urls}")
    return default_urls


LOCAL_LLM_URLS = load_llm_urls()
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.2:3b-instruct-fp16")

# Load balancing strategy: "round_robin", "random", "fastest"
LOAD_BALANCE_STRATEGY = os.getenv("LOAD_BALANCE_STRATEGY", "random")

# Global variables for load balancing
_current_instance_index = 0
_instance_response_times: Dict[str, List[float]] = {url: [] for url in LOCAL_LLM_URLS}


async def _call_single_llm_instance(url: str, payload: Dict[str, Any], timeout: float = 480.0) -> Dict[str, Any]:
    """Call a single LLM instance and return response with metadata"""
    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            response_time = time.time() - start_time

            if response.status_code != 200:
                raise Exception(f"LLM API returned status {response.status_code}: {response.text}")

            response_data = response.json()

            return {
                "success": True,
                "response": response_data.get("response", ""),
                "url": url,
                "response_time": response_time,
                "instance": url.split(":")[-2][-5:] if ":" in url else "unknown"
            }

    except Exception as e:
        response_time = time.time() - start_time
        logger.error(f"Error calling LLM instance {url}: {e}")

        return {
            "success": False,
            "error": str(e),
            "url": url,
            "response_time": response_time,
            "instance": url.split(":")[-2][-5:] if ":" in url else "unknown"
        }

async def _call_local_llm_parallel(system_message: str, user_message: str) -> str:
    """Call both LLM instances in parallel and return the fastest response - FIXED VERSION"""

    payload = {
        "model": LOCAL_LLM_MODEL,
        "prompt": f"System: {system_message}\nUser: {user_message}",
        "stream": False,
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_predict": 2000  # Reasonable limit for faster responses
        }
    }

    logger.debug("Making parallel calls to both LLM instances")

    try:
        # Create tasks properly using asyncio.create_task()
        tasks = [
            asyncio.create_task(_call_single_llm_instance(url, payload, timeout=240.0))
            for url in LOCAL_LLM_URLS
        ]

        # Use asyncio.wait with FIRST_COMPLETED for better control
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
            timeout=240.0  # Overall timeout
        )

        # Cancel all pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Process completed tasks
        for task in done:
            try:
                result = await task
                if result["success"]:
                    logger.info(
                        f"🚀 Parallel LLM call successful - Instance: {result['instance']}, "
                        f"Response time: {result['response_time']:.2f}s"
                    )
                    return result["response"]
                else:
                    logger.warning(f"Parallel LLM instance {result['instance']} failed: {result['error']}")
            except Exception as e:
                logger.error(f"Error processing completed task: {e}")

        # If we get here, no task succeeded
        logger.error("All parallel LLM calls failed or timed out")
        return "I'm sorry, but both GPU instances are currently unavailable. Please try again later."

    except asyncio.TimeoutError:
        logger.error("Parallel LLM calls timed out")
        # Cancel all tasks on timeout
        for task in tasks:
            task.cancel()
        return "I'm experiencing response timeouts. Please try again."

    except Exception as e:
        logger.error(f"Error in parallel LLM calls: {e}")
        return "I'm experiencing technical difficulties. Please try again."

async def call_local_llm(system_message: str, user_message: str) -> str:
    """Helper function for local LLM calls"""
    return await _call_local_llm_parallel(system_message, user_message)