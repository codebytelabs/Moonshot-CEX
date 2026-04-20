import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from loguru import logger
from pydantic import BaseModel, Field

_SUPPORTED_STRATEGIES = {"ema_trend", "vwap_momentum", "bb_squeeze", "bb_mean_rev"}
_SETUP_TO_STRATEGY = {
    "ema_trend": "ema_trend",
    "ema_trend_follow": "ema_trend",
    "vwap_momentum": "vwap_momentum",
    "vwap_momentum_breakout": "vwap_momentum",
    "bb_squeeze": "bb_squeeze",
    "bb_squeeze_breakout": "bb_squeeze",
    "bb_mean_rev": "bb_mean_rev",
    "bb_mean_reversion": "bb_mean_rev",
}


class ChironProposal(BaseModel):
    kind: str
    key: str
    current_value: Any = None
    proposed_value: Any = None
    setup_type: Optional[str] = None
    strategy: Optional[str] = None
    regime: Optional[str] = None
    reason: str
    risk_tier: str = "low"
    action: str = "suggest"
    evidence: dict = Field(default_factory=dict)


class ChironCoach:
    def __init__(
        self,
        db,
        risk_manager=None,
        regime_engine=None,
        openrouter_api_key: Optional[str] = None,
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        openrouter_model: str = "anthropic/claude-haiku-4.5",
        openrouter_fallback_model: str = "google/gemini-3.1-flash-lite-preview",
        enabled: bool = True,
        llm_enabled: bool = True,
        interval_hours: int = 6,
        lookback_hours: int = 72,
        override_ttl_hours: int = 12,
        min_trades_per_bucket: int = 8,
        min_total_trades: int = 16,
        param_cooldown_hours: int = 24,
        max_proposals_per_run: int = 6,
        auto_apply_low_risk: bool = True,
        promotion_enabled: bool = True,
        promotion_file_path: str = "config/chiron_promotions.json",
        promotion_min_occurrences: int = 3,
        promotion_lookback_runs: int = 8,
        repo_path: Optional[str] = None,
        git_auto_commit: bool = False,
        git_auto_push: bool = False,
        git_remote: str = "origin",
        git_branch: str = "main",
        git_committer_name: str = "Chiron Bot",
        git_committer_email: str = "chiron@moonshot.local",
    ):
        self.db = db
        self.risk_manager = risk_manager
        self.regime_engine = regime_engine
        self.api_key = openrouter_api_key or ""
        self.base_url = openrouter_base_url.rstrip("/")
        self.model = openrouter_model
        self.fallback_model = openrouter_fallback_model
        self.enabled = enabled
        self.llm_enabled = llm_enabled
        self.interval_hours = max(1, int(interval_hours))
        self.lookback_hours = max(6, int(lookback_hours))
        self.override_ttl_hours = max(1, int(override_ttl_hours))
        self.min_trades_per_bucket = max(3, int(min_trades_per_bucket))
        self.min_total_trades = max(self.min_trades_per_bucket, int(min_total_trades))
        self.param_cooldown_hours = max(1, int(param_cooldown_hours))
        self.max_proposals_per_run = max(1, int(max_proposals_per_run))
        self.auto_apply_low_risk = auto_apply_low_risk
        self.promotion_enabled = promotion_enabled
        self.promotion_min_occurrences = max(2, int(promotion_min_occurrences))
        self.promotion_lookback_runs = max(
            self.promotion_min_occurrences,
            int(promotion_lookback_runs),
        )
        self.repo_path = Path(repo_path).resolve() if repo_path else Path(__file__).resolve().parent.parent
        raw_promotion_path = Path(promotion_file_path)
        self.promotion_file_path = (
            raw_promotion_path
            if raw_promotion_path.is_absolute()
            else self.repo_path / raw_promotion_path
        )
        self.git_auto_commit = git_auto_commit
        self.git_auto_push = git_auto_push
        self.git_remote = git_remote
        self.git_branch = git_branch
        self.git_committer_name = git_committer_name
        self.git_committer_email = git_committer_email
        self._param_last_changed: dict[str, int] = {}
        self._history: list[dict] = []
        self._last_promotion: dict = {
            "status": "idle",
            "enabled": self.promotion_enabled,
            "file_path": str(self.promotion_file_path),
            "artifact": _default_promotion_artifact(),
            "promoted_keys": [],
            "git": {},
        }
        self._last_run: dict = {
            "ok": False,
            "status": "idle",
            "enabled": enabled,
            "interval_hours": self.interval_hours,
            "lookback_hours": self.lookback_hours,
            "last_run_at": None,
            "proposals": [],
            "applied_overrides": {},
        }

    def get_state(self) -> dict:
        return {
            **self._last_run,
            "enabled": self.enabled,
            "llm_enabled": self.llm_enabled,
            "history": list(self._history[-10:]),
            "promotion": dict(self._last_promotion),
        }

    async def review(
        self,
        current_regime: str,
        current_equity: float,
        current_min_score: float,
        current_bayesian_threshold: float,
    ) -> dict:
        started_at = int(time.time())
        if not self.enabled:
            run = {
                "ok": False,
                "status": "disabled",
                "enabled": False,
                "last_run_at": started_at,
                "proposals": [],
                "applied_overrides": {},
            }
            self._remember(run)
            return run

        try:
            snapshot = await self.observe(current_regime=current_regime, current_equity=current_equity)
            reflection = await self.reflect(snapshot)
            proposals = self.propose(
                snapshot=snapshot,
                current_min_score=current_min_score,
                current_bayesian_threshold=current_bayesian_threshold,
            )
            applied_overrides = self.select_applied_overrides(proposals)
            run = {
                "ok": True,
                "status": "ok",
                "enabled": True,
                "last_run_at": started_at,
                "interval_hours": self.interval_hours,
                "lookback_hours": self.lookback_hours,
                "snapshot": snapshot,
                "reflection": reflection,
                "proposals": [p.model_dump() for p in proposals],
                "applied_overrides": applied_overrides,
            }
            if self.db is not None:
                try:
                    await self.db.chiron_runs.insert_one(dict(run))
                except Exception as exc:
                    logger.debug(f"[Chiron] run save error: {exc}")
            run["promotion"] = await self.promote()
            self._remember(run)
            return run
        except Exception as exc:
            logger.error(f"[Chiron] review failed: {exc}")
            run = {
                "ok": False,
                "status": "error",
                "enabled": True,
                "last_run_at": started_at,
                "error": str(exc),
                "proposals": [],
                "applied_overrides": {},
            }
            self._remember(run)
            return run

    async def observe(self, current_regime: str, current_equity: float) -> dict:
        now = int(time.time())
        since = now - self.lookback_hours * 3600
        trade_docs: list[dict] = []
        equity_docs: list[dict] = []

        if self.db is not None:
            cursor = self.db.trades.find(
                {"saved_at": {"$gte": since}, "pnl_usd": {"$exists": True}},
                {
                    "_id": 0,
                    "setup_type": 1,
                    "strategy": 1,
                    "regime": 1,
                    "pnl_usd": 1,
                    "pnl_pct": 1,
                    "close_reason": 1,
                    "hold_time_hours": 1,
                    "saved_at": 1,
                    "closed_at": 1,
                },
                sort=[("saved_at", 1)],
                limit=2000,
            )
            trade_docs = await cursor.to_list(length=2000)
            eq_cursor = self.db.equity_snapshots.find(
                {"t": {"$gte": since}},
                {"_id": 0, "t": 1, "v": 1},
                sort=[("t", 1)],
                limit=1000,
            )
            equity_docs = await eq_cursor.to_list(length=1000)

        by_setup: dict[str, list[dict]] = {}
        by_regime_setup: dict[str, list[dict]] = {}
        by_regime_strategy: dict[str, list[dict]] = {}

        for doc in trade_docs:
            setup_type = str(doc.get("setup_type") or doc.get("strategy") or "unknown")
            regime = str(doc.get("regime") or "unknown")
            strategy = _resolve_strategy(doc)
            by_setup.setdefault(setup_type, []).append(doc)
            by_regime_setup.setdefault(f"{regime}|{setup_type}", []).append(doc)
            if strategy:
                by_regime_strategy.setdefault(f"{regime}|{strategy}", []).append(doc)

        return {
            "observed_at": now,
            "since_ts": since,
            "current_regime": current_regime,
            "current_equity": round(_safe_float(current_equity), 2),
            "trade_count": len(trade_docs),
            "overall": _bucket_stats(trade_docs),
            "by_setup": {key: _bucket_stats(docs) for key, docs in by_setup.items()},
            "by_regime_setup": {
                key: _bucket_stats(docs) for key, docs in by_regime_setup.items()
            },
            "by_regime_strategy": {
                key: _bucket_stats(docs) for key, docs in by_regime_strategy.items()
            },
            "equity": _equity_stats(equity_docs, current_equity),
        }

    async def reflect(self, snapshot: dict) -> dict:
        if (
            not self.llm_enabled
            or not self.api_key
            or snapshot.get("trade_count", 0) < self.min_total_trades
        ):
            return {}

        payload = {
            "current_regime": snapshot.get("current_regime"),
            "current_equity": snapshot.get("current_equity"),
            "overall": snapshot.get("overall", {}),
            "equity": snapshot.get("equity", {}),
            "by_setup": snapshot.get("by_setup", {}),
            "by_regime_strategy": snapshot.get("by_regime_strategy", {}),
        }
        prompt = (
            "You are CHIRON, a conservative quant trading coach. "
            "Analyze this trading bot snapshot and return ONLY valid JSON with keys "
            '"findings" and "warnings". Each finding must have "observation", "confidence", and "scope". '
            "Do not propose parameter values. Do not mention anything outside the provided data.\n\n"
            f"SNAPSHOT:\n{json.dumps(payload, separators=(",", ":"), sort_keys=True)}"
        )

        for model in [self.model, self.fallback_model]:
            if not model:
                continue
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://moonshot-cex.ai",
                            "X-Title": "Moonshot-CEX CHIRON",
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 600,
                            "temperature": 0.0,
                        },
                    )
                if resp.status_code != 200:
                    logger.warning(f"[Chiron] reflection HTTP {resp.status_code} via {model}")
                    continue
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                parsed = _extract_json(raw)
                if isinstance(parsed, dict):
                    parsed["model"] = model
                    return parsed
            except Exception as exc:
                logger.warning(f"[Chiron] reflection error via {model}: {exc}")
        return {}

    def propose(
        self,
        snapshot: dict,
        current_min_score: float,
        current_bayesian_threshold: float,
    ) -> list[ChironProposal]:
        proposals: list[ChironProposal] = []
        now = int(time.time())

        by_setup = snapshot.get("by_setup", {})
        by_regime_strategy = snapshot.get("by_regime_strategy", {})
        overall = snapshot.get("overall", {})

        for setup_type, stats in by_setup.items():
            trades = int(stats.get("trades", 0))
            smoothed_wr = _safe_float(stats.get("smoothed_win_rate"), 0.5)
            pnl_usd = _safe_float(stats.get("pnl_usd"), 0.0)
            profit_factor = _safe_float(stats.get("profit_factor"), 0.0)
            if trades < self.min_trades_per_bucket:
                continue

            current_mult = 1.0
            if self.risk_manager and hasattr(self.risk_manager, "get_effective_setup_size_multiplier"):
                current_mult = _safe_float(
                    self.risk_manager.get_effective_setup_size_multiplier(setup_type),
                    1.0,
                )

            if pnl_usd < 0 and smoothed_wr < 0.42:
                target_mult = round(max(0.25, current_mult - (0.15 if smoothed_wr < 0.30 else 0.10)), 2)
                if target_mult < current_mult and self._cooldown_allows(f"setup_size_mult:{setup_type}", now):
                    proposals.append(
                        ChironProposal(
                            kind="setup_size_mult",
                            key=f"setup_size_mult:{setup_type}",
                            current_value=current_mult,
                            proposed_value=target_mult,
                            setup_type=setup_type,
                            reason="negative expectancy in recent window",
                            risk_tier="low",
                            action="auto_apply" if self.auto_apply_low_risk else "suggest",
                            evidence={
                                "trades": trades,
                                "smoothed_win_rate": round(smoothed_wr, 3),
                                "profit_factor": round(profit_factor, 3),
                                "pnl_usd": round(pnl_usd, 2),
                            },
                        )
                    )
                if smoothed_wr <= 0.25 and self._cooldown_allows(f"setup_pause:{setup_type}", now):
                    proposals.append(
                        ChironProposal(
                            kind="setup_pause",
                            key=f"setup_pause:{setup_type}",
                            current_value=0,
                            proposed_value=self.interval_hours * 60,
                            setup_type=setup_type,
                            reason="recent setup quality collapsed",
                            risk_tier="low",
                            action="auto_apply" if self.auto_apply_low_risk else "suggest",
                            evidence={
                                "trades": trades,
                                "smoothed_win_rate": round(smoothed_wr, 3),
                                "pnl_usd": round(pnl_usd, 2),
                            },
                        )
                    )
            elif pnl_usd > 0 and smoothed_wr >= 0.62 and profit_factor >= 1.20:
                target_mult = round(min(1.25, current_mult + 0.10), 2)
                if target_mult > current_mult and self._cooldown_allows(f"setup_size_mult:{setup_type}", now):
                    proposals.append(
                        ChironProposal(
                            kind="setup_size_mult",
                            key=f"setup_size_mult:{setup_type}",
                            current_value=current_mult,
                            proposed_value=target_mult,
                            setup_type=setup_type,
                            reason="strong positive expectancy in recent window",
                            risk_tier="medium",
                            action="suggest",
                            evidence={
                                "trades": trades,
                                "smoothed_win_rate": round(smoothed_wr, 3),
                                "profit_factor": round(profit_factor, 3),
                                "pnl_usd": round(pnl_usd, 2),
                            },
                        )
                    )

        for bucket_key, stats in by_regime_strategy.items():
            trades = int(stats.get("trades", 0))
            if trades < self.min_trades_per_bucket or "|" not in bucket_key:
                continue
            regime, strategy = bucket_key.split("|", 1)
            smoothed_wr = _safe_float(stats.get("smoothed_win_rate"), 0.5)
            pnl_usd = _safe_float(stats.get("pnl_usd"), 0.0)
            profit_factor = _safe_float(stats.get("profit_factor"), 0.0)
            current_mult = 1.0
            if self.regime_engine and hasattr(self.regime_engine, "get_runtime_weight_multiplier"):
                current_mult = _safe_float(
                    self.regime_engine.get_runtime_weight_multiplier(regime, strategy),
                    1.0,
                )

            if pnl_usd < 0 and smoothed_wr < 0.40 and self._cooldown_allows(f"regime_weight_mult:{regime}:{strategy}", now):
                target_mult = round(max(0.50, current_mult - (0.20 if smoothed_wr < 0.28 else 0.10)), 2)
                if target_mult < current_mult:
                    proposals.append(
                        ChironProposal(
                            kind="regime_weight_mult",
                            key=f"regime_weight_mult:{regime}:{strategy}",
                            current_value=current_mult,
                            proposed_value=target_mult,
                            regime=regime,
                            strategy=strategy,
                            reason="regime-strategy pairing degraded",
                            risk_tier="low",
                            action="auto_apply" if self.auto_apply_low_risk else "suggest",
                            evidence={
                                "trades": trades,
                                "smoothed_win_rate": round(smoothed_wr, 3),
                                "profit_factor": round(profit_factor, 3),
                                "pnl_usd": round(pnl_usd, 2),
                            },
                        )
                    )
            elif pnl_usd > 0 and smoothed_wr >= 0.65 and profit_factor >= 1.30 and self._cooldown_allows(f"regime_weight_mult:{regime}:{strategy}", now):
                target_mult = round(min(1.20, current_mult + 0.10), 2)
                if target_mult > current_mult:
                    proposals.append(
                        ChironProposal(
                            kind="regime_weight_mult",
                            key=f"regime_weight_mult:{regime}:{strategy}",
                            current_value=current_mult,
                            proposed_value=target_mult,
                            regime=regime,
                            strategy=strategy,
                            reason="regime-strategy pairing improved",
                            risk_tier="medium",
                            action="suggest",
                            evidence={
                                "trades": trades,
                                "smoothed_win_rate": round(smoothed_wr, 3),
                                "profit_factor": round(profit_factor, 3),
                                "pnl_usd": round(pnl_usd, 2),
                            },
                        )
                    )

        total_trades = int(overall.get("trades", 0))
        overall_wr = _safe_float(overall.get("smoothed_win_rate"), 0.5)
        overall_pnl = _safe_float(overall.get("pnl_usd"), 0.0)
        overall_pf = _safe_float(overall.get("profit_factor"), 0.0)
        if total_trades >= self.min_total_trades:
            if overall_pnl < 0 and overall_wr < 0.45 and self._cooldown_allows("min_score", now):
                proposals.append(
                    ChironProposal(
                        kind="min_score",
                        key="min_score",
                        current_value=round(current_min_score, 1),
                        proposed_value=round(min(80.0, current_min_score + 2.0), 1),
                        reason="recent flow quality is weak",
                        risk_tier="medium",
                        action="suggest",
                        evidence={
                            "trades": total_trades,
                            "smoothed_win_rate": round(overall_wr, 3),
                            "profit_factor": round(overall_pf, 3),
                            "pnl_usd": round(overall_pnl, 2),
                        },
                    )
                )
            elif overall_pnl > 0 and overall_wr > 0.62 and overall_pf >= 1.20 and self._cooldown_allows("min_score", now):
                proposals.append(
                    ChironProposal(
                        kind="min_score",
                        key="min_score",
                        current_value=round(current_min_score, 1),
                        proposed_value=round(max(35.0, current_min_score - 1.0), 1),
                        reason="recent flow quality supports slightly wider intake",
                        risk_tier="medium",
                        action="suggest",
                        evidence={
                            "trades": total_trades,
                            "smoothed_win_rate": round(overall_wr, 3),
                            "profit_factor": round(overall_pf, 3),
                            "pnl_usd": round(overall_pnl, 2),
                        },
                    )
                )

            if overall_pnl < 0 and overall_wr < 0.42 and self._cooldown_allows("bayesian_threshold", now):
                proposals.append(
                    ChironProposal(
                        kind="bayesian_threshold",
                        key="bayesian_threshold",
                        current_value=round(current_bayesian_threshold, 3),
                        proposed_value=round(min(0.75, current_bayesian_threshold + 0.01), 3),
                        reason="recent posterior quality is weak",
                        risk_tier="medium",
                        action="suggest",
                        evidence={
                            "trades": total_trades,
                            "smoothed_win_rate": round(overall_wr, 3),
                            "profit_factor": round(overall_pf, 3),
                            "pnl_usd": round(overall_pnl, 2),
                        },
                    )
                )

        proposals.sort(key=_proposal_sort_key)
        return proposals[: self.max_proposals_per_run]

    def select_applied_overrides(self, proposals: list[ChironProposal]) -> dict:
        now = int(time.time())
        applied = {
            "source": "chiron",
            "generated_at": now,
            "expires_at": now + self.override_ttl_hours * 3600,
            "setup_size_mult": {},
            "setup_pause_minutes": {},
            "regime_weight_mult": {},
            "proposal_keys": [],
        }

        for proposal in proposals:
            if proposal.action != "auto_apply":
                continue
            applied["proposal_keys"].append(proposal.key)
            self._param_last_changed[proposal.key] = now
            if proposal.kind == "setup_size_mult" and proposal.setup_type:
                applied["setup_size_mult"][proposal.setup_type] = float(proposal.proposed_value)
            elif proposal.kind == "setup_pause" and proposal.setup_type:
                applied["setup_pause_minutes"][proposal.setup_type] = int(proposal.proposed_value)
            elif proposal.kind == "regime_weight_mult" and proposal.regime and proposal.strategy:
                applied["regime_weight_mult"].setdefault(proposal.regime, {})[proposal.strategy] = float(proposal.proposed_value)

        if not any(
            [
                applied["setup_size_mult"],
                applied["setup_pause_minutes"],
                applied["regime_weight_mult"],
            ]
        ):
            return {}
        return applied

    def load_promoted_overrides(self) -> dict:
        artifact = _default_promotion_artifact()
        try:
            if self.promotion_file_path.exists():
                raw = json.loads(self.promotion_file_path.read_text())
                if isinstance(raw, dict):
                    artifact = _normalize_promotion_artifact(raw)
        except Exception as exc:
            logger.warning(f"[Chiron] promotion load error: {exc}")
        self._last_promotion = {
            **self._last_promotion,
            "status": "loaded" if self.promotion_file_path.exists() else "idle",
            "artifact": artifact,
            "promoted_keys": list((artifact.get("metadata") or {}).get("promoted_keys") or []),
        }
        return artifact

    async def promote(
        self,
        recent_runs: Optional[list[dict]] = None,
        force_commit: bool = False,
        push: Optional[bool] = None,
    ) -> dict:
        artifact = self.load_promoted_overrides()
        result = {
            "enabled": self.promotion_enabled,
            "status": "disabled" if not self.promotion_enabled else "noop",
            "file_path": str(self.promotion_file_path),
            "artifact": artifact,
            "promoted_keys": [],
            "git": {},
            "min_occurrences": self.promotion_min_occurrences,
            "lookback_runs": self.promotion_lookback_runs,
        }
        if not self.promotion_enabled:
            self._last_promotion = dict(result)
            return result

        runs = recent_runs if recent_runs is not None else await self._load_recent_runs()
        counts: dict[str, int] = {}
        proposals_by_signature: dict[str, dict] = {}
        for run in runs:
            for proposal in run.get("proposals", []):
                if not _proposal_is_promotable(proposal):
                    continue
                signature = _promotion_signature(proposal)
                counts[signature] = counts.get(signature, 0) + 1
                proposals_by_signature[signature] = proposal

        promoted_keys: list[str] = []
        for signature, count in counts.items():
            if count < self.promotion_min_occurrences:
                continue
            proposal = proposals_by_signature[signature]
            if _apply_promoted_proposal(artifact.setdefault("promotions", {}), proposal):
                promoted_keys.append(str(proposal.get("key") or signature))

        if promoted_keys:
            artifact["updated_at"] = int(time.time())
            artifact["metadata"] = {
                "promoted_keys": promoted_keys,
                "source": "chiron",
            }
            self._write_promotion_artifact(artifact)
            result["status"] = "updated"
            result["promoted_keys"] = promoted_keys
            result["artifact"] = artifact
            if force_commit or self.git_auto_commit:
                result["git"] = self.commit_promotions(push=push)
        elif force_commit:
            result["git"] = self.commit_promotions(push=push)

        self._last_promotion = dict(result)
        return result

    def commit_promotions(self, push: Optional[bool] = None) -> dict:
        push_enabled = self.git_auto_push if push is None else bool(push)
        repo_git_dir = self.repo_path / ".git"
        if not repo_git_dir.exists():
            return {
                "status": "not_git_repo",
                "repo_path": str(self.repo_path),
                "file_path": str(self.promotion_file_path),
            }
        rel_path = os.path.relpath(self.promotion_file_path, self.repo_path)
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_AUTHOR_NAME"] = self.git_committer_name
        env["GIT_AUTHOR_EMAIL"] = self.git_committer_email
        env["GIT_COMMITTER_NAME"] = self.git_committer_name
        env["GIT_COMMITTER_EMAIL"] = self.git_committer_email

        try:
            status_cmd = subprocess.run(
                ["git", "-C", str(self.repo_path), "status", "--porcelain", "--", rel_path],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            if status_cmd.returncode != 0:
                return {
                    "status": "error",
                    "step": "status",
                    "error": (status_cmd.stderr or status_cmd.stdout).strip(),
                }
            if not status_cmd.stdout.strip():
                return {"status": "clean", "file_path": str(self.promotion_file_path)}

            add_cmd = subprocess.run(
                ["git", "-C", str(self.repo_path), "add", "--", rel_path],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            if add_cmd.returncode != 0:
                return {
                    "status": "error",
                    "step": "add",
                    "error": (add_cmd.stderr or add_cmd.stdout).strip(),
                }

            commit_message = "chiron: promote stable runtime tuning"
            commit_cmd = subprocess.run(
                ["git", "-C", str(self.repo_path), "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                env=env,
                timeout=20,
            )
            if commit_cmd.returncode != 0:
                return {
                    "status": "error",
                    "step": "commit",
                    "error": (commit_cmd.stderr or commit_cmd.stdout).strip(),
                }

            result = {
                "status": "committed",
                "file_path": str(self.promotion_file_path),
                "branch": self.git_branch,
                "remote": self.git_remote,
            }
            if push_enabled:
                push_cmd = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.repo_path),
                        "push",
                        self.git_remote,
                        f"HEAD:{self.git_branch}",
                    ],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )
                if push_cmd.returncode != 0:
                    result.update(
                        {
                            "status": "push_error",
                            "error": (push_cmd.stderr or push_cmd.stdout).strip(),
                        }
                    )
                else:
                    result["status"] = "pushed"
            return result
        except Exception as exc:
            return {"status": "error", "step": "exception", "error": str(exc)}

    async def _load_recent_runs(self) -> list[dict]:
        if self.db is None:
            return []
        try:
            cursor = self.db.chiron_runs.find(
                {"ok": True},
                {"_id": 0, "last_run_at": 1, "proposals": 1},
                sort=[("last_run_at", -1)],
                limit=self.promotion_lookback_runs,
            )
            return await cursor.to_list(length=self.promotion_lookback_runs)
        except Exception as exc:
            logger.warning(f"[Chiron] promotion history load error: {exc}")
            return []

    def _write_promotion_artifact(self, artifact: dict):
        self.promotion_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.promotion_file_path.write_text(
            json.dumps(_normalize_promotion_artifact(artifact), indent=2, sort_keys=True) + "\n"
        )

    def _cooldown_allows(self, key: str, now: int) -> bool:
        changed_at = self._param_last_changed.get(key)
        if not changed_at:
            return True
        return (now - changed_at) >= self.param_cooldown_hours * 3600

    def _remember(self, run: dict):
        self._last_run = dict(run)
        self._history.append(
            {
                "last_run_at": run.get("last_run_at"),
                "status": run.get("status"),
                "proposal_count": len(run.get("proposals", [])),
                "applied_count": len(run.get("applied_overrides", {}).get("proposal_keys", []))
                if run.get("applied_overrides")
                else 0,
            }
        )
        self._history = self._history[-10:]


