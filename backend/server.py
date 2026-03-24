"""
Moonshot-CEX — FastAPI backend + autonomous trading swarm.
All agents are initialized here and run in a background async loop.
"""
import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorClient
from prometheus_client import generate_latest

# ── Path setup so src/ is importable ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.logger import setup_logging
from src.redis_client import RedisClient
from src.exchange_ccxt import ExchangeConnector
from src.watcher import WatcherAgent
from src.analyzer import AnalyzerAgent
from src.context_agent import ContextAgent
from src.bayesian_engine import BayesianDecisionEngine
from src.execution_core import ExecutionCore
from src.position_manager import PositionManager
from src.risk_manager import RiskManager
from src.quant_mutator import QuantMutator
from src.bigbrother import BigBrotherAgent
from src.alerts import AlertManager
from src.metrics import account_equity, portfolio_value
from src.performance_tracker import PerformanceTracker

# ── Global state ──────────────────────────────────────────────────────────────
cfg = get_settings()
setup_logging(debug=cfg.log_level == "DEBUG", log_file=cfg.log_level and "backend/backend.log" or "backend/backend.log")

STATE: dict = {
    "running": False,
    "paused": False,
    "emergency_stop": False,
    "cycle_count": 0,
    "mode": "paper",
    "regime": "sideways",
    "regime_params": {},
    # NOTE: 0.0 = equity not yet known. Will be set from exchange at startup.
    # NEVER use a hardcoded value here — position sizing must be based on real account size.
    "current_equity": 0.0,
    "peak_equity": 0.0,
    "day_pnl_usd": 0.0,
    "day_pnl_pct": 0.0,
    "total_pnl_usd": 0.0,
    "_cb_day_start_equity": 0.0,
    "_cb_day_date": "",
    "last_cycle_at": 0,
    "last_watcher_candidates": [],
    "last_setups": [],
    "last_decisions": [],
    "recent_events": [],
    "start_time": 0.0,
    "equity_history": [],
}

_ws_clients: list[WebSocket] = []
_mongo_client: Optional[AsyncIOMotorClient] = None
_db = None

# ── Agent instances (set in lifespan) ────────────────────────────────────────
_exchange: Optional[ExchangeConnector] = None
_redis: Optional[RedisClient] = None
_watcher: Optional[WatcherAgent] = None
_analyzer: Optional[AnalyzerAgent] = None
_context: Optional[ContextAgent] = None
_bayesian: Optional[BayesianDecisionEngine] = None
_execution: Optional[ExecutionCore] = None
_position_manager: Optional[PositionManager] = None
_risk_manager: Optional[RiskManager] = None
_quant_mutator: Optional[QuantMutator] = None
_bigbrother: Optional[BigBrotherAgent] = None
_alerts: Optional[AlertManager] = None
_min_score_live: float = cfg.analyzer_min_score
_bayesian_threshold_live: float = cfg.bayesian_threshold_normal
_swarm_task: Optional[asyncio.Task] = None
_consecutive_zero_setups: int = 0  # cycles with 0 setups; drought relief triggers at 200


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    yield
    await _shutdown()


async def _startup():
    global _mongo_client, _db, _exchange, _redis, _watcher, _analyzer, _context
    global _bayesian, _execution, _position_manager, _risk_manager, _quant_mutator
    global _bigbrother, _alerts, _swarm_task

    logger.info("=" * 60)
    logger.info("  MOONSHOT-CEX  starting up")
    logger.info(f"  Exchange: {cfg.exchange_name} | Mode: {cfg.exchange_mode}")
    logger.info(f"  Initial equity: ${cfg.initial_equity_usd:,.2f}")
    logger.info("=" * 60)

    # MongoDB
    _mongo_client = AsyncIOMotorClient(cfg.mongo_url)
    _db = _mongo_client[cfg.db_name]
    logger.info(f"MongoDB connected: {cfg.mongo_url} db={cfg.db_name}")

    # Redis
    _redis = RedisClient(cfg.redis_url, cfg.redis_password)
    await _redis.connect()

    # Alerts
    _alerts = AlertManager(
        discord_webhook=cfg.discord_webhook,
        telegram_token=cfg.telegram_bot_token,
        telegram_chat_id=cfg.telegram_chat_id,
    )

    # Exchange connector
    _exchange = _build_exchange()
    await _exchange.initialize()

    # Agents
    _watcher = WatcherAgent(
        exchange=_exchange,
        redis=_redis,
        min_volume_24h_usd=cfg.watcher_min_volume_24h_usd,
        top_n=cfg.watcher_top_n,
    )
    _analyzer = AnalyzerAgent(
        exchange=_exchange,
        redis=_redis,
        timeframes=cfg.analyzer_timeframes,
        min_score=cfg.analyzer_min_score,
        top_n=cfg.analyzer_top_n,
    )
    _context = ContextAgent(
        openrouter_api_key=cfg.openrouter_api_key or "",
        model=cfg.openrouter_primary_model,   # Gemini Flash — works with standard chat API
        base_url=cfg.openrouter_base_url,
        redis=_redis,
        cache_ttl=cfg.context_cache_ttl,
        enabled=cfg.context_agent_enabled and bool(cfg.openrouter_api_key),
    )
    _bayesian = BayesianDecisionEngine(
        mode="normal",
        threshold_normal=cfg.bayesian_threshold_normal,
        threshold_volatile=cfg.bayesian_threshold_volatile,
        threshold_safety=cfg.bayesian_threshold_safety,
    )
    _execution = ExecutionCore(
        exchange=_exchange,
        exchange_mode=cfg.exchange_mode,
        max_retries=cfg.max_sell_retries,
    )
    _position_manager = PositionManager(
        execution=_execution,
        trailing_activate_pct=cfg.trailing_stop_activate_pct,
        trailing_distance_pct=cfg.trailing_stop_distance_pct,
        tier1_exit_pct=cfg.tier1_exit_pct,
        tier2_exit_pct=cfg.tier2_exit_pct,
        time_exit_hours=cfg.time_exit_hours,
        pyramid_enabled=cfg.pyramid_enabled,
        pyramid_max_adds=cfg.pyramid_max_adds,
        pyramid_min_r=cfg.pyramid_min_r_to_add,
        max_sell_retries=cfg.max_sell_retries,
        stop_loss_pct=cfg.stop_loss_pct,
        momentum_recheck_interval_minutes=cfg.momentum_recheck_interval_minutes,
        symbol_cooldown_minutes=cfg.symbol_cooldown_minutes,
    )
    _risk_manager = RiskManager(
        max_positions=cfg.max_positions,
        max_portfolio_exposure_pct=cfg.max_portfolio_exposure_pct,
        max_single_exposure_pct=cfg.max_single_exposure_pct,
        max_risk_per_trade_pct=cfg.max_risk_per_trade_pct,
        max_drawdown_pct=cfg.max_drawdown_pct,
        daily_loss_limit_pct=cfg.daily_loss_limit_pct,
        consecutive_loss_threshold=cfg.consecutive_loss_threshold,
        consecutive_loss_pause_minutes=cfg.consecutive_loss_pause_minutes,
        kelly_fraction=cfg.kelly_fraction,
        max_kelly_fraction=cfg.max_kelly_fraction,
        min_trades_for_kelly=cfg.min_trades_for_kelly,
        max_daily_trades=cfg.max_daily_trades,
        # Pass 0.0 — will be overridden with real exchange equity during startup.
        # This prevents the risk manager from using a stale/config-defined equity value.
        initial_equity=0.0,
    )
    _quant_mutator = QuantMutator(
        every_n_cycles=cfg.quant_mutator_every_n_cycles,
        high_win_rate=cfg.mutator_high_win_rate,
        low_win_rate=cfg.mutator_low_win_rate,
        min_closed_trades=cfg.mutator_min_closed_trades,
        score_raise_step=cfg.mutator_score_raise_step,
        score_lower_step=cfg.mutator_score_lower_step,
        min_score_floor=cfg.mutator_min_score_floor,
        min_score_ceiling=cfg.mutator_min_score_ceiling,
    )
    _bigbrother = BigBrotherAgent(
        risk_manager=_risk_manager,
        bayesian_engine=_bayesian,
        alerts=_alerts,
        openrouter_api_key=cfg.openrouter_api_key,
        openrouter_base_url=cfg.openrouter_base_url,
        openrouter_model=cfg.openrouter_primary_model,
        llm_macro_enabled=cfg.llm_macro_enabled,
        regime_detection_interval_cycles=cfg.regime_detection_interval_cycles,
        bull_threshold=cfg.regime_bull_threshold,
        bear_threshold=cfg.regime_bear_threshold,
        max_drawdown_pct=cfg.max_drawdown_pct,
        daily_loss_limit_pct=cfg.daily_loss_limit_pct,
        stop_loss_pct=cfg.stop_loss_pct,
        trailing_activate_pct=cfg.trailing_stop_activate_pct,
        trailing_distance_pct=cfg.trailing_stop_distance_pct,
        time_exit_hours=cfg.time_exit_hours,
    )

    STATE["mode"] = cfg.exchange_mode
    STATE["start_time"] = time.time()

    # ── Fetch real account equity — REQUIRED before trading starts ──────────
    # Retry up to 5 times with 3s backoff. Do NOT start the swarm if equity
    # is unknown — all position sizing would be wrong on a $0 base.
    equity_fetched = False
    for attempt in range(1, 6):
        try:
            await _update_equity()
            eq = STATE["current_equity"]
            if eq > 0:
                _risk_manager.peak_equity = eq
                _risk_manager._day_start_equity = eq
                STATE["peak_equity"] = eq
                # v3.1: detect account size tier — sets Kelly fraction + per-tier caps
                tier = _risk_manager.detect_account_tier(eq)
                STATE["account_tier"] = tier
                logger.info(f"[Startup] Real account equity fetched: ${eq:,.2f} (attempt {attempt}) | tier={tier}")
                equity_fetched = True
                break
            else:
                logger.warning(f"[Startup] Equity fetch returned 0 (attempt {attempt}/5), retrying...")
        except Exception as e:
            logger.warning(f"[Startup] Equity fetch error (attempt {attempt}/5): {e}")
        if attempt < 5:
            await asyncio.sleep(3)

    if not equity_fetched:
        # Use paper balance as absolute last resort so bot can still function
        fallback = float(cfg.paper_balance_usd) if hasattr(cfg, "paper_balance_usd") else 1000.0
        STATE["current_equity"] = fallback
        STATE["peak_equity"] = fallback
        _risk_manager.peak_equity = fallback
        _risk_manager._day_start_equity = fallback
        logger.error(
            f"[Startup] Could not fetch real equity after 5 attempts. "
            f"Using paper_balance_usd=${fallback:,.2f} as fallback. "
            f"Bot will retry equity update each cycle."
        )

    # ── Crash Recovery: reload open positions from MongoDB ─────────────────
    await _recover_positions_from_db()

    # Auto-start swarm
    _swarm_task = asyncio.create_task(_swarm_loop())
    STATE["running"] = True
    logger.info("Swarm started automatically.")

    await _alerts.send(
        f"Moonshot-CEX started | exchange={cfg.exchange_name} | mode={cfg.exchange_mode}",
        priority="medium",
    )


