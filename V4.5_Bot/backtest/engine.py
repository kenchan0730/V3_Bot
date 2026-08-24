"""Replay historical bars through the same strategy and risk components used live.

Deliberately reuses QuantEngine, the strategy plugins and RiskManager so the
backtest cannot drift from production behaviour.
"""

import logging

from core.data_utils import normalize_columns
from core.portfolio import Portfolio
from core.position_sizer import scale_shares
from core.quant_engine import QuantEngine
from core.risk_manager import RiskManager
from core.strategies import MarketContext, load_strategies
from core.trading_state import TradingState

logger = logging.getLogger(__name__)


class BacktestResult:
    def __init__(self, initial_capital):
        self.initial_capital = initial_capital
        self.trades = []
        self.equity_curve = []
        self.mind_rejections = 0

    def add_trade(self, trade):
        self.trades.append(trade)

    @property
    def final_capital(self):
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_capital

    @property
    def total_return_pct(self):
        if self.initial_capital <= 0:
            return 0.0
        return (self.final_capital / self.initial_capital - 1) * 100

    @property
    def wins(self):
        return [t for t in self.trades if t["pnl"] > 0]

    @property
    def losses(self):
        return [t for t in self.trades if t["pnl"] <= 0]

    @property
    def win_rate(self):
        return len(self.wins) / len(self.trades) * 100 if self.trades else 0.0

    @property
    def profit_factor(self):
        gross_win = sum(t["pnl"] for t in self.wins)
        gross_loss = abs(sum(t["pnl"] for t in self.losses))
        if gross_loss == 0:
            return float("inf") if gross_win > 0 else 0.0
        return gross_win / gross_loss

    @property
    def max_drawdown_pct(self):
        peak, max_dd = self.initial_capital, 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        return max_dd

    @property
    def total_costs(self):
        return round(sum(t.get("costs", 0.0) for t in self.trades), 2)

    def summary(self):
        return {
            "initial_capital": round(self.initial_capital, 2),
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "trades": len(self.trades),
            "win_rate_pct": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "total_costs": self.total_costs,
            "mind_rejections": self.mind_rejections,
        }

    def __repr__(self):
        return f"<BacktestResult {self.summary()}>"


