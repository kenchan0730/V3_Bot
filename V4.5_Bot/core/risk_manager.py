"""Risk management driven entirely by config.yaml, backed by TradingState."""

import logging
from datetime import datetime

import pytz

from core.market_calendar import MarketCalendar
from core.trading_state import TradingState

logger = logging.getLogger(__name__)


class RiskManager:
    """Per-trade sizing plus account-level drawdown and daily-loss enforcement.

    All thresholds come from the ``risk`` section of config.yaml; the literal
    defaults below apply only when a key is absent.
    """

    def __init__(self, initial_capital=385.0, max_risk_pct=2.0, daily_loss_limit=2.0,
                 config=None, state=None, vix_threshold=25.0):
        cfg = config or {}
        self.initial_capital = float(initial_capital)
        self.max_risk_pct = float(cfg.get("max_risk_percent", max_risk_pct))
        self.reduced_risk_pct = float(cfg.get("reduced_risk_percent", 1.0))
        self.max_loss_streak = int(cfg.get("max_loss_streak", 3))
        self.max_position_pct = float(cfg.get("max_position_pct", 50.0))
        self.concentration_source = "risk.max_position_pct"
        self.max_drawdown_limit = float(cfg.get("max_drawdown_limit", 10.0))
        self.max_absolute_loss = float(cfg.get("max_absolute_loss", 8.0))
        self.drawdown_warning_pct = float(
            cfg.get("drawdown_warning_pct", self.max_drawdown_limit * 0.6)
        )
        self.drawdown_warning_risk_pct = float(
            cfg.get("drawdown_warning_risk_pct", self.reduced_risk_pct)
        )
        self.daily_loss_limit = float(cfg.get("daily_loss_limit", daily_loss_limit))
        self.vix_threshold = float(cfg.get("vix_threshold", vix_threshold))
        self.vix_risk_cap = float(cfg.get("vix_risk_cap", 1.5))

        self.state = state if state is not None else TradingState(initial_capital=initial_capital)
        self.current_risk_pct = self.max_risk_pct

    def set_concentration_cap(self, pct, source="portfolio.max_symbol_pct"):
        """Adopt the book-level single-name cap as the sizing concentration cap.

        Portfolio owns this limit; injecting it here keeps ``RiskManager`` sizing
        and ``Portfolio.can_open`` from drifting apart across config edits.
        """
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return self.max_position_pct
        if pct <= 0:
            return self.max_position_pct

        if abs(pct - self.max_position_pct) > 1e-9:
            logger.warning(
                f"集中度上限對齊 {source}: {self.max_position_pct}% → {pct}%"
            )
        self.max_position_pct = pct
        self.concentration_source = source
        return self.max_position_pct

    # ----- state delegation (single source of truth) -----

    @property
    def total_capital(self):
        return self.state.total_capital

    @total_capital.setter
    def total_capital(self, value):
        self.state.total_capital = float(value)

    @property
    def peak_capital(self):
        return self.state.peak_capital

    @peak_capital.setter
    def peak_capital(self, value):
        self.state.peak_capital = float(value)

    @property
    def consecutive_losses(self):
        return self.state.consecutive_losses

    @consecutive_losses.setter
    def consecutive_losses(self, value):
        self.state.consecutive_losses = int(value)

    @property
    def today_trades(self):
        return self.state.today_trades

    @today_trades.setter
    def today_trades(self, value):
        self.state.today_trades = int(value)

    @property
    def daily_loss(self):
        return self.state.daily_realized_pnl

    @daily_loss.setter
    def daily_loss(self, value):
        self.state.daily_realized_pnl = float(value)

    # ----- capital tracking -----

    def update_capital(self, new_capital):
        self.state.sync_capital(new_capital)

    def get_daily_pnl(self):
        """Realised P&L for the current trading day (from fills)."""
        return self.state.daily_realized_pnl

    def drawdown_pct(self):
        """Give-back from the equity high-water mark."""
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.total_capital) / self.peak_capital * 100

    def absolute_loss_pct(self):
        """Loss measured against starting capital (capital-preservation floor)."""
        if self.initial_capital <= 0:
            return 0.0
        return (self.initial_capital - self.total_capital) / self.initial_capital * 100

    def drawdown_state(self):
        """Three-tier verdict: OK, WARNING (de-risk) or HALT.

        The two halt lines are deliberately distinct: peak drawdown protects
        accumulated profit, while absolute loss is the floor under the starting
        capital. A warning band de-risks before either line is breached.
        """
        drawdown = self.drawdown_pct()
        absolute = self.absolute_loss_pct()

        if drawdown > self.max_drawdown_limit:
            return {
                "level": "HALT", "drawdown_pct": drawdown, "absolute_loss_pct": absolute,
                "message": f"高位回撤 {drawdown:.1f}% > {self.max_drawdown_limit}%",
            }
        if absolute > self.max_absolute_loss:
            return {
                "level": "HALT", "drawdown_pct": drawdown, "absolute_loss_pct": absolute,
                "message": f"絕對虧損 {absolute:.1f}% > {self.max_absolute_loss}%",
            }
        if drawdown > self.drawdown_warning_pct:
            return {
                "level": "WARNING", "drawdown_pct": drawdown, "absolute_loss_pct": absolute,
                "message": (
                    f"回撤 {drawdown:.1f}% 超過警戒 {self.drawdown_warning_pct}%，"
                    f"風險降至 {self.drawdown_warning_risk_pct}%"
                ),
            }
        return {
            "level": "OK", "drawdown_pct": drawdown, "absolute_loss_pct": absolute,
            "message": "OK",
        }

    def check_drawdown(self):
        state = self.drawdown_state()
        if state["level"] == "HALT":
            return False, state["message"]
        if state["level"] == "WARNING":
            self.current_risk_pct = min(self.current_risk_pct, self.drawdown_warning_risk_pct)
            logger.warning(f"⚠️ {state['message']}")
        return True, state["message"]

    def check_daily_loss(self, pnl):
        """Apply a realised P&L delta and re-evaluate the daily limit."""
        self.state.apply_realized_pnl(pnl)
        self._apply_loss_streak_policy()
        return self.is_within_daily_loss_limit()

    def is_within_daily_loss_limit(self):
        if self.total_capital <= 0:
            return True, "OK"
        loss_pct = (self.state.daily_realized_pnl / self.total_capital) * 100
        if loss_pct < -self.daily_loss_limit:
            return False, f"今日虧損 {loss_pct:.2f}% 已達限額 {self.daily_loss_limit}%"
        return True, f"今日虧損 {loss_pct:.2f}%"

    # ----- sizing -----

    def calculate_position_size(self, entry_price, stop_loss_price, price_limit=40, max_shares=20):
        if entry_price <= stop_loss_price or entry_price > price_limit:
            return 0
        risk_per_share = entry_price - stop_loss_price
        if risk_per_share <= 0:
            return 0
        max_loss = self.total_capital * (self.current_risk_pct / 100.0)
        shares = int(max_loss / risk_per_share)
        cost = shares * entry_price
        concentration_cap = self.total_capital * (self.max_position_pct / 100.0)
        if cost > concentration_cap:
            shares = int(concentration_cap / entry_price)
        shares = min(shares, max_shares)
        return max(0, shares)

    def record_trade(self, pnl_usd):
        self.state.apply_realized_pnl(pnl_usd)
        self.state.today_trades += 1
        self._apply_loss_streak_policy()

    def _apply_loss_streak_policy(self):
        if self.consecutive_losses >= self.max_loss_streak:
            self.current_risk_pct = self.reduced_risk_pct
            logger.warning(f"連續 {self.consecutive_losses} 次止蝕，風險降至 {self.reduced_risk_pct}%")
        else:
            self.current_risk_pct = self.max_risk_pct

    def check_vix(self, vix):
        if vix > self.vix_threshold:
            self.current_risk_pct = min(self.current_risk_pct, self.vix_risk_cap)
        return self.current_risk_pct

    @staticmethod
    def is_market_open(now=None):
        """US regular session check honouring holidays and half-day closes."""
        now = now or datetime.now(pytz.timezone("US/Eastern"))
        return MarketCalendar.is_session_open(now)