async def _shutdown():
    global _swarm_task
    STATE["running"] = False
    if _swarm_task and not _swarm_task.done():
        _swarm_task.cancel()
        try:
            await _swarm_task
        except asyncio.CancelledError:
            pass
    if _exchange:
        await _exchange.close()
    if _redis:
        await _redis.close()
    if _mongo_client:
        _mongo_client.close()
    logger.info("Moonshot-CEX shutdown complete.")


def _build_exchange() -> ExchangeConnector:
    name = cfg.exchange_name
    mode = cfg.exchange_mode

    if name == "gateio":
        if mode == "demo":
            return ExchangeConnector(
                name="gateio",
                api_key=cfg.gateio_testnet_api_key,
                api_secret=cfg.gateio_testnet_secret_key,
                demo_url=cfg.gateio_testnet_url,
            )
        else:
            return ExchangeConnector(
                name="gateio",
                api_key=cfg.gateio_api_key if mode == "live" else None,
                api_secret=cfg.gateio_api_secret if mode == "live" else None,
            )
    elif name == "binance":
        if mode == "demo":
            return ExchangeConnector(
                name="binance",
                api_key=cfg.binance_demo_api_key,
                api_secret=cfg.binance_demo_api_secret,
                demo_url=cfg.binance_demo_url,
            )
        else:
            return ExchangeConnector(
                name="binance",
                api_key=cfg.binance_api_key if mode == "live" else None,
                api_secret=cfg.binance_api_secret if mode == "live" else None,
            )
    elif name == "kucoin":
        extra = {}
        if cfg.kucoin_passphrase:
            extra["password"] = cfg.kucoin_passphrase
        return ExchangeConnector(
            name="kucoin",
            api_key=cfg.kucoin_api_key if mode == "live" else None,
            api_secret=cfg.kucoin_api_secret if mode == "live" else None,
            extra=extra if extra else None,
        )
    else:
        raise ValueError(f"Unknown exchange: {name}")


# ── Swarm trading loop ────────────────────────────────────────────────────────
async def _swarm_loop():
    global _min_score_live, _bayesian_threshold_live

    logger.info("[Swarm] Loop started.")
    while STATE["running"]:
        if STATE["paused"] or STATE["emergency_stop"]:
            await asyncio.sleep(5)
            continue

        t0 = time.monotonic()
        try:
            await _run_cycle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Swarm] Cycle error: {e}")
            await asyncio.sleep(cfg.network_error_wait_seconds)
            continue

        elapsed = time.monotonic() - t0
        sleep_time = max(0, cfg.cycle_interval_seconds - elapsed)
        await asyncio.sleep(sleep_time)

    logger.info("[Swarm] Loop ended.")


