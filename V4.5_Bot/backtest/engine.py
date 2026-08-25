"""Replay historical bars through the same strategy and risk components used live.

Deliberately reuses QuantEngine, the strategy plugins, RiskManager and
``EntryPipeline`` so the backtest cannot drift from production behaviour.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd

from core.broker_costs import resolve as resolve_broker_costs
from core.data_utils import normalize_columns
from core.entry_pipeline import EntryPipeline
from core.intraday_engine import IntradayEngine
from core.portfolio import Portfolio
from core.quant_engine import QuantEngine
from core.retail_mind import RetailMind
from core.risk_manager import RiskManager
from core.strategies import MarketContext, load_strategies
from core.swing_filters import SwingQualityFilter
from core.trade_pacing import TradePacer
from core.trading_state import TradingState

logger = logging.getLogger(__name__)


class BacktestResult:
    def __init__(self, initial_capital):
        self.initial_capital = initial_capital
        self.trades = []
        self.equity_curve = []
        self.mind_rejections = 0
        self.retail_rejections = 0
        self.bars = 0

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

    @property
    def trades_per_month(self):
        """Entries per 21 trading bars — the frequency target is expressed monthly."""
        if not self.bars:
            return 0.0
        return round(len(self.trades) / (self.bars / 21.0), 2)

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
            "retail_rejections": self.retail_rejections,
            "trades_per_month": self.trades_per_month,
        }

    def __repr__(self):
        return f"<BacktestResult {self.summary()}>"


class BacktestEngine:
    """Bar-by-bar replay with bracket-style exits (stop / target / timeout).

    Entry evaluation routes through the same ``EntryPipeline`` used live so
    sizing, mind approval and portfolio gates stay aligned.
    """

    def __init__(self, config=None, initial_capital=10000.0, warmup_bars=60,
                 max_hold_bars=20, professional_mind=None, pacing_target=None):
        self.config = config or {}
        self.initial_capital = float(initial_capital)
        self.warmup_bars = int(warmup_bars)
        self.max_hold_bars = int(max_hold_bars)
        self.strategies = load_strategies(self.config)
        self.price_limit = float(self.config.get("trading", {}).get("price_limit", 1e9))
        self.max_shares = int(self.config.get("trading", {}).get("max_shares", 100))
        regime_cfg = self.config.get("regime", {}) or {}
        zscore_cfg = self.config.get("zscore", {}) or {}
        self.zscore_min = float(
            regime_cfg.get("neutral_zscore_min", zscore_cfg.get("best_zone_min", 0.5))
        )
        self.factor_weights = (self.config.get("zscore", {}) or {}).get("weights") or None

        exec_cfg = self.config.get("execution", {}) or {}
        self.slippage_ticks = float(exec_cfg.get("slippage_ticks", 1))
        self.tick_size = float(exec_cfg.get("tick_size", 0.01))

        costs = self.config.get("backtest", {}) or {}
        broker = resolve_broker_costs(self.config)
        self.broker_profile = broker.name
        self.commission_per_share = broker.commission_per_share
        self.commission_minimum = broker.commission_minimum
        self.exit_slippage_ticks = float(costs.get("exit_slippage_ticks", 1))
        self.apply_costs = bool(costs.get("apply_costs", True))

        self.professional = professional_mind
        self.mind_rejections = 0
        self.retail_rejections = 0
        self.pacing_blocks = 0
        self._disabled_intraday = IntradayEngine({"enabled": False})
        self.swing_filter = SwingQualityFilter(self.config.get("swing_trading", {}))
        self.breadth_score = 50.0

        retail_cfg = dict(self.config.get("retail_mind", {}) or {})
        broker = resolve_broker_costs(self.config)
        retail_cfg["broker_profile"] = broker
        retail_cfg.setdefault("commission_per_share", broker.commission_per_share)
        retail_cfg.setdefault("commission_minimum", broker.commission_minimum)
        self.use_retail_mind = bool(costs.get("use_retail_mind", True))
        self.retail_mind = RetailMind(retail_cfg)

        # Pacing is portfolio-level live; a per-symbol replay gets a scaled target.
        pacing_cfg = dict(self.config.get("trade_pacing", {}) or {})
        pacing_cfg["state_file"] = None
        if pacing_target is not None:
            pacing_cfg["target_trades_per_month"] = pacing_target
            # The portfolio-level hard cap cannot be modelled per symbol, so it
            # is lifted here; only the relax/tighten behaviour is replayed.
            pacing_cfg["max_trades_per_month"] = 10_000
        self.use_pacing = bool(costs.get("use_pacing", True))
        self.pacing_cfg = pacing_cfg
        self.max_symbol_pct = float(
            self.config.get("portfolio", {}).get("max_symbol_pct", 100.0)
        )

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

    def _build_entry_pipeline(self, risk_mgr, portfolio):
        """Shared buy path with live bot; backtest uses min_shares=0 floor."""
        slippage = self.slippage_ticks if self.apply_costs else 0.0
        gross_cap = float(self.config.get("portfolio", {}).get("max_gross_exposure_pct", 100.0))
        return EntryPipeline(
            risk_mgr,
            portfolio,
            self.professional,
            self._disabled_intraday,
            slippage_ticks=slippage,
            tick_size=self.tick_size,
            price_limit=self.price_limit,
            max_shares=self.max_shares,
            auto_trade=False,
            min_shares=0,
            max_gross_pct_fn=lambda: gross_cap,
            min_notional=(
                self.retail_mind.min_viable_notional() if self.use_retail_mind else 0.0
            ),
        )

    def _base_thresholds(self):
        swing = self.config.get("swing_trading", {}) or {}
        candle = self.config.get("candle", {}) or {}
        strat = (self.config.get("strategies") or [{}])[0] or {}
        return {
            "strong_min_confluence": int(swing.get("strong_min_confluence", 4)),
            "moderate_min_confluence": int(swing.get("moderate_min_confluence", 3)),
            "moderate_min_edges": int(swing.get("moderate_min_edges", 3)),
            "rsi_max": float(swing.get("rsi_max", 72)),
            "reject_rsi_above": float(swing.get("reject_rsi_above", 78)),
            "zscore_max": float(swing.get("zscore_max", 1.45)),
            "zscore_min": float(self.zscore_min),
            "min_candle_strength": float(candle.get("min_strength", 0.30)),
            "min_vol_ratio_high": float(strat.get("min_vol_ratio_high", 1.2)),
            "retail_min_score": int(self.retail_mind.cfg.get("min_retail_score", 5)),
        }

    def run(self, symbol, df, vix=18.0):
        frame = normalize_columns(df)
        bar_dates = (
            list(frame.index) if isinstance(frame.index, pd.DatetimeIndex) else None
        )
        df = frame.reset_index(drop=True)
        result = BacktestResult(self.initial_capital)
        pacer = TradePacer(self.pacing_cfg, state_file=None)
        base_thresholds = self._base_thresholds()
        synthetic_epoch = datetime(2000, 1, 1)

        state = TradingState(initial_capital=self.initial_capital)
        risk_mgr = RiskManager(
            initial_capital=self.initial_capital,
            config=self.config.get("risk", {}),
            state=state,
        )
        portfolio = Portfolio(self.config.get("portfolio", {}))
        self.swing_filter.portfolio = portfolio
        risk_mgr.set_concentration_cap(portfolio.max_symbol_pct)
        pipeline = self._build_entry_pipeline(risk_mgr, portfolio)
        pipeline.moderate_size_factor = float(
            (self.config.get("swing_trading", {}) or {}).get("moderate_size_factor", 0.5)
        )
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

            bar_time = (
                bar_dates[index].to_pydatetime()
                if bar_dates is not None
                else synthetic_epoch + timedelta(days=index * 1.4)
            )
            if self.use_pacing:
                thresholds, pace = pacer.apply(base_thresholds, now=bar_time)
            else:
                thresholds, pace = dict(base_thresholds), None

            context = MarketContext(
                symbol=symbol, price=price, vix=vix,
                zscore_min=float(thresholds.get("zscore_min", self.zscore_min)),
                quant=quant, vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
                breadth_score=self.breadth_score,
                threshold_overrides=thresholds,
            )

            if pace is not None and not pace.allow_new_entry:
                self.pacing_blocks += 1
                continue

            for strategy in self.strategies:
                ok, _ = strategy.prefilter(window, context)
                if not ok:
                    continue
                signal = strategy.generate_signal(window, context)
                if signal.get("action") not in ("STRONG_BUY", "MODERATE_BUY"):
                    continue

                quality_ok, _ = self.swing_filter.validate(symbol, signal, context, df=window)
                if not quality_ok:
                    continue

                if self.use_retail_mind:
                    retail_cfg_score = thresholds.get("retail_min_score")
                    if retail_cfg_score is not None:
                        self.retail_mind.cfg["min_retail_score"] = int(retail_cfg_score)
                    retail = self.retail_mind.evaluate(
                        symbol, signal, context, df=window,
                        capital=risk_mgr.total_capital,
                        max_shares=self.max_shares,
                        max_symbol_pct=self.max_symbol_pct,
                    )
                    if not retail.approve:
                        self.retail_rejections += 1
                        continue
                    signal["retail_size_factor"] = retail.size_factor

                entry_result = pipeline.run(
                    symbol, signal, quant, df=window,
                    exposure=100,
                    allow_intraday_entries=False,
                    current_regime="NEUTRAL",
                    allow_new_entries=True,
                    vix=vix,
                    zscore_min=self.zscore_min,
                    intraday_mode=False,
                )
                if not entry_result.proceed:
                    if entry_result.stage in ("MIND", "CONVICTION"):
                        self.mind_rejections += 1
                    continue

                entry = entry_result.entry
                stop = entry_result.stop
                shares = entry_result.shares
                if shares <= 0:
                    continue

                open_trade = {
                    "index": index, "entry": entry, "stop": stop,
                    "target": entry_result.target or signal.get("target1"),
                    "shares": shares,
                    "commission": self.commission(shares),
                }
                pacer.record_entry(when=bar_time, persist=False)
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
        result.retail_rejections = self.retail_rejections
        result.bars = max(0, len(df) - self.warmup_bars)
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
