"""
ContextAgent — LLM-powered market intelligence.
Enriches technical setups with real-time sentiment, catalysts, and risk factors
via OpenRouter (Perplexity Sonar Pro for live web search).
"""
import asyncio
import json
import time
from typing import Optional
from loguru import logger
import httpx

from .redis_client import RedisClient
from .metrics import signals_generated, errors_total


class ContextAgent:
    """LLM market intelligence enrichment agent."""

    def __init__(
        self,
        openrouter_api_key: str,
        model: str = "perplexity/sonar-pro-search",
        base_url: str = "https://openrouter.ai/api/v1",
        redis: Optional[RedisClient] = None,
        cache_ttl: int = 900,
        batch_size: int = 5,
        enabled: bool = True,
    ):
        self.api_key = openrouter_api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.redis = redis
        self.cache_ttl = cache_ttl
        self.batch_size = batch_size
        self.enabled = enabled
        self._call_count = 0
        self._cache_hits = 0

    async def enrich(self, setups: list[dict]) -> list[dict]:
        """
        Enrich setups with LLM market context.
        Returns the same list with 'context' key added to each setup.
        """
        if not self.enabled or not self.api_key:
            return [dict(s, context=_neutral_context(s["symbol"])) for s in setups]

        symbols = [s["symbol"] for s in setups]
        contexts = await self._batch_get_contexts(symbols)

        enriched = []
        for setup in setups:
            ctx = contexts.get(setup["symbol"], _neutral_context(setup["symbol"]))
            enriched.append(dict(setup, context=ctx))

        signals_generated.labels(agent="context").inc(len(enriched))
        return enriched

    async def _batch_get_contexts(self, symbols: list[str]) -> dict:
        """Fetch contexts for all symbols, using cache where available."""
        results = {}
        to_fetch = []

        for symbol in symbols:
            if self.redis:
                cached = await self.redis.get(f"context:{symbol}")
                if cached:
                    results[symbol] = cached
                    self._cache_hits += 1
                    continue
            to_fetch.append(symbol)

        if to_fetch:
            for i in range(0, len(to_fetch), self.batch_size):
                batch = to_fetch[i : i + self.batch_size]
                batch_results = await self._call_llm_batch(batch)
                for sym, ctx in batch_results.items():
                    results[sym] = ctx
                    if self.redis:
                        await self.redis.set(f"context:{sym}", ctx, ttl=self.cache_ttl)

        return results

    async def _call_llm_batch(self, symbols: list[str]) -> dict:
        """Call LLM API for a batch of symbols."""
        symbol_list = ", ".join(symbols)
        prompt = f"""Analyze the current market conditions for these crypto trading pairs: {symbol_list}

For each symbol, provide a brief JSON response with these exact fields:
- sentiment: "bullish", "bearish", or "neutral"  
- confidence: float 0.0-1.0
- catalysts: list of up to 3 positive drivers
- risks: list of up to 2 risk factors
- driver_type: "narrative", "technical", "fundamental", "whale", or "unknown"
- summary: one sentence max

Respond ONLY with a valid JSON object where each key is the symbol and value is the analysis object.
Example: {{"BTC/USDT": {{"sentiment": "bullish", "confidence": 0.7, "catalysts": ["ETF inflows"], "risks": ["rate hike"], "driver_type": "fundamental", "summary": "Institutional demand driving price."}}}}"""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://moonshot-cex.ai",
                        "X-Title": "Moonshot-CEX",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 800,
                        "temperature": 0.1,
                    },
                )

                if resp.status_code != 200:
                    logger.warning(f"[Context] LLM call failed: HTTP {resp.status_code}")
                    errors_total.labels(component="context_agent", error_type="llm_http_error").inc()
                    return {sym: _neutral_context(sym) for sym in symbols}

                data = resp.json()
                self._call_count += 1
                raw_text = data["choices"][0]["message"]["content"].strip()

                parsed = _extract_json(raw_text)
                if not parsed:
                    logger.warning("[Context] Failed to parse LLM JSON response")
                    return {sym: _neutral_context(sym) for sym in symbols}

                results = {}
                for sym in symbols:
                    if sym in parsed:
                        ctx = _validate_context(sym, parsed[sym])
                    else:
                        ctx = _neutral_context(sym)
                    results[sym] = ctx
                return results

        except Exception as e:
            logger.error(f"[Context] LLM call error: {e}")
            errors_total.labels(component="context_agent", error_type="exception").inc()
            return {sym: _neutral_context(sym) for sym in symbols}

    def get_stats(self) -> dict:
        return {
            "api_calls": self._call_count,
            "cache_hits": self._cache_hits,
            "enabled": self.enabled,
            "model": self.model,
        }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _neutral_context(symbol: str) -> dict:
    return {
        "sentiment": "neutral",
        "confidence": 0.5,
        "catalysts": [],
        "risks": [],
        "driver_type": "unknown",
        "summary": f"No context available for {symbol}.",
    }


def _validate_context(symbol: str, raw: dict) -> dict:
    sentiment = raw.get("sentiment", "neutral")
    if sentiment not in ("bullish", "bearish", "neutral"):
        sentiment = "neutral"
    confidence = float(raw.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    return {
        "sentiment": sentiment,
        "confidence": confidence,
        "catalysts": raw.get("catalysts", [])[:3],
        "risks": raw.get("risks", [])[:2],
        "driver_type": raw.get("driver_type", "unknown"),
        "summary": str(raw.get("summary", ""))[:200],
    }


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