async def _run_cycle():
    global _min_score_live, _bayesian_threshold_live, _consecutive_zero_setups

    STATE["cycle_count"] += 1
    cycle = STATE["cycle_count"]
    trace = {"cycle": cycle, "steps": []}

    # ── CIRCUIT BREAKER: emergency stop if day loss exceeds 3% of equity ──
    # Uses actual equity vs day-start equity (captures unrealized losses too)
    equity = STATE.get("current_equity", 0)
    _today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if STATE["_cb_day_date"] != _today_str and equity > 0:
        STATE["_cb_day_start_equity"] = equity
        STATE["_cb_day_date"] = _today_str
        STATE["_circuit_breaker_tripped"] = False
        logger.info(f"[CIRCUIT BREAKER] New day — start equity ${equity:.2f}")
    cb_start = STATE.get("_cb_day_start_equity", 0)
    day_pnl = equity - cb_start if cb_start > 0 else 0
    if equity > 0 and cb_start > 0 and day_pnl < 0 and abs(day_pnl) / cb_start > 0.03:
        if not STATE.get("_circuit_breaker_tripped"):
            STATE["_circuit_breaker_tripped"] = True
            logger.warning(
                f"[CIRCUIT BREAKER] Day loss ${day_pnl:.2f} exceeds 3% of equity ${equity:.2f}. "
                f"Emergency closing all positions and pausing."
            )
            if _position_manager:
                await _position_manager.emergency_close_all()
            if _alerts:
                await _alerts.send(
                    f"🚨 CIRCUIT BREAKER: Day loss ${day_pnl:.2f} ({day_pnl/equity*100:.1f}%). All positions closed.",
                    priority="critical",
                )
        trace["steps"].append("circuit_breaker_active")
        await _tick_positions()  # still tick to clean up ghost-closes
        return
    elif STATE.get("_circuit_breaker_tripped") and day_pnl >= 0:
        STATE["_circuit_breaker_tripped"] = False
        logger.info("[CIRCUIT BREAKER] Reset — day PnL back to positive.")

    # ── Step 1: Watcher scan ────────────────────────────────────────────────
    current_regime = STATE.get("regime", "sideways")
    candidates = await _watcher.scan(regime=current_regime)
    STATE["last_watcher_candidates"] = candidates[:10]
    trace["steps"].append(f"watcher:{len(candidates)}")
    logger.info(f"[Cycle {cycle}] Watcher → {len(candidates)} candidates")

    if not candidates:
        STATE["_cycle_trace"] = trace
        await _tick_positions()
        return

    # ── Step 2: Analyzer ───────────────────────────────────────────────────
    await asyncio.sleep(2)
    _analyzer.min_score = _min_score_live
    try:
        setups = await _analyzer.analyze(candidates, regime=STATE.get("regime", "sideways"))
        trace["steps"].append(f"analyzer:{len(setups)}")
        if setups:
            _consecutive_zero_setups = 0
    except Exception as exc:
        trace["steps"].append(f"analyzer_error:{exc}")
        logger.error(f"[Cycle {cycle}] Analyzer error: {exc}")
        setups = []
    STATE["last_setups"] = [
        {k: v for k, v in s.items() if k != "features"} for s in setups[:5]
    ]
    STATE["_cycle_trace"] = trace
    logger.info(f"[Cycle {cycle}] Analyzer → {len(setups)} setups (min_score={_min_score_live})")

    if not setups:
        _consecutive_zero_setups += 1
        await _tick_positions()
        return

    # ── Step 3: Context enrichment ─────────────────────────────────────────
    enriched = await _context.enrich(setups)
    trace["steps"].append(f"context:{len(enriched)}")

    # ── Step 4: Bayesian decisions ─────────────────────────────────────────
    _bayesian.mode = STATE.get("bigbrother_mode", "normal")
    approved = _bayesian.batch_decide(enriched)
    STATE["last_decisions"] = approved[:3]
    trace["steps"].append(f"bayesian:{len(approved)}")
    trace["approved_syms"] = [s["symbol"] for s in approved]

    # ── Step 5: Risk gates + entry ─────────────────────────────────────────
    equity = STATE["current_equity"]
    open_syms = _position_manager.get_open_symbols()
    trace["open_syms"] = list(open_syms)
    entries = []

    # In demo/live mode: fetch real available USDT cash so we never send an
    # order larger than what the exchange account actually holds.
    _MIN_POSITION_USD = 50.0
    available_cash_usd = equity  # paper fallback: treat full equity as available
    if _uses_exchange_account_state() and _exchange:
        try:
            _bal = await _exchange.fetch_balance()
            _usdt = _bal.get("USDT", {})
            available_cash_usd = float(
                _usdt.get("free") or _usdt.get("total") or 0.0
            )
            logger.info(f"[Cycle {cycle}] Available USDT cash: ${available_cash_usd:.2f}")
        except Exception as _e:
            logger.warning(f"[Cycle {cycle}] Could not fetch cash balance, using equity: {_e}")

    if _uses_exchange_account_state() and available_cash_usd < _MIN_POSITION_USD:
        trace["steps"].append(f"skip_entries:cash_too_low:${available_cash_usd:.0f}")
        logger.warning(
            f"[Cycle {cycle}] Only ${available_cash_usd:.2f} USDT free — "
            f"skipping new entries until positions close and cash frees up."
        )
        await _tick_positions()
        return

    # ── Phase 1C: Block entries if any position has failed exits ─────────
    if _position_manager and _position_manager.has_failed_exits:
        trace["steps"].append("skip_entries:failed_exits_pending")
        logger.warning(
            f"[Cycle {cycle}] Blocked new entries — position(s) have failed exit attempts. "
            f"Waiting for ghost-close before deploying more capital."
        )
        await _tick_positions()
        return

    # ── Pull regime capital params from BigBrother (set in Step 8 of previous cycle) ──
    _regime_capital = STATE.get("regime_capital", {})
    _regime_setup_allowlist = set(STATE.get("regime_setup_allowlist", []))  # empty = all allowed
    _regime_size_mult = float(_regime_capital.get("size_mult", 1.0))
    _regime_max_positions = _regime_capital.get("max_positions")
    _regime_max_exposure = _regime_capital.get("max_exposure_pct")
    _choppy_min_ta = float(STATE.get("choppy_min_ta_score", 0.0))
    _current_regime = STATE.get("regime", "sideways")

    # ── BTC Trend Gate — no alt longs if BTC is bearish ─────────────────────
    # Alts correlate 70-90% with BTC. Buying alt longs while BTC drops is
    # fighting the tide — historically causes 80% of momentum long failures.
    # Short tokens (3S/5S/DOWN) are exempt — they profit from BTC falling.
    _btc_bullish = True  # default: allow longs
    try:
        _btc_bullish = await _watcher.is_btc_trend_bullish()
        STATE["btc_trend_bullish"] = _btc_bullish
    except Exception as _btc_err:
        logger.warning(f"[Cycle {cycle}] BTC trend check failed: {_btc_err}")

    for setup in approved:
        symbol = setup["symbol"]

        # ── Pre-compute desired size (needed for both scale and new-entry paths) ──
        sl_pct = STATE.get("regime_params", {}).get("stop_loss_pct", cfg.stop_loss_pct)
        decision = setup.get("decision", {})
        size_usd = _risk_manager.compute_position_size(
            symbol=symbol,
            current_equity=equity,
            stop_loss_pct=sl_pct,
            posterior=float(decision.get("posterior", 0.65)),
            threshold=float(decision.get("threshold", cfg.bayesian_threshold_normal)),
            vol_usd=float(setup.get("vol_usd", 0.0)),
            ta_score=float(setup.get("ta_score", 50.0)),
            regime_size_mult=_regime_size_mult,
            current_regime=_current_regime,
        )
        size_usd = min(size_usd, equity * cfg.max_single_exposure_pct)
        if _uses_exchange_account_state():
            size_usd = min(size_usd, available_cash_usd * 0.92)

        # ── Already holding this symbol? → Scale instead of sell+rebuy ──────
        if symbol in open_syms:
            if cfg.position_scale_tolerance_pct > 0:
                # Cooldown gate applies to scaling too — a symbol that just stopped out
                # must not be immediately re-bought via scale_up (root cause of the
                # "death by a thousand cuts" loop with TAO/MOODENG).
                if _position_manager.is_symbol_on_cooldown(symbol):
                    trace["steps"].append(f"skip_scale_cooldown:{symbol}")
                    logger.info(f"[Swarm] {symbol} scale skipped: symbol cooldown active after stop-loss")
                    continue

                existing_pos = _position_manager.get_position_for_symbol(symbol)
                if existing_pos and existing_pos.setup_type not in ("synced_holding", "exchange_holding"):
                    try:
                        _scale_price = await _execution.get_current_price(symbol)
                        if _scale_price > 0 and size_usd >= _MIN_POSITION_USD:
                            scale_result = await _position_manager.scale_position(
                                existing_pos,
                                target_usd=size_usd,
                                current_price=_scale_price,
                                tolerance_pct=cfg.position_scale_tolerance_pct,
                            )
                            trace["steps"].append(f"scale_{scale_result}:{symbol}")
                            logger.info(f"[Swarm] {symbol} already held → scale={scale_result}")
                            # Track committed cash so subsequent entries see accurate available
                            if scale_result == "scaled_up":
                                current_val = existing_pos.amount * _scale_price
                                delta_spent = max(0.0, size_usd - current_val)
                                available_cash_usd = max(0.0, available_cash_usd - delta_spent)
                    except Exception as _se:
                        logger.debug(f"[Swarm] Scale check failed for {symbol}: {_se}")
                else:
                    trace["steps"].append(f"skip_held:{symbol}")
            else:
                trace["steps"].append(f"skip_held:{symbol}")
            continue

        # BTC trend gate — no alt longs if BTC 1h EMA9 < EMA21
        # Short tokens (3S/5S/DOWN) are exempt — they profit from BTC falling.
        _direction = setup.get("direction", "long")
        if not _btc_bullish and _direction == "long":
            _base = symbol.replace("/USDT", "")
            _is_short_token = any(_base.endswith(sfx) for sfx in ("3S", "5S", "DOWN"))
            if not _is_short_token:
                trace["steps"].append(f"skip_btc_bearish:{symbol}")
                logger.info(f"[Swarm] {symbol} skipped: BTC trend bearish (no alt longs)")
                continue

        # Symbol cooldown gate — prevent revenge-trading after recent stop-loss
        if _position_manager.is_symbol_on_cooldown(symbol):
            trace["steps"].append(f"skip_cooldown:{symbol}")
            logger.info(f"[Swarm] {symbol} skipped: symbol cooldown active")
            continue

        # Session churn guard — block tokens entered 3+ times in last 4h
        # Prevents repeatedly re-entering the same failing token (TRX 16×, ANIME 14×).
        if _position_manager.is_symbol_churning(symbol):
            trace["steps"].append(f"skip_churn:{symbol}")
            logger.info(f"[Swarm] {symbol} skipped: churn guard (3+ entries in 4h)")
            continue

        # v3.1: Setup allowlist gate — regime restricts which setup types are allowed
        setup_type = setup.get("setup_type", "neutral")
        if _regime_setup_allowlist and setup_type not in _regime_setup_allowlist:
            trace["steps"].append(f"skip_regime_setup:{symbol}:{setup_type}")
            logger.info(
                f"[Swarm] {symbol} skipped: setup_type '{setup_type}' not allowed in "
                f"{_current_regime} regime (allowlist={_regime_setup_allowlist})"
            )
            continue

        # v3.1: Choppy regime — additional ta_score gate (only high-quality breakouts)
        if _choppy_min_ta > 0:
            ta_score_check = float(setup.get("ta_score", 0.0))
            if ta_score_check < _choppy_min_ta:
                trace["steps"].append(f"skip_choppy_ta:{symbol}:score={ta_score_check:.0f}<{_choppy_min_ta:.0f}")
                logger.info(
                    f"[Swarm] {symbol} skipped: choppy regime requires ta_score >= {_choppy_min_ta:.0f} "
                    f"(got {ta_score_check:.0f})"
                )
                continue

        # Use bot-only exposure/count for risk gates (exclude synced holdings)
        # v3.1: pass regime-specific position + exposure limits from BigBrother
        can_open, gate_reason = _risk_manager.can_open_position(
            current_equity=equity,
            open_count=_position_manager.bot_open_count,
            current_exposure_usd=_position_manager.get_bot_exposure_usd(),
            symbol=symbol,
            open_symbols=open_syms,
            regime_max_positions=_regime_max_positions,
            regime_max_exposure_pct=_regime_max_exposure,
        )
        if not can_open:
            trace["steps"].append(f"risk_block:{symbol}:{gate_reason}")
            logger.info(f"[Swarm] {symbol} blocked: {gate_reason}")
            # Rejected trade journal — async fire-and-forget, never blocks the cycle
            asyncio.create_task(_save_rejected_setup_to_db(setup, gate_reason, "risk_gate"))
            continue

        # Cash sufficiency check for new entries
        if _uses_exchange_account_state() and size_usd < _MIN_POSITION_USD:
            trace["steps"].append(f"skip_{symbol}:cash_depleted:${available_cash_usd:.0f}")
            logger.info(f"[Swarm] {symbol} skipped: only ${available_cash_usd:.2f} USDT left")
            break

        trace["steps"].append(f"sizing:{symbol}:${size_usd:.0f}")

        try:
            pos = await _position_manager.open_position(
                setup=setup,
                amount_usd=size_usd,
                tier1_r=cfg.tier1_r_multiple,
                tier2_r=cfg.tier2_r_multiple,
            )
        except Exception as exc:
            trace["steps"].append(f"exec_error:{symbol}:{exc}")
            logger.error(f"[Swarm] Entry failed for {symbol}: {exc}")
            pos = None

        if pos:
            entries.append(symbol)
            _risk_manager.record_entry()  # count new entries only (not exits) toward daily limit
            available_cash_usd -= size_usd  # track committed cash within this cycle
            await _save_position_to_db(pos)
            if _alerts:
                decision = setup.get("decision", {})
                await _alerts.send(
                    f"🟢 ENTERED {symbol}\n"
                    f"Setup: {setup.get('setup_type')} | Score: {setup.get('ta_score'):.1f}\n"
                    f"Entry: {pos.entry_price:.6f} | Size: ${size_usd:.2f}\n"
                    f"Posterior: {decision.get('posterior', 0):.3f}",
                    priority="medium",
                )
            open_syms.add(symbol)
    
    trace["steps"].append(f"entries:{len(entries)}")
    trace["entries"] = entries
    STATE["_cycle_trace"] = trace

    # ── Step 6: Update open positions ──────────────────────────────────────
    exits = await _tick_positions()
    for exit_result in exits:
        if exit_result and exit_result.get("pnl_usd") is not None:
            pnl = float(exit_result["pnl_usd"])
            pnl_pct = float(exit_result.get("pnl_pct", 0))
            r_mult = float(exit_result.get("decision", {}).get("r_multiple", 0))
            hold_h = float(exit_result.get("hold_time_hours", 0))
            _risk_manager.record_trade(pnl, pnl_pct, r_mult)
            STATE["total_pnl_usd"] += pnl
            STATE["day_pnl_usd"] += pnl
            await _save_trade_to_db(exit_result)
            # Mark position closed in DB (so crash recovery skips it)
            if _db is not None:
                try:
                    await _db.positions.update_one(
                        {"id": exit_result.get("id")},
                        {"$set": {"status": "closed", "close_reason": exit_result.get("close_reason")}},
                    )
                except Exception:
                    pass
            _bayesian.update_prior(exit_result.get("setup_type", "neutral"), pnl > 0)
            if _alerts:
                emoji = "🟢" if pnl > 0 else "🔴"
                await _alerts.send(
                    f"{emoji} CLOSED {exit_result.get('symbol')} ({exit_result.get('close_reason')})\n"
                    f"PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%) | Hold: {hold_h:.1f}h | Regime: {STATE['regime']}",
                    priority="medium",
                )

    # ── Step 7: Quant Mutator ──────────────────────────────────────────────
    closed_history = _position_manager.get_closed_history(50)
    day_pnl_pct = STATE["day_pnl_usd"] / STATE["current_equity"] if STATE["current_equity"] else 0.0
    mutation = _quant_mutator.maybe_mutate(
        current_min_score=_min_score_live,
        current_bayesian_threshold=_bayesian_threshold_live,
        closed_trades=closed_history,
        current_day_pnl_pct=day_pnl_pct,
        consecutive_zero_setups=_consecutive_zero_setups,
    )
    if mutation["mutated"]:
        _min_score_live = mutation["min_score"]
        _bayesian_threshold_live = mutation["bayesian_threshold"]
        # BUG FIX: actually push mutated threshold into Bayesian engine so self-tuning takes effect
        _bayesian._thresholds["normal"] = mutation["bayesian_threshold"]
        logger.info(
            f"[QuantMutator] Applied threshold {mutation['bayesian_threshold']:.3f} → Bayesian engine"
        )
        await _save_mutation_to_db(mutation)

    # ── Step 8: BigBrother supervision ─────────────────────────────────────
    btc_ticker = await _get_btc_ticker()
    bb_result = await _bigbrother.supervise(
        current_equity=equity,
        open_count=_position_manager.open_count,
        closed_trades=closed_history,
        btc_ticker=btc_ticker,
    )
    old_regime = STATE.get("regime", "sideways")
    STATE["regime"] = bb_result["regime"]
    STATE["regime_params"] = bb_result["regime_params"]
    STATE["regime_capital"] = bb_result.get("regime_capital", {})
    STATE["regime_setup_allowlist"] = bb_result.get("regime_setup_allowlist", [])
    STATE["choppy_min_ta_score"] = bb_result.get("choppy_min_ta_score", 0.0)
    STATE["bigbrother_mode"] = bb_result["mode"]
    STATE["recent_events"].extend(bb_result.get("events", []))
    STATE["recent_events"] = STATE["recent_events"][-50:]

    # Track consecutive bear/choppy cycles — only sweep after 2+ cycles to avoid
    # false sweeps from single-cycle regime blips (sideways→bear→sideways).
    if STATE["regime"] in ("bear", "choppy"):
        STATE["_bear_cycle_count"] = STATE.get("_bear_cycle_count", 0) + 1
    else:
        STATE["_bear_cycle_count"] = 0

    if (old_regime != STATE["regime"] and STATE["regime"] in ("bear", "choppy")
            and STATE.get("_bear_cycle_count", 0) >= 2):
        logger.warning(f"[Swarm] Regime confirmed {STATE['regime']} for {STATE['_bear_cycle_count']} cycles (from {old_regime}). Sweeping vulnerable positions.")
        sweep_exits = await _position_manager.sweep_vulnerable_positions()
        for exit_result in sweep_exits:
            if exit_result and exit_result.get("pnl_usd") is not None:
                pnl = float(exit_result["pnl_usd"])
                pnl_pct = float(exit_result.get("pnl_pct", 0))
                r_mult = float(exit_result.get("decision", {}).get("r_multiple", 0))
                hold_h = float(exit_result.get("hold_time_hours", 0))
                _risk_manager.record_trade(pnl, pnl_pct, r_mult)
                STATE["total_pnl_usd"] += pnl
                STATE["day_pnl_usd"] += pnl
                await _save_trade_to_db(exit_result)
                if _db is not None:
                    try:
                        await _db.positions.update_one(
                            {"id": exit_result.get("id")},
                            {"$set": {"status": "closed", "close_reason": exit_result.get("close_reason")}},
                        )
                    except Exception:
                        pass
                _bayesian.update_prior(exit_result.get("setup_type", "neutral"), pnl > 0)
                if _alerts:
                    emoji = "🟢" if pnl > 0 else "🔴"
                    await _alerts.send(
                        f"{emoji} CLOSED {exit_result.get('symbol')} ({exit_result.get('close_reason')})\n"
                        f"PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%) | Hold: {hold_h:.1f}h | Regime: {STATE['regime']}",
                        priority="high",
                    )

    if bb_result["mode"] == "paused":
        STATE["paused"] = True

    # ── Step 9: Update equity and push to WebSocket ────────────────────────
    await _update_equity()
    STATE["last_cycle_at"] = int(time.time())
    await _broadcast_ws()

    logger.info(
        f"[Swarm] Cycle {cycle} complete | "
        f"regime={bb_result['regime']} mode={bb_result['mode']} "
        f"open={_position_manager.open_count} "
        f"total_pnl=${STATE['total_pnl_usd']:+.2f}"
    )


