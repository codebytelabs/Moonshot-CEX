"""
Redis client wrapper for caching OHLCV, context, and watcher signals.
"""
import json
from typing import Any, Optional
from loguru import logger


class RedisClient:
    """Async Redis wrapper with JSON serialization and TTL support."""

    def __init__(self, url: str = "redis://localhost:6379/0", password: Optional[str] = None):
        self.url = url
        self.password = password
        self._client = None

    async def connect(self):
        """Initialize Redis connection."""
        try:
            import redis.asyncio as aioredis
            kwargs = {"decode_responses": True}
            if self.password:
                kwargs["password"] = self.password
            self._client = aioredis.from_url(self.url, **kwargs)
            await self._client.ping()
            logger.info(f"Redis connected: {self.url}")
        except Exception as e:
            logger.warning(f"Redis unavailable ({e}) — running without cache")
            self._client = None

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        if not self._client:
            return False
        try:
            await self._client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            logger.debug(f"Redis SET error [{key}]: {e}")
            return False

    async def get(self, key: str) -> Optional[Any]:
        if not self._client:
            return None
        try:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.debug(f"Redis GET error [{key}]: {e}")
            return None

    async def delete(self, key: str) -> bool:
        if not self._client:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception:
            return False

    async def cache_ohlcv(self, symbol: str, timeframe: str, candles: list, ttl: int = 240):
        await self.set(f"ohlcv:{symbol}:{timeframe}", candles, ttl=ttl)

    async def get_ohlcv(self, symbol: str, timeframe: str) -> Optional[list]:
        return await self.get(f"ohlcv:{symbol}:{timeframe}")

    async def cache_ticker(self, symbol: str, ticker: dict, ttl: int = 30):
        await self.set(f"ticker:{symbol}", ticker, ttl=ttl)

    async def get_ticker(self, symbol: str) -> Optional[dict]:
        return await self.get(f"ticker:{symbol}")

    @property
    def available(self) -> bool:
        return self._client is not None
