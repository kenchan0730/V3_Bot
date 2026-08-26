"""Broker cost profile resolution."""

import pytest

from core.broker_costs import resolve


def test_resolve_ibkr_pro():
    costs = resolve({"broker": {"profile": "ibkr_pro"}})
    assert costs.name == "ibkr_pro"
    assert costs.commission(10) == pytest.approx(1.0)
    assert costs.round_trip(10) == pytest.approx(2.0)


def test_resolve_zero_commission_profile():
    costs = resolve({"broker": {"profile": "alpaca"}})
    assert costs.is_commission_free
    assert costs.commission(50) == 0.0


def test_legacy_backtest_keys_override_profile():
    costs = resolve({
        "broker": {"profile": "alpaca"},
        "backtest": {"commission_per_share": 0.01, "commission_minimum": 2.0},
    })
    assert costs.commission(10) == pytest.approx(2.0)
