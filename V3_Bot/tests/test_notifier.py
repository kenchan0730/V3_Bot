import pytest

from core.notifier import CRITICAL, WARNING, Notifier


class StubResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def notifier(monkeypatch):
    sent = []

    def fake_post(url, json=None, timeout=None):
        sent.append({"url": url, "payload": json})
        return StubResponse()

    monkeypatch.setattr("core.notifier.requests.post", fake_post)
    instance = Notifier({
        "enabled": True,
        "throttle_seconds": 300,
        "telegram": {"bot_token": "token", "chat_id": "chat"},
    })
    instance.sent = sent
    return instance


def test_disabled_notifier_sends_nothing(monkeypatch):
    called = []
    monkeypatch.setattr("core.notifier.requests.post", lambda *a, **k: called.append(1))
    assert Notifier({"enabled": False}).send_telegram("hi") is False
    assert called == []


def test_missing_credentials_short_circuits(monkeypatch):
    called = []
    monkeypatch.setattr("core.notifier.requests.post", lambda *a, **k: called.append(1))
    assert Notifier({"enabled": True}).send_telegram("hi") is False
    assert called == []


def test_send_telegram_success(notifier):
    assert notifier.send_telegram("hello") is True
    assert notifier.sent[0]["payload"]["text"] == "hello"


def test_send_telegram_handles_error_status(monkeypatch):
    monkeypatch.setattr("core.notifier.requests.post",
                        lambda *a, **k: StubResponse(500, "boom"))
    instance = Notifier({"enabled": True, "telegram": {"bot_token": "t", "chat_id": "c"}})
    assert instance.send_telegram("x") is False


def test_send_telegram_handles_exception(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("core.notifier.requests.post", raise_error)
    instance = Notifier({"enabled": True, "telegram": {"bot_token": "t", "chat_id": "c"}})
    assert instance.send_telegram("x") is False


def test_alert_throttles_repeats(notifier):
    assert notifier.alert(WARNING, "Title", "first", key="dup") is True
    assert notifier.alert(WARNING, "Title", "second", key="dup") is False
    assert len(notifier.sent) == 1


def test_alert_force_bypasses_throttle(notifier):
    notifier.alert(WARNING, "Title", "first", key="dup")
    assert notifier.alert(CRITICAL, "Title", "second", key="dup", force=True) is True


def test_alert_different_keys_both_send(notifier):
    notifier.alert(WARNING, "A", "x", key="a")
    notifier.alert(WARNING, "B", "y", key="b")
    assert len(notifier.sent) == 2


def test_alert_disconnect(notifier):
    assert notifier.alert_disconnect("connection lost") is True
    assert "IBKR" in notifier.sent[0]["payload"]["text"]


def test_alert_data_failure(notifier):
    notifier.alert_data_failure("AVAH", 3, "timeout")
    assert "AVAH" in notifier.sent[0]["payload"]["text"]


def test_alert_stale_data(notifier):
    notifier.alert_stale_data("QXO", "落後 5 個交易日")
    assert "QXO" in notifier.sent[0]["payload"]["text"]


def test_alert_daily_loss_is_forced(notifier):
    notifier.alert_daily_loss("limit hit")
    notifier.alert_daily_loss("limit hit again")
    assert len(notifier.sent) == 2


def test_alert_risk_limit(notifier):
    assert notifier.alert_risk_limit("drawdown") is True


def test_alert_exception_includes_traceback(notifier):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        notifier.alert_exception("unit_test", exc)
    assert "ValueError" in notifier.sent[0]["payload"]["text"]


def test_alert_order_issue(notifier):
    notifier.alert_order_issue("AVAH", "rejected")
    assert "rejected" in notifier.sent[0]["payload"]["text"]


def test_startup_and_shutdown_alerts(notifier):
    notifier.alert_startup("up")
    notifier.alert_shutdown("down")
    assert len(notifier.sent) == 2


def test_send_trade_signal_formats_message(notifier):
    notifier.send_trade_signal("AVAH", "BUY", 12.0, 11.0, 13.5, 15.0, 10)
    text = notifier.sent[0]["payload"]["text"]
    assert "AVAH" in text and "BUY" in text and "$12.00" in text


def test_send_email_disabled_by_default(notifier):
    assert notifier.send_email("subject", "body") is False
