"""Replay historical bars through the same strategy and risk components used live.

Deliberately reuses QuantEngine, the strategy plugins and RiskManager so the
backtest cannot drift from production behaviour.
"""

import logging

from core.data_utils import normalize_columns
from core.portfolio import Portfolio
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

    def summary(self):
        return {
            "initial_capital": round(self.initial_capital, 2),
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "trades": len(self.trades),
            "win_rate_pct": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
        }

    def __repr__(self):
        return f"<BacktestResult {self.summary()}>"


class BacktestEngine:
    """Bar-by-bar replay with bracket-style exits (stop / target / timeout)."""

    def __init__(self, config=None, initial_capital=10000.0, warmup_bars=60, max_hold_bars=20):
        self.config = config or {}
        self.initial_capital = float(initial_capital)
        self.warmup_bars = int(warmup_bars)
        self.max_hold_bars = int(max_hold_bars)
        self.strategies = load_strategies(self.config)
        self.price_limit = float(self.config.get("trading", {}).get("price_limit", 1e9))
        self.max_shares = int(self.config.get("trading", {}).get("max_shares", 100))
        self.zscore_min = float(self.config.get("zscore", {}).get("best_zone_min", 0.5))

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
                    pnl = (exit_price - open_trade["entry"]) * open_trade["shares"]
                    risk_mgr.record_trade(pnl)
                    portfolio.sync({})
                    result.add_trade({
                        "symbol": symbol,
                        "entry_index": open_trade["index"],
                        "exit_index": index,
                        "entry": round(open_trade["entry"], 2),
                        "exit": round(exit_price, 2),
                        "shares": open_trade["shares"],
                        "pnl": round(pnl, 2),
                        "reason": exit_reason,
                    })
                    open_trade = None

            result.equity_curve.append((index, risk_mgr.total_capital))

            if open_trade is not None or price <= 0 or price > self.price_limit:
                continue

            quant = QuantEngine.dynamic_score(window)
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

                entry, stop = signal["entry"], signal["stop"]
                shares = risk_mgr.calculate_position_size(entry, stop, self.price_limit, self.max_shares)
                cost = shares * entry
                allowed, _ = portfolio.can_open(symbol, cost, risk_mgr.total_capital, (entry - stop) * shares)
                if shares <= 0 or not allowed:
                    continue

                open_trade = {
                    "index": index, "entry": entry, "stop": stop,
                    "target": signal.get("target1"), "shares": shares,
                }
                portfolio.sync({symbol: {"quantity": shares, "avg_cost": entry}}, {symbol: entry})
                portfolio.set_stop(symbol, stop)
                break

        if open_trade is not None:
            final_price = float(df.iloc[-1]["close"])
            pnl = (final_price - open_trade["entry"]) * open_trade["shares"]
            risk_mgr.record_trade(pnl)
            result.add_trade({
                "symbol": symbol,
                "entry_index": open_trade["index"],
                "exit_index": len(df) - 1,
                "entry": round(open_trade["entry"], 2),
                "exit": round(final_price, 2),
                "shares": open_trade["shares"],
                "pnl": round(pnl, 2),
                "reason": "END_OF_DATA",
            })
            result.equity_curve.append((len(df) - 1, risk_mgr.total_capital))

        return result

    def _check_exit(self, bar, trade, index):
        low, high = float(bar["low"]), float(bar["high"])
        if trade["stop"] and low <= trade["stop"]:
            return trade["stop"], "STOP"
        if trade["target"] and high >= trade["target"]:
            return trade["target"], "TARGET"
        if index - trade["index"] >= self.max_hold_bars:
            return float(bar["close"]), "TIMEOUT"
        return None, None
