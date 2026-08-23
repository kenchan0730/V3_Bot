#!/usr/bin/env python3
"""V4.5 交易機器人 — 機構級版本

新增：即時盈虧對帳、Bracket 訂單、持倉平倉、下單前驗證、組合層風控、
稽核軌跡、數據新鮮度驗證、告警、訂單生命週期管理。
"""

import argparse
import logging
import signal
import sys
import time
from datetime import datetime

import yfinance as yf

from core.blotter import Blotter
from core.config_loader import load_config
from core.data_utils import normalize_columns, quality_report
from core.emotion_manager import EmotionManager
from core.fundamental_filter import FundamentalFilter
from core.ibkr_connector import IBKRConnector
from core.intraday_engine import IntradayEngine
from core.logging_setup import configure_logging
from core.market_breadth import MarketBreadth
from core.news_sentiment import NewsSentiment
from core.notifier import Notifier
from core.order_manager import OrderManager
from core.portfolio import Portfolio
from core.professional_mind import ProfessionalMind
from core.quant_engine import QuantEngine
from core.regime import CRISIS, RegimeDetector
from core.risk_manager import RiskManager
from core.sector_tracker import SectorTracker
from core.strategies import MarketContext, load_strategies
from core.trading_state import TradingState
from core.watchlist_manager import WatchlistManager

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, config, dry_run=False):
        self.config = config
        self.dry_run = dry_run
        self.shutdown_requested = False

        trading_cfg = config.get("trading", {}) or {}
        risk_cfg = config.get("risk", {}) or {}
        data_cfg = config.get("data", {}) or {}
        exec_cfg = config.get("execution", {}) or {}

        self.auto_trade = bool(trading_cfg.get("auto_trade", False)) and not dry_run
        self.market_hours_only = bool(trading_cfg.get("market_hours_only", True))
        self.intraday_mode = bool(trading_cfg.get("intraday_mode", False))
        self.price_limit = float(trading_cfg.get("price_limit", 40))
        self.max_shares = int(trading_cfg.get("max_shares", 20))
        self.scan_interval = int(trading_cfg.get("scan_interval_seconds", 300))
        self.scan_interval_intraday = int(trading_cfg.get("scan_interval_intraday", 60))

        wl_cfg = config.get("watchlist", ["AVAH"])
        self.regime_detector = RegimeDetector(config.get("regime", {}))
        self.watchlist_mgr = WatchlistManager(wl_cfg, portfolio=None)
        self.watchlist = self.watchlist_mgr.get_active_watchlist()

        self.min_bars = int(data_cfg.get("min_bars", 60))
        self.max_age_trading_days = int(data_cfg.get("max_age_trading_days", 2))
        self.max_daily_move_pct = float(data_cfg.get("max_daily_move_pct", 40.0))
        self.max_data_failures = int(data_cfg.get("max_consecutive_failures", 3))
        self.context_refresh_seconds = int(data_cfg.get("context_refresh_seconds", 3600))

        self.slippage_ticks = float(exec_cfg.get("slippage_ticks", 1))
        self.tick_size = float(exec_cfg.get("tick_size", 0.01))
        self.use_bracket_orders = bool(exec_cfg.get("use_bracket_orders", True))
        self.order_timeout = int(exec_cfg.get("order_timeout_seconds", 300))

        total_capital = float(config.get("capital", {}).get("total", 385.0))

        self.state = TradingState(
            initial_capital=total_capital,
            state_file=config.get("state", {}).get("file", "logs/state.json"),
        )
        self.state.load()

        self.notifier = Notifier(config.get("notifier", {}))
        self.blotter = Blotter(config.get("audit", {}).get("blotter_file", "logs/trade_blotter.csv"))
        self.risk_mgr = RiskManager(
            initial_capital=total_capital,
            config={**risk_cfg, "vix_threshold": (config.get("volatility", {}) or {}).get("vix_threshold", 25)},
            state=self.state,
        )
        self.emotion = EmotionManager(state=self.state, config=config.get("emotion", {}))
        self.portfolio = Portfolio(config.get("portfolio", {}))
        self.fundamental = FundamentalFilter(config.get("fundamental", {}))
        self.news = NewsSentiment(config.get("news", {}))
        self.strategies = load_strategies(config)

        ibkr_cfg = config.get("ibkr", {}) or {}
        self.ibkr = IBKRConnector(
            ibkr_cfg.get("host", "127.0.0.1"),
            ibkr_cfg.get("port", 7497),
            ibkr_cfg.get("client_id", 1),
            max_retries=int(ibkr_cfg.get("max_retries", 10)),
            account_mode=ibkr_cfg.get("account_mode", "paper"),
        )
        self.order_mgr = OrderManager(
            ibkr=self.ibkr, timeout_seconds=self.order_timeout,
            blotter=self.blotter, notifier=self.notifier,
        )
        self.watchlist_mgr.portfolio = self.portfolio
        self.intraday = IntradayEngine(config.get("intraday", {}), ibkr=self.ibkr)
        self.professional = ProfessionalMind(config.get("professional_mind", {}), state=self.state)
        self.cycle_mind = None
        self.current_regime = None
        self.allow_new_entries = True
        self.allow_intraday_entries = True

        self.seen_exec_ids = set()
        self.data_failures = {}
        self.returns_cache = {}
        self.zscore_min = float((config.get("zscore", {}) or {}).get("best_zone_min", 0.5))
        self.exposure = 100
        self.breadth_score = None
        self.last_context_refresh = 0.0
        self.was_connected = False
        self.current_vix = 18.0
        self.max_cycles = None

    # ----- signals -----

    def request_shutdown(self, signum, _frame):
        logger.info(f"收到停止信號 ({signum})，準備安全關閉...")
        self.shutdown_requested = True

    def _sleep(self, seconds):
        """Interruptible sleep so shutdown stays responsive."""
        deadline = time.time() + seconds
        while time.time() < deadline and not self.shutdown_requested:
            time.sleep(min(2, max(0, deadline - time.time())))

    # ----- market context (M14) -----

    def refresh_market_context(self, force=False):
        if not force and time.time() - self.last_context_refresh < self.context_refresh_seconds:
            return
        self.last_context_refresh = time.time()

        try:
            breadth = MarketBreadth.get_breadth_score()
        except Exception as e:
            logger.warning(f"市場寬度獲取失敗: {e}")
            breadth = None

        breadth_score = breadth.get("score", 50) if breadth else 50
        self.breadth_score = breadth_score

        if breadth:
            zone, zone_msg = MarketBreadth.get_health_zone(breadth_score)
            logger.info(f"📊 市場寬度: {breadth_score}/100 ({zone}) — {zone_msg}")
            if breadth_score < 20 and self.regime_detector.cfg.get("halt_on_crisis", True):
                self.state.halt(f"市場寬度危急 ({breadth_score}/100)")
                self.notifier.alert_risk_limit(f"市場寬度 {breadth_score}/100，暫停交易")
                self.blotter.log_event("HALT", reason=f"breadth={breadth_score}")

        regime_result = self.regime_detector.detect(
            vix=self.current_vix, breadth_score=breadth_score, force_macro_refresh=force,
        )
        self.current_regime = regime_result
        self.allow_new_entries = regime_result.allow_new_entries
        self.allow_intraday_entries = regime_result.allow_intraday_entries
        self.zscore_min = regime_result.zscore_min
        exposure = regime_result.exposure_pct

        logger.info(
            f"🌡️ Regime: {regime_result.regime} ({regime_result.score:.0f}/100) | "
            f"曝險 {exposure}% | Z下限 {self.zscore_min} | "
            f"新倉 {'允許' if self.allow_new_entries else '禁止'}"
        )
        if regime_result.regime == CRISIS:
            self.blotter.log_event("REGIME", reason=f"CRISIS score={regime_result.score:.0f}")

        self.exposure = self._apply_sector_exposure(exposure)
        logger.info(f"📉 建議曝險: {self.exposure}% | Z-Score 下限: {self.zscore_min}")

    def refresh_watchlist_if_due(self, force=False):
        try:
            positions = list(self.portfolio.positions.keys()) if self.portfolio else []
            if force or self.watchlist_mgr.needs_refresh():
                active = self.watchlist_mgr.refresh(
                    fundamental_filter=self.fundamental if self.fundamental else None,
                    force=force,
                )
            else:
                active = self.watchlist_mgr.get_active_watchlist(open_positions=positions)
            if positions:
                seen = set(active)
                for sym in positions:
                    if sym not in seen:
                        active.insert(0, sym)
            theme_syms = self.professional.theme_symbols()
            for sym in theme_syms:
                if sym not in active:
                    active.append(sym)
            self.watchlist = active[: int(self.watchlist_mgr.cfg.get("max_active", 20))]
            logger.info(f"📋 活躍 watchlist ({len(self.watchlist)}): {self.watchlist}")
        except Exception as e:
            logger.warning(f"Watchlist 更新失敗: {e}")

    def _apply_sector_exposure(self, base_exposure):
        if not (self.config.get("sector", {}) or {}).get("enabled", True):
            return base_exposure
        try:
            rating = SectorTracker.get_sector_rating()
            weights = rating.get("weights", {})
            if not weights:
                return base_exposure
            avg_weight = sum(weights.values()) / len(weights)
            for alert in rating.get("alerts", []):
                logger.warning(f"板塊警報: {alert}")
            return max(0, min(100, int(base_exposure * avg_weight / 100)))
        except Exception as e:
            logger.warning(f"板塊分析失敗: {e}")
            return base_exposure

    # ----- reconciliation (H1) -----

    def reconcile(self):
        """Sync positions, capital and realised P&L from the broker."""
        if not self.ibkr.is_connected():
            if self.was_connected and RiskManager.is_market_open():
                self.notifier.alert_disconnect("交易時段內 IBKR 連線中斷，嘗試重連")
                self.blotter.log_event("DISCONNECT", reason="market hours")
                self.ibkr.connect()
            self.was_connected = self.ibkr.is_connected()
            return

        self.was_connected = True
        try:
            positions = self.ibkr.sync_positions()
            prices = {s: p.get("avg_cost", 0) for s, p in positions.items()}
            self.portfolio.sync(positions, prices)

            account = self.ibkr.get_account_values()
            if account.get("net_liquidation"):
                self.risk_mgr.update_capital(account["net_liquidation"])

            realized, new_ids, details = self.ibkr.get_realized_pnl_since(self.seen_exec_ids)
            for fill in details:
                self.seen_exec_ids.add(fill["exec_id"])
                self.state.record_fill(
                    fill["symbol"], fill["side"], fill["shares"],
                    fill["price"], fill["realized_pnl"], fill["exec_id"],
                )
                self.blotter.log_fill(
                    fill["symbol"], fill["side"], fill["shares"], fill["price"],
                    fill["exec_id"], fill["realized_pnl"],
                )
            if realized:
                ok, msg = self.risk_mgr.is_within_daily_loss_limit()
                logger.info(f"💱 對帳已實現盈虧 ${realized:.2f} | {msg}")
                if not ok:
                    self.state.halt(msg)
                    self.notifier.alert_daily_loss(msg)
        except Exception as e:
            logger.exception(f"對帳失敗: {e}")
            self.notifier.alert_exception("reconcile", e)

    # ----- data (H7) -----

    def fetch_symbol_data(self, symbol):
        raw = None
        if self.ibkr.is_connected():
            try:
                raw = self.ibkr.get_historical_data(symbol, duration="6 M", bar_size="1 day")
            except Exception as e:
                logger.warning(f"{symbol} IBKR 數據錯誤: {e}")
                raw = None
        if raw is None or len(raw) < self.min_bars:
            try:
                raw = yf.download(symbol, period="6mo", interval="1d", progress=False)
            except Exception as e:
                logger.warning(f"{symbol} yfinance 數據錯誤: {e}")
                raw = None

        if raw is None or len(raw) == 0:
            failures = self.data_failures.get(symbol, 0) + 1
            self.data_failures[symbol] = failures
            if failures >= self.max_data_failures:
                self.notifier.alert_data_failure(symbol, failures)
                self.blotter.log_rejection(symbol, f"數據獲取失敗 {failures} 次", stage="DATA")
            return None

        df = normalize_columns(raw)
        report = quality_report(
            df, min_bars=self.min_bars,
            max_age_trading_days=self.max_age_trading_days,
            max_daily_move_pct=self.max_daily_move_pct,
        )
        if not report["ok"]:
            failures = self.data_failures.get(symbol, 0) + 1
            self.data_failures[symbol] = failures
            logger.warning(f"   ⏳ {symbol} 數據品質不合格 [{report['stage']}]: {report['message']}")
            self.blotter.log_rejection(symbol, report["message"], stage="DATA_QUALITY")
            if report["stage"] == "freshness":
                self.notifier.alert_stale_data(symbol, report["message"])
            elif failures >= self.max_data_failures:
                self.notifier.alert_data_failure(symbol, failures, report["message"])
            return None

        self.data_failures[symbol] = 0
        if "close" in df.columns:
            self.returns_cache[symbol] = df["close"].pct_change().dropna()
        return df

    def _effective_gross_cap(self):
        """Tighten book gross limit by regime exposure (e.g. RISK_OFF 25%)."""
        return min(self.portfolio.max_gross_exposure_pct, float(self.exposure))

    # ----- pre-trade validation (H4) -----

    def validate_pre_trade(self, symbol, shares, entry, stop):
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
            max_gross_pct_override=self._effective_gross_cap(),
        )
        if not allowed:
            return False, reason

        if self.auto_trade and self.ibkr.is_connected():
            buying_power = self.ibkr.get_buying_power()
            if buying_power and cost > buying_power:
                return False, f"購買力不足: 需 ${cost:.2f} > 可用 ${buying_power:.2f}"

        return True, "OK"

    def entry_with_slippage(self, price):
        return round(price + self.slippage_ticks * self.tick_size, 2)

    # ----- trade handling -----

    def handle_buy(self, symbol, signal, quant, vol_ratio, df=None):
        entry = self.entry_with_slippage(signal["entry"])
        stop = signal["stop"]
        target = signal.get("target1")

        intraday_check = {"ok": True, "reason": "intraday skipped", "entry_price": entry, "metrics": {}}
        if self.intraday_mode and self.intraday.cfg.get("enabled", True):
            if not self.allow_intraday_entries:
                logger.info(f"   ⏳ Regime 禁止盤中進場")
                self.blotter.log_rejection(symbol, f"regime {self.current_regime.regime} blocks intraday", stage="REGIME")
                return
            intraday_check = self.intraday.evaluate_entry(symbol, signal.get("action", "STRONG_BUY"), entry)
            if not intraday_check.get("ok"):
                logger.info(f"   ⏳ 盤中確認未通過: {intraday_check.get('reason')}")
                self.blotter.log_rejection(symbol, intraday_check.get("reason", ""), stage="INTRADAY")
                return
            entry = intraday_check.get("entry_price", entry)
            logger.info(
                f"   ✅ 盤中確認: {intraday_check.get('reason')} | "
                f"VWAP {intraday_check.get('metrics', {}).get('vwap')} | 進場 ${entry:.2f}"
            )

        shares = self.risk_mgr.calculate_position_size(entry, stop, self.price_limit, self.max_shares)
        if self.exposure < 100:
            shares = int(shares * self.exposure / 100)
        scale = self.portfolio.correlation_scale(symbol, self.returns_cache)
        if scale < 1.0:
            shares = int(shares * scale)

        mind_ctx = MarketContext(
            symbol=symbol, price=entry, vix=self.current_vix, zscore_min=self.zscore_min,
            exposure=self.exposure, breadth_score=self.breadth_score, quant=quant,
            regime=self.current_regime.regime if self.current_regime else "NEUTRAL",
            allow_new_entries=self.allow_new_entries,
        )
        mind_decision = self.professional.approve_entry(
            symbol, signal, df, mind_ctx, self.portfolio, self.risk_mgr,
            entry, stop, shares, is_day_trade=False,
        )
        if not mind_decision.approve:
            reason = "; ".join(mind_decision.reasons or mind_decision.thoughts or ["mind rejected"])
            logger.info(f"   🧠 專業心態拒絕: {reason}")
            self.blotter.log_rejection(symbol, reason, stage="MIND")
            return
        if mind_decision.stop_override:
            stop = mind_decision.stop_override
        if mind_decision.shares_scale and mind_decision.shares_scale < 1.0:
            shares = max(1, int(shares * mind_decision.shares_scale))
        if mind_decision.risk_multiplier < 1.0:
            shares = max(1, int(shares * mind_decision.risk_multiplier))
        if mind_decision.thoughts:
            logger.info(f"   🧠 {' | '.join(mind_decision.thoughts[:3])} (exec {mind_decision.execution_score}/10)")

        ok, reason = self.validate_pre_trade(symbol, shares, entry, stop)
        if not ok:
            logger.info(f"   ⏳ 下單前驗證未通過: {reason}")
            self.blotter.log_rejection(symbol, reason)
            return

        cost = shares * entry
        logger.info("   🎯 買入信號觸發！")
        logger.info(f"   📊 買入 {shares} 股 @ ${entry:.2f} (停損 ${stop:.2f} / 目標 ${target})")
        logger.info(f"   💰 成本 ${cost:.2f} ({cost / self.risk_mgr.total_capital * 100:.1f}%) "
                    f"| 風險 ${(entry - stop) * shares:.2f}")

        self.notifier.send_trade_signal(
            symbol, "BUY", entry, stop, target, signal.get("target2", target), shares
        )

        if not self.auto_trade:
            self.blotter.log_event(
                "SIGNAL_ONLY", symbol=symbol, reason="auto_trade 停用",
                shares=shares, entry_price=entry, stop_price=stop, target_price=target,
            )
            return

        bracket = None
        if self.use_bracket_orders:
            bracket = self.ibkr.place_bracket_order(symbol, shares, entry, stop, target, action="BUY")
        if bracket is None:
            logger.error(f"   ❌ {symbol} Bracket 下單失敗，未建立無保護倉位")
            self.notifier.alert_order_issue(symbol, "Bracket 下單失敗，已跳過（避免無停損持倉）")
            self.blotter.log_rejection(symbol, "bracket 下單失敗", stage="EXECUTION")
            return

        self.order_mgr.track_bracket(bracket)
        self.portfolio.set_stop(symbol, stop)
        self.blotter.log_order(
            symbol, "BUY", shares, bracket.get("parent_id"), entry, stop, target,
            reason=signal.get("reason", ""),
        )
        self.emotion.record_trade(0)

    def handle_sell(self, symbol, signal, price):
        logger.info(f"   🔴 賣出信號: {signal.get('reason', '')}")
        quantity = self.portfolio.position_quantity(symbol)
        if quantity <= 0:
            logger.info(f"   ⏳ {symbol} 無持倉，僅記錄信號")
            self.blotter.log_event("SIGNAL_NO_POSITION", symbol=symbol, reason=signal.get("reason", ""))
            return

        self.notifier.send_trade_signal(symbol, "SELL", price, price, price, price, quantity)
        if not self.auto_trade:
            self.blotter.log_event("SIGNAL_ONLY", symbol=symbol, reason="auto_trade 停用 (SELL)")
            return

        cancelled = self.ibkr.cancel_orders_for_symbol(symbol)
        trade = self.ibkr.close_position(symbol, limit_price=None)
        if trade is None:
            self.notifier.alert_order_issue(symbol, "平倉下單失敗")
            self.blotter.log_rejection(symbol, "平倉失敗", stage="EXECUTION")
            return
        self.blotter.log_order(
            symbol, "SELL", quantity, getattr(getattr(trade, "order", None), "orderId", None),
            price, None, None, reason=f"STRONG_SELL (取消 {cancelled} 筆掛單)",
        )

    # ----- per-symbol pipeline -----

    def process_symbol(self, symbol):
        logger.info(f"\n🔍 分析: {symbol}")

        passed, reason = self.fundamental.filter(symbol)
        if not passed:
            logger.info(f"   ⏳ 基本面過濾: {reason}")
            self.blotter.log_rejection(symbol, reason, stage="FUNDAMENTAL")
            return

        if getattr(self.news, "enabled", False):
            try:
                news_ok, news_msg = self.news.is_sentiment_ok(symbol)
                if not news_ok:
                    logger.info(f"   ⏳ {news_msg}")
                    self.blotter.log_rejection(symbol, news_msg, stage="NEWS")
                    return
            except Exception as e:
                logger.warning(f"新聞情緒檢查失敗 {symbol}: {e}")

        df = self.fetch_symbol_data(symbol)
        if df is None:
            return

        price = float(df["close"].iloc[-1])
        if price <= 0 or price > self.price_limit:
            logger.info(f"   ⏳ 股價 ${price:.2f} 超出上限 ${self.price_limit}")
            self.blotter.log_rejection(symbol, f"股價 {price:.2f} 超出上限")
            return

        quant = QuantEngine.dynamic_score(df)
        ma20 = float(df["close"].rolling(20).mean().iloc[-1])
        ma50 = float(df["close"].rolling(50).mean().iloc[-1])
        volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].rolling(5).mean().iloc[-1])
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        context = MarketContext(
            symbol=symbol, price=price, vix=self.current_vix, zscore_min=self.zscore_min,
            exposure=self.exposure, breadth_score=self.breadth_score, quant=quant,
            vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
            regime=self.current_regime.regime if self.current_regime else "NEUTRAL",
            regime_score=self.current_regime.score if self.current_regime else None,
            allow_new_entries=self.allow_new_entries,
        )

        can_trade, emo_msg = self.emotion.check_before_trade()

        for strategy in self.strategies:
            ok, prefilter_reason = strategy.prefilter(df, context)
            if not ok:
                logger.info(f"   ⏳ [{strategy.name}] {prefilter_reason}")
                self.blotter.log_rejection(symbol, prefilter_reason, stage="PREFILTER")
                continue

            signal = strategy.generate_signal(df, context)
            self.blotter.log_signal(symbol, signal, quant, vol_ratio, self.exposure)

            action = signal.get("action")
            if action == "STRONG_BUY":
                if not can_trade:
                    logger.warning(f"   {emo_msg}")
                    self.blotter.log_rejection(symbol, emo_msg, stage="EMOTION")
                    continue
                self.handle_buy(symbol, signal, quant, vol_ratio, df=df)
                return True
            elif action == "STRONG_SELL":
                self.handle_sell(symbol, signal, price)
                return True
            else:
                logger.info(f"   ⏳ [{strategy.name}] {signal.get('reason', '')} (RSI {quant.get('rsi', 0):.1f})")
        return False

    # ----- risk gates -----

    def check_gates(self):
        """Returns (may_trade, reason). Halts on breach."""
        if self.state.halted:
            return False, f"系統已停機: {self.state.halt_reason}"

        ok, msg = self.risk_mgr.check_drawdown()
        if not ok:
            self.state.halt(msg)
            self.notifier.alert_risk_limit(msg)
            self.blotter.log_event("HALT", reason=msg)
            return False, msg

        ok, msg = self.risk_mgr.is_within_daily_loss_limit()
        if not ok:
            self.state.halt(msg)
            self.notifier.alert_daily_loss(msg)
            self.blotter.log_event("HALT", reason=msg)
            return False, msg

        ok, msg = self.portfolio.check_book_limits(
            self.risk_mgr.total_capital,
            max_gross_pct_override=self._effective_gross_cap(),
        )
        if not ok:
            logger.warning(f"⚠️ 組合限額: {msg}（暫停新進場）")
            return False, msg

        return True, msg

    # ----- vix -----

    def refresh_vix(self):
        for attempt in range(3):
            try:
                data = yf.Ticker("^VIX").history(period="1d")
                if not data.empty:
                    self.current_vix = float(data["Close"].iloc[-1])
                    self.risk_mgr.check_vix(self.current_vix)
                    return self.current_vix
            except Exception as e:
                logger.warning(f"VIX 獲取失敗 (嘗試 {attempt + 1}/3): {e}")
                time.sleep(1)
        self.current_vix = getattr(self, "current_vix", 18.0)
        self.risk_mgr.check_vix(self.current_vix)
        return self.current_vix

    # ----- main loop -----

    def run(self):
        signal.signal(signal.SIGINT, self.request_shutdown)
        signal.signal(signal.SIGTERM, self.request_shutdown)

        mode = "DRY-RUN" if self.dry_run else ("AUTO-TRADE" if self.auto_trade else "SIGNAL-ONLY")
        logger.info("=" * 60)
        logger.info(f"🚀 V4.5 交易機器人啟動 ({mode})")
        logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"💼 資本 ${self.risk_mgr.total_capital:.2f} | 觀察名單 {self.watchlist}")
        logger.info("=" * 60)
        self.notifier.alert_startup(f"模式 {mode}，資本 ${self.risk_mgr.total_capital:.2f}")
        self.blotter.log_event("STARTUP", reason=mode)

        try:
            if not self.ibkr.connect():
                logger.warning("⚠️ IBKR 連線失敗，將使用 yfinance（僅信號）")
                if self.auto_trade:
                    self.auto_trade = False
                    self.notifier.alert_disconnect("啟動時無法連線 IBKR，auto_trade 已自動關閉")
            else:
                self.was_connected = True
        except Exception as e:
            logger.exception(f"IBKR 初始化失敗: {e}")
            self.notifier.alert_exception("ibkr_connect", e)

        self.refresh_vix()
        self.refresh_market_context(force=True)
        self.refresh_watchlist_if_due(force=True)
        self.reconcile()

        cycle = 0
        try:
            while not self.shutdown_requested:
                cycle += 1
                logger.info(f"\n🔄 第 {cycle} 次掃描 ({datetime.now().strftime('%H:%M:%S')})")

                try:
                    self.state.reset_daily_if_needed()

                    if self.market_hours_only and not RiskManager.is_market_open():
                        logger.info("💤 美股已收市，暫停掃描 10 分鐘")
                        self.publish_state()
                        self._sleep(600)
                        continue

                    self.refresh_market_context()
                    self.refresh_vix()
                    self.refresh_watchlist_if_due()
                    self.reconcile()

                    self.cycle_mind = self.professional.deliberate_cycle(
                        self.current_regime, self.portfolio, self.risk_mgr.total_capital,
                        watchlist_len=len(self.watchlist),
                    )
                    if self.cycle_mind.action == "STRATEGIC_CASH":
                        logger.info(
                            f"🧠 主動空倉: {' | '.join(self.cycle_mind.thoughts[:2])}"
                        )
                        self.blotter.log_event(
                            "STRATEGIC_CASH",
                            reason=" | ".join(self.cycle_mind.thoughts[:3]),
                        )

                    self.order_mgr.poll()
                    self.order_mgr.cancel_stale()

                    may_trade, gate_reason = self.check_gates()
                    regime_label = self.current_regime.regime if self.current_regime else "N/A"
                    logger.info(
                        f"💰 當日已實現 ${self.risk_mgr.get_daily_pnl():.2f} | "
                        f"Regime {regime_label} | "
                        f"曝險 {self.portfolio.gross_exposure_pct(self.risk_mgr.total_capital):.1f}% | "
                        f"持倉 {self.portfolio.open_position_count()} | 風控: {gate_reason}"
                    )
                    if self.state.halted:
                        logger.error(f"🔴 停機中: {self.state.halt_reason}")
                        self.publish_state()
                        break

                    cycle_had_setup = False
                    for symbol in self.watchlist:
                        if self.shutdown_requested:
                            break
                        try:
                            if not may_trade and not self.portfolio.has_position(symbol):
                                continue
                            if not self.allow_new_entries and not self.portfolio.has_position(symbol):
                                continue
                            if self.professional.strategic_cash_mode and not self.portfolio.has_position(symbol):
                                continue
                            if self.process_symbol(symbol):
                                cycle_had_setup = True
                        except Exception as e:
                            logger.exception(f"分析 {symbol} 時發生錯誤: {e}")
                            self.notifier.alert_exception(f"process_symbol:{symbol}", e)

                    if cycle_had_setup:
                        self.professional.record_setup_found()
                    else:
                        self.professional.record_no_setup_cycle()

                    self.publish_state()

                except Exception as e:
                    logger.exception(f"掃描週期異常: {e}")
                    self.notifier.alert_exception(f"cycle:{cycle}", e)

                if self.shutdown_requested:
                    break
                if self.max_cycles and cycle >= self.max_cycles:
                    logger.info(f"已完成 {cycle} 次掃描（max_cycles），結束")
                    break
                interval = self.scan_interval
                if self.intraday_mode and RiskManager.is_market_open():
                    interval = self.scan_interval_intraday
                self._sleep(interval)

        except Exception as e:
            logger.exception(f"主循環異常: {e}")
            self.notifier.alert_exception("main_loop", e)
        finally:
            self.shutdown()

    def publish_state(self):
        """Persist state plus a portfolio snapshot for the dashboard."""
        self.state.publish_portfolio(
            self.portfolio, self.risk_mgr.total_capital, self.order_mgr.snapshot()
        )
        self.state.save()

    def shutdown(self):
        logger.info("正在安全關閉...")
        try:
            self.order_mgr.poll()
        except Exception as e:
            logger.warning(f"關閉時輪詢訂單失敗: {e}")
        self.publish_state()
        self.blotter.log_event(
            "SHUTDOWN",
            reason=f"daily_pnl={self.risk_mgr.get_daily_pnl():.2f}",
            realized_pnl=self.state.total_realized_pnl,
        )
        try:
            self.ibkr.disconnect()
        except Exception as e:
            logger.warning(f"IBKR 斷線時發生錯誤: {e}")
        self.notifier.alert_shutdown(
            f"已實現總盈虧 ${self.state.total_realized_pnl:.2f}，持倉 {self.portfolio.open_position_count()}"
        )
        logger.info("👋 V4.5 交易機器人已安全關閉")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="V4.5 交易機器人")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--dry-run", action="store_true", help="強制僅信號模式，不下單")
    parser.add_argument("--once", action="store_true", help="只執行一次掃描後結束")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config, args.env)
    configure_logging(config.get("logging", {}))

    bot = TradingBot(config, dry_run=args.dry_run)
    if args.once:
        bot.max_cycles = 1
        bot.market_hours_only = False
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
