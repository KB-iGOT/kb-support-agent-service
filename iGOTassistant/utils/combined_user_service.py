"""
Combined User Service that merges fetch_userdetails and load_details_for_registered_users
into a single object and stores it in Redis for efficient access.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, Any, Tuple, List
import redis.asyncio as redis
from redis.asyncio import Redis
from pydantic import BaseModel

from .userDetails import get_user_details, UserDetailsError, UserDetailsResponse
from ..config.config import API_ENDPOINTS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass
class CombinedUserDetails:
    """Combined user details object containing both profile and enrollment information"""
    # Basic user information
    user_id: str
    first_name: str
    last_name: str
    primary_email: str
    phone: str
    
    # Profile details
    profile_details: Dict[str, Any]
    
    # Enrollment information
    course_count: int
    event_count: int
    total_enrollments: int
    user_course_enrollment_info: Dict[str, Any]
    course_enrollments: List[Dict[str, Any]]
    event_enrollments: List[Dict[str, Any]]
    
    # Enrollment summaries
    course_summary: Dict[str, Any]
    event_summary: Dict[str, Any]
    combined_enrollment_summary: Dict[str, Any]
    
    # Metadata
    cache_timestamp: float
    # cookie_hash: str
    is_authenticated: bool
    is_registered: bool
    
    def to_summary(self) -> Dict[str, Any]:
        """Return lightweight summary for session storage"""
        return {
            "user_id": self.user_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "primary_email": self.primary_email,
            "course_count": self.course_count,
            "event_count": self.event_count,
            "total_enrollments": self.total_enrollments,
            "is_authenticated": self.is_authenticated,
            "is_registered": self.is_registered,
            "last_updated": datetime.fromtimestamp(self.cache_timestamp).isoformat(),
            "cache_age_minutes": (time.time() - self.cache_timestamp) / 60
        }
    
    def is_expired(self, ttl_minutes: int = 30) -> bool:
        """Check if cache entry is expired"""
        return (time.time() - self.cache_timestamp) > (ttl_minutes * 60)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CombinedUserDetails':
        """Create instance from dictionary (Redis retrieval)"""
        return cls(**data)
    
    def get_full_context(self) -> str:
        """Get full context string for LLM usage"""
        context_parts = [
            f"User ID: {self.user_id}",
            f"Name: {self.first_name} {self.last_name}",
            f"Email: {self.primary_email}",
            f"Phone: {self.phone}",
            f"Course Enrollments: {self.course_count}",
            f"Event Enrollments: {self.event_count}",
            f"Total Enrollments: {self.total_enrollments}",
            f"Authentication Status: {'Authenticated' if self.is_authenticated else 'Not Authenticated'}",
            f"Registration Status: {'Registered' if self.is_registered else 'Not Registered'}"
        ]
        
        if self.combined_enrollment_summary:
            context_parts.append(f"Enrollment Summary: {json.dumps(self.combined_enrollment_summary, indent=2)}")
        
        return "\n".join(context_parts)


class CombinedUserService:
    """
    Service that combines fetch_userdetails and load_details_for_registered_users
    into a single object and stores it in Redis for efficient access.
    """
    
    def __init__(
        self,
        redis_url: str = f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379",
        default_ttl_minutes: int = 30,
        key_prefix: str = "combined_user:",
        max_connections: int = 20
    ):
        self.redis_url = redis_url
        self.default_ttl = default_ttl_minutes
        self.key_prefix = key_prefix
        self.max_connections = max_connections
        self._redis: Optional[Redis] = None
        self._connection_pool: Optional[redis.ConnectionPool] = None
    
    async def _get_redis(self) -> Redis:
        """Get Redis connection with lazy initialization"""
        if self._redis is None:
            self._connection_pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                retry_on_timeout=True,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                health_check_interval=30
            )
            self._redis = Redis(connection_pool=self._connection_pool)
            
            # Test connection
            try:
                await self._redis.ping()
                logger.info("Redis connection established successfully")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        
        return self._redis
    
    def _generate_cache_key(self, user_id: str) -> str:
        """Generate unique cache key for user_id + cookie combination"""
        combined = f"{user_id}"
        key_hash = hashlib.md5(combined.encode()).hexdigest()
        return f"{self.key_prefix}{key_hash}"
    
    def _generate_summary_key(self, cache_key: str) -> str:
        """Generate key for summary data"""
        return f"{cache_key}:summary"
    
    def hash_cookie(self, cookie: str) -> str:
        """Hash cookie for cache key generation"""
        return hashlib.sha256(cookie.encode('utf-8')).hexdigest()
    
    async def get_combined_user_details(
        self,
        user_id: str,
        force_refresh: bool = False
    ) -> Tuple[CombinedUserDetails, bool]:
        """
        Get combined user details from cache or fetch fresh data.
        
        This combines the functionality of:
        - fetch_userdetails: Gets basic user profile information
        - load_details_for_registered_users: Gets enrollment details
        
        Args:
            user_id: User identifier
            force_refresh: Force fetch from API even if cached
            
        Returns:
            Tuple of (CombinedUserDetails, was_cached: bool)
        """
        redis_client = await self._get_redis()
        
        # Check cache first (unless force refresh)
        if not force_refresh:
            try:
                cache_key = self._generate_cache_key(user_id)
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    cached_dict = json.loads(cached_data)
                    cached_details = CombinedUserDetails.from_dict(cached_dict)
                    
                    if not cached_details.is_expired(self.default_ttl):
                        cache_age = (time.time() - cached_details.cache_timestamp) / 60
                        logger.info(f"Cache HIT for combined user details {user_id} (age: {cache_age:.1f}m)")
                        return cached_details, True
                    else:
                        logger.info(f"Cache EXPIRED for user {user_id}, refreshing...")
                        await redis_client.delete(cache_key, self._generate_summary_key(cache_key))
                        
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to deserialize cached data for user {user_id}: {e}")
                await redis_client.delete(cache_key, self._generate_summary_key(cache_key))
        
        # Fetch fresh data
        logger.info(f"Cache MISS for user {user_id}, fetching combined details...")
        try:
            # Step 1: Get user details and enrollment information (cookie pre-validated)
            user_details_response = await get_user_details(user_id )
            
            # Step 2: Extract profile details from the enrollment summary
            profile_details = user_details_response.enrollment_summary.get("user_profile", {})
            
            # Step 3: Create combined user details object
            combined_details = CombinedUserDetails(
                user_id=user_details_response.user_id,
                first_name=profile_details.get("firstName", ""),
                last_name=profile_details.get("lastName", ""),
                primary_email=profile_details.get("primaryEmail", ""),
                phone=profile_details.get("mobile", ""),
                profile_details=profile_details,
                course_count=len(user_details_response.course_enrollments),
                event_count=len(user_details_response.event_enrollments),
                total_enrollments=len(user_details_response.course_enrollments) + len(user_details_response.event_enrollments),
                user_course_enrollment_info=user_details_response.enrollment_summary.get("user_course_enrollment_info", {}),
                course_enrollments=user_details_response.course_enrollments,
                event_enrollments=user_details_response.event_enrollments,
                course_summary=user_details_response.enrollment_summary.get("courses", {}),
                event_summary=user_details_response.enrollment_summary.get("events", {}),
                combined_enrollment_summary=user_details_response.enrollment_summary,
                cache_timestamp=time.time(),
                # cookie_hash=cookie_hash,
                is_authenticated=True,  # Cookie pre-validated at application layer
                is_registered=True  # If we got here, user is registered
            )
            
            # Store in Redis with TTL
            ttl_seconds = self.default_ttl * 60
            summary_key = self._generate_summary_key(cache_key)
            
            # Use pipeline for atomic operations
            async with redis_client.pipeline() as pipe:
                pipe.set(cache_key, json.dumps(combined_details.to_dict()), ex=ttl_seconds)
                pipe.set(summary_key, json.dumps(combined_details.to_summary()), ex=ttl_seconds)
                await pipe.execute()
            
            logger.info(f"Cached combined user details for {user_id} (enrollments: {combined_details.total_enrollments})")
            
            return combined_details, False
            
        except UserDetailsError as e:
            logger.error(f"Failed to fetch user details for {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Redis operation failed for user {user_id}: {e}")
            raise
    
    async def get_summary_for_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get lightweight summary for session storage (doesn't trigger API call).
        
        Args:
            user_id: User identifier
            cookie_hash: Hashed cookie
            
        Returns:
            Lightweight summary or None if not cached
        """
        cache_key = self._generate_cache_key(user_id)
        summary_key = self._generate_summary_key(cache_key)
        redis_client = await self._get_redis()
        
        try:
            # Try summary first (lighter operation)
            summary_data = await redis_client.get(summary_key)
            if summary_data:
                return json.loads(summary_data)
            
            # Fallback to full data if summary not available
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                cached_dict = json.loads(cached_data)
                cached_details = CombinedUserDetails.from_dict(cached_dict)
                
                if not cached_details.is_expired(self.default_ttl):
                    return cached_details.to_summary()
                    
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to get summary for user {user_id}: {e}")
        
        return None
    
    async def get_full_details(self, user_id: str) -> Optional[CombinedUserDetails]:
        """
        Get full cached details (for LLM context when needed).
        
        Args:
            user_id: User identifier
            
        Returns:
            Full cached details or None if not cached/expired
        """
        cache_key = self._generate_cache_key(user_id)
        redis_client = await self._get_redis()
        
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                cached_dict = json.loads(cached_data)
                cached_details = CombinedUserDetails.from_dict(cached_dict)
                
                if not cached_details.is_expired(self.default_ttl):
                    return cached_details
                    
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to get full details for user {user_id}: {e}")
        
        return None
    
    async def invalidate_user_cache(self, user_id: str) -> bool:
        """
        Invalidate cache for specific user.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if cache entry was removed, False if not found
        """
        cache_key = self._generate_cache_key(user_id)
        summary_key = self._generate_summary_key(cache_key)
        redis_client = await self._get_redis()
        
        try:
            # Delete both full and summary data
            result = await redis_client.delete(cache_key, summary_key)
            
            if result > 0:
                logger.info(f"Invalidated combined user cache for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to invalidate cache for user {user_id}: {e}")
        
        return False
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        redis_client = await self._get_redis()
        
        try:
            # Get all cache keys
            pattern = f"{self.key_prefix}*"
            cache_keys = await redis_client.keys(pattern)
            
            # Filter out summary keys for counting
            full_cache_keys = [key for key in cache_keys if not key.endswith(':summary')]
            
            # Get Redis info
            redis_info = await redis_client.info()
            
            return {
                "total_entries": len(full_cache_keys),
                "redis_connected_clients": redis_info.get('connected_clients', 0),
                "redis_used_memory_human": redis_info.get('used_memory_human', 'Unknown'),
                "default_ttl_minutes": self.default_ttl,
                "cache_key_pattern": pattern,
                "sample_keys": full_cache_keys[:10]  # Show first 10 keys as sample
            }
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {
                "error": str(e),
                "total_entries": 0,
                "default_ttl_minutes": self.default_ttl
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Redis connection health"""
        try:
            redis_client = await self._get_redis()
            start_time = time.time()
            await redis_client.ping()
            response_time = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "redis_url": self.redis_url.split('@')[-1] if '@' in self.redis_url else self.redis_url
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
            logger.info("Redis connection closed")
        if self._connection_pool:
            await self._connection_pool.disconnect()
            logger.info("Redis connection pool disconnected")


# Global service instance
combined_user_service = CombinedUserService(
    redis_url=f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379",
    default_ttl_minutes=30
)


# Convenience functions for easy import
async def get_combined_user_details(user_id: str, force_refresh: bool = False) -> Tuple[CombinedUserDetails, bool]:
    """Get combined user details from cache or fetch fresh"""
    return await combined_user_service.get_combined_user_details(user_id, force_refresh)


async def get_combined_user_summary(user_id: str) -> Optional[Dict[str, Any]]:
    """Get lightweight summary for session storage"""
    return await combined_user_service.get_summary_for_session(user_id)


async def get_combined_user_full_details(user_id: str) -> Optional[CombinedUserDetails]:
    """Get full cached details for LLM context"""
    return await combined_user_service.get_full_details(user_id)


async def invalidate_combined_user_cache(user_id: str) -> bool:
    """Invalidate cache for specific user"""
    return await combined_user_service.invalidate_user_cache(user_id)


# Context manager for LLM-optimized combined user details
class CombinedUserDetailsContext:
    """
    Context manager that provides optimized combined user details for LLM usage.
    Only loads full details when explicitly requested to minimize token usage.
    """
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self._full_details: Optional[CombinedUserDetails] = None
    
    async def get_summary(self) -> Optional[Dict[str, Any]]:
        """Get lightweight summary (always safe for tokens)"""
        return await get_combined_user_summary(self.user_id)
    
    async def get_user_context(self) -> str:
        """Get user info as concise string for LLM context"""
        summary = await self.get_summary()
        if summary:
            return f"User {summary['first_name']} {summary['last_name']} has {summary['course_count']} courses and {summary['event_count']} events enrolled."
        return "User details not available."
    
    async def load_full_details(self) -> Optional[CombinedUserDetails]:
        """Load full details only when needed (use sparingly due to token cost)"""
        if self._full_details is None:
            self._full_details = await get_combined_user_full_details(self.user_id)
        return self._full_details
    
    async def get_course_titles(self, max_courses: int = 5) -> List[str]:
        """Get limited course titles for LLM context"""
        full_details = await self.load_full_details()
        if full_details and full_details.course_enrollments:
            courses = []
            for course in full_details.course_enrollments[:max_courses]:
                title = course.get('title', course.get('name', 'Unknown Course'))
                courses.append(title)
            return courses
        return []
    
    async def get_event_titles(self, max_events: int = 5) -> List[str]:
        """Get limited event titles for LLM context"""
        full_details = await self.load_full_details()
        if full_details and full_details.event_enrollments:
            events = []
            for event in full_details.event_enrollments[:max_events]:
                title = event.get('title', event.get('name', 'Unknown Event'))
                events.append(title)
            return events
        return [] 