"""Redis caching service for query result caching, versioning, and proactive cache invalidation."""

import hashlib
import json
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.constants import REDIS_PROJECT_TASKS_CACHE_PREFIX


class CacheService:
    """Service providing JSON serialization, key versioning, and race-free cache invalidation."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    def _project_tasks_version_key(self, project_id: int) -> str:
        """Construct the Redis key tracking the current version of a project's tasks."""
        return f"{REDIS_PROJECT_TASKS_CACHE_PREFIX}:{project_id}:tasks:ver"

    async def get_project_tasks_version(self, project_id: int) -> int:
        """Retrieve current tasks cache version for a project, defaulting to 1."""
        try:
            raw_version = await self.client.get(self._project_tasks_version_key(project_id))
            if raw_version is not None:
                return int(raw_version)
        except (RedisError, ValueError, TypeError) as exc:
            logger.warning("Redis read failure for project {} tasks version: {}", project_id, exc)
        return 1

    async def bump_project_tasks_version(self, project_id: int) -> int:
        """Increment project tasks version, atomically invalidating all previous query results."""
        try:
            return int(await self.client.incr(self._project_tasks_version_key(project_id)))
        except RedisError as exc:
            logger.warning("Redis version increment failure for project {}: {}", project_id, exc)
            return 1

    def build_project_tasks_cache_key(
        self,
        project_id: int,
        version: int,
        page: int,
        limit: int,
        query_parts: dict[str, Any],
    ) -> str:
        """Construct a deterministic MD5-hashed cache key incorporating project ID, version, and query parts."""
        serialized_query = json.dumps(query_parts, sort_keys=True, default=str)
        query_hash = hashlib.md5(serialized_query.encode()).hexdigest()
        return (
            f"{REDIS_PROJECT_TASKS_CACHE_PREFIX}:{project_id}:tasks:"
            f"v_{version}:page_{page}_limit_{limit}:{query_hash}"
        )

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

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Serialize a dictionary or JSON-compatible value to Redis with a TTL."""
        try:
            effective_ttl = ttl if ttl is not None else get_settings().TASK_CACHE_TTL_SECONDS
            payload = json.dumps(value, default=str)
            await self.client.setex(key, effective_ttl, payload)
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
