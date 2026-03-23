"""
Central configuration using Pydantic Settings.
Reads all environment variables from .env and provides typed, validated config.
"""
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """All configuration for Moonshot-CEX trading bot."""

    # ── Exchange ────────────────────────────────────────────────────────────
    exchange_name: str = Field(default="gateio", alias="EXCHANGE_NAME")
    exchange_mode: str = Field(default="paper", alias="EXCHANGE_MODE", description="paper | demo | live")

    gateio_api_key: Optional[str] = Field(default=None, alias="GATEIO_API_KEY")
    gateio_api_secret: Optional[str] = Field(default=None, alias="GATEIO_API_SECRET")

    gateio_testnet_api_key: Optional[str] = Field(default=None, alias="GATEIO_TESTNET_API_KEY")
    gateio_testnet_secret_key: Optional[str] = Field(default=None, alias="GATEIO_TESTNET_SECRET_KEY")
    gateio_testnet_url: str = Field(default="https://api-testnet.gateapi.io/api/v4", alias="GATEIO_TESTNET_URL_Endpoint")

    binance_api_key: Optional[str] = Field(default=None, alias="BINANCE_API_KEY")
    binance_api_secret: Optional[str] = Field(default=None, alias="BINANCE_API_SECRET")

    binance_demo_api_key: Optional[str] = Field(default=None, alias="BINANCE_DEMO_API_KEY")
    binance_demo_api_secret: Optional[str] = Field(default=None, alias="BINANCE_DEMO_API_SECRET")
    binance_demo_url: str = Field(default="https://demo-api.binance.com", alias="BINANCE_DEMO_URL")

    kucoin_api_key: Optional[str] = Field(default=None, alias="KUCOIN_API_KEY")
    kucoin_api_secret: Optional[str] = Field(default=None, alias="KUCOIN_API_SECRET")
    kucoin_passphrase: Optional[str] = Field(default=None, alias="KUCOIN_PASSPHRASE")

    # ── Database ────────────────────────────────────────────────────────────
    mongo_url: str = Field(default="mongodb://localhost:27017", alias="MONGO_URL")
    db_name: str = Field(default="moonshot_cex", alias="DB_NAME")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")

    # ── LLM ─────────────────────────────────────────────────────────────────
    llm_provider: str = Field(default="openrouter", alias="LLM_PROVIDER")
    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    # Accept both OPENROUTER_BASE_URL (set in .env) and legacy OPENROUTER_API_BASE_URL
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    # Primary chat model — used by ContextAgent and BigBrother
    openrouter_primary_model: str = Field(default="google/gemini-2.5-flash-lite-preview-09-2025", alias="OPENROUTER_MODEL")
    openrouter_secondary_model: str = Field(default="deepseek/deepseek-v3.2-exp", alias="OPENROUTER_SECONDARY_MODEL")
    openrouter_fallback_model: str = Field(default="google/gemini-2.5-flash-lite-preview-09-2025", alias="OPENROUTER_FALLBACK_MODEL")

    # ── Watcher ─────────────────────────────────────────────────────────────
    watcher_min_volume_24h_usd: float = Field(default=2_000_000.0, alias="WATCHER_MIN_VOLUME_24H_USD")
    watcher_top_n: int = Field(default=30, alias="WATCHER_TOP_N")  # was 20 — wider universe for dual-side

    # ── Analyzer ────────────────────────────────────────────────────────────
    analyzer_min_score: float = Field(default=40.0, alias="ANALYZER_MIN_SCORE")  # sideways=45, bear=50 after regime boost
    analyzer_top_n: int = Field(default=12, alias="ANALYZER_TOP_N")  # was 5 — need more pipeline for 6-10 positions
    analyzer_timeframes: List[str] = Field(default=["5m", "15m", "1h", "4h"], alias="ANALYZER_TIMEFRAMES")

    # ── Context Agent ────────────────────────────────────────────────────────
    context_agent_enabled: bool = Field(default=True, alias="CONTEXT_AGENT_ENABLED")
    context_cache_ttl: int = Field(default=900, alias="CONTEXT_CACHE_TTL")
    llm_macro_enabled: bool = Field(default=False, alias="LLM_MACRO_ENABLED")

    # ── Bayesian ────────────────────────────────────────────────────────────
    # Calibrated thresholds — each must be REACHABLE given priors 0.48-0.62.
    # CRITICAL: volatile/bear threshold must be HIGHER than normal, not lower.
    # Lower volatile threshold = easier to enter in bear = direct cause of bleeding.
    bayesian_threshold_normal: float = Field(default=0.45, alias="BAYESIAN_THRESHOLD_NORMAL")
    bayesian_threshold_volatile: float = Field(default=0.52, alias="BAYESIAN_THRESHOLD_VOLATILE")  # was 0.38 (inverted!)
    bayesian_threshold_safety: float = Field(default=0.58, alias="BAYESIAN_THRESHOLD_SAFETY")

    # ── Risk Management ─────────────────────────────────────────────────────
    max_positions: int = Field(default=3, alias="MAX_POSITIONS")
    max_portfolio_exposure_pct: float = Field(default=0.50, alias="MAX_PORTFOLIO_EXPOSURE_PCT")
    max_single_exposure_pct: float = Field(default=0.15, alias="MAX_SINGLE_EXPOSURE_PCT")
    max_risk_per_trade_pct: float = Field(default=0.08, alias="MAX_RISK_PER_TRADE_PCT")
    max_drawdown_pct: float = Field(default=0.15, alias="MAX_DRAWDOWN_PCT")
    daily_loss_limit_pct: float = Field(default=0.05, alias="DAILY_LOSS_LIMIT_PCT")
    max_daily_trades: int = Field(default=6, alias="MAX_DAILY_TRADES")
    consecutive_loss_threshold: int = Field(default=3, alias="CONSECUTIVE_LOSS_THRESHOLD")
    consecutive_loss_pause_minutes: int = Field(default=30, alias="CONSECUTIVE_LOSS_PAUSE_MINUTES")
    # DEPRECATED: initial_equity_usd is ignored at runtime.
    # Real equity is always fetched from the exchange before the swarm starts.
    # Keeping this field so .env files that set INITIAL_EQUITY_USD don't error.
    initial_equity_usd: float = Field(default=0.0, alias="INITIAL_EQUITY_USD")

    # ── Position Sizing ─────────────────────────────────────────────────────
    position_sizing_method: str = Field(default="half_kelly", alias="POSITION_SIZING_METHOD")
    kelly_fraction: float = Field(default=0.5, alias="KELLY_FRACTION")
    max_kelly_fraction: float = Field(default=0.40, alias="MAX_KELLY_FRACTION")                 # allow larger Kelly fractions
    min_trades_for_kelly: int = Field(default=10, alias="MIN_TRADES_FOR_KELLY")                 # Kelly kicks in after 10 trades

    # ── Exit Rules ──────────────────────────────────────────────────────────
    stop_loss_pct: float = Field(default=-6.0, alias="STOP_LOSS_PCT")
    trailing_stop_activate_pct: float = Field(default=5.0, alias="TRAILING_STOP_ACTIVATE_PCT")
    trailing_stop_distance_pct: float = Field(default=4.0, alias="TRAILING_STOP_DISTANCE_PCT")
    tier1_r_multiple: float = Field(default=2.0, alias="TIER1_R_MULTIPLE")
    tier1_exit_pct: float = Field(default=0.33, alias="TIER1_EXIT_PCT")
    tier2_r_multiple: float = Field(default=3.0, alias="TIER2_R_MULTIPLE")
    tier2_exit_pct: float = Field(default=0.25, alias="TIER2_EXIT_PCT")
    runner_trailing_stop_pct: float = Field(default=0.03, alias="RUNNER_TRAILING_STOP_PCT")
    time_exit_hours: float = Field(default=6.0, alias="TIME_EXIT_HOURS")  # was 4.0 — give winners room to run
    max_sell_retries: int = Field(default=3, alias="MAX_SELL_RETRIES")
    momentum_recheck_interval_minutes: int = Field(default=30, alias="MOMENTUM_RECHECK_INTERVAL_MINUTES")  # was 5 — stop the 15-min chop
    symbol_cooldown_minutes: float = Field(default=30.0, alias="SYMBOL_COOLDOWN_MINUTES")  # min wait before re-entering same symbol after any non-TP exit
    exit_limit_poll_seconds: int = Field(default=3, alias="EXIT_LIMIT_POLL_SECONDS")
    exit_limit_initial_markup_bps: float = Field(default=8.0, alias="EXIT_LIMIT_INITIAL_MARKUP_BPS")
    exit_limit_reprice_step_bps: float = Field(default=6.0, alias="EXIT_LIMIT_REPRICE_STEP_BPS")
    exit_limit_final_cross_bps: float = Field(default=2.0, alias="EXIT_LIMIT_FINAL_CROSS_BPS")

    # ── Pyramiding ──────────────────────────────────────────────────────────
    pyramid_enabled: bool = Field(default=True, alias="PYRAMID_ENABLED")
    pyramid_max_adds: int = Field(default=2, alias="PYRAMID_MAX_ADDS")
    pyramid_min_r_to_add: float = Field(default=1.5, alias="PYRAMID_MIN_R_TO_ADD")

    # ── Position Scaling ─────────────────────────────────────────────────────
    # When a signal fires for a symbol already held, scale instead of sell+rebuy.
    # If existing size is within ±N% of desired size → hold (no txn).
    # Outside that band → buy or sell only the delta.
    # Set to 0.0 to disable smart scaling (always re-enters as before).
    position_scale_tolerance_pct: float = Field(default=10.0, alias="POSITION_SCALE_TOLERANCE_PCT")

    # ── Regime ──────────────────────────────────────────────────────────────
    regime_detection_interval_cycles: int = Field(default=10, alias="REGIME_DETECTION_INTERVAL_CYCLES")
    regime_bull_threshold: float = Field(default=3.0, alias="REGIME_BULL_THRESHOLD")
    regime_bear_threshold: float = Field(default=-3.0, alias="REGIME_BEAR_THRESHOLD")

    # ── Quant Mutator ────────────────────────────────────────────────────────
    quant_mutator_every_n_cycles: int = Field(default=5, alias="QUANT_MUTATOR_EVERY_N_CYCLES")
    mutator_high_win_rate: float = Field(default=0.65, alias="MUTATOR_HIGH_WIN_RATE")
    mutator_low_win_rate: float = Field(default=0.40, alias="MUTATOR_LOW_WIN_RATE")
    mutator_min_closed_trades: int = Field(default=5, alias="MUTATOR_MIN_CLOSED_TRADES")
    mutator_score_raise_step: float = Field(default=5.0, alias="MUTATOR_SCORE_RAISE_STEP")
    mutator_score_lower_step: float = Field(default=3.0, alias="MUTATOR_SCORE_LOWER_STEP")
    mutator_min_score_floor: float = Field(default=35.0, alias="MUTATOR_MIN_SCORE_FLOOR")  # raised from 15 — score can never drop below meaningful threshold
    mutator_min_score_ceiling: float = Field(default=60.0, alias="MUTATOR_MIN_SCORE_CEILING")

    # ── Timing ──────────────────────────────────────────────────────────────
    cycle_interval_seconds: int = Field(default=30, alias="SWARM_CYCLE_INTERVAL_SECONDS")
    network_error_wait_seconds: int = Field(default=45, alias="NETWORK_ERROR_WAIT_SECONDS")

    # ── Alerts ──────────────────────────────────────────────────────────────
    discord_webhook: Optional[str] = Field(default=None, alias="DISCORD_WEBHOOK")
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # ── Server ──────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
