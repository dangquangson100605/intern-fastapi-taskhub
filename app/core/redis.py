"""Redis connection and token blacklist management.

Provides async Redis client and token blacklist functions with graceful fallback.
"""

import redis.asyncio as aioredis
from loguru import logger
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import get_settings

settings = get_settings()

# Global async Redis client
redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    socket_timeout=2.0,
    socket_connect_timeout=2.0,
)

# In-memory fallback if Redis is unreachable in local dev environment
_in_memory_blacklist: set[str] = set()


async def add_token_to_blacklist(token: str, expire_seconds: int = 604800) -> None:
    """Store a revoked token in Redis blacklist with a TTL (default 7 days)."""
    key = f"token_blacklist:{token}"
    try:
        await redis_client.set(key, "revoked", ex=max(expire_seconds, 1))
        logger.debug("Token added to Redis blacklist: key={}", key)
    except (RedisConnectionError, RedisTimeoutError, OSError) as e:
        logger.warning("Redis unavailable ({}), falling back to in-memory blacklist", e)
        _in_memory_blacklist.add(token)


async def is_token_blacklisted(token: str) -> bool:
    """Check if a token has been revoked / blacklisted."""
    key = f"token_blacklist:{token}"
    try:
        exists = await redis_client.exists(key)
        return bool(exists)
    except (RedisConnectionError, RedisTimeoutError, OSError) as e:
        logger.warning("Redis unavailable ({}), checking in-memory blacklist", e)
        return token in _in_memory_blacklist


async def close_redis() -> None:
    """Close Redis client connection pool."""
    try:
        await redis_client.aclose()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.warning("Error closing Redis connection: {}", e)
