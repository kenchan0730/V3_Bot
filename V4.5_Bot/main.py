#!/usr/bin/env python3
"""V4.5 交易機器人 — 機構級版本

新增：即時盈虧對帳、Bracket 訂單、持倉平倉、下單前驗證、組合層風控、
稽核軌跡、數據新鮮度驗證、告警、訂單生命週期管理。
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime

import yfinance as yf

from core.blotter import Blotter
from core.config_loader import load_config
from core.data_utils import normalize_columns, quality_report
from core.entry_pipeline import EntryPipeline
from core.emotion_manager import EmotionManager
from core.external_signals import ExternalSignalInbox
from core.fundamental_filter import FundamentalFilter
from core.ibkr_connector import IBKRConnector
from core.intraday_engine import IntradayEngine
from core.logging_setup import configure_logging
from core.market_breadth import MarketBreadth
from core.market_data_sources import fetch_daily_bars
from core.news_credibility import NewsCredibilityAuditor
from core.news_sentiment import NewsSentiment
from core.notifier import Notifier
from core.order_manager import OrderManager
from core.portfolio import Portfolio
from core.professional_mind import ProfessionalMind
from core.quant_engine import QuantEngine
from core.realtime_pulse import RealtimePulse
from core.retail_mind import RetailMind
from core.signal_reviewer import ExternalSignalReviewer, SymbolAnalysis
from core.swing_filters import SwingQualityFilter
from core.regime import CRISIS, RegimeDetector
from core.risk_manager import RiskManager
from core.sector_tracker import SectorTracker
from core.strategies import MarketContext, load_strategies
from core.trade_pacing import TradePacer
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
        self.fetch_timeout = int(data_cfg.get("fetch_timeout_seconds", 30))
        self.market_data_cfg = self._build_market_data_config(config)

        self.slippage_ticks = float(exec_cfg.get("slippage_ticks", 1))
        self.tick_size = float(exec_cfg.get("tick_size", 0.01))
        self.use_bracket_orders = bool(exec_cfg.get("use_bracket_orders", True))
        self.order_timeout = int(exec_cfg.get("order_timeout_seconds", 300))
        self.protection_poll_interval = int(exec_cfg.get("protection_poll_interval_seconds", 60))

        total_capital = float(config.get("capital", {}).get("total", 385.0))

        self.state = TradingState(
            initial_capital=total_capital,
            state_file=config.get("state", {}).get("file", "data/state.json"),
        )
        self.state.load()

        self.notifier = Notifier(config.get("notifier", {}))
        self.blotter = Blotter(config.get("audit", {}).get("blotter_file", "data/trade_blotter.csv"))
        self.risk_mgr = RiskManager(
            initial_capital=total_capital,
            config={**risk_cfg, "vix_threshold": (config.get("volatility", {}) or {}).get("vix_threshold", 25)},
            state=self.state,
        )
        self.emotion = EmotionManager(state=self.state, config=config.get("emotion", {}))
        self.portfolio = Portfolio(config.get("portfolio", {}))
        self._restore_stops_from_state()
        # Portfolio owns the single-name cap; keep sizing aligned with it.
        self.risk_mgr.set_concentration_cap(self.portfolio.max_symbol_pct)
        self.fundamental = FundamentalFilter(config.get("fundamental", {}))
        self.news = NewsSentiment(config.get("news", {}))
        self.swing_filter = SwingQualityFilter(
            config.get("swing_trading", {}),
            portfolio=self.portfolio,
        )
        self.realtime_pulse = RealtimePulse(
            config.get("market_data", {}),
            ibkr=None,
        )
        self.retail_mind = RetailMind(self._build_retail_config(config))
        self.pacer = TradePacer(config.get("trade_pacing", {}))
        self.credibility = NewsCredibilityAuditor(
            (config.get("news", {}) or {}).get("credibility", {})
        )
        self.external_inbox = ExternalSignalInbox(config.get("external_signals", {}))
        self.threshold_overrides = {}
        self.pace_status = None
        self.strategies = load_strategies(config)

        ibkr_cfg = config.get("ibkr", {}) or {}
        self._validate_live_config(ibkr_cfg)
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
        self.intraday = IntradayEngine(
            config.get("intraday", {}),
            ibkr=self.ibkr,
            market_data_config=self.market_data_cfg,
        )
        self.realtime_pulse.ibkr = self.ibkr
        self.professional = ProfessionalMind(config.get("professional_mind", {}), state=self.state)
        self.entry_pipeline = EntryPipeline(
            self.risk_mgr,
            self.portfolio,
            self.professional,
            self.intraday,
            slippage_ticks=self.slippage_ticks,
            tick_size=self.tick_size,
            price_limit=self.price_limit,
            max_shares=self.max_shares,
            auto_trade=self.auto_trade,
            ibkr=self.ibkr,
            max_gross_pct_fn=self._effective_gross_cap,
            min_notional=self.retail_mind.min_viable_notional(),
        )
        swing_cfg = config.get("swing_trading", {}) or {}
        self.entry_pipeline.moderate_size_factor = float(swing_cfg.get("moderate_size_factor", 0.5))
        self.reviewer = ExternalSignalReviewer(
            analyzer=self.analyze_symbol,
            credibility=self.credibility,
            retail_mind=self.retail_mind,
            news=self.news,
            fundamental=self.fundamental,
            capital_fn=lambda: self.risk_mgr.total_capital,
            max_shares=self.max_shares,
            max_symbol_pct=self.portfolio.max_symbol_pct,
        )
        self.cycle_mind = None
        self.current_regime = None
        self.allow_new_entries = True
        self.allow_intraday_entries = True
        self.vix_blocks_entries = False
        self.stop_protection_blocks_entries = False

        self.seen_exec_ids = set()
        self.data_failures = {}
        self.returns_cache = {}
        self.zscore_min = float((config.get("zscore", {}) or {}).get("best_zone_min", 0.5))
        self.factor_weights = (config.get("zscore", {}) or {}).get("weights") or None
        self.exposure = 100
        self.breadth_score = None
        self.last_context_refresh = 0.0
        self.was_connected = False
        self.current_vix = 18.0
        self.vix_failures = 0
        self.vix_is_stale = False
        self.max_cycles = None
        self.last_protection_check = 0.0

    def _validate_live_config(self, ibkr_cfg):
        """Refuse to start live trading on the wrong IBKR port without explicit confirm."""
        mode = str(ibkr_cfg.get("account_mode", "paper")).lower()
        port = int(ibkr_cfg.get("port", 7497))
        if mode != "live":
            return
        if port != 7496:
            raise SystemExit(
                f"IBKR account_mode=live 要求 port=7496（TWS 實盤），目前為 {port}。"
                "請修正 data/.env 後重試。"
            )
        confirm = os.environ.get("LIVE_TRADING_CONFIRM", "").strip().lower()
        if confirm not in ("yes", "true", "1"):
            raise SystemExit(
                "live 模式需要明確確認：請在 data/.env 設定 LIVE_TRADING_CONFIRM=yes"
            )
        logger.warning("⚠️ LIVE TRADING MODE — port=7496 已確認，請再次核對 TWS 帳戶")

    @staticmethod
    def _build_retail_config(config):
        """Retail mind inherits the same cost model the backtest charges."""
        retail_cfg = dict(config.get("retail_mind", {}) or {})
        costs = config.get("backtest", {}) or {}
        retail_cfg.setdefault("commission_per_share", costs.get("commission_per_share", 0.005))
        retail_cfg.setdefault("commission_minimum", costs.get("commission_minimum", 1.0))
        return retail_cfg

    @staticmethod
    def _build_market_data_config(config):
        """Merge data/intraday/news keys into one fetcher config."""
        data_cfg = config.get("data", {}) or {}
        md_cfg = dict(config.get("market_data", {}) or {})
        news_cfg = config.get("news", {}) or {}
        md_cfg.setdefault("min_bars", data_cfg.get("min_bars", 60))
        md_cfg.setdefault("fetch_timeout_seconds", data_cfg.get("fetch_timeout_seconds", 30))
        md_cfg.setdefault("finnhub_key", news_cfg.get("finnhub_key", ""))
        intraday_cfg = config.get("intraday", {}) or {}
        md_cfg.setdefault("bar_size", intraday_cfg.get("bar_size", "5 mins"))
        md_cfg.setdefault("fallback_interval", intraday_cfg.get("fallback_interval", "5m"))
        md_cfg.setdefault("min_intraday_bars", intraday_cfg.get("min_intraday_bars", 12))
        alpaca = md_cfg.get("alpaca") or {}
        alpaca.setdefault("api_key", md_cfg.get("alpaca_api_key", ""))
        alpaca.setdefault("api_secret", md_cfg.get("alpaca_api_secret", ""))
        md_cfg["alpaca"] = alpaca
        return md_cfg

    def _entries_permitted(self):
        """Combine regime, VIX freshness and stop-protection gates."""
        return (
            self.allow_new_entries
            and not self.vix_blocks_entries
            and not self.stop_protection_blocks_entries
        )

    def _restore_stops_from_state(self):
        """Seed intended stops from the last persisted portfolio snapshot."""
        for symbol, pos in (self.state.positions or {}).items():
            if isinstance(pos, dict) and pos.get("stop"):
                self.portfolio.record_intended_stop(symbol, pos["stop"])

    def _hydrate_broker_orders(self):
        if not self.ibkr.is_connected():
            return 0
        return self.order_mgr.hydrate_from_broker()

    def _run_candle_lab_auto_learn(self):
        """Background-friendly auto-learn: pulls OHLCV, no user images required."""
        candle_cfg = self.config.get("candle", {}) or {}
        if not candle_cfg.get("auto_learn_on_startup", False):
            return
        try:
            from candle_lab.engine import CandleLabEngine
            engine = CandleLabEngine(self.config)
            result = engine.auto_learn(self.watchlist, save=True)
            logger.info(
                f"🕯️ Candle Lab 启动学习完成："
                f"{result.get('symbols_scanned', 0)} 只股票，"
                f"{len(result.get('patterns', {}))} 种形态"
            )
        except Exception as exc:
            logger.warning(f"Candle Lab 自动学习跳过: {exc}")

    # ----- signals -----

    def request_shutdown(self, signum, _frame):
        logger.info(f"收到停止信號 ({signum})，準備安全關閉...")
        self.shutdown_requested = True

    def _sleep(self, seconds):
        """Interruptible sleep; poll stop protection while holding open positions."""
        deadline = time.time() + seconds
        while time.time() < deadline and not self.shutdown_requested:
            if (
                self.portfolio.open_position_count() > 0
                and time.time() - self.last_protection_check >= self.protection_poll_interval
            ):
                self.verify_stop_protection()
                self.last_protection_check = time.time()
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
        try:
            self.swing_filter.refresh_sector_context(force=True)
            logger.info(f"🏭 {self.swing_filter.market_summary()}")
        except Exception as exc:
            logger.warning(f"板塊輪動更新失敗: {exc}")

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
            self._hydrate_broker_orders()

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

    def verify_stop_protection(self):
        """Detect positions whose broker-side stop vanished and re-arm it."""
        if not self.portfolio.positions:
            self.stop_protection_blocks_entries = False
            return []
        try:
            reports = self.order_mgr.check_protection(
                self.portfolio.positions,
                stops=self.portfolio.stops,
                auto_rearm=self.auto_trade and self.ibkr.is_connected(),
            )
        except Exception as e:
            logger.exception(f"停損保護檢查失敗: {e}")
            self.notifier.alert_exception("verify_stop_protection", e)
            return []

        at_risk = []
        for report in reports:
            if report.get("rearmed"):
                logger.warning(f"🛡️ {report['symbol']} 已自動補掛停損")
                continue
            if report["status"] in ("unprotected", "untracked"):
                at_risk.append(report)
                msg = (
                    f"CRITICAL 裸倉：{report['symbol']} 停損缺失 ({report['status']})，"
                    f"re-arm {'失敗' if report.get('rearm_failed') else '未執行'}"
                )
                logger.error(f"🚨 {msg}")
                self.notifier.alert_risk_limit(msg)
                self.blotter.log_event(
                    "STOP_REARM_FAILED",
                    symbol=report["symbol"],
                    reason=msg,
                    shares=report.get("quantity"),
                    stop_price=report.get("stop_price") or "",
                )

        self.stop_protection_blocks_entries = len(at_risk) > 0
        self.last_protection_check = time.time()
        return reports

    # ----- data (H7) -----

    def fetch_symbol_data(self, symbol):
        raw, source = fetch_daily_bars(
            symbol,
            ibkr=self.ibkr,
            config=self.market_data_cfg,
        )
        if raw is None or len(raw) == 0:
            failures = self.data_failures.get(symbol, 0) + 1
            self.data_failures[symbol] = failures
            if failures >= self.max_data_failures:
                self.notifier.alert_data_failure(symbol, failures)
                self.blotter.log_rejection(symbol, f"數據獲取失敗 {failures} 次", stage="DATA")
            return None

        df = normalize_columns(raw)
        if source:
            logger.debug("%s daily bars source=%s", symbol, source)
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

    def entry_with_slippage(self, price):
        return self.entry_pipeline.step_slippage(price)

    def _log_entry_rejection(self, symbol, result):
        stage = result.stage
        reason = result.reason
        if stage == "REGIME":
            logger.info("   ⏳ Regime 禁止盤中進場")
            self.blotter.log_rejection(symbol, reason, stage=stage)
        elif stage == "INTRADAY":
            logger.info(f"   ⏳ 盤中確認未通過: {reason}")
            self.blotter.log_rejection(symbol, reason, stage=stage)
        elif stage == "MIND":
            logger.info(f"   🧠 專業心態拒絕: {reason}")
            self.blotter.log_rejection(symbol, reason, stage=stage)
        elif stage == "CONVICTION":
            logger.info(f"   🧠 {reason}")
            self.blotter.log_rejection(symbol, reason, stage=stage)
        elif stage == "PRE_TRADE":
            logger.info(f"   ⏳ 下單前驗證未通過: {reason}")
            self.blotter.log_rejection(symbol, reason)

    # ----- trade handling -----

    def handle_buy(self, symbol, signal, quant, vol_ratio, df=None):
        result = self.entry_pipeline.run(
            symbol, signal, quant, df=df,
            exposure=self.exposure,
            allow_intraday_entries=self.allow_intraday_entries,
            current_regime=self.current_regime.regime if self.current_regime else "NEUTRAL",
            allow_new_entries=self._entries_permitted(),
            vix=self.current_vix,
            zscore_min=self.zscore_min,
            breadth_score=self.breadth_score,
            returns_cache=self.returns_cache,
            intraday_mode=self.intraday_mode,
        )

        if not result.proceed:
            self._log_entry_rejection(symbol, result)
            return

        entry = result.entry
        stop = result.stop
        target = result.target
        shares = result.shares
        mind_decision = result.mind_decision
        intraday_check = result.intraday_check

        if (
            self.intraday_mode
            and self.intraday.cfg.get("enabled", True)
            and intraday_check.get("ok")
            and intraday_check.get("reason") != "intraday skipped"
        ):
            logger.info(
                f"   ✅ 盤中確認: {intraday_check.get('reason')} | "
                f"VWAP {intraday_check.get('metrics', {}).get('vwap')} | 進場 ${entry:.2f}"
            )

        if result.conviction < 1.0:
            logger.info(
                f"   🎚️ 共振分級 exec {mind_decision.execution_score}/10 "
                f"→ 倉位 x{result.conviction:.2f} = {shares} 股"
            )

        if mind_decision and mind_decision.thoughts:
            logger.info(
                f"   🧠 {' | '.join(mind_decision.thoughts[:3])} "
                f"(exec {mind_decision.execution_score}/10)"
            )

        cost = shares * entry
        logger.info("   🎯 買入信號觸發！")
        logger.info(f"   📊 買入 {shares} 股 @ ${entry:.2f} (停損 ${stop:.2f} / 目標 ${target})")
        logger.info(f"   💰 成本 ${cost:.2f} ({cost / self.risk_mgr.total_capital * 100:.1f}%) "
                    f"| 風險 ${(entry - stop) * shares:.2f}")

        self.notifier.send_trade_signal(
            symbol, "BUY", entry, stop, target, signal.get("target2", target), shares
        )

        if not self.auto_trade:
            # Signal-only still counts toward pacing so the frequency target
            # reflects what the strategy would have traded.
            self.pacer.record_entry()
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
        self.portfolio.record_intended_stop(symbol, stop)
        self.blotter.log_order(
            symbol, "BUY", shares, bracket.get("parent_id"), entry, stop, target,
            reason=signal.get("reason", ""),
        )
        self.emotion.record_trade(0)
        self.pacer.record_entry()

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
        self.portfolio.clear_stop(symbol)
        self.blotter.log_order(
            symbol, "SELL", quantity, getattr(getattr(trade, "order", None), "orderId", None),
            price, None, None, reason=f"STRONG_SELL (取消 {cancelled} 筆掛單)",
        )

    # ----- pacing -----

    def refresh_pacing(self):
        """Translate the rolling 30-day trade count into effective soft thresholds."""
        swing_cfg = self.config.get("swing_trading", {}) or {}
        candle_cfg = self.config.get("candle", {}) or {}
        strat_cfg = (self.config.get("strategies") or [{}])[0] or {}
        base = {
            "strong_min_confluence": int(swing_cfg.get("strong_min_confluence", 4)),
            "moderate_min_confluence": int(swing_cfg.get("moderate_min_confluence", 3)),
            "moderate_min_edges": int(swing_cfg.get("moderate_min_edges", 3)),
            "rsi_max": float(swing_cfg.get("rsi_max", 72)),
            "reject_rsi_above": float(swing_cfg.get("reject_rsi_above", 78)),
            "zscore_max": float(swing_cfg.get("zscore_max", 1.45)),
            "zscore_min": float(self.zscore_min),
            "min_candle_strength": float(candle_cfg.get("min_strength", 0.30)),
            "min_vol_ratio_high": float(strat_cfg.get("min_vol_ratio_high", 1.2)),
            "retail_min_score": int(self.retail_mind.cfg.get("min_retail_score", 5)),
        }
        effective, status = self.pacer.apply(base)
        self.threshold_overrides = effective
        self.pace_status = status
        if status.relax_level:
            logger.info(
                f"🎚️ {status.summary()} → 共振 {effective['strong_min_confluence']}/"
                f"{effective['moderate_min_confluence']}, RSI≤{effective['rsi_max']:.0f}, "
                f"Z {effective['zscore_min']:.2f}–{effective['zscore_max']:.2f}, "
                f"散戶分 ≥{effective['retail_min_score']}"
            )
        else:
            logger.info(f"🎚️ {status.summary()}")
        return status

    # ----- per-symbol pipeline -----

    def analyze_symbol(self, symbol) -> SymbolAnalysis:
        """Read-only pipeline: fundamentals → news → data → signal → quality gate.

        Shared by the live loop, ``--analyze`` and the external-signal reviewer so
        all three see identical numbers.
        """
        analysis = SymbolAnalysis(symbol=symbol)

        view = self.fundamental.assess(symbol)
        analysis.fundamental_view = view.to_dict()
        if not view.passed:
            analysis.stage = "FUNDAMENTAL"
            analysis.reason = view.reason
            return analysis

        if getattr(self.news, "enabled", False):
            try:
                analysis.news_view = self.news.get_sentiment(symbol)
                news_ok, news_msg = self.news.is_sentiment_ok(symbol)
                if not news_ok:
                    analysis.stage = "NEWS"
                    analysis.reason = news_msg
                    return analysis
                analysis.reason = news_msg
            except Exception as exc:
                logger.warning(f"新聞情緒檢查失敗 {symbol}: {exc}")

        df = self.fetch_symbol_data(symbol)
        if df is None:
            analysis.stage = "DATA"
            analysis.reason = "數據不可用"
            return analysis
        analysis.df = df

        price = float(df["close"].iloc[-1])
        pulse = self.realtime_pulse.check(symbol, last_close=price)
        if not pulse.get("ok", True):
            analysis.stage = "REALTIME"
            analysis.reason = pulse.get("reason", "即時報價過舊")
            return analysis
        if pulse.get("quote", {}).get("price"):
            price = float(pulse["quote"]["price"])
        if price <= 0 or price > self.price_limit:
            analysis.stage = "PRICE_LIMIT"
            analysis.reason = f"股價 ${price:.2f} 超出上限 ${self.price_limit}"
            analysis.price = price
            return analysis
        analysis.price = price

        quant = QuantEngine.dynamic_score(df, weights=self.factor_weights)
        ma20 = float(df["close"].rolling(20).mean().iloc[-1])
        ma50 = float(df["close"].rolling(50).mean().iloc[-1])
        volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].rolling(5).mean().iloc[-1])
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        analysis.quant = quant

        context = MarketContext(
            symbol=symbol, price=price, vix=self.current_vix,
            zscore_min=float(self.threshold_overrides.get("zscore_min", self.zscore_min)),
            exposure=self.exposure, breadth_score=self.breadth_score, quant=quant,
            vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
            regime=self.current_regime.regime if self.current_regime else "NEUTRAL",
            regime_score=self.current_regime.score if self.current_regime else None,
            allow_new_entries=self.allow_new_entries,
            threshold_overrides=self.threshold_overrides,
        )
        analysis.context = context

        for strategy in self.strategies:
            ok, prefilter_reason = strategy.prefilter(df, context)
            if not ok:
                analysis.stage = "PREFILTER"
                analysis.reason = f"[{strategy.name}] {prefilter_reason}"
                return analysis

            signal = strategy.generate_signal(df, context)
            analysis.signal = signal
            if signal.get("action") in ("STRONG_BUY", "MODERATE_BUY"):
                analysis.quality_ok, analysis.quality_reason = self.swing_filter.validate(
                    symbol, signal, context, df=df,
                )
            analysis.ok = True
            analysis.stage = "SIGNAL"
            return analysis

        analysis.stage = "NO_STRATEGY"
        analysis.reason = "未載入策略"
        return analysis

    def evaluate_retail(self, analysis, external_signal=None):
        """Second opinion from the retail seat: affordable, tradable, worth it?"""
        return self.retail_mind.evaluate(
            analysis.symbol,
            analysis.signal,
            analysis.context,
            df=analysis.df,
            fundamental_view=analysis.fundamental_view,
            news_view=analysis.news_view,
            external_signal=external_signal,
            capital=self.risk_mgr.total_capital,
            max_shares=self.max_shares,
            max_symbol_pct=self.portfolio.max_symbol_pct,
        )

    # ----- external app integration -----

    def process_external_signals(self):
        """Review ideas pushed in from the companion app and log a verdict."""
        if not getattr(self.external_inbox, "enabled", False):
            return []

        try:
            pending = self.external_inbox.poll()
        except Exception as exc:
            logger.warning(f"外部訊號讀取失敗: {exc}")
            return []
        if not pending:
            return []

        logger.info(f"📥 收到 {len(pending)} 則外部訊號")
        reports = []
        for signal_in in pending:
            try:
                report = self.reviewer.review(signal_in)
            except Exception as exc:
                logger.exception(f"外部訊號審視失敗 {signal_in.symbol}: {exc}")
                self.external_inbox.mark_processed(signal_in.id)
                continue

            logger.info(
                f"   📌 {signal_in.symbol} → {report['verdict']}: {report.get('explanation', '')}"
            )
            self.external_inbox.write_verdict(signal_in, report)
            self.external_inbox.mark_processed(signal_in.id)
            self.blotter.log_event(
                "EXTERNAL_REVIEW",
                symbol=signal_in.symbol,
                reason=f"{report['verdict']} | {report.get('explanation', '')[:160]}",
            )
            if signal_in.symbol not in self.watchlist and report["verdict"] in ("BUY", "WATCH"):
                self.watchlist.append(signal_in.symbol)
                logger.info(f"   ➕ {signal_in.symbol} 已加入本輪 watchlist")
            reports.append(report)
        return reports

    def analyze_watchlist(self):
        """One-shot decision table for the active watchlist (no orders placed)."""
        self.refresh_vix()
        self.refresh_market_context(force=True)
        self.refresh_watchlist_if_due(force=True)
        self.refresh_pacing()

        rows = []
        for symbol in self.watchlist:
            analysis = self.analyze_symbol(symbol)
            row = {
                "symbol": symbol,
                "stage": analysis.stage,
                "price": round(analysis.price, 2) if analysis.price else None,
                "tier": (analysis.fundamental_view or {}).get("tier"),
                "action": (analysis.signal or {}).get("action", "—"),
                "confluence": (analysis.signal or {}).get("confluence_score"),
                "missing_edges": (analysis.signal or {}).get("missing_edges"),
                "quality": analysis.quality_reason,
                "verdict": "SKIP",
                "reason": analysis.reason,
            }
            if analysis.ok and (analysis.signal or {}).get("action") in ("STRONG_BUY", "MODERATE_BUY"):
                if analysis.quality_ok:
                    retail = self.evaluate_retail(analysis)
                    row["verdict"] = retail.verdict
                    row["retail_score"] = retail.retail_score
                    row["size_factor"] = retail.size_factor
                    row["reason"] = retail.summary()
                    row["metrics"] = retail.metrics
                else:
                    row["verdict"] = "FILTERED"
                    row["reason"] = analysis.quality_reason
            elif analysis.ok:
                row["verdict"] = "HOLD"
            rows.append(row)

        rank = {"BUY": 0, "WATCH": 1, "FILTERED": 2, "HOLD": 3, "SKIP": 4}
        rows.sort(key=lambda r: (rank.get(r["verdict"], 5), -(r.get("confluence") or 0)))
        return {
            "market": {
                "regime": self.current_regime.regime if self.current_regime else "N/A",
                "vix": round(self.current_vix, 2),
                "breadth": self.breadth_score,
                "pacing": self.pace_status.summary() if self.pace_status else None,
                "thresholds": self.threshold_overrides,
            },
            "symbols": rows,
        }

    def process_symbol(self, symbol):
        logger.info(f"\n🔍 分析: {symbol}")

        analysis = self.analyze_symbol(symbol)
        if not analysis.ok:
            logger.info(f"   ⏳ [{analysis.stage}] {analysis.reason}")
            if analysis.stage in ("FUNDAMENTAL", "NEWS", "REALTIME", "PRICE_LIMIT", "PREFILTER"):
                self.blotter.log_rejection(symbol, analysis.reason, stage=analysis.stage)
            return
        if analysis.reason:
            logger.info(f"   📰 {analysis.reason}")

        signal = analysis.signal
        quant = analysis.quant
        vol_ratio = analysis.context.vol_ratio
        df = analysis.df
        self.blotter.log_signal(symbol, signal, quant, vol_ratio, self.exposure)

        action = signal.get("action")
        if action in ("STRONG_BUY", "MODERATE_BUY"):
            can_trade, emo_msg = self.emotion.check_before_trade()
            if not can_trade:
                logger.warning(f"   {emo_msg}")
                self.blotter.log_rejection(symbol, emo_msg, stage="EMOTION")
                return False

            if self.pace_status is not None and not self.pace_status.allow_new_entry:
                reason = "; ".join(self.pace_status.reasons)
                logger.info(f"   ⏳ 交易節奏: {reason}")
                self.blotter.log_rejection(symbol, reason, stage="PACING")
                return False

            if not analysis.quality_ok:
                logger.info(f"   ⏳ 品質過濾: {analysis.quality_reason}")
                self.blotter.log_rejection(symbol, analysis.quality_reason, stage="SWING_QUALITY")
                return False
            logger.info(f"   ✅ {analysis.quality_reason}")

            retail = self.evaluate_retail(analysis)
            if not retail.approve:
                logger.info(f"   🧑‍💻 散戶視角: {retail.summary()}")
                self.blotter.log_rejection(symbol, retail.summary(), stage="RETAIL")
                return False
            logger.info(f"   🧑‍💻 {retail.summary()}")
            for thought in retail.thoughts[:2]:
                logger.info(f"      · {thought}")
            signal["retail_size_factor"] = retail.size_factor
            signal["retail_score"] = retail.retail_score

            self.handle_buy(symbol, signal, quant, vol_ratio, df=df)
            return True

        if action == "STRONG_SELL":
            self.handle_sell(symbol, signal, analysis.price)
            return True

        logger.info(
            f"   ⏳ {signal.get('reason', '')} (RSI {quant.get('rsi', 0):.1f})"
        )
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
        last_error = None
        for attempt in range(3):
            try:
                data = yf.Ticker("^VIX").history(period="1d")
                if not data.empty:
                    self.current_vix = float(data["Close"].iloc[-1])
                    self.vix_failures = 0
                    self.vix_is_stale = False
                    self.vix_blocks_entries = False
                    self.risk_mgr.check_vix(self.current_vix)
                    return self.current_vix
                last_error = "空數據"
            except Exception as e:
                last_error = e
                logger.warning(f"VIX 獲取失敗 (嘗試 {attempt + 1}/3): {e}")
                time.sleep(1)

        # Regime, sizing and risk caps all key off VIX; a silent stale value
        # would quietly invalidate every downstream gate.
        self.vix_failures += 1
        self.vix_is_stale = True
        self.current_vix = getattr(self, "current_vix", 18.0)
        message = (
            f"VIX 連續 {self.vix_failures} 次獲取失敗，沿用舊值 {self.current_vix:.1f}"
            f"（風控/regime 判斷可能失準）: {last_error}"
        )
        logger.error(f"⚠️ {message}")
        self.blotter.log_event("VIX_STALE", reason=message)
        if self.vix_failures >= self.max_data_failures:
            self.vix_blocks_entries = True
            self.notifier.alert_stale_data("^VIX", message)
            self.blotter.log_event(
                "VIX_BLOCK_ENTRIES",
                reason=f"VIX stale {self.vix_failures} 次，暫停新倉",
            )
            logger.error("🚫 VIX 數據失效 — 已暫停新倉直至恢復")
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
                self._hydrate_broker_orders()
        except Exception as e:
            logger.exception(f"IBKR 初始化失敗: {e}")
            self.notifier.alert_exception("ibkr_connect", e)

        self.refresh_vix()
        self.refresh_market_context(force=True)
        self.refresh_watchlist_if_due(force=True)
        self.refresh_pacing()
        self._run_candle_lab_auto_learn()
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
                    self.refresh_pacing()
                    self.reconcile()
                    self.process_external_signals()

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
                    self.verify_stop_protection()

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
                            if not self._entries_permitted() and not self.portfolio.has_position(symbol):
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
    parser.add_argument("--env", default="data/.env")
    parser.add_argument("--dry-run", action="store_true", help="強制僅信號模式，不下單")
    parser.add_argument("--once", action="store_true", help="只執行一次掃描後結束")
    parser.add_argument(
        "--analyze", action="store_true",
        help="輸出觀察名單的買/不買決策表後結束（不下單）",
    )
    parser.add_argument(
        "--review-external", action="store_true",
        help="只處理外部 App 送來的訊號後結束",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出 --analyze 結果")
    return parser.parse_args(argv)


def print_analysis(report):
    market = report["market"]
    print(
        f"市場: {market['regime']} | VIX {market['vix']} | 廣度 {market['breadth']} | "
        f"{market['pacing']}"
    )
    header = f"{'標的':<8}{'判定':<10}{'動作':<14}{'共振':<6}{'散戶分':<8}{'倉位':<8}說明"
    print(header)
    print("-" * len(header))
    for row in report["symbols"]:
        size = row.get("size_factor")
        print(
            f"{row['symbol']:<8}{row['verdict']:<10}{str(row['action']):<14}"
            f"{str(row.get('confluence') or '-'):<6}"
            f"{str(row.get('retail_score') or '-'):<8}"
            f"{(f'{size:.0%}' if size else '-'):<8}"
            f"{(row.get('reason') or '')[:70]}"
        )


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config, args.env)
    configure_logging(config.get("logging", {}))

    bot = TradingBot(config, dry_run=args.dry_run or args.analyze)

    if args.analyze:
        report = bot.analyze_watchlist()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        else:
            print_analysis(report)
        return 0

    if args.review_external:
        bot.refresh_vix()
        bot.refresh_market_context(force=True)
        bot.refresh_pacing()
        reports = bot.process_external_signals()
        print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
        return 0

    if args.once:
        bot.max_cycles = 1
        bot.market_hours_only = False
    bot.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
