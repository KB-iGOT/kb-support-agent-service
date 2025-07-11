"""
Chat routes for the Karmayogi Bharat chatbot API.
"""
import hashlib
import json
import os
import re
from typing import Annotated
import redis
import requests
import logging

from fastapi import APIRouter, HTTPException,Header
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
from google.adk.sessions import InMemorySessionService

from ..models.chat import Request
from ..agent_fastapi import ChatAgent
from ..config.config import API_ENDPOINTS

from ..utils.contentCache import UserDetailsContext, get_cached_user_details, hash_cookie
from ..utils.userDetails import UserDetailsError
from ..utils.vertexContentCache import initialize_vertex_cache, generate_with_user_context

load_dotenv()
logger = logging.getLogger(__name__)

# # Initialize Vertex AI content cache
# GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
# GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
# GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
# GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")


# if GOOGLE_CLOUD_PROJECT:
#     try:
#         vertex_cache_service = initialize_vertex_cache(GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, None)
#         logger.info(f"Vertex AI content cache initialized for project: {GOOGLE_CLOUD_PROJECT}")
#     except Exception as e:
#         logger.error(f"Failed to initialize Vertex AI content cache: {e}")
#         vertex_cache_service = None
# else:
#     logger.warning("GOOGLE_CLOUD_PROJECT not set. Vertex AI content caching disabled.")
#     vertex_cache_service = None


redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=os.getenv("REDIS_PORT"),
    db=os.getenv("REDIS_DB"),
    max_connections=50,
    retry_on_timeout=True,
    socket_keepalive=True,
    socket_keepalive_options={},
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    health_check_interval=30,
    # pipeline_timeout=10,
    )

router = APIRouter(prefix="/chat", tags=["chat"])
agent = ChatAgent()

@router.get("/")
async def health_check():
    """Health check endpoint to verify chat service status."""
    return {"message": "Chat service is running"}

# def auth_user(cookies):
#     """cookie verification"""
#     url = API_ENDPOINTS["PROXIES"]
#     print(cookies, '*'*100)
#     payload = {}
#     headers = {
#     'accept': 'application/json, text/plain, */*',
#     # 'accept': 'application/json',
#     'Cookie': cookies,
#     }
#     print("auth_user:: url:: ", url)
#     response = requests.request("GET", url, headers=headers, data=payload, timeout=60)

#     print("auth_user:: response:: ", response.text)
#     if response.status_code == 200: # and response.json()['params']['status'] == 'SUCCESS':
#         try:
#             if response.text.strip() == "":
#                 return False

#             data = response.json()
#             if data["params"]["status"] == 'SUCCESS':
#                 # return True
#                 return data
#         except json.JSONDecodeError as e:
#             logger.info(f"JSON decode error in auth_user: {e}")
#             return False
    
#     return False


# def verify_and_store_cookie(user_id: str, cookie: str):
#     if not cookie:
#         raise HTTPException(status_code=400, detail="Missing Cookie from request header.")

#     match = re.search(r'connect\.sid=([^;]+)', str(cookie))

#     if not match:
#         raise HTTPException(status_code=400, detail="Invalid Cookie format received.")

#     session_id = hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()
#     stored_cookie = redis_client.get(user_id)

#     if stored_cookie is None or str(cookie) != stored_cookie.decode('utf-8'):
#         if not auth_user(str(cookie)):
#             raise HTTPException(status_code=403, detail="Authentication failure.")
#         redis_client.set(user_id, str(cookie))
    
#     return session_id

    


