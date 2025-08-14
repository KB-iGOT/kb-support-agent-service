# utils/redis_connection_manager.py - MINIMAL COMPATIBLE VERSION
import asyncio
import logging
import os
import time
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis, ConnectionPool
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


class RedisConnectionManager:
    """
    Minimal Redis connection manager for maximum compatibility.
    Implements singleton pattern to ensure only one connection pool exists.
    """

    _instance: Optional['RedisConnectionManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> 'RedisConnectionManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Prevent re-initialization of singleton
        if hasattr(self, '_initialized'):
            return

        self.redis_host = os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = int(os.getenv('REDIS_PORT', 6379))
        self.redis_url = f"redis://{self.redis_host}:{self.redis_port}"

        # ✅ MINIMAL: Basic connection pool configuration only
        self.max_connections = int(os.getenv('REDIS_MAX_CONNECTIONS', '20'))

        # Connection pool and clients
        self._connection_pool: Optional[ConnectionPool] = None
        self._redis_client: Optional[Redis] = None
        self._connection_stats = {
            'total_connections_created': 0,
            'current_connections': 0,
            'failed_connections': 0,
            'last_health_check': 0,
            'pool_created_at': 0
        }
        self._initialized = True

        logger.info(f"RedisConnectionManager initialized - URL: {self.redis_url}")

    async def _create_connection_pool(self) -> ConnectionPool:
        """Create minimal Redis connection pool for maximum compatibility."""
        try:
            # ✅ ULTRA-MINIMAL: Only the most basic parameters
            pool = ConnectionPool.from_url(
                self.redis_url,
                max_connections=self.max_connections,
                decode_responses=True,
            )

            self._connection_stats['pool_created_at'] = time.time()
            self._connection_stats['total_connections_created'] += 1

            logger.info(f"✅ Redis connection pool created - Max connections: {self.max_connections}")
            return pool

        except Exception as e:
            self._connection_stats['failed_connections'] += 1
            logger.error(f"❌ Failed to create Redis connection pool: {e}")
            raise

    async def get_redis_client(self) -> Redis:
        """
        Get Redis client with shared connection pool (thread-safe).
        Uses double-checked locking pattern for optimal performance.
        """
        if self._redis_client is not None:
            return self._redis_client

        async with self._lock:
            # Double-check after acquiring lock
            if self._redis_client is not None:
                return self._redis_client

            try:
                # Create connection pool if it doesn't exist
                if self._connection_pool is None:
                    self._connection_pool = await self._create_connection_pool()

                # Create Redis client with shared pool
                self._redis_client = Redis(connection_pool=self._connection_pool)

                # Test connection
                await self._test_connection()

                logger.info("✅ Redis client created successfully with shared connection pool")
                return self._redis_client

            except Exception as e:
                logger.error(f"❌ Failed to create Redis client: {e}")
                # Cleanup on failure
                await self._cleanup_failed_connection()
                raise

    async def _test_connection(self) -> None:
        """Test Redis connection with timeout."""
        try:
            start_time = time.time()
            await asyncio.wait_for(self._redis_client.ping(), timeout=5.0)
            response_time = (time.time() - start_time) * 1000

            self._connection_stats['last_health_check'] = time.time()
            logger.info(f"✅ Redis connection test successful - Response time: {response_time:.2f}ms")

        except asyncio.TimeoutError:
            raise redis.ConnectionError("Redis connection test timeout")
        except Exception as e:
            raise redis.ConnectionError(f"Redis connection test failed: {e}")

    async def _cleanup_failed_connection(self) -> None:
        """Cleanup failed connection attempts."""
        if self._redis_client:
            try:
                await self._redis_client.close()
            except:
                pass
            self._redis_client = None

        if self._connection_pool:
            try:
                await self._connection_pool.disconnect()
            except:
                pass
            self._connection_pool = None

    @asynccontextmanager
    async def get_connection(self):
        """
        Context manager for getting Redis connections.
        """
        client = await self.get_redis_client()
        try:
            yield client
        except Exception as e:
            logger.error(f"Error in Redis operation: {e}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """Basic health check with connection statistics."""
        try:
            start_time = time.time()
            client = await self.get_redis_client()

            # Test basic operations
            await client.ping()
            test_key = f"health_check_{int(time.time())}"
            await client.set(test_key, "ok", ex=1)
            result = await client.get(test_key)
            await client.delete(test_key)

            response_time = (time.time() - start_time) * 1000

            # Get Redis info safely
            redis_info = {}
            try:
                redis_info = await client.info()
            except Exception as info_error:
                logger.warning(f"Could not retrieve Redis server info: {info_error}")

            # Update stats
            self._connection_stats['last_health_check'] = time.time()
            self._connection_stats['current_connections'] = redis_info.get('connected_clients', 0)

            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "redis_url": self.redis_url,
                "connection_pool_size": self.max_connections,
                "current_connections": self._connection_stats['current_connections'],
                "redis_memory_used": redis_info.get('used_memory_human', 'Unknown'),
                "redis_version": redis_info.get('redis_version', 'Unknown'),
                "uptime_seconds": redis_info.get('uptime_in_seconds', 0),
                "connection_stats": self._connection_stats.copy(),
                "test_result": "ok" if result == "ok" else "failed",
                "compatibility_mode": "minimal"
            }

        except Exception as e:
            self._connection_stats['failed_connections'] += 1
            return {
                "status": "unhealthy",
                "error": str(e),
                "redis_url": self.redis_url,
                "connection_stats": self._connection_stats.copy(),
                "compatibility_mode": "minimal"
            }

    async def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        try:
            client = await self.get_redis_client()
            redis_info = {}

            try:
                redis_info = await client.info()
            except Exception as info_error:
                logger.warning(f"Could not retrieve Redis server info: {info_error}")

            return {
                "connection_manager_stats": self._connection_stats.copy(),
                "redis_server_stats": {
                    "connected_clients": redis_info.get('connected_clients', 0),
                    "total_connections_received": redis_info.get('total_connections_received', 0),
                    "used_memory_human": redis_info.get('used_memory_human', 'Unknown'),
                    "keyspace_hits": redis_info.get('keyspace_hits', 0),
                    "keyspace_misses": redis_info.get('keyspace_misses', 0),
                    "redis_version": redis_info.get('redis_version', 'Unknown'),
                },
                "compatibility_mode": "minimal"
            }

        except Exception as e:
            logger.error(f"Error getting connection stats: {e}")
            return {
                "error": str(e),
                "compatibility_mode": "minimal"
            }

    async def close(self) -> None:
        """Gracefully close Redis connections and cleanup resources."""
        async with self._lock:
            try:
                if self._redis_client:
                    await self._redis_client.close()
                    logger.info("✅ Redis client closed")

                if self._connection_pool:
                    await self._connection_pool.disconnect()
                    logger.info("✅ Redis connection pool disconnected")

                self._redis_client = None
                self._connection_pool = None

                logger.info("✅ Redis connection manager shutdown complete")

            except Exception as e:
                logger.error(f"❌ Error during Redis connection cleanup: {e}")

    @classmethod
    async def get_instance(cls) -> 'RedisConnectionManager':
        """Get singleton instance of RedisConnectionManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    async def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        if cls._instance:
            await cls._instance.close()
        cls._instance = None


# Global singleton instance
_redis_manager: Optional[RedisConnectionManager] = None


async def get_redis_manager() -> RedisConnectionManager:
    """Get the global Redis connection manager instance."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisConnectionManager()
    return _redis_manager


async def get_redis_client() -> Redis:
    """Convenience function to get Redis client."""
    try:
        manager = await get_redis_manager()
        return await manager.get_redis_client()
    except Exception as e:
        logger.error(f"❌ Failed to get Redis client: {e}")
        raise


async def redis_health_check() -> Dict[str, Any]:
    """Convenience function for Redis health check."""
    try:
        manager = await get_redis_manager()
        return await manager.health_check()
    except Exception as e:
        logger.error(f"❌ Redis health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "compatibility_mode": "minimal"
        }


async def cleanup_redis_connections() -> None:
    """Cleanup Redis connections on application shutdown."""
    global _redis_manager
    if _redis_manager:
        try:
            await _redis_manager.close()
            _redis_manager = None
            logger.info("✅ Redis connections cleaned up successfully")
        except Exception as e:
            logger.error(f"❌ Error during Redis cleanup: {e}")
    else:
        logger.info("ℹ️ No Redis connections to clean up")