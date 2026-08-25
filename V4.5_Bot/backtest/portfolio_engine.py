"""Portfolio-level backtest — shared capital, concurrent positions, live throttles.

Per-symbol replay (`BacktestEngine`) overstates frequency and understates
portfolio constraints. This engine walks a common calendar, maintains one
book, and applies the same gates the live bot uses:

    - regime exposure + entry permission
    - emotion daily trade cap + loss streak pause
    - drawdown warning (de-risk) and halt
    - portfolio gross / sector / open-risk limits
    - trade pacing (portfolio-wide monthly target)
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd

from backtest.engine import BacktestEngine, BacktestResult
from core.data_utils import normalize_columns
from core.emotion_manager import EmotionManager
from core.regime import RegimeDetector
from core.trading_state import TradingState
from core.trade_pacing import TradePacer

logger = logging.getLogger(__name__)


class PortfolioBacktestResult(BacktestResult):
  def __init__(self, initial_capital):
    super().__init__(initial_capital)
    self.throttle_stats = {
      "regime_blocks": 0,
      "emotion_blocks": 0,
      "drawdown_halts": 0,
      "drawdown_warnings": 0,
      "pacing_blocks": 0,
      "portfolio_blocks": 0,
      "mind_rejections": 0,
      "retail_rejections": 0,
    }

  def summary(self):
    base = super().summary()
    base["throttle_stats"] = dict(self.throttle_stats)
    return base


class PortfolioBacktestEngine(BacktestEngine):
  """Multi-symbol replay with one capital pool and live-style throttles."""

  def __init__(self, config=None, initial_capital=1275.0, warmup_bars=60,
               max_hold_bars=20, professional_mind=None, pacing_target=None,
               use_live_throttles=True):
    super().__init__(
      config, initial_capital=initial_capital, warmup_bars=warmup_bars,
      max_hold_bars=max_hold_bars, professional_mind=professional_mind,
      pacing_target=pacing_target,
    )
    bt_cfg = (config or {}).get("backtest", {}) or {}
    self.use_live_throttles = bool(bt_cfg.get("use_live_throttles", use_live_throttles))
    self.regime_detector = RegimeDetector((config or {}).get("regime", {}))
    self.emotion = EmotionManager(
      state=None,
      config=(config or {}).get("emotion", {}),
    )
    self.pacing_cfg = dict(self.pacing_cfg)
    if pacing_target is None:
      self.pacing_cfg["target_trades_per_month"] = float(
        (config or {}).get("trade_pacing", {}).get("target_trades_per_month", 8)
      )
    self.pacing_cfg["max_trades_per_month"] = float(
      (config or {}).get("trade_pacing", {}).get("max_trades_per_month", 12)
    )

  @staticmethod
  def _align_frames(symbol_dfs):
    """Normalize and index each frame by calendar date."""
    aligned = {}
    for symbol, raw in symbol_dfs.items():
      frame = normalize_columns(raw)
      if frame.empty:
        continue
      if not isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index)
      aligned[symbol.upper()] = frame.sort_index()
    return aligned

  @staticmethod
  def _common_dates(frames):
    if not frames:
      return []
    sets = [set(df.index.normalize()) for df in frames.values()]
    return sorted(set.intersection(*sets))

  def run_portfolio(self, symbol_dfs, vix_df=None, breadth_score=50.0):
    frames = self._align_frames(symbol_dfs)
    if not frames:
      return PortfolioBacktestResult(self.initial_capital)

    dates = self._common_dates(frames)
    if len(dates) < self.warmup_bars + 5:
      return PortfolioBacktestResult(self.initial_capital)

    result = PortfolioBacktestResult(self.initial_capital)
    pacer = TradePacer(self.pacing_cfg, state_file=None)
    base_thresholds = self._base_thresholds()

    from core.risk_manager import RiskManager
    from core.portfolio import Portfolio
    from core.quant_engine import QuantEngine
    from core.strategies import MarketContext

    state = TradingState(initial_capital=self.initial_capital)
    self.emotion.state = state
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

    open_trades = {}
    returns_cache = {}
    vix_by_date = self._vix_lookup(vix_df, dates)

    for day_idx, stamp in enumerate(dates):
      if day_idx < self.warmup_bars:
        continue

      day = stamp.date() if hasattr(stamp, "date") else stamp
      risk_mgr.state.reset_daily_if_needed(day)

      exposure = 100
      allow_new = True
      zscore_min = self.zscore_min
      regime_label = "NEUTRAL"

      if self.use_live_throttles:
        vix = vix_by_date.get(stamp, 18.0)
        regime = self.regime_detector.detect(vix=vix, breadth_score=breadth_score)
        exposure = int(regime.exposure_pct)
        allow_new = bool(regime.allow_new_entries)
        zscore_min = float(regime.zscore_min)
        regime_label = regime.regime
        gross_cap = min(portfolio.max_gross_exposure_pct, float(exposure))
      else:
        gross_cap = portfolio.max_gross_exposure_pct

      ok_dd, _ = risk_mgr.check_drawdown()
      if not ok_dd:
        result.throttle_stats["drawdown_halts"] += 1
        allow_new = False
      elif risk_mgr.drawdown_state()["level"] == "WARNING":
        result.throttle_stats["drawdown_warnings"] += 1

      risk_mgr.check_vix(vix_by_date.get(stamp, 18.0))

      # ----- exits -----
      for symbol in list(open_trades.keys()):
        trade = open_trades[symbol]
        df = frames[symbol]
        if stamp not in df.index:
          continue
        bar = df.loc[stamp]
        bar_idx = df.index.get_loc(stamp)
        exit_price, exit_reason = self._check_exit(bar, trade, bar_idx)
        if exit_price is None:
          portfolio.update_price(symbol, float(bar["close"]))
          continue

        fill = self.exit_with_slippage(exit_price)
        gross = (fill - trade["entry"]) * trade["shares"]
        costs = trade["commission"] + self.commission(trade["shares"])
        pnl = gross - costs
        risk_mgr.record_trade(pnl)
        self.emotion.record_trade(pnl)
        portfolio.clear_stop(symbol)
        portfolio.clear_entry_date(symbol)
        portfolio.sync({})
        result.add_trade({
          "symbol": symbol,
          "entry_date": trade.get("entry_date"),
          "exit_date": str(day),
          "entry": round(trade["entry"], 2),
          "exit": round(fill, 2),
          "shares": trade["shares"],
          "gross_pnl": round(gross, 2),
          "costs": round(costs, 2),
          "pnl": round(pnl, 2),
          "reason": exit_reason,
          "risk_dollars": trade.get("risk_dollars"),
          "risk_pct": trade.get("risk_pct"),
        })
        open_trades.pop(symbol, None)

      result.equity_curve.append((day_idx, risk_mgr.total_capital))
      result.bars += 1

      if not allow_new:
        result.throttle_stats["regime_blocks"] += 1
        continue

      thresholds, pace = pacer.apply(base_thresholds, now=datetime.combine(day, datetime.min.time()))
      if pace is not None and not pace.allow_new_entry:
        result.throttle_stats["pacing_blocks"] += 1
        continue

      can_trade, emo_reason = self.emotion.check_before_trade()
      if self.use_live_throttles and not can_trade:
        result.throttle_stats["emotion_blocks"] += 1
        continue

      candidates = []
      for symbol, df in frames.items():
        if symbol in open_trades or portfolio.has_position(symbol):
          continue
        if stamp not in df.index:
          continue
        window = df.loc[:stamp]
        if len(window) < self.warmup_bars:
          continue

        bar = df.loc[stamp]
        price = float(bar["close"])
        if price <= 0 or price > self.price_limit:
          continue

        quant = QuantEngine.dynamic_score(window, weights=self.factor_weights)
        ma20 = float(window["close"].rolling(20).mean().iloc[-1])
        ma50 = float(window["close"].rolling(50).mean().iloc[-1])
        volume = float(bar["volume"])
        avg_volume = float(window["volume"].rolling(5).mean().iloc[-1])
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        if len(window) >= 2:
          prev_close = window["close"].iloc[-2]
          if prev_close and prev_close > 0:
            ret = (price - prev_close) / prev_close
            series = returns_cache.get(symbol)
            if series is None:
              series = pd.Series(dtype=float)
              returns_cache[symbol] = series
            series.loc[stamp] = ret

        context = MarketContext(
          symbol=symbol, price=price, vix=vix_by_date.get(stamp, 18.0),
          zscore_min=float(thresholds.get("zscore_min", zscore_min)),
          quant=quant, vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
          breadth_score=self.breadth_score,
          threshold_overrides=thresholds,
          exposure=exposure,
          regime=regime_label,
          allow_new_entries=allow_new,
        )

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
              result.throttle_stats["retail_rejections"] += 1
              continue
            signal["retail_size_factor"] = retail.size_factor

          entry_result = pipeline.run(
            symbol, signal, quant, df=window,
            exposure=exposure,
            allow_intraday_entries=False,
            current_regime=regime_label,
            allow_new_entries=allow_new,
            vix=vix_by_date.get(stamp, 18.0),
            zscore_min=zscore_min,
            intraday_mode=False,
            returns_cache=returns_cache,
          )
          if not entry_result.proceed:
            if entry_result.stage in ("MIND", "CONVICTION"):
              self.mind_rejections += 1
              result.throttle_stats["mind_rejections"] += 1
            elif entry_result.stage == "PRE_TRADE":
              result.throttle_stats["portfolio_blocks"] += 1
            continue

          conf = int(signal.get("confluence_score") or 0)
          candidates.append((conf, symbol, signal, quant, window, entry_result))

      candidates.sort(key=lambda row: -row[0])
      entries_today = 0
      max_daily = int(self.emotion.max_daily_trades)

      for _, symbol, signal, quant, window, entry_result in candidates:
        if entries_today >= max_daily:
          break
        ok_book, _ = portfolio.check_book_limits(
          risk_mgr.total_capital, max_gross_pct_override=gross_cap,
        )
        if not ok_book:
          break

        entry = entry_result.entry
        stop = entry_result.stop
        shares = entry_result.shares
        if shares <= 0:
          continue

        bar_idx = frames[symbol].index.get_loc(stamp)
        risk_dollars = (entry - stop) * shares
        risk_pct = risk_dollars / risk_mgr.total_capital * 100 if risk_mgr.total_capital else 0

        open_trades[symbol] = {
          "index": int(bar_idx),
          "entry": entry,
          "stop": stop,
          "original_stop": stop,
          "target": entry_result.target or signal.get("target1"),
          "shares": shares,
          "commission": self.commission(shares),
          "entry_date": str(day),
          "risk_dollars": round(risk_dollars, 2),
          "risk_pct": round(risk_pct, 3),
          "breakeven_after_r": self.breakeven_after_r,
        }
        pacer.record_entry(when=datetime.combine(day, datetime.min.time()), persist=False)
        portfolio.sync(
          {symbol: {"quantity": shares, "avg_cost": entry}},
          {symbol: entry},
        )
        portfolio.set_stop(symbol, stop)
        portfolio.record_entry_date(symbol, when=day)
        self.emotion.record_trade(0)
        entries_today += 1

    # Close remaining at last bar
    last_stamp = dates[-1]
    for symbol, trade in list(open_trades.items()):
      df = frames[symbol]
      if last_stamp not in df.index:
        continue
      final_price = self.exit_with_slippage(float(df.loc[last_stamp]["close"]))
      gross = (final_price - trade["entry"]) * trade["shares"]
      costs = trade["commission"] + self.commission(trade["shares"])
      pnl = gross - costs
      risk_mgr.record_trade(pnl)
      result.add_trade({
        "symbol": symbol,
        "entry_date": trade.get("entry_date"),
        "exit_date": str(last_stamp.date()),
        "entry": round(trade["entry"], 2),
        "exit": round(final_price, 2),
        "shares": trade["shares"],
        "gross_pnl": round(gross, 2),
        "costs": round(costs, 2),
        "pnl": round(pnl, 2),
        "reason": "END_OF_DATA",
        "risk_dollars": trade.get("risk_dollars"),
        "risk_pct": trade.get("risk_pct"),
      })

    result.mind_rejections = self.mind_rejections
    result.retail_rejections = self.retail_rejections
    return result

  @staticmethod
  def _vix_lookup(vix_df, dates):
    if vix_df is None or vix_df.empty:
      return {}
    frame = normalize_columns(vix_df)
    if not isinstance(frame.index, pd.DatetimeIndex):
      frame = frame.copy()
      frame.index = pd.to_datetime(frame.index)
    col = "close" if "close" in frame.columns else frame.columns[0]
    series = frame[col]
    lookup = {}
    for stamp in dates:
      key = stamp.normalize()
      if key in series.index:
        lookup[stamp] = float(series.loc[key])
      else:
        prior = series.loc[:key]
        if len(prior):
          lookup[stamp] = float(prior.iloc[-1])
    return lookup