async def _tick_positions() -> list[dict]:
    regime_params = dict(STATE.get("regime_params") or {})
    regime_params["regime"] = STATE.get("regime", "sideways")  # explicit name for is_aggressive check
    exits = await _position_manager.update_all(regime_params=regime_params)
    return [e for e in exits if e is not None]


async def _get_btc_ticker() -> Optional[dict]:
    try:
        btc_symbol = "BTC/USDT"
        markets = _exchange.exchange.markets or {}
        if btc_symbol not in markets:
            return None
        return await _exchange.fetch_ticker(btc_symbol)
    except Exception:
        return None


async def _update_equity():
    """Compute total portfolio NAV: USDT balance + all coin holdings at current market prices."""
    try:
        balance = await _exchange.fetch_balance()

        # USDT base
        usdt = balance.get("USDT", {})
        total_usd = float(usdt.get("total", 0.0) or 0.0)
        if total_usd == 0:
            total_usd = float(usdt.get("free", 0.0) or 0.0)

        # Collect all non-zero non-USDT coin holdings
        coin_holdings: dict[str, float] = {}
        for currency, amounts in balance.items():
            if currency in ("USDT", "free", "used", "total", "info", "timestamp", "datetime"):
                continue
            if not isinstance(amounts, dict):
                continue
            amount = float(amounts.get("total", 0) or amounts.get("free", 0) or 0)
            if amount > 1e-8:
                coin_holdings[currency] = amount

        # Price each coin holding via batch ticker fetch
        if coin_holdings and _exchange:
            markets = _exchange.exchange.markets or {}
            valid_symbols = [f"{c}/USDT" for c in coin_holdings if f"{c}/USDT" in markets]
            if valid_symbols:
                try:
                    tickers = await _exchange.fetch_tickers(valid_symbols)
                    for sym, ticker in tickers.items():
                        coin = sym.split("/")[0]
                        if coin in coin_holdings:
                            price = float(ticker.get("last") or ticker.get("close") or 0)
                            if price > 0:
                                total_usd += coin_holdings[coin] * price
                except Exception as te:
                    logger.debug(f"[Equity] Ticker batch error: {te}")
                    # Fallback: add open position exposure as proxy
                    if _position_manager:
                        total_usd += _position_manager.get_total_exposure_usd()

        equity = total_usd
        if equity > 0:
            STATE["current_equity"] = equity
            if equity > STATE.get("peak_equity", 0):
                STATE["peak_equity"] = equity
            account_equity.set(equity)
            STATE["equity_history"].append({"t": int(time.time()), "v": round(equity, 2)})
            if len(STATE["equity_history"]) > 2000:
                STATE["equity_history"] = STATE["equity_history"][-2000:]
            # Persist snapshot to MongoDB for historical chart (fire-and-forget)
            if _db is not None:
                ts_now = int(time.time())
                try:
                    await _db.equity_snapshots.insert_one({"t": ts_now, "v": round(equity, 2)})
                    # Keep only last 30 days of data in the collection
                    cutoff = ts_now - 30 * 86400
                    await _db.equity_snapshots.delete_many({"t": {"$lt": cutoff}})
                except Exception as _dbe:
                    logger.debug(f"[Equity] DB snapshot error: {_dbe}")
    except Exception as e:
        logger.debug(f"Balance fetch error: {e}")


# ── MongoDB helpers ──────────────────────────────────────────────────────────
async def _save_position_to_db(pos):
    """Upsert an open position document so we can recover it after a crash."""
    if _db is None:
        return
    try:
        doc = pos.to_dict()
        doc["exchange"] = cfg.exchange_name
        doc["exchange_mode"] = cfg.exchange_mode
        doc["status"] = "open"  # always mark live positions as open
        await _db.positions.update_one(
            {"id": pos.id},
            {"$set": doc},
            upsert=True,
        )
    except Exception as e:
        logger.debug(f"DB save position error: {e}")


async def _save_trade_to_db(trade: dict):
    if _db is None:
        return
    try:
        doc = dict(trade)
        doc["exchange"] = cfg.exchange_name
        doc["exchange_mode"] = cfg.exchange_mode
        doc["saved_at"] = int(time.time())
        await _db.trades.insert_one(doc)
    except Exception as e:
        logger.debug(f"DB save trade error: {e}")


async def _save_mutation_to_db(mutation: dict):
    if _db is None:
        return
    try:
        await _db.quant_mutations.insert_one(dict(mutation))
    except Exception as e:
        logger.debug(f"DB save mutation error: {e}")


async def _save_rejected_setup_to_db(setup: dict, reason: str, gate: str):
    """Persist a rejected trade setup to MongoDB for missed-opportunity analysis."""
    if _db is None:
        return
    try:
        doc = {
            "timestamp": int(time.time()),
            "symbol": setup.get("symbol"),
            "setup_type": setup.get("setup_type"),
            "ta_score": setup.get("ta_score"),
            "posterior": setup.get("decision", {}).get("posterior"),
            "rejection_reason": reason,
            "rejection_gate": gate,   # "risk_gate" | "bayesian" | "cooldown"
            "regime": STATE.get("regime", "unknown"),
            "mode": STATE.get("bigbrother_mode", "normal"),
            "exchange": cfg.exchange_name,
        }
        await _db.rejected_setups.insert_one(doc)
    except Exception as e:
        logger.debug(f"DB save rejected setup error: {e}")




async def _recover_positions_from_db():
    """Crash recovery: reload open positions from MongoDB into PositionManager.
    Called once at startup, after agents are initialised.
    Reconciles each position's amount against the live exchange balance so we
    don't manage positions that were already closed on the exchange.
    """
    if _db is None or _position_manager is None:
        return
    try:
        cursor = _db.positions.find(
            {"status": "open", "exchange": cfg.exchange_name},
            {"_id": 0},
        )
        docs = await cursor.to_list(length=200)
        if not docs:
            return

        # Fetch live exchange balance for amount reconciliation if possible
        live_balances: dict[str, float] = {}
        if _exchange and _uses_exchange_account_state():
            try:
                raw_balance = await _exchange.fetch_balance()
                for currency, amounts in raw_balance.items():
                    if isinstance(amounts, dict):
                        live_balances[currency] = float(
                            amounts.get("total", 0) or amounts.get("free", 0) or 0
                        )
            except Exception as e:
                logger.warning(f"[Recovery] Could not fetch live balances: {e}")

        recovered = 0
        seen_symbols: set = set()
        for doc in docs:
            symbol = doc.get("symbol", "")
            # Skip exchange_holding / synced_holding — these are the user's personal
            # holdings, not bot trades. Recovering them creates -$7000+ unrealized PnL
            # swings every restart and triggers exit loops through the wrong exchange.
            doc_setup_type = doc.get("setup_type", "")
            if doc_setup_type in ("exchange_holding", "synced_holding"):
                logger.debug(f"[Recovery] Skipping {symbol} ({doc_setup_type}) — user holding, not bot trade")
                continue
            # De-duplicate: only recover the first DB record per symbol.
            # Multiple records arise from partial fills updating in-memory but not DB.
            # Loading all = each gets reconciled to full exchange balance → total > held.
            if symbol in seen_symbols:
                logger.warning(f"[Recovery] Skipping duplicate {symbol} DB record")
                continue
            seen_symbols.add(symbol)
            # Skip dust positions — amount_usd < $5 OR estimated current value < $20.
            # BUG: doc_amount_usd = ORIGINAL position size (e.g., TAO $1392), not remaining.
            # TAO with 0.002 tokens left has amount_usd=$1392 → old filter never fires.
            # Fix: also check amount × entry_price (estimated remaining value).
            doc_amount_usd = float(doc.get("amount_usd") or 0)
            doc_amount = float(doc.get("amount") or 0)
            doc_entry_price = float(doc.get("entry_price") or 0)
            estimated_remaining_usd = doc_amount * doc_entry_price if doc_entry_price > 0 else doc_amount_usd
            if doc_amount_usd < 5.0 or doc_amount < 1e-6 or estimated_remaining_usd < 20.0:
                logger.debug(f"[Recovery] Skipping dust position {symbol}: amount_usd=${doc_amount_usd:.4f}")
                try:
                    await _db.positions.update_one(
                        {"id": doc.get("id")},
                        {"$set": {"status": "closed_dust"}},
                    )
                except Exception:
                    pass
                continue
            pos = _position_manager.restore_position_from_dict(doc)
            if pos is None:
                continue

            # Reconcile: if exchange shows < 1% of expected amount, position is gone
            if live_balances:
                currency = symbol.split("/")[0] if "/" in symbol else symbol
                live_qty = live_balances.get(currency, 0.0)
                if live_qty < pos.amount * 0.01:
                    logger.warning(
                        f"[Recovery] {symbol} shows {live_qty:.6f} on exchange "
                        f"vs. {pos.amount:.6f} expected — skipping (already closed?)"
                    )
                    # Mark closed in DB so we don't revisit it
                    try:
                        await _db.positions.update_one(
                            {"id": pos.id},
                            {"$set": {"status": "closed_on_restart"}}
                        )
                    except Exception:
                        pass
                    continue
                # Correct the amount to what the exchange actually holds
                pos.amount = live_qty
                pos.amount_usd = live_qty * pos.entry_price
                # Post-reconciliation dust check — DB stored original amount (e.g. TAO 3.976)
                # so the pre-filter passed ($1089), but exchange only has 0.000574 TAO ($0.16).
                # Gate.io min sell = 0.001 → close_all_positions fails forever.
                if pos.amount_usd < 20.0:
                    logger.warning(
                        f"[Recovery] {symbol} reconciled to {live_qty:.6f} (${pos.amount_usd:.2f}) "
                        f"— below $20 after reconciliation, ghost-closing as dust"
                    )
                    try:
                        await _db.positions.update_one(
                            {"id": pos.id},
                            {"$set": {"status": "closed_dust"}}
                        )
                    except Exception:
                        pass
                    continue

            _position_manager._positions[pos.id] = pos
            recovered += 1

        if recovered > 0:
            from src.metrics import active_positions
            active_positions.set(len(_position_manager._positions))
            logger.info(f"[Recovery] ✅ Restored {recovered} open position(s) from DB")
            if _alerts:
                await _alerts.send(
                    f"♻️ Crash recovery: {recovered} position(s) reloaded from DB.",
                    priority="medium",
                )
    except Exception as e:
        logger.error(f"[Recovery] Failed to restore positions: {e}")

    # ── Cancel orphaned sell orders for bot-tracked symbols ──────────────────
    # When the bot crashes mid-exit, GTC limit sells stay on the exchange and
    # can fill silently (selling coins without bot tracking the close).
    # Only cancels SELL orders for symbols the bot has open positions in —
    # preserves any user-placed manual orders for unrelated symbols.
    if _exchange and _uses_exchange_account_state() and _position_manager:
        try:
            tracked_symbols = {
                pos.symbol
                for pos in _position_manager._positions.values()
            }
            # Also include symbols that were in DB as "open" before recovery
            if _db is not None:
                try:
                    db_syms_cursor = _db.positions.find(
                        {"status": {"$in": ["open", "closed_on_restart"]}, "exchange": cfg.exchange_name},
                        {"_id": 0, "symbol": 1},
                    )
                    db_sym_docs = await db_syms_cursor.to_list(length=200)
                    tracked_symbols |= {d["symbol"] for d in db_sym_docs if d.get("symbol")}
                except Exception:
                    pass

            open_orders = await _exchange.fetch_open_orders()
            orphans = [
                o for o in open_orders
                if o.get("side") == "sell" and o.get("symbol") in tracked_symbols
            ]
            if orphans:
                logger.warning(
                    f"[Recovery] Found {len(orphans)} orphaned SELL order(s) for bot symbols — cancelling."
                )
                for order in orphans:
                    oid = order.get("id")
                    sym = order.get("symbol")
                    try:
                        await _exchange.cancel_order(oid, sym)
                        logger.info(
                            f"[Recovery] Cancelled orphaned SELL {oid} for {sym} @ {order.get('price')}"
                        )
                    except Exception as ce:
                        logger.debug(f"[Recovery] Could not cancel order {oid}: {ce}")
        except Exception as e:
            logger.debug(f"[Recovery] Orphan order sweep error: {e}")

    # ── Seed risk manager trade history from DB so win rate is correct after restart ──
    if _db is not None and _risk_manager is not None:
        try:
            cursor = _db.trades.find(
                {"pnl_usd": {"$exists": True}, "exchange": cfg.exchange_name},
                {"_id": 0, "pnl_usd": 1, "pnl_pct": 1},
                sort=[("saved_at", 1)],
                limit=500,
            )
            trade_docs = await cursor.to_list(length=500)
            for t in trade_docs:
                pnl = float(t.get("pnl_usd") or 0)
                pct = float(t.get("pnl_pct") or 0)
                r = pct / abs(cfg.stop_loss_pct) if cfg.stop_loss_pct else 0.0
                _risk_manager.record_trade(pnl, pct, r)
            if trade_docs:
                wr = sum(1 for t in trade_docs if (t.get("pnl_usd") or 0) > 0) / len(trade_docs) * 100
                logger.info(f"[Recovery] Seeded risk manager with {len(trade_docs)} historical trades (WR={wr:.0f}%)")
            # Reset session-level safeguards — consecutive_loss_pause and day_trade_count
            # are within-session guards, not persistent state. Replaying historical trades
            # would re-trigger pauses and exhaust daily trade quota every restart.
            _risk_manager._consecutive_losses = 0
            _risk_manager._consecutive_wins = 0
            _risk_manager._pause_until = None
            _risk_manager._day_trade_count = 0
        except Exception as e:
            logger.debug(f"[Recovery] Risk manager seed error: {e}")

    # ── Restore peak equity from snapshots so drawdown protection survives restarts ──
    # Without this, every restart resets peak_equity to current equity → safety/drawdown
    # mode never triggers across sessions even during persistent NAV declines.
    if _db is not None and _risk_manager is not None:
        try:
            peak_cursor = _db.equity_snapshots.find(
                {}, {"_id": 0, "v": 1}
            ).sort("v", -1).limit(1)
            peak_docs = await peak_cursor.to_list(length=1)
            if peak_docs:
                historical_peak = float(peak_docs[0]["v"])
                if historical_peak > _risk_manager.peak_equity:
                    _risk_manager.peak_equity = historical_peak
                    logger.info(f"[Recovery] Restored peak equity ${historical_peak:.2f} from snapshots")
        except Exception as e:
            logger.debug(f"[Recovery] Peak equity restore error: {e}")



