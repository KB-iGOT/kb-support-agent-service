# utils/contentCache.py - OPTIMIZED VERSION
import hashlib
import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional, Any, Tuple, List

from redis.asyncio import Redis
from dotenv import load_dotenv

from utils.userDetails import get_user_details, UserDetailsError
from utils.redis_session_service import redis_session_service, get_or_create_session
from utils.redis_connection_manager import get_redis_client  # ✅ Use shared connection

logger = logging.getLogger(__name__)
load_dotenv()


def hash_cookie(cookie: str) -> str:
    """Hash cookie for cache key generation"""
    return hashlib.sha256(cookie.encode('utf-8')).hexdigest()


@dataclass
class CachedUserDetails:
    """Cached user details with metadata - updated to match new UserDetailsResponse structure"""
    user_id: str
    profile: Dict[str, Any]
    course_count: int
    event_count: int
    total_enrollments: int
    enrollment_summary: Dict[str, Any]  # Combined course and event summary
    course_enrollments: list
    event_enrollments: list
    cache_timestamp: float
    cookie_hash: str

    def to_summary(self) -> Dict[str, Any]:
        """Return lightweight summary for session storage"""
        return {
            "user_id": self.user_id,
            "course_count": self.course_count,
            "event_count": self.event_count,
            "total_enrollments": self.total_enrollments,
            "enrollment_summary": self.enrollment_summary,
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
    def from_dict(cls, data: Dict[str, Any]) -> 'CachedUserDetails':
        """Create instance from dictionary (Redis retrieval)"""
        return cls(**data)

    def get_karma_points(self) -> int:
        """Get karma points from enrollment summary"""
        return self.enrollment_summary.get('karma_points', 0)

    def get_course_completion_stats(self) -> Dict[str, int]:
        """Get course completion statistics"""
        return {
            "completed": self.enrollment_summary.get('total_courses_completed', 0),
            "in_progress": self.enrollment_summary.get('total_courses_in_progress', 0),
            "not_started": self.enrollment_summary.get('total_courses_not_started', 0),
            "certified": self.enrollment_summary.get('certified_courses_count', 0)
        }

    def get_event_completion_stats(self) -> Dict[str, int]:
        """Get event completion statistics"""
        return {
            "completed": self.enrollment_summary.get('total_events_completed', 0),
            "in_progress": self.enrollment_summary.get('total_events_in_progress', 0),
            "not_started": self.enrollment_summary.get('total_events_not_started', 0),
            "certified": self.enrollment_summary.get('certified_events_count', 0)
        }

    def get_time_spent_summary(self) -> Dict[str, int]:
        """Get time spent summary in minutes"""
        return {
            "courses": self.enrollment_summary.get('time_spent_on_completed_courses_in_minutes', 0),
            "events": self.enrollment_summary.get('time_spent_on_completed_events_in_minutes', 0)
        }


class ContentCache:
    """
    ✅ OPTIMIZED: Redis-based cache using shared connection pool from RedisConnectionManager.

    Key optimizations:
    - Uses shared Redis connection pool (no duplicate connections)
    - Removed redundant connection management code
    - Simplified initialization
    - Better error handling with shared health checks
    """

    def __init__(
            self,
            default_ttl_minutes: int = 30,
            key_prefix: str = "user_cache:"
    ):
        # ✅ SIMPLIFIED: No longer manages its own Redis connection
        self.default_ttl = default_ttl_minutes
        self.key_prefix = key_prefix
        logger.info(f"ContentCache initialized with shared Redis connection - TTL: {default_ttl_minutes}min")

    async def _get_redis(self) -> Redis:
        """✅ OPTIMIZED: Get Redis client from shared connection manager"""
        return await get_redis_client()

    def _generate_cache_key(self, user_id: str, cookie_hash: str) -> str:
        """Generate unique cache key for user_id + cookie combination"""
        combined = f"{user_id}:{cookie_hash}"
        key_hash = hashlib.md5(combined.encode()).hexdigest()
        return f"{self.key_prefix}{key_hash}"

    def _generate_summary_key(self, cache_key: str) -> str:
        """Generate key for summary data"""
        return f"{cache_key}:summary"

    async def contentcache_get_user_details(
            self,
            user_id: str,
            cookie: str,
            force_refresh: bool = False,
            session_id: Optional[str] = None,
            app_name: str = "adk_agent",
            channel: str = "web"
    ) -> Tuple[CachedUserDetails, bool]:
        """
        ✅ OPTIMIZED: Get user details from cache using shared Redis connection.
        """
        cookie_hash = hash_cookie(cookie)
        cache_key = self._generate_cache_key(user_id, cookie_hash)
        redis_client = await self._get_redis()  # ✅ Uses shared connection

        # Check cache first (unless force refresh)
        if not force_refresh:
            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    cached_dict = json.loads(cached_data)
                    cached_details = CachedUserDetails.from_dict(cached_dict)

                    if not cached_details.is_expired(self.default_ttl):
                        cache_age = (time.time() - cached_details.cache_timestamp) / 60
                        logger.info(f"Cache HIT for user {user_id} (age: {cache_age:.1f}m)")
                        return cached_details, True
                    else:
                        logger.info(f"Cache EXPIRED for user {user_id}, refreshing...")
                        # Redis TTL should handle cleanup, but delete explicitly for consistency
                        await redis_client.delete(cache_key, self._generate_summary_key(cache_key))

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to deserialize cached data for user {user_id}: {e}")
                await redis_client.delete(cache_key, self._generate_summary_key(cache_key))

        # Fetch fresh data
        logger.info(f"Cache MISS for user {user_id}, fetching from API...")
        try:
            user_details = await get_user_details(user_id)

            # Create cached details using new UserDetailsResponse structure
            cached_details = CachedUserDetails(
                user_id=user_details.user_id,
                profile=user_details.profile,
                course_count=len(user_details.course_enrollments),
                event_count=len(user_details.event_enrollments),
                total_enrollments=len(user_details.course_enrollments) + len(user_details.event_enrollments),
                enrollment_summary=user_details.enrollment_summary,  # New combined summary
                course_enrollments=user_details.course_enrollments,
                event_enrollments=user_details.event_enrollments,
                cache_timestamp=time.time(),
                cookie_hash=cookie_hash
            )

            # Store in Redis with TTL
            ttl_seconds = self.default_ttl * 60
            summary_key = self._generate_summary_key(cache_key)

            # ✅ OPTIMIZED: Use pipeline for atomic operations with shared connection
            async with redis_client.pipeline() as pipe:
                pipe.set(cache_key, json.dumps(cached_details.to_dict()), ex=ttl_seconds)
                pipe.set(summary_key, json.dumps(cached_details.to_summary()), ex=ttl_seconds)
                await pipe.execute()

            logger.info(f"Cached user details for {user_id} (enrollments: {cached_details.total_enrollments})")
            karma_points = cached_details.get_karma_points()
            logger.info(f"Cached user details for {user_id} (karmaPoints: {karma_points})")

            if session_id:
                await self._update_session(
                    session_id, cached_details, app_name, user_id, channel, cookie_hash
                )

            return cached_details, False

        except UserDetailsError as e:
            logger.error(f"Failed to fetch user details for {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Redis operation failed for user {user_id}: {e}")
            raise

    async def _ensure_session(self, session_id: str):
        try:
            session = await redis_session_service.get_session(session_id)
        except Exception as e:
            logger.warning(f"Failed to ensure session: {e}")

    async def _update_session(
            self,
            session_id: str,
            cached_details: CachedUserDetails,
            app_name: str,
            user_id: str,
            channel: str,
            cookie_hash: str
    ):
        """Update or create session"""
        try:
            # Get or create session
            session, is_new = await get_or_create_session(
                app_name, user_id, channel, cookie_hash
            )

            # Update session context with cache info
            context_updates = {
                "user_cache_key": self._generate_cache_key(user_id, cookie_hash),
                "last_cache_update": cached_details.cache_timestamp,
                "total_enrollments": cached_details.total_enrollments,
                "karma_points": cached_details.get_karma_points()
            }

            await redis_session_service.update_session_context(
                session.session_id, context_updates
            )

            if is_new:
                logger.info(f"Created new session {session.session_id}")
            else:
                logger.info(f"Updated existing session {session.session_id}")

        except Exception as e:
            logger.error(f"Failed to update session: {e}")

    async def get_summary_for_session(self, user_id: str, cookie_hash: str) -> Optional[Dict[str, Any]]:
        """✅ OPTIMIZED: Get lightweight summary using shared Redis connection"""
        cache_key = self._generate_cache_key(user_id, cookie_hash)
        summary_key = self._generate_summary_key(cache_key)
        redis_client = await self._get_redis()  # ✅ Uses shared connection

        try:
            # Try summary first (lighter operation)
            summary_data = await redis_client.get(summary_key)
            if summary_data:
                return json.loads(summary_data)

            # Fallback to full data if summary not available
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                cached_dict = json.loads(cached_data)
                cached_details = CachedUserDetails.from_dict(cached_dict)

                if not cached_details.is_expired(self.default_ttl):
                    return cached_details.to_summary()

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to get summary for user {user_id}: {e}")

        return None

    async def get_full_details(self, user_id: str, cookie_hash: str) -> Optional[CachedUserDetails]:
        """✅ OPTIMIZED: Get full cached details using shared Redis connection"""
        cache_key = self._generate_cache_key(user_id, cookie_hash)
        redis_client = await self._get_redis()  # ✅ Uses shared connection

        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                cached_dict = json.loads(cached_data)
                cached_details = CachedUserDetails.from_dict(cached_dict)

                if not cached_details.is_expired(self.default_ttl):
                    return cached_details

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to get full details for user {user_id}: {e}")

        return None

    async def invalidate_user_cache(self, user_id: str, cookie_hash: str) -> bool:
        """✅ OPTIMIZED: Invalidate cache using shared Redis connection"""
        cache_key = self._generate_cache_key(user_id, cookie_hash)
        summary_key = self._generate_summary_key(cache_key)
        redis_client = await self._get_redis()  # ✅ Uses shared connection

        try:
            # Delete both full and summary data
            result = await redis_client.delete(cache_key, summary_key)

            if result > 0:
                logger.info(f"Invalidated cache for user {user_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to invalidate cache for user {user_id}: {e}")

        return False

    async def search_user_enrollments(
            self,
            user_id: str,
            cookie_hash: str,
            query: str,
            limit: int = 10,
            session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """✅ OPTIMIZED: Search user enrollments using shared Redis connection"""
        # Fallback to cache-based text search
        cached_details = await self.get_full_details(user_id, cookie_hash)
        if not cached_details:
            logger.warning(f"No cached details available for search")
            return []

        try:
            from fuzzywuzzy import fuzz

            results = []
            query_lower = query.lower()

            # Search course enrollments
            for course in cached_details.course_enrollments:
                course_name = course.get('course_name', '').lower()
                if course_name:
                    ratio = fuzz.partial_ratio(query_lower, course_name)
                    if ratio > 60:  # 60% similarity threshold
                        course_data = course.copy()
                        course_data["match_score"] = ratio / 100.0
                        course_data["data_type"] = "course"
                        results.append(course_data)

            # Search event enrollments
            for event in cached_details.event_enrollments:
                event_name = event.get('event_name', '').lower()
                if event_name:
                    ratio = fuzz.partial_ratio(query_lower, event_name)
                    if ratio > 60:  # 60% similarity threshold
                        event_data = event.copy()
                        event_data["match_score"] = ratio / 100.0
                        event_data["data_type"] = "event"
                        results.append(event_data)

            # Sort by match score
            results.sort(key=lambda x: x.get("match_score", 0), reverse=True)

            logger.info(f"Cache text search found {len(results)} results for query: {query}")
            return results[:limit]

        except ImportError:
            logger.error("fuzzywuzzy not installed, cannot perform text search")
            return []
        except Exception as e:
            logger.error(f"Error in cache text search: {e}")
            return []

    async def get_cache_stats(self) -> Dict[str, Any]:
        """✅ OPTIMIZED: Get cache statistics using shared Redis connection"""
        redis_client = await self._get_redis()  # ✅ Uses shared connection

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
                "sample_keys": full_cache_keys[:10],  # Show first 10 keys as sample
                "session_service_connected": await self._check_session_service_health(),
                "connection_shared": True  # ✅ Indicates using shared connection
            }

        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {
                "error": str(e),
                "total_entries": 0,
                "default_ttl_minutes": self.default_ttl,
                "connection_shared": True
            }

    async def _check_session_service_health(self) -> bool:
        """Check if session service is healthy"""
        try:
            health = await redis_session_service.health_check()
            return health.get("status") == "healthy"
        except:
            return False

    async def health_check(self) -> Dict[str, Any]:
        """✅ OPTIMIZED: Health check using shared Redis connection and manager"""
        try:
            from utils.redis_connection_manager import get_redis_manager

            # Use shared connection manager's health check
            manager = await get_redis_manager()
            health_data = await manager.health_check()

            # Add cache-specific information
            health_data.update({
                "service": "ContentCache",
                "default_ttl_minutes": self.default_ttl,
                "key_prefix": self.key_prefix,
                "connection_type": "shared_pool"
            })

            return health_data

        except Exception as e:
            return {
                "status": "unhealthy",
                "service": "ContentCache",
                "error": str(e),
                "connection_type": "shared_pool"
            }

    # ✅ REMOVED: No longer needs shutdown method since using shared connections
    # The shared connection manager handles cleanup


# ✅ OPTIMIZED: Global cache instance with simplified initialization
user_cache = ContentCache(default_ttl_minutes=30)


# Enhanced convenience functions (no changes needed - they work with optimized cache)
async def get_cached_user_details(
        user_id: str,
        cookie: str,
        force_refresh: bool = False,
        session_id: Optional[str] = None,
        app_name: str = "adk_agent",
        channel: str = "web"
) -> Tuple[CachedUserDetails, bool]:
    """Get user details from cache or fetch fresh with session integration"""
    print("ContentCache: get_cached_user_details called")
    return await user_cache.contentcache_get_user_details(
        user_id, cookie, force_refresh, session_id, app_name, channel
    )


async def get_user_summary_for_session(user_id: str, cookie_hash: str) -> Optional[Dict[str, Any]]:
    """Get lightweight summary for session storage"""
    return await user_cache.get_summary_for_session(user_id, cookie_hash)


async def get_full_user_details_from_cache(user_id: str, cookie_hash: str) -> Optional[CachedUserDetails]:
    """Get full details from cache (for LLM context)"""
    return await user_cache.get_full_details(user_id, cookie_hash)


async def invalidate_user_cache(user_id: str, cookie_hash: str) -> bool:
    """Invalidate cache for user"""
    return await user_cache.invalidate_user_cache(user_id, cookie_hash)


async def search_user_enrollments(
        user_id: str,
        cookie_hash: str,
        query: str,
        limit: int = 10,
        session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Search user enrollments with text search"""
    return await user_cache.search_user_enrollments(user_id, cookie_hash, query, limit, session_id)


async def get_cache_statistics() -> Dict[str, Any]:
    """Get cache statistics"""
    return await user_cache.get_cache_stats()


async def get_cache_health() -> Dict[str, Any]:
    """Get cache health status"""
    return await user_cache.health_check()


# Enhanced context manager for LLM-optimized user details with session integration
class UserDetailsContext:
    """
    Enhanced context manager that provides optimized user details for LLM usage with session integration.
    Only loads full details when explicitly requested to minimize token usage.
    """

    def __init__(self, user_id: str, cookie_hash: str, session_id: Optional[str] = None):
        self.user_id = user_id
        self.cookie_hash = cookie_hash
        self.session_id = session_id
        self._full_details: Optional[CachedUserDetails] = None

    async def get_summary(self) -> Optional[Dict[str, Any]]:
        """Get lightweight summary (always safe for tokens)"""
        return await get_user_summary_for_session(self.user_id, self.cookie_hash)

    async def search_enrollments(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search enrollments using if session available"""
        return await search_user_enrollments(
            self.user_id, self.cookie_hash, query, limit, self.session_id
        )

    async def get_enrollment_context(self) -> str:
        """Get enrollment info as concise string for LLM context"""
        summary = await self.get_summary()
        if summary:
            enrollment_summary = summary.get('enrollment_summary', {})
            karma_points = enrollment_summary.get('karma_points', 0)
            courses_completed = enrollment_summary.get('total_courses_completed', 0)
            events_completed = enrollment_summary.get('total_events_completed', 0)

            return (f"User has {summary['course_count']} courses and {summary['event_count']} events enrolled. "
                    f"Karma Points: {karma_points}, Completed: {courses_completed} courses, {events_completed} events.")
        return "User enrollment details not available."

    async def get_progress_summary(self) -> str:
        """Get progress summary for LLM context"""
        full_details = await self.load_full_details()
        if full_details:
            course_stats = full_details.get_course_completion_stats()
            event_stats = full_details.get_event_completion_stats()
            time_stats = full_details.get_time_spent_summary()

            return (
                f"Progress: Courses - {course_stats['completed']} completed, {course_stats['in_progress']} in progress. "
                f"Events - {event_stats['completed']} completed, {event_stats['in_progress']} in progress. "
                f"Time spent: {time_stats['courses']}min on courses, {time_stats['events']}min on events.")
        return "Progress details not available."

    async def load_full_details(self) -> Optional[CachedUserDetails]:
        """Load full details only when needed (use sparingly due to token cost)"""
        if self._full_details is None:
            self._full_details = await get_full_user_details_from_cache(self.user_id, self.cookie_hash)
        return self._full_details

    async def get_course_titles(self, max_courses: int = 5) -> list:
        """Get limited course titles for LLM context"""
        full_details = await self.load_full_details()
        if full_details and full_details.course_enrollments:
            courses = []
            for course in full_details.course_enrollments[:max_courses]:
                title = course.get('course_name', 'Unknown Course')
                courses.append(title)
            return courses
        return []

    async def get_event_titles(self, max_events: int = 5) -> list:
        """Get limited event titles for LLM context"""
        full_details = await self.load_full_details()
        if full_details and full_details.event_enrollments:
            events = []
            for event in full_details.event_enrollments[:max_events]:
                title = event.get('event_name', 'Unknown Event')
                events.append(title)
            return events
        return []

    async def get_recent_completions(self, max_items: int = 3) -> Dict[str, list]:
        """Get recently completed courses and events"""
        full_details = await self.load_full_details()
        if not full_details:
            return {"courses": [], "events": []}

        recent_courses = []
        recent_events = []

        # Get recently completed courses
        for course in full_details.course_enrollments:
            if (course.get('course_completion_status') == 'completed' and
                    course.get('course_completed_on')):
                recent_courses.append({
                    "name": course.get('course_name', 'Unknown Course'),
                    "completed_on": course.get('course_completed_on'),
                    "certificate_id": course.get('issued_certificate_id')
                })

        # Get recently completed events
        for event in full_details.event_enrollments:
            if (event.get('event_completion_status') == 'completed' and
                    event.get('event_completed_on')):
                recent_events.append({
                    "name": event.get('event_name', 'Unknown Event'),
                    "completed_on": event.get('event_completed_on'),
                    "certificate_id": event.get('issued_certificate_id')
                })

        # Sort by completion date and limit
        recent_courses.sort(key=lambda x: x.get('completed_on', 0), reverse=True)
        recent_events.sort(key=lambda x: x.get('completed_on', 0), reverse=True)

        return {
            "courses": recent_courses[:max_items],
            "events": recent_events[:max_items]
        }