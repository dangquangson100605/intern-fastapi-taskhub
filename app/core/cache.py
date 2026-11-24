"""Redis caching service for query result caching and proactive cache invalidation."""

import hashlib
import json
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

DEFAULT_CACHE_TTL: int = 300


class CacheService:
    """Service providing JSON serialization, key generation, and non-blocking invalidation."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    def build_project_tasks_cache_key(
        self,
        project_id: int,
        page: int,
        limit: int,
        query_parts: dict[str, Any],
    ) -> str:
        """Construct a deterministic MD5-hashed cache key for a specific query combination."""
        serialized_query = json.dumps(query_parts, sort_keys=True, default=str)
        query_hash = hashlib.md5(serialized_query.encode()).hexdigest()
        return f"cache:project:{project_id}:tasks:page_{page}_limit_{limit}:{query_hash}"

    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve and deserialize a JSON cached dictionary from Redis."""
        try:
            cached_raw = await self.client.get(key)
            if cached_raw is None:
                return None
            parsed = json.loads(cached_raw)
            if isinstance(parsed, dict):
                return parsed
            return None
        except (RedisError, json.JSONDecodeError) as exc:
            logger.warning("Redis cache read failure for key '{}': {}", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int = DEFAULT_CACHE_TTL) -> bool:
        """Serialize a dictionary or JSON-compatible value to Redis with a TTL."""
        try:
            payload = json.dumps(value, default=str)
            await self.client.setex(key, ttl, payload)
            return True
        except (RedisError, TypeError) as exc:
            logger.warning("Redis cache write failure for key '{}': {}", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """Delete a single cache key."""
        try:
            deleted = await self.client.delete(key)
            return bool(deleted > 0)
        except RedisError as exc:
            logger.warning("Redis cache delete failure for key '{}': {}", key, exc)
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Scan and asynchronously unlink all keys matching the specified pattern."""
        deleted_count = 0
        try:
            keys_to_unlink: list[str] = []
            async for matched_key in self.client.scan_iter(match=pattern, count=100):
                keys_to_unlink.append(matched_key)

            if keys_to_unlink:
                deleted_count = await self.client.unlink(*keys_to_unlink)
        except RedisError as exc:
            logger.warning("Redis cache invalidation failure for pattern '{}': {}", pattern, exc)
        return deleted_count

    async def invalidate_project_tasks(self, project_id: int) -> int:
        """Invalidate all cached task queries for a specific project."""
        return await self.invalidate_pattern(f"cache:project:{project_id}:tasks:*")