def _proposal_sort_key(proposal: ChironProposal) -> tuple[int, float, float, str]:
    tier_rank = {"low": 0, "medium": 1, "high": 2}.get(proposal.risk_tier, 3)
    evidence = proposal.evidence or {}
    trades = _safe_float(evidence.get("trades"), 0.0)
    pnl = abs(_safe_float(evidence.get("pnl_usd"), 0.0))
    return (tier_rank, -trades, -pnl, proposal.key)


def _default_promotion_artifact() -> dict:
    return {
        "version": 1,
        "updated_at": None,
        "promotions": {
            "setup_size_mult": {},
            "regime_weight_mult": {},
        },
        "metadata": {
            "promoted_keys": [],
            "source": "chiron",
        },
    }


def _normalize_promotion_artifact(raw: dict) -> dict:
    base = _default_promotion_artifact()
    promotions = raw.get("promotions") or {}
    base["version"] = int(raw.get("version") or 1)
    base["updated_at"] = raw.get("updated_at")
    base["promotions"]["setup_size_mult"] = {
        str(k): max(0.25, min(1.25, float(v)))
        for k, v in (promotions.get("setup_size_mult") or {}).items()
    }
    normalized_regime_weights: dict[str, dict[str, float]] = {}
    for regime, weights in (promotions.get("regime_weight_mult") or {}).items():
        if not isinstance(weights, dict):
            continue
        normalized_regime_weights[str(regime)] = {
            str(strategy): max(0.0, min(1.25, float(mult)))
            for strategy, mult in weights.items()
        }
    base["promotions"]["regime_weight_mult"] = normalized_regime_weights
    metadata = raw.get("metadata") or {}
    base["metadata"] = {
        "promoted_keys": list(metadata.get("promoted_keys") or []),
        "source": metadata.get("source") or "chiron",
    }
    return base


