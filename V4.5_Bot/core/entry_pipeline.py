"""Buy-entry pipeline — discrete, testable stages extracted from handle_buy()."""

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.position_sizer import scale_shares
from core.professional_mind import MindDecision
from core.strategies.base import MarketContext

logger = logging.getLogger(__name__)


@dataclass
class EntryResult:
    proceed: bool = False
    stage: str = ""
    reason: str = ""
    entry: float = 0.0
    stop: float = 0.0
    target: Optional[float] = None
    shares: int = 0
    conviction: float = 1.0
    mind_decision: Optional[MindDecision] = None
    intraday_check: dict = field(default_factory=dict)


class EntryPipeline:
    """Pre-execution buy path: slippage → intraday → sizing → mind → conviction → validate."""

    def __init__(
        self,
        risk_mgr,
        portfolio,
        professional,
        intraday,
        *,
        slippage_ticks=1.0,
        tick_size=0.01,
        price_limit=40.0,
        max_shares=20,
        auto_trade=False,
        ibkr=None,
        max_gross_pct_fn: Optional[Callable[[], float]] = None,
        min_shares=1,
    ):
        self.risk_mgr = risk_mgr
        self.portfolio = portfolio
        self.professional = professional
        self.intraday = intraday
        self.slippage_ticks = slippage_ticks
        self.tick_size = tick_size
        self.price_limit = price_limit
        self.max_shares = max_shares
        self.auto_trade = auto_trade
        self.ibkr = ibkr
        self.min_shares = max(0, int(min_shares))
        self.max_gross_pct_fn = max_gross_pct_fn or (lambda: portfolio.max_gross_exposure_pct)

    def step_slippage(self, signal_entry):
        return round(signal_entry + self.slippage_ticks * self.tick_size, 2)

    def step_intraday(self, symbol, signal, entry, *, intraday_mode, allow_intraday, current_regime):
        intraday_check = {
            "ok": True,
            "reason": "intraday skipped",
            "entry_price": entry,
            "metrics": {},
        }
        if not intraday_mode or not self.intraday.cfg.get("enabled", True):
            return intraday_check, entry, None

        if not allow_intraday:
            reason = f"regime {current_regime} blocks intraday"
            return intraday_check, entry, (reason, "REGIME")

        intraday_check = self.intraday.evaluate_entry(
            symbol, signal.get("action", "STRONG_BUY"), entry,
        )
        if not intraday_check.get("ok"):
            return intraday_check, entry, (
                intraday_check.get("reason", ""),
                "INTRADAY",
            )

        entry = intraday_check.get("entry_price", entry)
        return intraday_check, entry, None

    def step_sizing(self, entry, stop, exposure, symbol, returns_cache):
        shares = self.risk_mgr.calculate_position_size(
            entry, stop, self.price_limit, self.max_shares,
        )
        if exposure < 100:
            shares = int(shares * exposure / 100)
        scale = self.portfolio.correlation_scale(symbol, returns_cache)
        if scale < 1.0:
            shares = int(shares * scale)
        return shares

    def step_mind_approval(self, symbol, signal, df, entry, stop, shares, mind_ctx):
        if self.professional is None:
            return MindDecision(approve=True, execution_score=10)
        cfg = getattr(self.professional, "cfg", None) or {}
        if not cfg.get("enabled", True):
            return MindDecision(approve=True, execution_score=10)
        try:
            return self.professional.approve_entry(
                symbol, signal, df, mind_ctx, self.portfolio, self.risk_mgr,
                entry, stop, shares, is_day_trade=False,
            )
        except Exception as exc:
            logger.warning(f"{symbol} mind evaluation failed: {exc}")
            return MindDecision(
                approve=False,
                action="MIND_ERROR",
                reasons=[f"mind evaluation error: {exc}"],
            )

    def step_apply_mind_decision(self, mind_decision, stop, shares):
        floor = self.min_shares
        if mind_decision.stop_override:
            stop = mind_decision.stop_override
        if mind_decision.shares_scale and mind_decision.shares_scale < 1.0:
            shares = scale_shares(shares, mind_decision.shares_scale, min_shares=floor)
        if mind_decision.risk_multiplier < 1.0:
            shares = scale_shares(shares, mind_decision.risk_multiplier, min_shares=floor)
        return stop, shares

    def step_conviction(self, mind_decision, shares, signal=None):
        if self.professional is None:
            return shares, 1.0, None
        conviction = self.professional.conviction_factor(mind_decision.execution_score)
        track = (signal or {}).get("track", "STRONG")
        moderate_cap = float(
            getattr(self, "moderate_size_factor", 0.5)
        )
        if track == "MODERATE":
            conviction = min(conviction, moderate_cap)
        retail_cap = (signal or {}).get("retail_size_factor")
        if retail_cap is not None:
            conviction = min(conviction, float(retail_cap))
        if conviction <= 0:
            reason = f"共振不足 (exec {mind_decision.execution_score}/10)"
            return shares, conviction, reason
        if conviction < 1.0:
            shares = scale_shares(shares, conviction, min_shares=self.min_shares)
        return shares, conviction, None

    def step_validate_pre_trade(self, symbol, shares, entry, stop):
        if shares <= 0:
            return False, "股數為 0"
        if shares > self.max_shares:
            return False, f"股數 {shares} > 上限 {self.max_shares}"
        if not stop or stop <= 0:
            return False, "缺少有效停損價"
        if entry <= stop:
            return False, "進場價必須高於停損價"

        cost = shares * entry
        stop_risk = (entry - stop) * shares
        allowed, reason = self.portfolio.can_open(
            symbol, cost, self.risk_mgr.total_capital, stop_risk,
            max_gross_pct_override=self.max_gross_pct_fn(),
        )
        if not allowed:
            return False, reason

        if self.auto_trade and self.ibkr and self.ibkr.is_connected():
            buying_power = self.ibkr.get_buying_power()
            if buying_power and cost > buying_power:
                return False, f"購買力不足: 需 ${cost:.2f} > 可用 ${buying_power:.2f}"

        return True, "OK"

    def run(
        self,
        symbol,
        signal,
        quant,
        df=None,
        *,
        exposure=100,
        allow_intraday_entries=True,
        current_regime="NEUTRAL",
        allow_new_entries=True,
        vix=18.0,
        zscore_min=0.5,
        breadth_score=None,
        returns_cache=None,
        intraday_mode=False,
    ):
        entry = self.step_slippage(signal["entry"])
        stop = signal["stop"]
        target = signal.get("target1")

        intraday_check, entry, rejection = self.step_intraday(
            symbol, signal, entry,
            intraday_mode=intraday_mode,
            allow_intraday=allow_intraday_entries,
            current_regime=current_regime,
        )
        if rejection:
            reason, stage = rejection
            return EntryResult(
                proceed=False, stage=stage, reason=reason,
                entry=entry, stop=stop, target=target,
                intraday_check=intraday_check,
            )

        if not allow_new_entries:
            return EntryResult(
                proceed=False, stage="GATE", reason="新倉已暫停",
                entry=entry, stop=stop, target=target, intraday_check=intraday_check,
            )

        shares = self.step_sizing(
            entry, stop, exposure, symbol, returns_cache or {},
        )

        mind_ctx = MarketContext(
            symbol=symbol, price=entry, vix=vix, zscore_min=zscore_min,
            exposure=exposure, breadth_score=breadth_score, quant=quant,
            regime=current_regime, allow_new_entries=allow_new_entries,
        )
        mind_decision = self.step_mind_approval(
            symbol, signal, df, entry, stop, shares, mind_ctx,
        )
        if not mind_decision.approve:
            reason = "; ".join(
                mind_decision.reasons or mind_decision.thoughts or ["mind rejected"],
            )
            return EntryResult(
                proceed=False, stage="MIND", reason=reason,
                entry=entry, stop=stop, target=target, shares=shares,
                mind_decision=mind_decision, intraday_check=intraday_check,
            )

        stop, shares = self.step_apply_mind_decision(mind_decision, stop, shares)
        shares, conviction, conviction_reason = self.step_conviction(
            mind_decision, shares, signal=signal,
        )
        if conviction_reason:
            return EntryResult(
                proceed=False, stage="CONVICTION", reason=conviction_reason,
                entry=entry, stop=stop, target=target, shares=shares,
                conviction=conviction, mind_decision=mind_decision,
                intraday_check=intraday_check,
            )

        ok, reason = self.step_validate_pre_trade(symbol, shares, entry, stop)
        if not ok:
            return EntryResult(
                proceed=False, stage="PRE_TRADE", reason=reason,
                entry=entry, stop=stop, target=target, shares=shares,
                conviction=conviction, mind_decision=mind_decision,
                intraday_check=intraday_check,
            )

        return EntryResult(
            proceed=True, stage="OK", reason="OK",
            entry=entry, stop=stop, target=target, shares=shares,
            conviction=conviction, mind_decision=mind_decision,
            intraday_check=intraday_check,
        )