def _uses_exchange_account_state() -> bool:
    return cfg.exchange_mode in ("demo", "live")


def _extract_balance_amount(amounts) -> float:
    if not isinstance(amounts, dict):
        return 0.0
    return float(amounts.get("total", 0.0) or amounts.get("free", 0.0) or 0.0)


async def _get_exchange_account_snapshot() -> dict:
    if not _exchange:
        return {
            "source": "internal",
            "equity": STATE["current_equity"],
            "cash_usd": 0.0,
            "open_positions": [],
            "open_count": 0,
            "exposure_usd": 0.0,
        }

    balance = await _exchange.fetch_balance()
    usdt = balance.get("USDT", {})
    cash_usd = _extract_balance_amount(usdt)
    tracked_by_symbol = {}
    if _position_manager:
        tracked_by_symbol = {
            pos.symbol: pos
            for pos in _position_manager._positions.values()
            if pos.status == "open"
        }

    holdings: list[tuple[str, float]] = []
    markets = _exchange.exchange.markets or {}
    for currency, amounts in balance.items():
        if currency in ("USDT", "free", "used", "total", "info", "timestamp", "datetime"):
            continue
        amount = _extract_balance_amount(amounts)
        if amount <= 1e-8:
            continue
        symbol = f"{currency}/USDT"
        if symbol in markets:
            holdings.append((symbol, amount))

    tickers = {}
    if holdings:
        try:
            tickers = await _exchange.fetch_tickers([symbol for symbol, _ in holdings])
        except Exception as e:
            logger.debug(f"Exchange snapshot tickers error: {e}")

    open_positions = []
    exposure_usd = 0.0
    equity = cash_usd
    now = time.time()

    for symbol, amount in holdings:
        tracked = tracked_by_symbol.get(symbol)
        ticker = tickers.get(symbol, {})
        current_price = float(
            ticker.get("last")
            or ticker.get("close")
            or (tracked.entry_price if tracked else 0.0)
            or 0.0
        )
        if current_price <= 0:
            continue
        amount_usd = amount * current_price
        # Skip dust positions below Gate.io minimum order size
        if amount_usd < 3.0:
            continue
        exposure_usd += amount_usd
        equity += amount_usd
        opened_at = tracked.opened_at if tracked else int(now)
        posterior = 0.0
        if tracked:
            posterior = tracked.decision.get("posterior", 0.0)
        entry_price_used = tracked.entry_price if tracked else current_price
        cost_basis = amount * entry_price_used if entry_price_used > 0 else 0.0
        unrealized_pnl = (amount_usd - cost_basis) if cost_basis > 0 else 0.0
        unrealized_pnl_pct = (unrealized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

        open_positions.append({
            "id": tracked.id if tracked else f"exchange-{symbol.replace('/', '-').lower()}",
            "symbol": symbol,
            "status": "open",
            "setup_type": tracked.setup_type if tracked else "exchange_holding",
            "entry_price": entry_price_used,
            "amount": amount,
            "amount_usd": round(amount_usd, 4),
            "current_price": current_price,
            "unrealized_pnl_usd": round(unrealized_pnl, 4),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "stop_loss": tracked.stop_loss if tracked else 0.0,
            "take_profit_1": tracked.take_profit_1 if tracked else 0.0,
            "take_profit_2": tracked.take_profit_2 if tracked else 0.0,
            "highest_price": tracked.highest_price if tracked else current_price,
            "trailing_stop": tracked.trailing_stop if tracked else None,
            "tier1_done": tracked.tier1_done if tracked else False,
            "tier2_done": tracked.tier2_done if tracked else False,
            "pyramid_count": tracked.pyramid_count if tracked else 0,
            "realized_pnl_usd": tracked.realized_pnl_usd if tracked else 0.0,
            "total_fees_usd": tracked.total_fees_usd if tracked else 0.0,
            "opened_at": opened_at,
            "closed_at": None,
            "close_reason": None,
            "hold_time_hours": round((now - opened_at) / 3600.0, 2) if opened_at else 0.0,
            "posterior": posterior,
            "source": "exchange",
        })

    open_positions.sort(key=lambda item: item["amount_usd"], reverse=True)
    return {
        "source": "exchange",
        "equity": round(equity, 2),
        "cash_usd": round(cash_usd, 2),
        "open_positions": open_positions,
        "open_count": len(open_positions),
        "exposure_usd": round(exposure_usd, 2),
    }


def _compute_pnl_from_fills(raw_fills: list[dict]) -> tuple[list[dict], float]:
    """
    FIFO cost-basis matching of raw exchange fills (buys + sells) to compute
    realized PnL for each completed buy→sell round trip.

    Returns:
        completed_trades: list of trade dicts with real pnl_usd, pnl_pct, etc.
        total_pnl_usd:    cumulative realized PnL across all matched trades
    """
    from collections import defaultdict

    # Sort fills oldest→newest so FIFO is applied in time order
    sorted_fills = sorted(raw_fills, key=lambda f: f.get("_ts_sec", 0))

    # Per-symbol buy queue: [[qty_remaining, avg_price, fee_per_unit, open_ts], ...]
    buy_queues: dict[str, list] = defaultdict(list)

    completed_trades: list[dict] = []
    total_pnl = 0.0

    for fill in sorted_fills:
        symbol = fill.get("symbol", "")
        side = fill.get("side", "")
        price = float(fill.get("price") or 0)
        amount = float(fill.get("amount") or 0)       # base currency qty
        cost = float(fill.get("cost") or (price * amount) or 0)  # quote cost
        fee_raw = fill.get("fee") or {}
        fee = float(fee_raw.get("cost", 0) or 0)
        ts = fill.get("_ts_sec", 0)

        if price <= 0 or amount <= 0:
            continue

        if side == "buy":
            fee_per_unit = fee / amount if amount > 0 else 0.0
            buy_queues[symbol].append([amount, price, fee_per_unit, ts])

        elif side == "sell":
            queue = buy_queues[symbol]
            qty_to_match = amount
            total_buy_cost = 0.0
            matched_qty = 0.0
            earliest_open_ts = ts  # fallback

            while qty_to_match > 1e-10 and queue:
                lot = queue[0]  # [qty, price, fee_per_unit, open_ts]
                matched = min(qty_to_match, lot[0])

                if matched_qty == 0:
                    earliest_open_ts = lot[3]

                total_buy_cost += matched * lot[1] + matched * lot[2]  # price + fee
                matched_qty += matched
                lot[0] -= matched
                qty_to_match -= matched

                if lot[0] <= 1e-10:
                    queue.pop(0)

            if matched_qty <= 1e-10:
                # No matching buy found — still record as sell-only fill
                completed_trades.append({
                    "symbol": symbol,
                    "close_reason": "sell",
                    "pnl_usd": 0.0,
                    "pnl_pct": 0.0,
                    "entry_price": price,
                    "exit_price": price,
                    "hold_time_hours": 0.0,
                    "setup_type": "exchange_fill",
                    "closed_at": ts,
                    "amount_usd": round(cost, 4),
                    "fee_usd": round(fee, 4),
                    "source": "exchange",
                })
                continue

            # Sell revenue proportional to matched qty (minus sell fee)
            sell_revenue = (matched_qty / amount) * cost - fee if amount > 0 else cost - fee
            pnl = sell_revenue - total_buy_cost
            total_pnl += pnl

            pnl_pct = (pnl / total_buy_cost * 100.0) if total_buy_cost > 0 else 0.0
            entry_price_avg = (total_buy_cost / matched_qty) if matched_qty > 0 else price
            hold_h = round((ts - earliest_open_ts) / 3600.0, 2) if earliest_open_ts else 0.0

            completed_trades.append({
                "symbol": symbol,
                "close_reason": "exchange_sell",
                "pnl_usd": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 2),
                "entry_price": round(entry_price_avg, 8),
                "exit_price": round(price, 8),
                "hold_time_hours": hold_h,
                "setup_type": "exchange_fill",
                "closed_at": ts,
                "amount_usd": round(matched_qty * price, 4),
                "fee_usd": round(fee, 4),
                "source": "exchange",
            })

    return completed_trades, round(total_pnl, 4)


