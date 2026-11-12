"""Async Redis client and token blacklist management."""

from datetime import UTC, datetime

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.constants import REDIS_BLACKLIST_PREFIX
from app.core.exceptions import ServiceUnavailableException
from app.core.messages import ERROR_REDIS_UNAVAILABLE

settings = get_settings()

redis_client: Redis = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
    socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
)


async def ping_redis() -> None:
    """Verify Redis connectivity on startup for fail-fast readiness."""
    await redis_client.ping()


async def close_redis() -> None:
    """Close the shared async Redis connection pool."""
    await redis_client.aclose()


class TokenBlacklistService:
    """Service for blacklisting and checking revoked JWT token JTIs in Redis."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    async def blacklist_token(self, jti: str, exp_timestamp: int) -> None:
        """Add a token JTI to the Redis blacklist until its expiration time."""
        ttl = max(1, exp_timestamp - int(datetime.now(UTC).timestamp()))
        try:
            await self.client.setex(f"{REDIS_BLACKLIST_PREFIX}{jti}", ttl, "1")
        except RedisError as exc:
            logger.error("Redis blacklist write failed: {}", exc)
            raise ServiceUnavailableException(ERROR_REDIS_UNAVAILABLE) from exc

    async def is_blacklisted(self, jti: str) -> bool:
        """Return True if the given token JTI has been blacklisted."""
        try:
            exists = await self.client.exists(f"{REDIS_BLACKLIST_PREFIX}{jti}")
            return bool(exists)
        except RedisError as exc:
            logger.error("Redis blacklist lookup failed: {}", exc)
            raise ServiceUnavailableException(ERROR_REDIS_UNAVAILABLE) from exc