class BacktestEngine:
    """Bar-by-bar replay with bracket-style exits (stop / target / timeout).

    To keep results comparable with live trading the replay also applies the
    live entry slippage, a commission model, and (optionally) the same
    ``ProfessionalMind`` approval chain that gates real entries. Without those
    the backtest systematically overstates achievable performance.
    """

    def __init__(self, config=None, initial_capital=10000.0, warmup_bars=60,
                 max_hold_bars=20, professional_mind=None):
        self.config = config or {}
        self.initial_capital = float(initial_capital)
        self.warmup_bars = int(warmup_bars)
        self.max_hold_bars = int(max_hold_bars)
        self.strategies = load_strategies(self.config)
        self.price_limit = float(self.config.get("trading", {}).get("price_limit", 1e9))
        self.max_shares = int(self.config.get("trading", {}).get("max_shares", 100))
        self.zscore_min = float(self.config.get("zscore", {}).get("best_zone_min", 0.5))
        self.factor_weights = (self.config.get("zscore", {}) or {}).get("weights") or None

        exec_cfg = self.config.get("execution", {}) or {}
        self.slippage_ticks = float(exec_cfg.get("slippage_ticks", 1))
        self.tick_size = float(exec_cfg.get("tick_size", 0.01))

        costs = self.config.get("backtest", {}) or {}
        self.commission_per_share = float(costs.get("commission_per_share", 0.005))
        self.commission_minimum = float(costs.get("commission_minimum", 1.0))
        self.exit_slippage_ticks = float(costs.get("exit_slippage_ticks", 1))
        self.apply_costs = bool(costs.get("apply_costs", True))

        self.professional = professional_mind
        self.mind_rejections = 0

    def entry_with_slippage(self, price):
        """Mirror ``TradingBot.entry_with_slippage`` so fills are comparable."""
        if not self.apply_costs:
            return round(price, 2)
        return round(price + self.slippage_ticks * self.tick_size, 2)

    def exit_with_slippage(self, price):
        if not self.apply_costs:
            return round(price, 2)
        return round(price - self.exit_slippage_ticks * self.tick_size, 2)

    def commission(self, shares):
        """IBKR-style tiered commission: per-share with a per-order minimum."""
        if not self.apply_costs or shares <= 0:
            return 0.0
        return round(max(self.commission_minimum, shares * self.commission_per_share), 4)

    def run(self, symbol, df, vix=18.0):
        df = normalize_columns(df).reset_index(drop=True)
        result = BacktestResult(self.initial_capital)

        state = TradingState(initial_capital=self.initial_capital)
        risk_mgr = RiskManager(
            initial_capital=self.initial_capital,
            config=self.config.get("risk", {}),
            state=state,
        )
        portfolio = Portfolio(self.config.get("portfolio", {}))
        open_trade = None

        for index in range(self.warmup_bars, len(df)):
            window = df.iloc[: index + 1]
            bar = df.iloc[index]
            price = float(bar["close"])

            if open_trade is not None:
                exit_price, exit_reason = self._check_exit(bar, open_trade, index)
                if exit_price is not None:
                    fill = self.exit_with_slippage(exit_price)
                    gross = (fill - open_trade["entry"]) * open_trade["shares"]
                    costs = open_trade["commission"] + self.commission(open_trade["shares"])
                    pnl = gross - costs
                    risk_mgr.record_trade(pnl)
                    portfolio.sync({})
                    result.add_trade({
                        "symbol": symbol,
                        "entry_index": open_trade["index"],
                        "exit_index": index,
                        "entry": round(open_trade["entry"], 2),
                        "exit": round(fill, 2),
                        "shares": open_trade["shares"],
                        "gross_pnl": round(gross, 2),
                        "costs": round(costs, 2),
                        "pnl": round(pnl, 2),
                        "reason": exit_reason,
                    })
                    open_trade = None

            result.equity_curve.append((index, risk_mgr.total_capital))

            if open_trade is not None or price <= 0 or price > self.price_limit:
                continue

            quant = QuantEngine.dynamic_score(window, weights=self.factor_weights)
            ma20 = float(window["close"].rolling(20).mean().iloc[-1])
            ma50 = float(window["close"].rolling(50).mean().iloc[-1])
            volume = float(bar["volume"])
            avg_volume = float(window["volume"].rolling(5).mean().iloc[-1])
            vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

            context = MarketContext(
                symbol=symbol, price=price, vix=vix, zscore_min=self.zscore_min,
                quant=quant, vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
            )

            for strategy in self.strategies:
                ok, _ = strategy.prefilter(window, context)
                if not ok:
                    continue
                signal = strategy.generate_signal(window, context)
                if signal.get("action") != "STRONG_BUY":
                    continue

                entry = self.entry_with_slippage(signal["entry"])
                stop = signal["stop"]
                shares = risk_mgr.calculate_position_size(entry, stop, self.price_limit, self.max_shares)
                if shares <= 0:
                    continue

                approved, stop, shares = self._apply_mind(
                    symbol, signal, window, context, portfolio, risk_mgr,
                    entry, stop, shares,
                )
                if not approved or shares <= 0:
                    continue

                cost = shares * entry
                allowed, _ = portfolio.can_open(symbol, cost, risk_mgr.total_capital, (entry - stop) * shares)
                if not allowed:
                    continue

                open_trade = {
                    "index": index, "entry": entry, "stop": stop,
                    "target": signal.get("target1"), "shares": shares,
                    "commission": self.commission(shares),
                }
                portfolio.sync({symbol: {"quantity": shares, "avg_cost": entry}}, {symbol: entry})
                portfolio.set_stop(symbol, stop)
                break

        if open_trade is not None:
            final_price = self.exit_with_slippage(float(df.iloc[-1]["close"]))
            gross = (final_price - open_trade["entry"]) * open_trade["shares"]
            costs = open_trade["commission"] + self.commission(open_trade["shares"])
            pnl = gross - costs
            risk_mgr.record_trade(pnl)
            result.add_trade({
                "symbol": symbol,
                "entry_index": open_trade["index"],
                "exit_index": len(df) - 1,
                "entry": round(open_trade["entry"], 2),
                "exit": round(final_price, 2),
                "shares": open_trade["shares"],
                "gross_pnl": round(gross, 2),
                "costs": round(costs, 2),
                "pnl": round(pnl, 2),
                "reason": "END_OF_DATA",
            })
            result.equity_curve.append((len(df) - 1, risk_mgr.total_capital))

        result.mind_rejections = self.mind_rejections
        return result

    def _apply_mind(self, symbol, signal, window, context, portfolio, risk_mgr,
                    entry, stop, shares):
        """Run the live approval chain so backtest entries face the same gates."""
        if self.professional is None:
            return True, stop, shares

        try:
            decision = self.professional.approve_entry(
                symbol, signal, window, context, portfolio, risk_mgr,
                entry, stop, shares, is_day_trade=False,
            )
        except Exception as exc:
            logger.warning(f"{symbol} backtest mind evaluation failed: {exc}")
            return True, stop, shares

        if not decision.approve:
            self.mind_rejections += 1
            return False, stop, 0

        if decision.stop_override:
            stop = decision.stop_override
        if decision.shares_scale and decision.shares_scale < 1.0:
            shares = scale_shares(shares, decision.shares_scale, min_shares=0)
        if decision.risk_multiplier < 1.0:
            shares = scale_shares(shares, decision.risk_multiplier, min_shares=0)

        factor = self.professional.conviction_factor(decision.execution_score)
        if factor <= 0:
            self.mind_rejections += 1
            return False, stop, 0
        if factor < 1.0:
            shares = scale_shares(shares, factor, min_shares=0)

        return True, stop, shares

    def _check_exit(self, bar, trade, index):
        low, high = float(bar["low"]), float(bar["high"])
        if trade["stop"] and low <= trade["stop"]:
            return trade["stop"], "STOP"
        if trade["target"] and high >= trade["target"]:
            return trade["target"], "TARGET"
        if index - trade["index"] >= self.max_hold_bars:
            return float(bar["close"]), "TIMEOUT"
        return None, None
