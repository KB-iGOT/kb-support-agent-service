import json
import os
import time
import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import numpy as np
from dotenv import load_dotenv
from fastembed import TextEmbedding

import redis.asyncio as redis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

load_dotenv()

@dataclass
class ChatMessage:
    """Individual chat message in a session"""
    message_id: str
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: float
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        return cls(**data)


@dataclass
class AgentSession:
    """Complete session data for ADK Agent"""
    session_id: str
    app_name: str
    user_id: str
    channel: str
    cookie_hash: str
    created_at: float
    last_activity: float
    message_count: int
    messages: List[ChatMessage]
    context: Dict[str, Any]
    agent_state: Dict[str, Any]
    vector_data: Optional[Dict[str, Any]] = None  # Store vectorized enrollment data

    def add_vector_data(self, vector_data: Dict[str, Any]):
        """Add vectorized enrollment data to session"""
        self.vector_data = vector_data
        self.last_activity = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """FIXED: Include vector_data in serialization"""
        return {
            "session_id": self.session_id,
            "app_name": self.app_name,
            "user_id": self.user_id,
            "channel": self.channel,
            "cookie_hash": self.cookie_hash,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "message_count": self.message_count,
            "messages": [msg.to_dict() for msg in self.messages],
            "context": self.context,
            "agent_state": self.agent_state,
            "vector_data": self.vector_data  # FIX: Include vector_data in serialization
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentSession':
        """FIXED: Include vector_data in deserialization"""
        messages = [ChatMessage.from_dict(msg) for msg in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            app_name=data["app_name"],
            user_id=data["user_id"],
            channel=data["channel"],
            cookie_hash=data["cookie_hash"],
            created_at=data["created_at"],
            last_activity=data["last_activity"],
            message_count=data["message_count"],
            messages=messages,
            context=data.get("context", {}),
            agent_state=data.get("agent_state", {}),
            vector_data=data.get("vector_data")  # FIX: Include vector_data in deserialization
        )

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> ChatMessage:
        """Add a new message to the session"""
        message = ChatMessage(
            message_id=str(uuid.uuid4()),
            role=role,
            content=content,
            timestamp=time.time(),
            metadata=metadata or {}
        )
        self.messages.append(message)
        self.message_count = len(self.messages)
        self.last_activity = time.time()
        return message

    def get_conversation_history(self, limit: Optional[int] = None) -> List[ChatMessage]:
        """Get conversation history with optional limit"""
        if limit:
            return self.messages[-limit:]
        return self.messages.copy()

    def update_context(self, updates: Dict[str, Any]):
        """Update session context"""
        self.context.update(updates)
        self.last_activity = time.time()

    def update_agent_state(self, state: Dict[str, Any]):
        """Update agent-specific state"""
        self.agent_state.update(state)
        self.last_activity = time.time()


class RedisSessionService:
    """
    Complete Redis-based session service replacing ADK's InMemorySessionService
    Provides all Runner functionality for session management
    """

    def __init__(
            self,
            redis_url: str = "redis://localhost:6379",
            session_ttl_hours: int = 24,
            max_messages_per_session: int = 100,
            key_prefix: str = "adk_session:",
            max_connections: int = 10
    ):
        logger.info(f"Initializing RedisSessionService with URL: {os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)} || redis_url: {redis_url}")
        self.redis_url = redis_url
        self.session_ttl = session_ttl_hours * 3600  # Convert to seconds
        self.max_messages = max_messages_per_session
        self.key_prefix = key_prefix
        self.max_connections = max_connections
        self._redis: Optional[Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
        self._embedding_model = None

    async def _get_redis(self) -> Redis:
        """Get Redis connection with lazy initialization"""
        if self._redis is None:
            self._connection_pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                retry_on_timeout=True,
                decode_responses=True
            )
            self._redis = Redis(connection_pool=self._connection_pool)

            # Test connection
            try:
                await self._redis.ping()
                logger.info("Redis session service connection established")
            except Exception as e:
                logger.error(f"Failed to connect to Redis for sessions: {e}")
                raise

        return self._redis

    def _generate_session_key(self, session_id: str) -> str:
        """Generate Redis key for session"""
        return f"{self.key_prefix}{session_id}"

    def _generate_user_sessions_key(self, app_name: str, user_id: str) -> str:
        """Generate Redis key for user's session list"""
        return f"{self.key_prefix}user:{app_name}:{user_id}"

    async def list_user_sessions(self, app_name: str, user_id: str) -> List[AgentSession]:
        """List all sessions for a user"""
        redis_client = await self._get_redis()
        user_sessions_key = self._generate_user_sessions_key(app_name, user_id)

        try:
            session_ids = await redis_client.smembers(user_sessions_key)
            sessions = []

            for session_id in session_ids:
                session = await self.get_session(session_id)
                if session:
                    sessions.append(session)
                else:
                    # Clean up orphaned session ID
                    await redis_client.srem(user_sessions_key, session_id)

            # Sort by last activity (most recent first)
            sessions.sort(key=lambda s: s.last_activity, reverse=True)
            return sessions

        except Exception as e:
            logger.error(f"Error listing sessions for user {user_id}: {e}")
            return []

    async def create_session(
            self,
            app_name: str,
            user_id: str,
            channel: str,
            cookie_hash: str,
            initial_context: Optional[Dict[str, Any]] = None
    ) -> AgentSession:
        """Create a new session"""
        session_id = str(uuid.uuid4())
        current_time = time.time()

        session = AgentSession(
            session_id=session_id,
            app_name=app_name,
            user_id=user_id,
            channel=channel,
            cookie_hash=cookie_hash,
            created_at=current_time,
            last_activity=current_time,
            message_count=0,
            messages=[],
            context=initial_context or {},
            agent_state={},
            vector_data=None  # Initialize as None
        )

        await self._save_session(session)
        await self._add_to_user_sessions(app_name, user_id, session_id)

        logger.info(f"Created new session: {session_id} for user: {user_id}")
        return session

    async def find_or_create_session(
            self,
            app_name: str,
            user_id: str,
            channel: str,
            cookie_hash: str,
            initial_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[AgentSession, bool]:
        """
        Find existing session for user/cookie combination or create new one
        Returns (session, is_new)
        """
        # Try to find existing session
        existing_sessions = await self.list_user_sessions(app_name, user_id)

        for session in existing_sessions:
            if session.cookie_hash == cookie_hash and session.channel == channel:
                logger.info(f"Found existing session: {session.session_id}")
                return session, False

        # Create new session if none found
        session = await self.create_session(
            app_name, user_id, channel, cookie_hash, initial_context)
        return session, True

    async def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Get session by ID"""
        redis_client = await self._get_redis()
        session_key = self._generate_session_key(session_id)

        try:
            session_data = await redis_client.get(session_key)
            if session_data:
                session_dict = json.loads(session_data)
                session = AgentSession.from_dict(session_dict)

                # Debug log for vector data presence
                if session.vector_data:
                    logger.debug(
                        f"Session {session_id} has vector data with {len(session.vector_data.get('courses', []))} courses")
                else:
                    logger.debug(f"Session {session_id} has no vector data")

                return session
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to deserialize session {session_id}: {e}")
            await redis_client.delete(session_key)

        return None

    async def update_session(self, session: AgentSession) -> bool:
        """Update existing session"""
        session.last_activity = time.time()
        return await self._save_session(session)

    async def add_message_to_session(
            self,
            session_id: str,
            role: str,
            content: str,
            metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ChatMessage]:
        """Add message to session and return the message"""
        session = await self.get_session(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            return None

        # Trim messages if approaching limit
        if len(session.messages) >= self.max_messages:
            # Keep last 80% of messages
            keep_count = int(self.max_messages * 0.8)
            session.messages = session.messages[-keep_count:]
            logger.info(f"Trimmed session {session_id} to {keep_count} messages")

        message = session.add_message(role, content, metadata)
        await self.update_session(session)
        return message

    async def get_conversation_history(
            self,
            session_id: str,
            limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """Get conversation history for session"""
        session = await self.get_session(session_id)
        if not session:
            return []

        return session.get_conversation_history(limit)

    async def update_session_context(
            self,
            session_id: str,
            context_updates: Dict[str, Any]
    ) -> bool:
        """Update session context"""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.update_context(context_updates)
        return await self.update_session(session)

    async def update_agent_state(
            self,
            session_id: str,
            agent_state: Dict[str, Any]
    ) -> bool:
        """Update agent state in session"""
        session = await self.get_session(session_id)
        if not session:
            return False

        session.update_agent_state(agent_state)
        return await self.update_session(session)

    async def _fuzzy_text_search(self, session, query: str, limit: int) -> List[Dict]:
        """Fallback fuzzy text search"""
        if not session or not session.vector_data:
            logger.warning("No session or vector data available for fuzzy search")
            return []

        try:
            from fuzzywuzzy import fuzz

            results = []
            query_lower = query.lower()

            # Search course names
            courses = session.vector_data.get("courses", [])
            for course in courses:
                course_name = course.get('course_name', '').lower()
                if course_name:
                    # Calculate fuzzy match score
                    ratio = fuzz.partial_ratio(query_lower, course_name)
                    if ratio > 60:  # 60% similarity threshold
                        course_data = course.copy()
                        course_data["match_score"] = ratio / 100.0
                        course_data["data_type"] = "course"
                        results.append(course_data)

            # Sort by match score
            results.sort(key=lambda x: x.get("match_score", 0), reverse=True)

            logger.info(f"Fuzzy text search found {len(results)} results")
            return results[:limit]

        except ImportError:
            logger.error("fuzzywuzzy not installed, cannot perform fuzzy search")
            return []
        except Exception as e:
            logger.error(f"Error in fuzzy text search: {e}")
            return []

    async def _save_session(self, session: AgentSession) -> bool:
        """Save session to Redis with enhanced debugging"""
        redis_client = await self._get_redis()
        session_key = self._generate_session_key(session.session_id)

        try:
            session_dict = session.to_dict()

            # DEBUG: Log if vector data is being included
            has_vectors = session_dict.get("vector_data") is not None
            logger.debug(f"Saving session {session.session_id} with vector data: {has_vectors}")

            session_data = json.dumps(session_dict)
            await redis_client.set(session_key, session_data, ex=self.session_ttl)

            logger.debug(f"Session {session.session_id} saved successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")
            return False

    async def _add_to_user_sessions(self, app_name: str, user_id: str, session_id: str):
        """Add session to user's session list"""
        redis_client = await self._get_redis()
        user_sessions_key = self._generate_user_sessions_key(app_name, user_id)

        await redis_client.sadd(user_sessions_key, session_id)
        await redis_client.expire(user_sessions_key, self.session_ttl)

    async def health_check(self) -> Dict[str, Any]:
        """Check Redis connection health"""
        try:
            redis_client = await self._get_redis()
            start_time = time.time()
            await redis_client.ping()
            response_time = (time.time() - start_time) * 1000

            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "redis_url": self.redis_url.split('@')[-1] if '@' in self.redis_url else self.redis_url,
                "session_ttl_hours": self.session_ttl / 3600
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "redis_url": self.redis_url.split('@')[-1] if '@' in self.redis_url else self.redis_url
            }

    async def shutdown(self):
        """Cleanup when shutting down"""
        if self._redis:
            await self._redis.close()
            logger.info("Redis session service connection closed")
        if self._connection_pool:
            await self._connection_pool.disconnect()
            logger.info("Redis session service connection pool disconnected")


# Global session service instance
redis_session_service = RedisSessionService(
    redis_url=f"redis://{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT', 6379)}",
    session_ttl_hours=24,
    max_messages_per_session=100
)


# Convenience functions
async def get_or_create_session(
        app_name: str,
        user_id: str,
        channel: str,
        cookie_hash: str,
        initial_context: Optional[Dict[str, Any]] = None
) -> Tuple[AgentSession, bool]:
    """Get existing session or create new one"""
    return await redis_session_service.find_or_create_session(app_name, user_id, channel, cookie_hash, initial_context)


async def add_chat_message(
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
) -> Optional[ChatMessage]:
    """Add message to session"""
    return await redis_session_service.add_message_to_session(
        session_id, role, content, metadata
    )


async def get_session_context(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session context"""
    session = await redis_session_service.get_session(session_id)
    return session.context if session else None


async def update_session_data(
        session_id: str,
        context_updates: Optional[Dict[str, Any]] = None,
        agent_state: Optional[Dict[str, Any]] = None
) -> bool:
    """Update session context and/or agent state"""
    success = True

    if context_updates:
        success &= await redis_session_service.update_session_context(session_id, context_updates)

    if agent_state:
        success &= await redis_session_service.update_agent_state(session_id, agent_state)

    return success