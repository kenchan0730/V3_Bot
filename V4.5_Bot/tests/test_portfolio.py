import pandas as pd
import pytest

from core.portfolio import Portfolio


@pytest.fixture
def portfolio():
    return Portfolio({
        "max_gross_exposure_pct": 100.0,
        "max_open_positions": 3,
        "max_sector_pct": 40.0,
        "max_symbol_pct": 30.0,
        "max_total_open_risk_pct": 6.0,
        "correlation_threshold": 0.8,
        "sector_map": {"AAA": "Technology", "BBB": "Technology", "CCC": "Energy"},
    })


def test_sync_from_dict_positions(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 22.0})
    assert portfolio.has_position("AAA")
    assert portfolio.position_quantity("AAA") == 10
    assert portfolio.gross_exposure() == pytest.approx(220.0)


def test_sync_from_scalar_positions(portfolio):
    portfolio.sync({"AAA": 5}, {"AAA": 10.0})
    assert portfolio.gross_exposure() == pytest.approx(50.0)


def test_sync_drops_zero_positions(portfolio):
    portfolio.sync({"AAA": 0})
    assert portfolio.open_position_count() == 0


def test_sync_preserves_stop(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    portfolio.set_stop("AAA", 18.0)
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 21.0})
    assert portfolio.positions["AAA"]["stop"] == 18.0


def test_intended_stop_before_fill(portfolio):
    portfolio.record_intended_stop("AAA", 18.0)
    assert portfolio.stops == {"AAA": 18.0}
    assert "AAA" not in portfolio.positions

    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    assert portfolio.positions["AAA"]["stop"] == 18.0


def test_intended_stop_survives_sync_without_position(portfolio):
    portfolio.record_intended_stop("AAA", 18.0)
    portfolio.sync({})
    assert portfolio.stops == {"AAA": 18.0}