_exchange_fills_cache: list[dict] = []
_exchange_fills_ts: float = 0.0
_EXCHANGE_FILLS_TTL = 60.0  # seconds between actual exchange calls


async def _get_exchange_trade_history(limit: int) -> list[dict]:
    """
    Fetch exchange fills, FIFO-match buys→sells, return completed trades
    with real realized pnl_usd. Falls back to raw fills if anything fails.
    Results are cached for _EXCHANGE_FILLS_TTL seconds to avoid hammering
    fetch_my_trades on every /api/trades poll.
    """
    global _exchange_fills_cache, _exchange_fills_ts
    if not _exchange:
        return []

    if time.time() - _exchange_fills_ts < _EXCHANGE_FILLS_TTL and _exchange_fills_cache:
        return _exchange_fills_cache[:limit]

    # Fetch 3× more fills than needed so FIFO matching can find buy lots
    fetch_limit = min(limit * 4, 500)
    try:
        raw = await _exchange.fetch_my_trades(limit=fetch_limit)
    except Exception as e:
        logger.debug(f"[TradeHistory] fetch_my_trades error: {e}")
        return _exchange_fills_cache[:limit]  # return stale cache on error rather than []

    # Normalize timestamps and attach _ts_sec for FIFO sorting
    fills: list[dict] = []
    for t in raw:
        ts = int(t.get("timestamp") or 0)
        if ts > 1_000_000_000_000:
            ts //= 1000
        fills.append({**t, "_ts_sec": ts})

    completed, _ = _compute_pnl_from_fills(fills)

    # Sort newest→oldest for display
    completed.sort(key=lambda x: x.get("closed_at", 0), reverse=True)
    _exchange_fills_cache = completed
    _exchange_fills_ts = time.time()
    return completed[:limit]


# ── Cumulative realized PnL from exchange (cached) ───────────────────────────
_equity_pnl_cache: dict = {"pnl": 0.0, "day_pnl": 0.0, "fetched_at": 0.0}
_EQUITY_PNL_CACHE_TTL = 30  # seconds


async def _compute_pnl_from_equity_snapshots(current_equity: float) -> dict:
    """
    Compute PnL from equity_snapshots (exchange ground truth).
    total_pnl = current_equity - oldest-ever snapshot
    day_pnl   = current_equity - first snapshot of today (UTC midnight)
    Cached for 30 s.
    """
    global _equity_pnl_cache
    now = time.time()
    if now - _equity_pnl_cache["fetched_at"] < _EQUITY_PNL_CACHE_TTL:
        # Re-apply live equity so the delta stays fresh even if snapshots are cached
        cached_base = _equity_pnl_cache.get("_base_total", 0.0)
        cached_today = _equity_pnl_cache.get("_base_day", 0.0)
        return {
            "pnl": round(current_equity - cached_base, 4) if cached_base else _equity_pnl_cache["pnl"],
            "day_pnl": round(current_equity - cached_today, 4) if cached_today else _equity_pnl_cache["day_pnl"],
        }

    if _db is None:
        return _equity_pnl_cache

    try:
        import datetime as _dt
        today_start_ts = int(
            _dt.datetime(
                *_dt.datetime.now(_dt.timezone.utc).timetuple()[:3],
                tzinfo=_dt.timezone.utc,
            ).timestamp()
        )

        # Oldest snapshot ever → baseline for total PnL
        oldest_cursor = _db.equity_snapshots.find({}, {"_id": 0, "t": 1, "v": 1}).sort("t", 1).limit(1)
        oldest = await oldest_cursor.to_list(length=1)

        # First snapshot of today → baseline for day PnL
        today_cursor = _db.equity_snapshots.find(
            {"t": {"$gte": today_start_ts}}, {"_id": 0, "t": 1, "v": 1}
        ).sort("t", 1).limit(1)
        today_first = await today_cursor.to_list(length=1)

        base_total = float(oldest[0]["v"]) if oldest else current_equity
        base_day = float(today_first[0]["v"]) if today_first else current_equity

        total_pnl = current_equity - base_total
        day_pnl = current_equity - base_day

        _equity_pnl_cache = {
            "pnl": round(total_pnl, 4),
            "day_pnl": round(day_pnl, 4),
            "fetched_at": now,
            "_base_total": base_total,
            "_base_day": base_day,
        }
        logger.debug(f"[PnL Snapshots] base_total={base_total:.2f} base_day={base_day:.2f} total={total_pnl:+.2f} today={day_pnl:+.2f}")
    except Exception as e:
        logger.debug(f"[PnL Snapshots] error: {e}")

    return _equity_pnl_cache


_exchange_pnl_cache: dict = {"pnl": 0.0, "day_pnl": 0.0, "fetched_at": 0.0}
_EXCHANGE_PNL_CACHE_TTL = 60  # seconds


async def _compute_cumulative_exchange_pnl() -> dict:
    """
    Fetch the last 1000 exchange fills, FIFO-match all buys→sells, and return
    total realized PnL + today's PnL. Result is cached for 60 s.
    """
    global _exchange_pnl_cache
    now = time.time()
    if now - _exchange_pnl_cache["fetched_at"] < _EXCHANGE_PNL_CACHE_TTL:
        return _exchange_pnl_cache

    if not _exchange:
        return _exchange_pnl_cache

    try:
        raw = await _exchange.fetch_my_trades(limit=1000)
    except Exception as e:
        logger.debug(f"[PnL cache] fetch_my_trades error: {e}")
        return _exchange_pnl_cache

    fills: list[dict] = []
    for t in raw:
        ts = int(t.get("timestamp") or 0)
        if ts > 1_000_000_000_000:
            ts //= 1000
        fills.append({**t, "_ts_sec": ts})

    completed, total_pnl = _compute_pnl_from_fills(fills)

    import datetime
    today_start_ts = int(
        datetime.datetime(
            *datetime.datetime.now(datetime.timezone.utc).timetuple()[:3],
            tzinfo=datetime.timezone.utc,
        ).timestamp()
    )
    day_pnl = sum(
        t["pnl_usd"] for t in completed if t.get("closed_at", 0) >= today_start_ts
    )

    _exchange_pnl_cache = {
        "pnl": round(total_pnl, 4),
        "day_pnl": round(day_pnl, 4),
        "fetched_at": now,
    }
    logger.debug(f"[PnL cache] total={total_pnl:+.2f} today={day_pnl:+.2f}")
    return _exchange_pnl_cache


# ── WebSocket broadcast ──────────────────────────────────────────────────────
async def _broadcast_ws():
    if not _ws_clients:
        return
    payload = json.dumps(await _build_ws_payload())
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


async def _build_ws_payload() -> dict:
    pm = _position_manager
    open_positions = pm.get_open_positions() if pm else []
    open_count = pm.open_count if pm else 0
    if _uses_exchange_account_state():
        try:
            snapshot = await _get_exchange_account_snapshot()
            open_positions = snapshot["open_positions"]
            open_count = snapshot["open_count"]
        except Exception as e:
            logger.debug(f"WS snapshot error: {e}")
    return {
        "type": "cycle_update",
        "timestamp": int(time.time()),
        "cycle": STATE["cycle_count"],
        "regime": STATE["regime"],
        "mode": STATE.get("bigbrother_mode", "normal"),
        "exchange": cfg.exchange_name,
        "exchange_mode": cfg.exchange_mode,
        "equity": STATE["current_equity"],
        "total_pnl_usd": round(STATE["total_pnl_usd"], 2),
        "day_pnl_usd": round(STATE["day_pnl_usd"], 2),
        "open_positions": open_positions,
        "open_count": open_count,
        "last_setups": STATE.get("last_setups", [])[:3],
        "last_decisions": STATE.get("last_decisions", [])[:3],
        "recent_events": STATE.get("recent_events", [])[-10:],
        "risk_health": _risk_manager.check_portfolio_health(STATE["current_equity"]) if _risk_manager else {},
        "recent_trades": _position_manager.get_closed_history(10) if _position_manager else [],
    }


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Moonshot-CEX API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health / Status ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    uptime = int(time.time() - STATE.get("start_time", time.time()))
    return {
        "status": "ok",
        "exchange": cfg.exchange_name,
        "exchange_mode": cfg.exchange_mode,
        "running": STATE["running"],
        "paused": STATE["paused"],
        "uptime": uptime,
        "cycle": STATE["cycle_count"],
    }


@app.get("/api/swarm/status")
async def swarm_status():
    if _bigbrother:
        summary = _bigbrother.get_status_summary()
    else:
        summary = {}
    open_count = _position_manager.open_count if _position_manager else 0
    bot_open_count = _position_manager.bot_open_count if _position_manager else 0
    if _uses_exchange_account_state():
        try:
            snapshot = await _get_exchange_account_snapshot()
            open_count = snapshot["open_count"]
        except Exception as e:
            logger.debug(f"Swarm status snapshot error: {e}")
    return {
        **summary,
        "running": STATE["running"],
        "paused": STATE["paused"],
        "emergency_stop": STATE["emergency_stop"],
        "cycle_count": STATE["cycle_count"],
        "equity": STATE["current_equity"],
        "total_pnl_usd": round(STATE["total_pnl_usd"], 2),
        "day_pnl_usd": round(STATE["day_pnl_usd"], 2),
        "open_count": open_count,
        "bot_open_count": bot_open_count,
        "last_cycle_at": STATE["last_cycle_at"],
        "last_setups": STATE.get("last_setups", []),
        "last_decisions": STATE.get("last_decisions", []),
        "recent_events": STATE.get("recent_events", []),
        "_cycle_trace": STATE.get("_cycle_trace", {}),
    }


@app.get("/api/account/snapshot")
async def account_snapshot():
    """Return raw exchange account snapshot — balances + open positions from Gate testnet."""
    if not _uses_exchange_account_state():
        return {"error": "Only available in demo/live mode", "mode": cfg.exchange_mode}
    snapshot = await _get_exchange_account_snapshot()
    return snapshot