def _proposal_is_promotable(proposal: dict) -> bool:
    return (
        isinstance(proposal, dict)
        and proposal.get("risk_tier") == "low"
        and proposal.get("action") == "auto_apply"
        and proposal.get("kind") in {"setup_size_mult", "regime_weight_mult"}
    )


def _promotion_signature(proposal: dict) -> str:
    return json.dumps(
        {
            "kind": proposal.get("kind"),
            "key": proposal.get("key"),
            "value": proposal.get("proposed_value"),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _apply_promoted_proposal(promotions: dict, proposal: dict) -> bool:
    kind = str(proposal.get("kind") or "")
    if kind == "setup_size_mult" and proposal.get("setup_type"):
        setup_type = str(proposal["setup_type"])
        proposed_value = max(0.25, min(1.25, _safe_float(proposal.get("proposed_value"), 1.0)))
        current_value = _safe_float((promotions.get("setup_size_mult") or {}).get(setup_type), 1.0)
        if abs(current_value - proposed_value) < 1e-9:
            return False
        promotions.setdefault("setup_size_mult", {})[setup_type] = proposed_value
        return True
    if kind == "regime_weight_mult" and proposal.get("regime") and proposal.get("strategy"):
        regime = str(proposal["regime"])
        strategy = str(proposal["strategy"])
        proposed_value = max(0.0, min(1.25, _safe_float(proposal.get("proposed_value"), 1.0)))
        current_value = _safe_float(
            (promotions.get("regime_weight_mult") or {}).get(regime, {}).get(strategy),
            1.0,
        )
        if abs(current_value - proposed_value) < 1e-9:
            return False
        promotions.setdefault("regime_weight_mult", {}).setdefault(regime, {})[strategy] = proposed_value
        return True
    return False


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return {}
    return {}


def _resolve_strategy(doc: dict) -> Optional[str]:
    raw_strategy = str(doc.get("strategy") or "").strip()
    if raw_strategy in _SUPPORTED_STRATEGIES:
        return raw_strategy
    setup_type = str(doc.get("setup_type") or "").lower()
    for hint, strategy in _SETUP_TO_STRATEGY.items():
        if hint in setup_type:
            return strategy
    return None


def _bucket_stats(docs: list[dict], prior_strength: float = 8.0) -> dict:
    trades = len(docs)
    if trades == 0:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "smoothed_win_rate": None,
            "pnl_usd": 0.0,
            "avg_pnl_usd": None,
            "avg_pnl_pct": None,
            "avg_hold_hours": None,
            "profit_factor": None,
            "expectancy_usd": None,
        }

    pnls = [_safe_float(doc.get("pnl_usd"), 0.0) for doc in docs]
    pnl_pcts = [_safe_float(doc.get("pnl_pct"), 0.0) for doc in docs]
    holds = [
        _safe_float(doc.get("hold_time_hours"), 0.0)
        for doc in docs
        if doc.get("hold_time_hours") is not None
    ]
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = trades - wins
    gross_win = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl <= 0))
    win_rate = wins / trades if trades else None
    smoothed_win_rate = (wins + 0.5 * prior_strength) / (trades + prior_strength)
    pnl_total = sum(pnls)
    avg_pnl_usd = pnl_total / trades if trades else None
    avg_pnl_pct = sum(pnl_pcts) / trades if trades else None
    avg_hold_hours = sum(holds) / len(holds) if holds else None
    expectancy_usd = avg_pnl_usd
    profit_factor = gross_win / gross_loss if gross_loss > 0 else None
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "smoothed_win_rate": round(smoothed_win_rate, 3),
        "pnl_usd": round(pnl_total, 2),
        "avg_pnl_usd": round(avg_pnl_usd, 2) if avg_pnl_usd is not None else None,
        "avg_pnl_pct": round(avg_pnl_pct, 3) if avg_pnl_pct is not None else None,
        "avg_hold_hours": round(avg_hold_hours, 2) if avg_hold_hours is not None else None,
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "expectancy_usd": round(expectancy_usd, 2) if expectancy_usd is not None else None,
    }


def _equity_stats(equity_docs: list[dict], current_equity: float) -> dict:
    if not equity_docs:
        return {
            "points": 0,
            "start": round(_safe_float(current_equity), 2),
            "end": round(_safe_float(current_equity), 2),
            "delta_usd": 0.0,
            "delta_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }

    values = [_safe_float(doc.get("v"), 0.0) for doc in equity_docs]
    peak = values[0] if values else 0.0
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    start = values[0]
    end = values[-1]
    delta_usd = end - start
    delta_pct = (delta_usd / start) if start > 0 else 0.0
    return {
        "points": len(values),
        "start": round(start, 2),
        "end": round(end, 2),
        "delta_usd": round(delta_usd, 2),
        "delta_pct": round(delta_pct, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
