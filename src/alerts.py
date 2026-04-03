"""
Alerts — Discord + Telegram push notifications with priority and rate limiting.
"""
import asyncio
import time
from typing import Optional
from loguru import logger
import httpx


class AlertManager:
    """Send alerts via Discord webhook and/or Telegram bot."""

    def __init__(
        self,
        discord_webhook: Optional[str] = None,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        self.discord_webhook = discord_webhook
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self._last_alert_time: dict[str, float] = {}
        self._rate_limit_seconds = {
            "low": 300,
            "medium": 60,
            "high": 15,
            "critical": 0,
        }

    async def send(self, message: str, priority: str = "medium"):
        """Send alert to all configured channels with rate limiting."""
        now = time.time()
        limit = self._rate_limit_seconds.get(priority, 60)
        key = f"{priority}:{message[:50]}"
        if key in self._last_alert_time and (now - self._last_alert_time[key]) < limit:
            return
        self._last_alert_time[key] = now

        prefix = {"low": "ℹ️", "medium": "⚡", "high": "⚠️", "critical": "🚨"}.get(priority, "")
        formatted = f"{prefix} **Moonshot-CEX**\n{message}"

        tasks = []
        if self.discord_webhook:
            tasks.append(self._send_discord(formatted))
        if self.telegram_token and self.telegram_chat_id:
            tasks.append(self._send_telegram(formatted))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_discord(self, message: str):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.discord_webhook, json={"content": message[:2000]})
                if resp.status_code not in (200, 204):
                    logger.warning(f"Discord alert failed ({resp.status_code})")
        except Exception as e:
            logger.error(f"Discord alert error: {e}")

    async def _send_telegram(self, message: str):
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={
                    "chat_id": self.telegram_chat_id,
                    "text": message[:4096],
                    "parse_mode": "Markdown",
                })
                if resp.status_code != 200:
                    logger.warning(f"Telegram alert failed ({resp.status_code})")
        except Exception as e:
            logger.error(f"Telegram alert error: {e}")
