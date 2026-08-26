"""Monthly trade-frequency governor.

The strict profile produced roughly half a trade per month, which is too few to
learn anything from. Permanently lowering every threshold produced more trades
and worse PnL. This module takes the middle path: thresholds stay at their
quality settings by default and are relaxed only while the rolling 30-day count
is behind the monthly target, then tightened again once it catches up.

Only soft signal thresholds move. Risk limits, stop placement and portfolio
caps are never touched here.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PaceStatus:
    trades_in_window: int = 0
    target: int = 8
    window_days: int = 30
    state: str = "ON_TRACK"        # BEHIND | ON_TRACK | AHEAD | CAPPED
    relax_level: float = 0.0       # +1 fully relaxed, -1 fully tightened
    allow_new_entry: bool = True
    reasons: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"節奏 {self.state} ({self.trades_in_window}/{self.target} 單 / "
            f"{self.window_days}天, 放寬 {self.relax_level:+.2f})"
        )


class TradePacer:
    """Track realised entry frequency and translate the gap into threshold deltas."""

    DEFAULTS = {
        "enabled": True,
        "target_trades_per_month": 8,
        "max_trades_per_month": 12,
        "window_days": 30,
        "tolerance_pct": 25.0,
        "max_relax_level": 1.0,
        "state_file": "data/trade_pacing.json",
        # Full-relax deltas, scaled linearly by relax_level.
        "relax_deltas": {
            "strong_min_confluence": -1,
            "moderate_min_confluence": -1,
            "moderate_min_edges": -1,
            "rsi_max": 4.0,
            "reject_rsi_above": 2.0,
            "zscore_max": 0.15,
            "zscore_min": -0.10,
            "min_candle_strength": -0.08,
            "min_vol_ratio_high": -0.10,
            "retail_min_score": -1,
        },
        # Floors so relaxation can never disable a gate entirely.
        "floors": {
            "strong_min_confluence": 3,
            "moderate_min_confluence": 3,
            "moderate_min_edges": 3,
            "zscore_min": 0.30,
            "min_candle_strength": 0.20,
            "min_vol_ratio_high": 1.0,
            "retail_min_score": 4,
        },
        "ceilings": {
            "rsi_max": 78.0,
            "reject_rsi_above": 82.0,
            "zscore_max": 1.80,
        },
    }

    def __init__(self, config=None, state_file=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        cfg["relax_deltas"] = {
            **self.DEFAULTS["relax_deltas"],
            **((config or {}).get("relax_deltas") or {}),
        }
        cfg["floors"] = {**self.DEFAULTS["floors"], **((config or {}).get("floors") or {})}
        cfg["ceilings"] = {**self.DEFAULTS["ceilings"], **((config or {}).get("ceilings") or {})}
        self.cfg = cfg
        path = state_file if state_file is not None else cfg["state_file"]
        # A falsy path keeps the pacer purely in memory (backtests, tests).
        self.state_file = Path(path) if path else None
        self._entries: list[datetime] = []
        self._load()

    # ----- persistence -----

    def _load(self):
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("交易節奏狀態讀取失敗: %s", exc)
            return
        for raw in payload.get("entries", []):
            try:
                self._entries.append(datetime.fromisoformat(raw))
            except (TypeError, ValueError):
                continue

    def _save(self):
        if self.state_file is None:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(
                    {"entries": [d.isoformat() for d in self._entries[-200:]]},
                    indent=2,
                )
            )
        except OSError as exc:
            logger.warning("交易節奏狀態寫入失敗: %s", exc)

    # ----- bookkeeping -----

    def record_entry(self, when=None, persist=True):
        self._entries.append(when or datetime.now())
        if persist:
            self._save()

    def reset(self):
        self._entries = []
        self._save()

    def count_in_window(self, now=None):
        now = now or datetime.now()
        cutoff = now - timedelta(days=int(self.cfg["window_days"]))
        return sum(1 for entry in self._entries if entry >= cutoff)

    # ----- pacing decision -----

    def status(self, now=None) -> PaceStatus:
        target = int(self.cfg["target_trades_per_month"])
        window = int(self.cfg["window_days"])
        count = self.count_in_window(now)
        status = PaceStatus(trades_in_window=count, target=target, window_days=window)

        if not self.cfg.get("enabled", True):
            status.state = "ON_TRACK"
            status.reasons = ["pacing disabled"]
            return status

        hard_cap = int(self.cfg["max_trades_per_month"])
        if count >= hard_cap:
            status.state = "CAPPED"
            status.relax_level = -1.0
            status.allow_new_entry = False
            status.reasons = [f"已達月上限 {hard_cap} 單，停止新倉"]
            return status

        tolerance = max(1.0, target * float(self.cfg["tolerance_pct"]) / 100.0)
        gap = target - count
        max_relax = float(self.cfg["max_relax_level"])

        if gap > tolerance:
            status.state = "BEHIND"
            status.relax_level = min(max_relax, gap / max(1, target))
            status.reasons = [f"落後目標 {gap} 單，放寬軟性門檻"]
        elif gap < -tolerance:
            status.state = "AHEAD"
            status.relax_level = max(-1.0, gap / max(1, target))
            status.reasons = [f"超前目標 {-gap} 單，收緊門檻"]
        else:
            status.state = "ON_TRACK"
            status.relax_level = 0.0
            status.reasons = [f"節奏正常 ({count}/{target})"]
        return status

    def deltas(self, now=None, status=None):
        """Threshold deltas to apply for the current pace (empty when on track)."""
        status = status or self.status(now)
        level = status.relax_level
        if not level:
            return {}
        return {
            key: round(delta * level, 4)
            for key, delta in self.cfg["relax_deltas"].items()
        }

    def apply(self, thresholds: dict, now=None, status=None):
        """Return ``thresholds`` shifted by the current pace, clamped to bounds."""
        status = status or self.status(now)
        deltas = self.deltas(status=status)
        if not deltas:
            return dict(thresholds), status

        floors = self.cfg["floors"]
        ceilings = self.cfg["ceilings"]
        adjusted = dict(thresholds)
        for key, delta in deltas.items():
            if key not in adjusted or delta == 0:
                continue
            value = adjusted[key] + delta
            if key in floors:
                value = max(floors[key], value)
            if key in ceilings:
                value = min(ceilings[key], value)
            adjusted[key] = int(round(value)) if isinstance(thresholds[key], int) else round(value, 4)
        return adjusted, status
