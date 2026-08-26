"""Tests for 9-Trader debate CRITICAL fixes (E2, H1, S1, X1 helpers)."""

import pytest

from core.config_loader import load_config
from core.order_manager import OrderManager
from main import TradingBot
from tests.helpers import FakeContract, FakeOrder, FakeTrade


MINIMAL_CONFIG = {
    "capital": {"total": 1275.0},
    "trading": {"auto_trade": False, "market_hours_only": False},
    "risk": {"max_risk_percent": 1.5},
    "portfolio": {"max_gross_exposure_pct": 60.0, "max_symbol_pct": 20.0},
    "ibkr": {"host": "127.0.0.1", "port": 7497, "client_id": 99, "account_mode": "paper"},
    "execution": {"protection_poll_interval_seconds": 60},
    "data": {"max_consecutive_failures": 3},
    "watchlist": ["AVAH"],
    "logging": {},
    "state": {"file": "data/state_test_gates.json"},
    "audit": {"blotter_file": "data/trade_blotter_test_gates.csv"},
}


class RecordingNotifier:
    def __init__(self):
        self.risk_alerts = []

    def alert_risk_limit(self, msg):
        self.risk_alerts.append(msg)

    def alert_order_issue(self, *args, **kwargs):
        pass

    def alert_exception(self, *args, **kwargs):
        pass

    def alert_stale_data(self, *args, **kwargs):
        pass

    def alert_startup(self, *args, **kwargs):
        pass

    def alert_shutdown(self, *args, **kwargs):
        pass

    def alert_disconnect(self, *args, **kwargs):
        pass

    def alert_daily_loss(self, *args, **kwargs):
        pass

    def send_trade_signal(self, *args, **kwargs):
        pass


class RecordingBlotter:
    def __init__(self):
        self.events = []

    def log_event(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(
        "core.ibkr_connector.IBKRConnector.connect",
        lambda self: False,
    )
    return TradingBot(MINIMAL_CONFIG, dry_run=True)


def test_live_mode_requires_port_7496(monkeypatch):
    cfg = dict(MINIMAL_CONFIG)
    cfg["ibkr"] = {
        **cfg["ibkr"],
        "account_mode": "live",
        "port": 7497,
    }
    monkeypatch.setenv("LIVE_TRADING_CONFIRM", "yes")
    monkeypatch.setattr("core.ibkr_connector.IBKRConnector.connect", lambda self: False)
    with pytest.raises(SystemExit, match="7496"):
        TradingBot(cfg, dry_run=True)


def test_live_mode_requires_confirm_env(monkeypatch):
    cfg = dict(MINIMAL_CONFIG)
    cfg["ibkr"] = {
        **cfg["ibkr"],
        "account_mode": "live",
        "port": 7496,
    }
    monkeypatch.delenv("LIVE_TRADING_CONFIRM", raising=False)
    monkeypatch.setattr("core.ibkr_connector.IBKRConnector.connect", lambda self: False)
    with pytest.raises(SystemExit, match="LIVE_TRADING_CONFIRM"):
        TradingBot(cfg, dry_run=True)


def test_vix_stale_blocks_entries(bot, monkeypatch):
    monkeypatch.setattr(
        "main.TradingBot.refresh_vix",
        lambda self: (
            setattr(self, "vix_failures", 3)
            or setattr(self, "vix_blocks_entries", True)
            or self.current_vix
        ),
    )
    bot.vix_blocks_entries = True
    assert bot._entries_permitted() is False


def test_stop_rearm_failure_blocks_entries(bot):
    bot.portfolio.sync({"AVAH": {"quantity": 5, "avg_cost": 12.0}}, {"AVAH": 12.0})
    bot.portfolio.record_intended_stop("AVAH", 11.0)
    bot.notifier = RecordingNotifier()
    bot.blotter = RecordingBlotter()

    class FailIBKR:
        def is_connected(self):
            return True

        def place_protective_stop(self, symbol, quantity, stop_price, action="SELL"):
            return None

    bot.order_mgr = OrderManager(ibkr=FailIBKR(), notifier=bot.notifier, blotter=bot.blotter)
    bot.auto_trade = True
    bot.ibkr = FailIBKR()

    reports = bot.verify_stop_protection()
    assert bot.stop_protection_blocks_entries is True
    assert bot._entries_permitted() is False
    assert reports[0]["rearm_failed"] is True
    assert any(evt == "STOP_REARM_FAILED" for evt, _ in bot.blotter.events)


def test_sleep_polls_protection_when_holding(bot, monkeypatch):
    bot.portfolio.sync({"AVAH": {"quantity": 5, "avg_cost": 12.0}}, {"AVAH": 12.0})
    calls = []
    monkeypatch.setattr(bot, "verify_stop_protection", lambda: calls.append(1) or [])
    bot.last_protection_check = 0.0
    bot.protection_poll_interval = 1
    bot._sleep(2.5)
    assert len(calls) >= 1


def test_check_protection_marks_rearm_failed():
    class FailIBKR:
        def place_protective_stop(self, *args, **kwargs):
            return None

    mgr = OrderManager(ibkr=FailIBKR())
    managed = mgr.track(
        9, "AVAH", "SELL", 10, role="stop_loss",
        trade=FakeTrade(FakeContract("AVAH"), FakeOrder("SELL", 10, 11.0)),
    )
    managed.status = "Cancelled"
    reports = mgr.check_protection({"AVAH": {"quantity": 10}}, stops={"AVAH": 11.0})
    assert reports[0]["rearm_failed"] is True