@app.get("/api/debug/pipeline")
async def debug_pipeline():
    """Run a single pipeline trace and return results at each stage."""
    trace = {"watcher": {}, "analyzer": {}, "bayesian": {}, "risk": {}}

    # Step 1: Watcher
    candidates = await _watcher.scan()
    trace["watcher"]["count"] = len(candidates)
    trace["watcher"]["top3"] = [
        {"symbol": c["symbol"], "score": c["score"], "vol_ratio": c.get("vol_ratio", 0)}
        for c in candidates[:3]
    ]

    if not candidates:
        return trace

    # Step 2: Analyzer
    _analyzer.min_score = _min_score_live
    setups = await _analyzer.analyze(candidates, regime=STATE.get("regime", "sideways"))
    trace["analyzer"]["count"] = len(setups)
    trace["analyzer"]["setups"] = [
        {
            "symbol": s["symbol"],
            "ta_score": s["ta_score"],
            "setup_type": s["setup_type"],
            "rr_ratio": s.get("entry_zone", {}).get("rr_ratio", 0),
            "vol_ratio": s.get("vol_ratio", "MISSING"),
        }
        for s in setups[:5]
    ]

    # If analyzer produced nothing, try analyzing one candidate manually
    if not setups and candidates:
        c = candidates[0]
        sym = c["symbol"]
        trace["analyzer"]["debug_symbol"] = sym
        try:
            for tf in ["5m", "15m", "1h", "4h"]:
                candles = await _exchange.fetch_ohlcv(sym, tf, limit=200)
                trace["analyzer"][f"ohlcv_{tf}"] = len(candles) if candles else 0
        except Exception as e:
            trace["analyzer"]["ohlcv_error"] = str(e)

    if not setups:
        return trace

    # Step 3: Context
    enriched = await _context.enrich(setups)

    # Step 4: Bayesian
    _bayesian.mode = STATE.get("bigbrother_mode", "normal")
    for s in enriched[:3]:
        decision = _bayesian.decide(s)
        trace["bayesian"][s["symbol"]] = {
            "posterior": decision["posterior"],
            "threshold": decision["threshold"],
            "action": decision["action"],
            "ta_lk": decision["ta_likelihood"],
            "ctx_lk": decision["ctx_likelihood"],
            "vol_lk": decision["vol_likelihood"],
            "rr": decision["rr_factor"],
        }

    # Step 5: Risk
    equity = STATE["current_equity"]
    total_exp = _position_manager.get_total_exposure_usd() if _position_manager else 0
    bot_exp = _position_manager.get_bot_exposure_usd() if _position_manager else 0
    trace["risk"] = {
        "equity": equity,
        "total_exposure": total_exp,
        "total_exposure_pct": round(total_exp / equity * 100, 1) if equity else 0,
        "bot_exposure": bot_exp,
        "bot_exposure_pct": round(bot_exp / equity * 100, 1) if equity else 0,
        "total_open": _position_manager.open_count if _position_manager else 0,
        "bot_open": _position_manager.bot_open_count if _position_manager else 0,
        "max_positions": _risk_manager.max_positions if _risk_manager else 0,
        "max_exposure_pct": _risk_manager.max_portfolio_exposure_pct if _risk_manager else 0,
    }

    return trace


@app.get("/api/swarm/autopilot")
async def autopilot():
    return {
        "mode": cfg.exchange_mode,
        "paper": cfg.exchange_mode == "paper",
        "demo": cfg.exchange_mode == "demo",
        "live": cfg.exchange_mode == "live",
        "exchange": cfg.exchange_name,
        "running": STATE["running"],
        "paused": STATE["paused"],
    }


@app.post("/api/swarm/start")
async def swarm_start():
    global _swarm_task
    if STATE["running"]:
        return {"status": "already_running"}
    STATE["running"] = True
    STATE["paused"] = False
    STATE["emergency_stop"] = False
    _swarm_task = asyncio.create_task(_swarm_loop())
    return {"status": "started"}


@app.post("/api/swarm/stop")
async def swarm_stop():
    STATE["paused"] = True
    return {"status": "paused"}


@app.post("/api/swarm/resume")
async def swarm_resume():
    STATE["paused"] = False
    return {"status": "resumed"}


@app.post("/api/swarm/emergency-stop")
async def emergency_stop():
    STATE["emergency_stop"] = True
    STATE["paused"] = True
    results = []
    if _position_manager:
        results = await _position_manager.emergency_close_all()
    if _alerts:
        await _alerts.send("🚨 EMERGENCY STOP — all positions closed.", priority="critical")
    return {"status": "emergency_stop", "positions_closed": len(results)}


@app.post("/api/swarm/close-all-positions")
async def close_all_positions():
    """Market-sell ALL exchange holdings (demo/live mode).
    Works even after restart when in-memory position manager is empty.
    Also closes any in-memory tracked positions.
    """
    sells = []
    errors = []

    # 1) Close in-memory tracked positions first
    if _position_manager:
        tracked = await _position_manager.emergency_close_all()
        sells.extend([{"source": "tracked", "symbol": r.get("symbol"), "pnl": r.get("pnl_usd")} for r in tracked])

    # 2) In demo/live mode, sweep the exchange for any remaining holdings
    if _uses_exchange_account_state() and _exchange:
        try:
            balance = await _exchange.fetch_balance()
            markets = _exchange.exchange.markets or {}
            for currency, amounts in balance.items():
                if currency in ("USDT", "free", "used", "total", "info", "timestamp", "datetime"):
                    continue
                amount = _extract_balance_amount(amounts)
                if amount <= 1e-8:
                    continue
                symbol = f"{currency}/USDT"
                if symbol not in markets:
                    continue
                logger.info(f"[CloseAll] Market selling {amount:.6f} {currency} ({symbol})")
                try:
                    order = await _exchange.create_market_sell(symbol, amount)
                    sells.append({"source": "exchange", "symbol": symbol, "amount": amount, "order_id": order.get("id")})
                except Exception as e:
                    logger.error(f"[CloseAll] Sell failed for {symbol}: {e}")
                    errors.append({"symbol": symbol, "error": str(e)})
        except Exception as e:
            logger.error(f"[CloseAll] Balance fetch failed: {e}")
            errors.append({"error": f"balance_fetch: {e}"})

    STATE["paused"] = False  # Resume so the bot can find new momentum trades
    STATE["emergency_stop"] = False

    if _alerts and sells:
        await _alerts.send(
            f"🔄 CLOSED ALL POSITIONS — {len(sells)} sold, {len(errors)} errors. Bot resumed.",
            priority="high",
        )

    return {"status": "closed", "sold": len(sells), "errors": len(errors), "details": sells}


# ── Portfolio ────────────────────────────────────────────────────────────────
@app.get("/api/portfolio")
async def portfolio():
    if _uses_exchange_account_state():
        snapshot = await _get_exchange_account_snapshot()
        health = _risk_manager.check_portfolio_health(snapshot["equity"]) if _risk_manager else {}

        # PnL from equity snapshots = exchange ground truth (accounts for ALL
        # equity changes: realized, unrealized, fees). Falls back to exchange
        # fill FIFO only when no DB snapshots exist yet.
        eq = snapshot["equity"]
        if _db is not None:
            pnl_data = await _compute_pnl_from_equity_snapshots(eq)
        else:
            pnl_data = await _compute_cumulative_exchange_pnl()
        total_pnl = pnl_data["pnl"]
        day_pnl = pnl_data["day_pnl"]

        # Keep STATE in sync so swarm/status also shows real PnL
        STATE["total_pnl_usd"] = total_pnl
        STATE["day_pnl_usd"] = day_pnl

        # Update equity tracking
        if eq > 0:
            STATE["current_equity"] = eq
            if eq > STATE.get("peak_equity", 0):
                STATE["peak_equity"] = eq
            if _risk_manager:
                _risk_manager.update_peak_equity(eq)

        return {
            "equity": eq,
            "peak_equity": STATE.get("peak_equity", eq),
            "total_pnl_usd": round(total_pnl, 2),
            "day_pnl_usd": round(day_pnl, 2),
            "cash_usd": snapshot["cash_usd"],
            "open_positions": snapshot["open_positions"],
            "open_count": snapshot["open_count"],
            "exposure_usd": snapshot["exposure_usd"],
            "health": health,
            "source": snapshot["source"],
        }
    open_pos = _position_manager.get_open_positions() if _position_manager else []
    health = _risk_manager.check_portfolio_health(STATE["current_equity"]) if _risk_manager else {}
    return {
        "equity": STATE["current_equity"],
        "peak_equity": STATE.get("peak_equity", STATE["current_equity"]),
        "total_pnl_usd": round(STATE["total_pnl_usd"], 2),
        "day_pnl_usd": round(STATE["day_pnl_usd"], 2),
        "open_positions": open_pos,
        "open_count": len(open_pos),
        "exposure_usd": _position_manager.get_total_exposure_usd() if _position_manager else 0.0,
        "health": health,
        "source": "internal",
    }


@app.get("/api/positions")
async def get_positions():
    if _uses_exchange_account_state():
        snapshot = await _get_exchange_account_snapshot()
        return {"positions": snapshot["open_positions"], "source": snapshot["source"]}
    if not _position_manager:
        return {"positions": []}
    return {"positions": _position_manager.get_open_positions(), "source": "internal"}


@app.post("/api/positions/sync-holdings")
async def sync_holdings():
    """Import existing exchange coin holdings as tracked positions.
    Skips coins already tracked. Creates a synthetic position at current price
    so the bot can manage exits/trailing stops going forward.
    """
    if not _position_manager or not _exchange:
        return {"error": "Agents not ready", "synced": []}

    synced = []
    skipped = []
    errors = []

    try:
        balance = await _exchange.fetch_balance()
        markets = _exchange.exchange.markets or {}
        already_tracked = _position_manager.get_open_symbols()

        for currency, amounts in balance.items():
            if currency in ("USDT", "free", "used", "total", "info", "timestamp", "datetime"):
                continue
            if not isinstance(amounts, dict):
                continue

            amount = float(amounts.get("total", 0) or amounts.get("free", 0) or 0)
            if amount < 1e-8:
                continue

            symbol = f"{currency}/USDT"
            if symbol not in markets:
                skipped.append({"symbol": symbol, "reason": "not_listed"})
                continue

            if symbol in already_tracked:
                skipped.append({"symbol": symbol, "reason": "already_tracked"})
                continue

            try:
                ticker = await _exchange.fetch_ticker(symbol)
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price <= 0:
                    skipped.append({"symbol": symbol, "reason": "no_price"})
                    continue

                amount_usd = amount * price
                if amount_usd < 1.0:
                    skipped.append({"symbol": symbol, "reason": f"too_small_${amount_usd:.2f}"})
                    continue

                regime_params = STATE.get("regime_params") or {}
                sl_pct = float(regime_params.get("stop_loss_pct", cfg.stop_loss_pct))
                stop_loss = price * (1 + sl_pct / 100.0)

                trail_activate = float(regime_params.get("trailing_activate_pct", cfg.trailing_stop_activate_pct))
                trail_dist = float(regime_params.get("trailing_distance_pct", cfg.trailing_stop_distance_pct))

                risk_per_unit = price - stop_loss
                take_profit_1 = price + 2.0 * risk_per_unit
                take_profit_2 = price + 5.0 * risk_per_unit

                from src.position_manager import Position
                pos = Position(
                    symbol=symbol,
                    entry_price=price,
                    amount=amount,
                    amount_usd=amount_usd,
                    stop_loss=stop_loss,
                    take_profit_1=take_profit_1,
                    take_profit_2=take_profit_2,
                    setup_type="synced_holding",
                    entry_fill={"filled_price": price, "filled_amount": amount, "amount_usd": amount_usd, "fee_usd": 0.0},
                )
                _position_manager._positions[pos.id] = pos
                from src.metrics import active_positions
                active_positions.set(len(_position_manager._positions))

                synced.append({
                    "symbol": symbol,
                    "amount": amount,
                    "amount_usd": round(amount_usd, 2),
                    "entry_price": price,
                    "stop_loss": round(stop_loss, 6),
                    "take_profit_1": round(take_profit_1, 6),
                })
                logger.info(
                    f"[SyncHoldings] Imported {symbol}: "
                    f"qty={amount:.6f} price={price:.6f} value=${amount_usd:.2f}"
                )
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
                logger.warning(f"[SyncHoldings] Failed to import {symbol}: {e}")

    except Exception as e:
        logger.error(f"[SyncHoldings] Balance fetch failed: {e}")
        return {"error": str(e), "synced": [], "skipped": [], "errors": []}

    return {
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "total_synced": len(synced),
        "total_open": _position_manager.open_count,
    }


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    db_trades: list = []

    # Priority 1: DB trades — actual bot close events (stop_loss, tp1, tp2, trailing…)
    if _db is not None:
        try:
            cursor = _db.trades.find(
                {"exchange": cfg.exchange_name},
                {"_id": 0},
                sort=[("saved_at", -1)],
                limit=limit,
            )
            db_trades = await cursor.to_list(length=limit)
        except Exception as e:
            logger.debug(f"Trades DB fetch error: {e}")

    # If DB is fully populated return it directly
    if len(db_trades) >= limit:
        return {"trades": db_trades, "source": "db"}

    # Priority 2: supplement with exchange fills when DB is sparse (new session / few closes)
    if _uses_exchange_account_state():
        try:
            remaining = limit - len(db_trades)
            exchange_fills = await _get_exchange_trade_history(remaining)
            # Avoid showing exchange fills that duplicate a DB entry (same symbol+close_reason)
            db_ids = {(t.get("symbol"), t.get("close_reason")) for t in db_trades}
            extra = [f for f in exchange_fills
                     if (f.get("symbol"), f.get("close_reason")) not in db_ids]
            merged = db_trades + extra
            if merged:
                return {"trades": merged, "source": "db+exchange" if db_trades else "exchange"}
        except Exception as e:
            logger.debug(f"Exchange trades fetch error: {e}")

    if db_trades:
        return {"trades": db_trades, "source": "db"}

    # Priority 3: In-memory closed history (paper/backtest mode, no DB)
    if _position_manager:
        history = _position_manager.get_closed_history(limit)
        if history:
            return {"trades": history, "source": "internal"}

    return {"trades": [], "source": "none"}