def test_open_risk_uses_stops(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    portfolio.set_stop("AAA", 18.0)
    assert portfolio.open_risk() == pytest.approx(20.0)
    assert portfolio.open_risk_pct(1000.0) == pytest.approx(2.0)


def test_open_risk_ignores_missing_stop(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    assert portfolio.open_risk() == 0.0


def test_sector_exposure_groups_symbols(portfolio):
    portfolio.sync(
        {"AAA": {"quantity": 5, "avg_cost": 10.0}, "CCC": {"quantity": 5, "avg_cost": 10.0}},
        {"AAA": 10.0, "CCC": 10.0},
    )
    exposure = portfolio.sector_exposure()
    assert exposure["Technology"] == pytest.approx(50.0)
    assert exposure["Energy"] == pytest.approx(50.0)


def test_sector_of_unknown_symbol(portfolio):
    assert portfolio.sector_of("ZZZZ") == "UNKNOWN"


# ----- limit enforcement -----

def test_can_open_allows_fresh_symbol(portfolio):
    allowed, reason = portfolio.can_open("AAA", 100.0, 1000.0, stop_risk=10.0)
    assert allowed is True and reason == "OK"


def test_can_open_blocks_duplicate(portfolio):
    portfolio.sync({"AAA": {"quantity": 5, "avg_cost": 10.0}}, {"AAA": 10.0})
    allowed, reason = portfolio.can_open("AAA", 50.0, 1000.0)
    assert allowed is False and "已有持倉" in reason


def test_can_open_blocks_symbol_concentration(portfolio):
    allowed, reason = portfolio.can_open("AAA", 400.0, 1000.0)
    assert allowed is False and "單一標的" in reason


def test_can_open_blocks_sector_concentration(portfolio):
    portfolio.sync({"AAA": {"quantity": 30, "avg_cost": 10.0}}, {"AAA": 10.0})
    allowed, reason = portfolio.can_open("BBB", 200.0, 1000.0)
    assert allowed is False and "板塊曝險" in reason


def test_can_open_blocks_on_position_count(portfolio):
    portfolio.sync({
        "AAA": {"quantity": 1, "avg_cost": 5.0},
        "BBB": {"quantity": 1, "avg_cost": 5.0},
        "CCC": {"quantity": 1, "avg_cost": 5.0},
    }, {"AAA": 5.0, "BBB": 5.0, "CCC": 5.0})
    allowed, reason = portfolio.can_open("DDD", 10.0, 1000.0)
    assert allowed is False and "持倉數" in reason


def test_can_open_blocks_on_total_open_risk(portfolio):
    # $500 gross (50%) with $55 open risk (5.5%); +$10 risk breaches the 6% cap.
    portfolio.sync({"AAA": {"quantity": 50, "avg_cost": 10.0}}, {"AAA": 10.0})
    portfolio.set_stop("AAA", 8.9)
    allowed, reason = portfolio.can_open("CCC", 100.0, 1000.0, stop_risk=10.0)
    assert allowed is False and "風險" in reason


def test_can_open_blocks_zero_capital(portfolio):
    allowed, reason = portfolio.can_open("AAA", 10.0, 0.0)
    assert allowed is False and "資本" in reason


def test_check_book_limits_ok(portfolio):
    ok, reason = portfolio.check_book_limits(1000.0)
    assert ok is True and reason == "OK"


def test_check_book_limits_blocks_gross(portfolio):
    portfolio.sync({"AAA": {"quantity": 200, "avg_cost": 10.0}}, {"AAA": 10.0})
    ok, reason = portfolio.check_book_limits(1000.0)
    assert ok is False and "曝險" in reason


def test_check_book_limits_respects_gross_override(portfolio):
    portfolio.sync({"AAA": {"quantity": 30, "avg_cost": 10.0}}, {"AAA": 10.0})
    ok_default, _ = portfolio.check_book_limits(1000.0)
    ok_tight, reason = portfolio.check_book_limits(1000.0, max_gross_pct_override=25.0)
    assert ok_default is True
    assert ok_tight is False and "曝險" in reason


def test_can_open_passes_gross_override(portfolio):
    portfolio.sync({"AAA": {"quantity": 22, "avg_cost": 10.0}}, {"AAA": 10.0})
    allowed, reason = portfolio.can_open("BBB", 50.0, 1000.0, stop_risk=5.0, max_gross_pct_override=25.0)
    assert allowed is False and "曝險" in reason


# ----- correlation -----

def test_correlation_scale_halves_for_correlated(portfolio):
    base = pd.Series([0.01, -0.02, 0.03, -0.01, 0.02, 0.01])
    portfolio.sync({"AAA": {"quantity": 5, "avg_cost": 10.0}}, {"AAA": 10.0})
    returns = {"AAA": base, "BBB": base * 1.01}
    assert portfolio.correlation_scale("BBB", returns) == 0.5


def test_correlation_scale_full_for_uncorrelated(portfolio):
    portfolio.sync({"AAA": {"quantity": 5, "avg_cost": 10.0}}, {"AAA": 10.0})
    returns = {
        "AAA": pd.Series([0.01, -0.02, 0.03, -0.01, 0.02, 0.01]),
        "BBB": pd.Series([-0.03, 0.04, -0.01, 0.02, -0.02, 0.03]),
    }
    assert portfolio.correlation_scale("BBB", returns) == 1.0


def test_correlation_scale_without_data(portfolio):
    assert portfolio.correlation_scale("BBB", {}) == 1.0


def test_snapshot_shape(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    portfolio.set_stop("AAA", 18.0)
    snapshot = portfolio.snapshot(1000.0)
    assert snapshot["open_positions"] == 1
    assert snapshot["gross_exposure_pct"] == pytest.approx(20.0)
    assert snapshot["positions"]["AAA"]["stop"] == 18.0


def test_update_price_recalculates_market_value(portfolio):
    portfolio.sync({"AAA": {"quantity": 10, "avg_cost": 20.0}}, {"AAA": 20.0})
    portfolio.update_price("AAA", 25.0)
    assert portfolio.gross_exposure() == pytest.approx(250.0)