@router.post("/start")
async def start_chat(
                    user_id: Annotated[str | None, Header()] = None,
                    cookie: Annotated[str | None, Header()] = None,
                    request : Request = None):
    """Endpoint to start a new chat session."""
    try:
        
        # print({"User-Agent request headers:: ", user_id, cookie})
        # stored_cookies = redis_client.get(user_id)
        # print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )
        # if request.channel_id == "web":
        #     if cookie is None:
        #         return { "message": "Missing Cookie."}
        #     match = re.search(r'connect\.sid=([^;]+)', str(cookie)) if cookie else None
        #     # request.session_id = match.group(1) if match else None
        #     request.session_id = hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()
        #     if request.session_id is None:
        #         return { "message" : "Not able to create the session."}
        # print(f" {user_id} session_id:: {request.session_id}")
        # if stored_cookies is None or str(cookie) != stored_cookies.decode('utf-8'):
        #     print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
        #     auth_cookies = auth_user(str(cookie))
        #     print(f"{user_id}:: Auth cookies: {auth_cookies}")
        #     if auth_cookies:
        #         print(f'{user_id}:: Storing the cookie in redis')
        #         redis_client.set(user_id, str(cookie))
        #     else:
        #         raise HTTPException(status_code=403, detail="Authentication failure.")
        logger.info(f"Start chat: user_id={user_id}, channel_id={request.channel_id}")
        # if request.channel_id == "web":
        #     session_id = verify_and_store_cookie(user_id, cookie)

        #     if session_id:
        #         request.session_id = session_id

        session_id = hashlib.sha256(cookie.encode("utf-8")).hexdigest()



        return await agent.start_new_session(user_id, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/send")
async def continue_chat(
                request: Request,
                user_id: Annotated[str | None, Header()] = None,
                cookie: Annotated[str | None, Header()] = None):
    """Endpoint to continue an existing chat session."""
    try:
        # print({"User-Agent request headers:: ", user_id, cookie})
        # if request.channel_id == "web" :
        #     stored_cookies = redis_client.get(user_id)
        #     print(f"Reading cookie from redis for {user_id} :: {stored_cookies}" )

        #     if cookie is None:
        #         return { "message": "Missing Cookie."}

        #     match = re.search(r'connect\.sid=([^;]+)', str(cookie)) if cookie else None
        #     # request.session_id = match.group(1) if match else None
        #     request.session_id = hashlib.sha256(match.group(1).encode("utf-8")).hexdigest()
        #     if request.session_id is None:
        #         return { "message" : "Not able to create the session."}
        #     print(f" {user_id} session_id:: {request.session_id}")

        #     if stored_cookies is None or str(cookie) != stored_cookies.decode('utf-8'):
        #         print(f" {user_id} :: Invoking auth_user with cookie:: {cookie}")
        #         auth_cookies = auth_user(str(cookie))
        #         print(f"{user_id}:: Auth cookies: {auth_cookies}")

        #         if auth_cookies:
        #             print(f'{user_id}:: Storing the cookie in redis')
        #             redis_client.set(user_id, str(cookie))
        #         else:
        #             raise HTTPException(status_code=403, detail="Authentication failure.")
        logger.info(f"Continue chat: user_id={user_id}, channel_id={request.channel_id}")
        # if request.channel_id == "web":
        #     session_id = verify_and_store_cookie(user_id, cookie)

        #     if session_id:
        #         request.session_id = session_id

        session_id = hashlib.sha256(cookie.encode("utf-8")).hexdigest()

        return await agent.send_message(user_id, request, session_id)
    except Exception as e:
        logger.error(f"Error in continue_chat: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# Request model for chat input
class ChatRequest(BaseModel):
    # message: str
    context: Optional[dict] = None
    channel_id : str
    session_id : str
    text : str | None = None
    audio : str | None = None
    language: str

class ChatResponse(BaseModel):
    session_id: str
    user_id: str
    channel_id: str
    message: str
    response: str
    timestamp: float

session_service = InMemorySessionService()

# @router.post("/cache_chat")
# async def _chat(
#         chat_request: ChatRequest,
#         user_id: str = Header(..., description="User ID from header"),
#         channel_id: str = Header(..., description="Channel from header"),
#         cookie: str = Header(..., description="Cookie from header")
# ):
#     """
#     Chat endpoint that creates/manages Google ADK sessions for user interactions.

#     Args:
#         chat_request: The chat message and optional context
#         user_id: User identifier from header
#         channel: Communication channel from header
#         cookie: Authentication cookie from header

#     Returns:
#         ChatResponse: Session details and chat response
#     """
#     try:
#         # Hash the cookie for secure storage
#         cookie_hash = hash_cookie(cookie)

#         logger.info(f"Received chat request from user: {user_id}, channel: {channel_id}")

#         # Validate required headers
#         if not user_id or not chat_request.channel_id or not cookie:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Missing required headers: user_id, channel, or cookie"
#             )

#         # Step 1: Authenticate user and validate user_id (with caching)
#         try:
#             # if chat_request.channel_id == "app":
#             #     cached_user_details = verify_and_store_cookie(user_id, cookie)
#             #     print(get_cached_user_details)

#             #     # if session_id:
#             #     #    chat_request.session_id = session_id

#             logger.info("Authenticating user and fetching details from cache...")
#             cached_user_details, was_cached = await get_cached_user_details(user_id, cookie)

#             logger.info(f"User details fetched: {cached_user_details}")

#             if was_cached:
#                 logger.info(
#                     f"Used cached user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")
#             else:
#                 logger.info(
#                     f"Fetched fresh user details. Enrollments: courses={cached_user_details.course_count}, events={cached_user_details.event_count}")

#         except UserDetailsError as e:
#             logger.error(f"User authentication failed: {e}")
#             raise HTTPException(
#                 status_code=401,
#                 detail=f"Authentication failed: {str(e)}"
#             )
#         except Exception as e:
#             logger.error(f"Unexpected error during authentication: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail="Authentication service temporarily unavailable"
#             )

#         # Try to get existing session or create new one
#         app_name = "karmayogi_bharat_support_bot"

#         try:
#             # First, try to get existing sessions for this user
#             existing_sessions = await session_service.list_sessions(
#                 app_name=app_name,
#                 user_id=user_id
#             )

#             # Debug: Check what list_sessions returns
#             logger.info(f"Existing sessions type: {type(existing_sessions)}")
#             logger.info(f"Existing sessions content: {existing_sessions}")

#             if existing_sessions:
#                 # Handle different return types from list_sessions
#                 matching_session = None

#                 # Check if it's a list of tuples or session objects
#                 for item in existing_sessions:
#                     if isinstance(item, tuple):
#                         # If it's a tuple, extract the session object (usually the first element)
#                         session_obj = item[0] if len(item) > 0 else None
#                         if session_obj and hasattr(session_obj, 'state'):
#                             if session_obj.state.get("cookie_hash") == cookie_hash:
#                                 matching_session = session_obj
#                                 break
#                     else:
#                         # If it's a session object directly
#                         if hasattr(item, 'state') and item.state.get("cookie_hash") == cookie_hash:
#                             matching_session = item
#                             break

#                 if matching_session:
#                     session = matching_session
#                     logger.info(f"Using existing session with matching cookie: {session.id}")
#                 else:
#                     # Create new session for new cookie
#                     session = await session_service.create_session(
#                         app_name=app_name,
#                         user_id=user_id,
#                         state={
#                             "channel": chat_request.channel_id,
#                             "cookie_hash": cookie_hash,
#                             "context": chat_request.context or {},
#                             "message_count": 0
#                         }
#                     )
#                     logger.info(f"Created new session for different cookie: {session.id}")
#             else:
#                 # Create new session if none exists
#                 session = await session_service.create_session(
#                     app_name=app_name,
#                     user_id=user_id,
#                     state={
#                         "channel": chat_request.channel_id,
#                         "cookie_hash": cookie_hash,
#                         "context": chat_request.context or {},
#                         "message_count": 0
#                     }
#                 )
#                 logger.info(f"Created new session: {session.id}")

#         except Exception as session_error:
#             logger.error(f"Session management error: {session_error}")
#             # Create new session as fallback with lightweight user summary
#             user_summary = cached_user_details.to_summary()
#             session = await session_service.create_session(
#                 app_name=app_name,
#                 user_id=user_id,
#                 state={
#                     "channel": chat_request.channel_id,
#                     "cookie_hash": cookie_hash,
#                     "context": chat_request.context or {},
#                     "message_count": 0,
#                     "user_summary": user_summary  # Lightweight summary instead of full details
#                 }
#             )
#             logger.info(f"Created fallback session: {session.id}")

#         # Update session state with new message
#         current_message_count = session.state.get("message_count", 0) + 1
#         updated_state = {
#             **session.state,
#             "last_message": chat_request.text,
#             "message_count": current_message_count,
#             "channel": chat_request.channel_id,
#             "cookie_hash": cookie_hash
#         }

#         # Update session state
#         session.state.update(updated_state)


#         # Log session properties for debugging (without sensitive cookie data)
#         logger.info(f"Session Properties:")
#         logger.info(f"ID: {session.id}")
#         logger.info(f"App Name: {session.app_name}")
#         logger.info(f"User ID: {session.user_id}")
#         logger.info(f"Channel: {session.state.get('channel')}")
#         logger.info(f"Cookie Hash: {session.state.get('cookie_hash')[:16]}...")
#         logger.info(f"Message Count: {current_message_count}")
#         logger.info(f"Last Update: {session.last_update_time}")

#         # TODO: Implement your actual chat processing logic here
#         # Use Vertex AI cached content for token-optimized responses
#         if vertex_cache_service:
#             try:
#                 logger.info("Generating response using Vertex AI cached content...")
#                 ai_response = await generate_with_user_context(
#                     user_id=user_id,
#                     cookie=cookie,
#                     prompt=f"User message: {chat_request.text}\n\nPlease respond helpfully based on their enrollment context.",
#                     force_refresh=False
#                 )

#                 if ai_response:
#                     bot_response = ai_response
#                     logger.info("Successfully generated response using cached content")
#                 else:
#                     # Fallback to basic response
#                     user_context = UserDetailsContext(user_id, cookie_hash)
#                     enrollment_info = user_context.get_enrollment_context()
#                     bot_response = f"Hello! I received your message: '{chat_request.text}'. {enrollment_info} (Note: AI response temporarily unavailable)"

#             except Exception as e:
#                 logger.error(f"Error generating AI response: {e}")
#                 # Fallback to basic response
#                 user_context = UserDetailsContext(user_id, cookie_hash)
#                 enrollment_info = user_context.get_enrollment_context()
#                 bot_response = f"Hello! I received your message: '{chat_request.text}'. {enrollment_info}"
#         else:
#             # Fallback when Vertex AI caching is not available
#             user_context = UserDetailsContext(user_id, cookie_hash)
#             enrollment_info = user_context.get_enrollment_context()
#             bot_response = f"Hello from Karmayogi Bharat Support Bot! I received your message: '{chat_request.text}'. This is message #{current_message_count} in our conversation. {enrollment_info}"

#         # return ChatResponse(
#         #     session_id=session.id,
#         #     user_id=user_id,
#         #     channel_id=chat_request.channel_id,
#         #     message=chat_request.text,
#         #     response=bot_response,
#         #     text=bot_response,
#         #     timestamp=session.last_update_time
#         # )
#         return { "text": bot_response , "audio" : ""}

#     except HTTPException:
#         # Re-raise HTTP exceptions
#         raise
#     except Exception as e:
#         logger.error(f"Unexpected error in chat endpoint: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Internal server error: {str(e)}"
#         )