@app.get("/api/equity/history")
async def equity_history(since: int = 0):
    """
    Return equity history. If `since` timestamp is provided, returns MongoDB
    historical data from that timestamp. Otherwise returns in-session history.
    
    Query params:
      since: unix timestamp. If 0 or missing, returns current session.
    """
    history = STATE.get("equity_history", [])
    peak = STATE.get("peak_equity", 0)

    if since > 0 and _db is not None:
        # Fetch from persistent store for historical intervals
        try:
            cursor = _db.equity_snapshots.find(
                {"t": {"$gte": since}},
                {"_id": 0, "t": 1, "v": 1}
            ).sort("t", 1).limit(2000)
            db_hist = await cursor.to_list(length=2000)
            if db_hist:
                history = [{"t": p["t"], "v": p["v"]} for p in db_hist]
                peak = max((p["v"] for p in history), default=peak)
        except Exception as e:
            logger.debug(f"[equity/history] DB query error: {e}")

    return {"history": history, "current": STATE["current_equity"], "peak": peak}


@app.get("/api/performance")
async def get_performance():
    health = _risk_manager.check_portfolio_health(STATE["current_equity"]) if _risk_manager else {}
    return {
        "health": health,
        "total_pnl_usd": round(STATE["total_pnl_usd"], 2),
        "day_pnl_usd": round(STATE["day_pnl_usd"], 2),
        "equity": STATE["current_equity"],
        "regime": STATE["regime"],
        "mode": STATE.get("bigbrother_mode", "normal"),
    }


@app.get("/api/metrics/performance")
async def get_metrics_performance():
    """Rolling 7d/30d metrics, equity curve, drawdown, win-rate alerts."""
    tracker = PerformanceTracker(db=_db)
    return await tracker.get_current_metrics()


@app.get("/api/metrics/daily")
async def get_metrics_daily():
    """Today's summary: trades, open positions, daily PnL, alerts."""
    tracker = PerformanceTracker(db=_db)
    return await tracker.get_daily_summary()


# ── Agents ───────────────────────────────────────────────────────────────────
@app.get("/api/agents")
async def get_agents():
    cycle = STATE["cycle_count"]
    bb_mode = STATE.get("bigbrother_mode", "normal")
    return {
        "watcher": {
            "status": "ok" if (_watcher and getattr(_watcher, "_scan_count", 0) > 0) else "idle",
            "runs": getattr(_watcher, "_scan_count", 0) if _watcher else 0,
            "errors": 0,
            "last_run": STATE.get("last_cycle_at"),
        },
        "analyzer": {
            "status": "ok" if cycle > 0 else "idle",
            "runs": cycle,
            "errors": 0,
            "min_score": _min_score_live,
        },
        "context": {
            **(_context.get_stats() if _context else {}),
            "status": "idle" if (_context and not _context.enabled) else ("ok" if _context else "idle"),
            "runs": getattr(_context, "_call_count", 0) if _context else 0,
            "errors": 0,
        },
        "bayesian": {
            **(_bayesian.get_status() if _bayesian else {}),
            "status": "warning" if bb_mode in ("safety", "paused") else "ok",
            "runs": cycle,
            "errors": 0,
        },
        "risk_manager": {
            "status": "ok",
            "runs": cycle,
            "errors": 0,
            "mode": bb_mode,
        },
        "position_manager": {
            "status": "ok",
            "runs": cycle,
            "errors": 0,
            "open": _position_manager.open_count if _position_manager else 0,
        },
        "bigbrother": {
            **(_bigbrother.get_status_summary() if _bigbrother else {}),
            "status": "ok" if bb_mode == "normal" else "warning",
            "runs": cycle,
            "errors": 0,
        },
        "quant_mutator": {
            "status": "ok",
            "runs": cycle,
            "errors": 0,
            "current_min_score": _min_score_live,
            "current_threshold": _bayesian_threshold_live,
        },
    }


@app.get("/api/feed")
async def get_feed():
    return {
        "candidates": STATE.get("last_watcher_candidates", [])[:10],
        "setups": STATE.get("last_setups", [])[:5],
        "decisions": STATE.get("last_decisions", [])[:3],
        "events": STATE.get("recent_events", [])[-20:],
    }


@app.get("/api/regime")
async def get_regime():
    return {
        "regime": STATE["regime"],
        "mode": STATE.get("bigbrother_mode", "normal"),
        "params": STATE.get("regime_params", {}),
    }


# ── Settings ─────────────────────────────────────────────────────────────────
@app.get("/api/settings")
async def get_settings_endpoint():
    return {
        "exchange": cfg.exchange_name,
        "exchange_mode": cfg.exchange_mode,
        "max_positions": cfg.max_positions,
        "max_portfolio_exposure_pct": cfg.max_portfolio_exposure_pct,
        "max_portfolio_pct": cfg.max_portfolio_exposure_pct,
        "daily_loss_limit_usd": round(STATE["current_equity"] * cfg.daily_loss_limit_pct, 2),
        "max_drawdown_pct": cfg.max_drawdown_pct,
        "stop_loss_pct": cfg.stop_loss_pct,
        "trailing_activate_pct": cfg.trailing_stop_activate_pct,
        "trailing_distance_pct": cfg.trailing_stop_distance_pct,
        "take_profit_t1_pct": cfg.tier1_exit_pct,
        "take_profit_t2_pct": cfg.tier2_exit_pct,
        "time_exit_hours": cfg.time_exit_hours,
        "min_score": _min_score_live,
        "min_watcher_score": cfg.watcher_min_volume_24h_usd,
        "min_ta_score": _min_score_live,
        "min_posterior": _bayesian_threshold_live,
        "bayesian_threshold": _bayesian_threshold_live,
        "cycle_interval_seconds": cfg.cycle_interval_seconds,
        "context_agent_enabled": cfg.context_agent_enabled,
        "pyramid_enabled": cfg.pyramid_enabled,
    }


# ── TinyClaw (AI orchestrator passthrough) ────────────────────────────────────
@app.post("/api/tc/api/message")
async def tc_message(payload: dict):
    """Handle TinyClaw natural language commands."""
    user_msg = payload.get("message", "")
    agent_id = payload.get("agentId", "bigbrother")
    response_text = await _process_tc_command(user_msg)
    return {
        "responseText": response_text,
        "agentId": agent_id,
        "timestamp": int(time.time()),
    }


async def _process_tc_command(message: str) -> str:
    msg = message.lower().strip()

    if any(k in msg for k in ["pnl", "profit", "loss", "performance"]):
        return (
            f"Total PnL: ${STATE['total_pnl_usd']:+.2f} | "
            f"Today: ${STATE['day_pnl_usd']:+.2f} | "
            f"Equity: ${STATE['current_equity']:.2f}"
        )
    if any(k in msg for k in ["position", "open", "holding"]):
        poss = _position_manager.get_open_positions() if _position_manager else []
        if not poss:
            return "No open positions currently."
        lines = [f"• {p['symbol']}: entry={p['entry_price']:.6f} size=${p['amount_usd']:.2f}" for p in poss]
        return f"{len(poss)} open positions:\n" + "\n".join(lines)
    if any(k in msg for k in ["regime", "market", "trend"]):
        return f"Current regime: *{STATE['regime']}* | Mode: *{STATE.get('bigbrother_mode', 'normal')}*"
    if any(k in msg for k in ["win rate", "winrate", "accuracy"]):
        health = _risk_manager.check_portfolio_health(STATE["current_equity"]) if _risk_manager else {}
        wr = health.get("win_rate", 0.0)
        return f"Win rate: {wr:.1%} over {health.get('total_trades', 0)} trades."
    if any(k in msg for k in ["pause", "stop trading"]):
        STATE["paused"] = True
        return "Trading paused. Use /resume to restart."
    if any(k in msg for k in ["resume", "start trading"]):
        STATE["paused"] = False
        return "Trading resumed."
    if "emergency" in msg:
        STATE["emergency_stop"] = True
        return "Emergency stop initiated. All positions will be closed."

    # Fallback to LLM
    if _bigbrother and cfg.openrouter_api_key:
        context_str = (
            f"Moonshot-CEX status: regime={STATE['regime']} mode={STATE.get('bigbrother_mode')} "
            f"equity=${STATE['current_equity']:.2f} pnl=${STATE['total_pnl_usd']:+.2f} "
            f"open_positions={_position_manager.open_count if _position_manager else 0}"
        )
        trade_context = {"symbol": "general", "setup_type": "inquiry", "context": {}, "decision": {}}
        explanation = await _bigbrother.explain_decision({"symbol": "swarm", "question": message, **trade_context})
        return explanation or "I'm monitoring the markets. Ask about PnL, positions, regime, or win rate."

    return "Moonshot-CEX swarm is running. Ask about PnL, positions, regime, or win rate."


@app.get("/api/tc/agents")
async def tc_agents():
    return {
        "agents": [
            {"id": "bigbrother", "name": "BigBrother", "role": "Supervisor"},
            {"id": "watcher", "name": "Watcher", "role": "Scanner"},
            {"id": "analyzer", "name": "Analyzer", "role": "TA Agent"},
            {"id": "bayesian", "name": "Bayesian Engine", "role": "Decision"},
            {"id": "risk", "name": "Risk Manager", "role": "Risk Control"},
        ]
    }


# ── Prometheus metrics ────────────────────────────────────────────────────────
@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest().decode("utf-8")


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        await ws.send_text(json.dumps(await _build_ws_payload()))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=cfg.api_host,
        port=cfg.api_port,
        reload=False,
        log_level=cfg.log_level.lower(),
    )
