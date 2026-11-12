"""Async Redis client and token blacklist management."""

from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.constants import REDIS_BLACKLIST_PREFIX

settings = get_settings()

redis_client: Redis = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
)


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
        await self.client.setex(f"{REDIS_BLACKLIST_PREFIX}{jti}", ttl, "1")

    async def is_blacklisted(self, jti: str) -> bool:
        """Return True if the given token JTI has been blacklisted."""
        exists = await self.client.exists(f"{REDIS_BLACKLIST_PREFIX}{jti}")
        return bool(exists)

